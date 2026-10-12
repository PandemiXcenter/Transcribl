from __future__ import annotations

from typing import Any

import openai
from pydantic import BaseModel

from transcribl.adapters.llm.base import ProviderRequestError
from transcribl.adapters.llm.structured import StructuredPageTranslator
from transcribl.ports.translation import (
    PageTranslationRequest,
    TableReconstructionRequest,
)


class OpenAIPageTranslator(StructuredPageTranslator):
    api_errors = (openai.APIError,)
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
            raise ProviderRequestError(
                "OpenAI returned an incomplete response; check the output token limit"
            )
        usage = response.usage
        return (
            response.output_parsed,
            response.id,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
        )
