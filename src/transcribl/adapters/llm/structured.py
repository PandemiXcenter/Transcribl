from __future__ import annotations

import base64
from abc import abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from transcribl.adapters.llm.base import (
    PageTranslatorAdapter,
    ProviderRequestError,
    StructuredResponse,
    inline_request_size,
)
from transcribl.config import StructuredProviderConfig
from transcribl.ports.translation import (
    PageTranslationRequest,
    ProviderDescriptor,
    TableReconstructionRequest,
)


class StructuredPageTranslator(PageTranslatorAdapter):
    provider: str
    contract: str
    api_errors: tuple[type[Exception], ...]

    def __init__(
        self, *, api_key: str, config: StructuredProviderConfig, client: Any = None
    ) -> None:
        self._config = config
        self._client = client or self._create_client(api_key)

    @abstractmethod
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

    def _generate_structured[T: BaseModel](
        self,
        *,
        request: PageTranslationRequest | TableReconstructionRequest,
        payload_model: type[T],
    ) -> StructuredResponse[T]:
        image_bytes = request.image_path.read_bytes()
        size = inline_request_size(image_bytes, request.prompt)
        if size >= self._config.max_inline_request_bytes:
            raise ProviderRequestError(
                "Inline request exceeds the configured byte limit; lower extraction.image_dpi"
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        try:
            parsed, response_id, input_tokens, output_tokens = self._request(
                request, encoded, payload_model
            )
            if parsed is None:
                raise ProviderRequestError("Provider returned no complete structured output")
            return StructuredResponse(
                payload_model.model_validate(parsed), response_id, input_tokens, output_tokens
            )
        except self.api_errors as exc:
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
            raise ProviderRequestError(
                f"{self.provider} request failed ({status}). {guidance}"
            ) from None
        except ValidationError:
            raise ProviderRequestError("Provider returned invalid structured output") from None

    @abstractmethod
    def _request(
        self,
        request: PageTranslationRequest | TableReconstructionRequest,
        encoded: str,
        payload_model: type[BaseModel],
    ) -> tuple[object, str | None, int | None, int | None]:
        raise NotImplementedError
