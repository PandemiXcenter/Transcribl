"""Structured multimodal adapters for OpenAI Responses and Anthropic Messages."""

from __future__ import annotations

import base64
from typing import Any, Self

import anthropic
import openai
from pydantic import BaseModel, ValidationError

from transcribl.config import StructuredProviderConfig
from transcribl.domain.models import GeneratedPagePayload, GeneratedTablePayload
from transcribl.ports.translation import (
    PageTranslationRequest,
    ProviderDescriptor,
    ProviderResult,
    TableReconstructionRequest,
    TableReconstructionResult,
)


class StructuredRequestError(ValueError):
    """Safe operator guidance without provider response bodies or credentials."""


class StructuredPageTranslator:
    provider: str
    contract: str

    def __init__(
        self, *, api_key: str, config: StructuredProviderConfig, client: Any = None
    ) -> None:
        self._config = config
        self._client = client or self._create_client(api_key)

    def _create_client(self, api_key: str) -> Any:
        raise NotImplementedError

    @property
    def descriptor(self) -> ProviderDescriptor:
        semantics: dict[str, str | int | float | bool] = {
            "structured_output_contract": self.contract,
            "max_output_tokens": self._config.max_output_tokens,
        }
        if self._config.thinking_level != "default":
            semantics["thinking_level"] = self._config.thinking_level
        return ProviderDescriptor(
            provider=self.provider,
            model=self._config.model,
            configuration={
                **semantics,
                "request_timeout_seconds": self._config.request_timeout_seconds,
                "request_attempts": self._config.request_attempts,
                "max_inline_request_bytes": self._config.max_inline_request_bytes,
            },
            semantic_configuration=semantics,
        )

    def translate_page(self, request: PageTranslationRequest) -> ProviderResult:
        payload, response_id, input_tokens, output_tokens = self._generate(
            request, GeneratedPagePayload
        )
        return ProviderResult(payload, response_id, input_tokens, output_tokens)

    def reconstruct_tables(self, request: TableReconstructionRequest) -> TableReconstructionResult:
        payload, response_id, input_tokens, output_tokens = self._generate(
            request, GeneratedTablePayload
        )
        return TableReconstructionResult(payload, response_id, input_tokens, output_tokens)

    def _generate[T: BaseModel](
        self,
        request: PageTranslationRequest | TableReconstructionRequest,
        payload_model: type[T],
    ) -> tuple[T, str | None, int | None, int | None]:
        image_bytes = request.image_path.read_bytes()
        size = 4 * ((len(image_bytes) + 2) // 3) + len(request.prompt.encode()) + 16_384
        if size >= self._config.max_inline_request_bytes:
            raise StructuredRequestError(
                "Inline request exceeds the configured byte limit; lower extraction.image_dpi"
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        try:
            parsed, response_id, input_tokens, output_tokens = self._request(
                request, encoded, payload_model
            )
            if parsed is None:
                raise StructuredRequestError("Provider returned no complete structured output")
            return payload_model.model_validate(parsed), response_id, input_tokens, output_tokens
        except (openai.APIError, anthropic.APIError) as exc:
            code = getattr(exc, "status_code", None)
            status = (
                f"HTTP {code}"
                if isinstance(code, int) and 100 <= code <= 599
                else "connection failure"
            )
            if code in (401, 403):
                guidance = "Check this provider's API key and account access."
            elif code == 429:
                guidance = "Check provider quota and rate limits, then retry later."
            elif code in (400, 404):
                guidance = "Check model availability and structured-output support."
            else:
                guidance = "Retry later or check the configured timeout."
            raise StructuredRequestError(
                f"{self.provider} request failed ({status}). {guidance}"
            ) from None
        except ValidationError:
            raise StructuredRequestError("Provider returned invalid structured output") from None

    def _request(
        self,
        request: PageTranslationRequest | TableReconstructionRequest,
        encoded: str,
        payload_model: type[BaseModel],
    ) -> tuple[object, str | None, int | None, int | None]:
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class OpenAIPageTranslator(StructuredPageTranslator):
    provider = "openai"
    contract = "responses-structured-v1"

    def _create_client(self, api_key: str) -> Any:
        return openai.OpenAI(
            api_key=api_key,
            timeout=self._config.request_timeout_seconds,
            max_retries=self._config.request_attempts - 1,
        )

    def _request(
        self,
        request: PageTranslationRequest | TableReconstructionRequest,
        encoded: str,
        payload_model: type[BaseModel],
    ) -> tuple[object, str | None, int | None, int | None]:
        response = self._client.responses.parse(
            model=self._config.model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_image",
                            "image_url": f"data:{request.image_media_type};base64,{encoded}",
                        },
                        {"type": "input_text", "text": request.prompt},
                    ],
                }
            ],
            text_format=payload_model,
            max_output_tokens=self._config.max_output_tokens,
            store=False,
            **(
                {"reasoning": {"effort": self._config.thinking_level}}
                if self._config.thinking_level != "default"
                else {}
            ),
        )
        if response.status != "completed":
            raise StructuredRequestError(
                "OpenAI returned an incomplete response; check the output token limit"
            )
        usage = response.usage
        return (
            response.output_parsed,
            response.id,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
        )


class AnthropicPageTranslator(StructuredPageTranslator):
    provider = "anthropic"
    contract = "messages-structured-v1"

    def _create_client(self, api_key: str) -> Any:
        return anthropic.Anthropic(
            api_key=api_key,
            timeout=self._config.request_timeout_seconds,
            max_retries=self._config.request_attempts - 1,
        )

    def _request(
        self,
        request: PageTranslationRequest | TableReconstructionRequest,
        encoded: str,
        payload_model: type[BaseModel],
    ) -> tuple[object, str | None, int | None, int | None]:
        response = self._client.messages.parse(
            model=self._config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": request.image_media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": request.prompt},
                    ],
                }
            ],
            output_format=payload_model,
            max_tokens=self._config.max_output_tokens,
            timeout=self._config.request_timeout_seconds,
            **(
                {
                    "output_config": {"effort": self._config.thinking_level},
                    "thinking": {"type": "adaptive"},
                }
                if self._config.thinking_level != "default"
                else {}
            ),
        )
        if response.stop_reason != "end_turn":
            raise StructuredRequestError(
                "Anthropic returned no complete response; check refusal or output token limit"
            )
        usage = response.usage
        return response.parsed_output, response.id, usage.input_tokens, usage.output_tokens
