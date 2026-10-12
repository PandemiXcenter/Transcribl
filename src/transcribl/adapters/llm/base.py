"""Provider-neutral adapter plumbing; SDK imports belong in providers/."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel

from transcribl.domain.models import GeneratedPagePayload, GeneratedTablePayload
from transcribl.ports.translation import (
    PageTranslationRequest,
    ProviderResult,
    TableReconstructionRequest,
    TableReconstructionResult,
)

MultimodalRequest = PageTranslationRequest | TableReconstructionRequest


class ProviderRequestError(ValueError):
    """Safe public error that never includes a provider response or secret."""


@dataclass(frozen=True, slots=True)
class StructuredResponse[PayloadT: BaseModel]:
    payload: PayloadT
    response_id: str | None
    input_tokens: int | None
    output_tokens: int | None


class PageTranslatorAdapter(ABC):
    _client: Any

    def translate_page(self, request: PageTranslationRequest) -> ProviderResult:
        response = self._generate_structured(request=request, payload_model=GeneratedPagePayload)
        return ProviderResult(
            response.payload, response.response_id, response.input_tokens, response.output_tokens
        )

    def reconstruct_tables(self, request: TableReconstructionRequest) -> TableReconstructionResult:
        response = self._generate_structured(request=request, payload_model=GeneratedTablePayload)
        return TableReconstructionResult(
            response.payload, response.response_id, response.input_tokens, response.output_tokens
        )

    @abstractmethod
    def _generate_structured[T: BaseModel](
        self, *, request: MultimodalRequest, payload_model: type[T]
    ) -> StructuredResponse[T]:
        """Make one bounded SDK request and return locally validated structured data."""
        raise NotImplementedError

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def inline_request_size(image_bytes: bytes, prompt: str) -> int:
    """Conservative base64 image + UTF-8 prompt + envelope estimate."""
    return 4 * ((len(image_bytes) + 2) // 3) + len(prompt.encode("utf-8")) + 16_384
