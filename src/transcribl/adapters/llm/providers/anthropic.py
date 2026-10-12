from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel

from transcribl.adapters.llm.base import ProviderRequestError
from transcribl.adapters.llm.structured import StructuredPageTranslator
from transcribl.ports.translation import (
    PageTranslationRequest,
    TableReconstructionRequest,
)


class AnthropicPageTranslator(StructuredPageTranslator):
    api_errors = (anthropic.APIError,)
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
            raise ProviderRequestError(
                "Anthropic returned no complete response; check refusal or output token limit"
            )
        usage = response.usage
        return response.parsed_output, response.id, usage.input_tokens, usage.output_tokens
