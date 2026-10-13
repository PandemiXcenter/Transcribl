import base64
import json
from pathlib import Path
from typing import Any

import anthropic
import httpx2 as httpx
import openai
import pytest

from transcribl.adapters.llm.base import ProviderRequestError
from transcribl.adapters.llm.providers.anthropic import AnthropicPageTranslator
from transcribl.adapters.llm.providers.openai import OpenAIPageTranslator
from transcribl.adapters.llm.structured import StructuredPageTranslator
from transcribl.config import load_project_config
from transcribl.domain.models import (
    GeneratedPagePayload,
    GeneratedTablePayload,
    TranslationSettings,
)
from transcribl.ports.translation import PageTranslationRequest, TableReconstructionRequest


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("table", [False, True])
@pytest.mark.parametrize("thinking", ["default", "high", "max"])
def test_real_sdk_serializes_page_and_table_contracts_offline(
    tmp_path: Path, provider: str, table: bool, thinking: str
) -> None:
    payload = (
        GeneratedTablePayload.model_validate(
            {"tables": [{"order": 2, "translated_markdown": "| A | B |\n| --- | --- |\n| 1 | 2 |"}]}
        )
        if table
        else GeneratedPagePayload.model_validate(
            {
                "blocks": [
                    {
                        "order": 1,
                        "type": "body",
                        "source_text": "mation subsided.",
                        "translated_text": "subsided.",
                        "paragraph_continuation": "from_previous_page",
                    }
                ],
                "paragraph_revisions": [
                    {
                        "original_page_number": 1,
                        "order": 1,
                        "translated_text": "The inflammation",
                        "uncertainties": [],
                    }
                ],
            }
        )
    )
    seen: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if provider == "openai":
            body = {
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6-astra",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": payload.model_dump_json(),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            }
        else:
            body = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "content": [{"type": "text", "text": payload.model_dump_json()}],
                "usage": {"input_tokens": 12, "output_tokens": 8},
            }
        return httpx.Response(200, json=body)

    http = httpx.Client(transport=httpx.MockTransport(respond))
    config = load_project_config(Path("config/default.toml"))
    adapter: StructuredPageTranslator
    if provider == "openai":
        adapter = OpenAIPageTranslator(
            api_key="unused",
            config=config.provider.openai.model_copy(update={"thinking_level": thinking}),
            client=openai.OpenAI(api_key="test-key", http_client=http),
        )
    else:
        adapter = AnthropicPageTranslator(
            api_key="unused",
            config=config.provider.anthropic.model_copy(update={"thinking_level": thinking}),
            client=anthropic.Anthropic(api_key="test-key", http_client=http),
        )
    image = tmp_path / "page.png"
    image.write_bytes(b"synthetic-image")
    args: dict[str, Any] = dict(
        original_page_number=2,
        markdown="complete markdown",
        image_path=image,
        image_media_type="image/png",
        prompt="instructions\ncomplete markdown",
        settings=TranslationSettings(),
    )
    with adapter:
        result = (
            adapter.reconstruct_tables(
                TableReconstructionRequest(**args, expected_block_orders=(2,))
            )
            if table
            else adapter.translate_page(PageTranslationRequest(**args))
        )
    assert result.payload == payload
    assert (result.input_tokens, result.output_tokens) == (12, 8)
    assert len(seen) == 1
    body = seen[0]
    content = body["input" if provider == "openai" else "messages"][0]["content"]
    assert len(content) == 2
    assert content[1]["text"] == args["prompt"]
    encoded = base64.b64encode(image.read_bytes()).decode()
    if provider == "openai":
        assert content[0]["image_url"] == f"data:image/png;base64,{encoded}"
        schema = body["text"]["format"]["schema"]
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
    else:
        assert content[0]["source"]["data"] == encoded
        schema = body["output_config"]["format"]["schema"]
    assert ("tables" if table else "blocks") in schema["properties"]
    if not table:
        assert "paragraph_revisions" in schema["properties"]
    if thinking == "default":
        assert "reasoning" not in body and "thinking" not in body
        assert "thinking_level" not in adapter.descriptor.semantic_configuration
    elif provider == "openai":
        assert body["reasoning"] == {"effort": thinking}
    else:
        assert body["thinking"] == {"type": "adaptive"}
        assert body["output_config"]["effort"] == thinking
    if thinking != "default":
        assert adapter.descriptor.semantic_configuration["thinking_level"] == thinking
    assert http.is_closed


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_provider_errors_are_redacted_and_permanent_errors_are_not_retried(
    tmp_path: Path, provider: str
) -> None:
    calls = []

    def reject(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            401,
            json={"error": {"type": "authentication_error", "message": "private-key private-page"}},
        )

    http = httpx.Client(transport=httpx.MockTransport(reject))
    config = load_project_config(Path("config/default.toml"))
    adapter = (
        OpenAIPageTranslator(
            api_key="unused",
            config=config.provider.openai,
            client=openai.OpenAI(api_key="test", http_client=http),
        )
        if provider == "openai"
        else AnthropicPageTranslator(
            api_key="unused",
            config=config.provider.anthropic,
            client=anthropic.Anthropic(api_key="test", http_client=http),
        )
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"image")
    with adapter, pytest.raises(ProviderRequestError, match="HTTP 401") as failure:
        adapter.translate_page(
            PageTranslationRequest(1, "source", image, "image/png", "prompt", TranslationSettings())
        )
    assert "private" not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_size_guard_prevents_sdk_calls(tmp_path: Path, provider: str) -> None:
    config = load_project_config(Path("config/default.toml"))
    settings = config.provider.openai if provider == "openai" else config.provider.anthropic
    settings = settings.model_copy(update={"max_inline_request_bytes": 1_000_000})
    image = tmp_path / "page.png"
    image.write_bytes(b"x" * 1_000_000)
    cls = OpenAIPageTranslator if provider == "openai" else AnthropicPageTranslator
    adapter = cls(api_key="unused", config=settings, client=object())
    with pytest.raises(ProviderRequestError, match="byte limit"):
        adapter.translate_page(
            PageTranslationRequest(1, "source", image, "image/png", "prompt", TranslationSettings())
        )


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {
            "blocks": [
                {
                    "order": 1,
                    "type": "body",
                    "source_text": "private-page",
                    "translated_text": "text",
                    "paragraph_continuation": None,
                }
            ]
        },
    ],
)
def test_missing_or_invalid_structured_output_is_rejected_without_content(
    tmp_path: Path, provider: str, invalid: object
) -> None:
    from types import SimpleNamespace

    config = load_project_config(Path("config/default.toml"))
    response = SimpleNamespace(
        output_parsed=invalid,
        parsed_output=invalid,
        status="completed",
        stop_reason="end_turn",
        id="response",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    client = SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kwargs: response),
        messages=SimpleNamespace(parse=lambda **kwargs: response),
    )
    adapter = (
        OpenAIPageTranslator(api_key="unused", config=config.provider.openai, client=client)
        if provider == "openai"
        else AnthropicPageTranslator(
            api_key="unused", config=config.provider.anthropic, client=client
        )
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"image")
    with pytest.raises(ProviderRequestError) as failure:
        adapter.translate_page(
            PageTranslationRequest(1, "source", image, "image/png", "prompt", TranslationSettings())
        )
    assert "private-page" not in str(failure.value)
