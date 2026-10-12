from __future__ import annotations

from pydantic import (
    Field,
    field_validator,
)

from transcribl.domain.enums import (
    ExtractionStatus,
)
from transcribl.domain.models.base import ContractModel, NonEmptyText, Sha256


class ArtifactRef(ContractModel):
    """Portable reference to a file below a job's artifact root."""

    path: NonEmptyText
    sha256: Sha256
    media_type: NonEmptyText
    byte_count: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def path_must_be_relative(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("artifact paths must be relative and may not contain '..'")
        return normalized


class PreparedPage(ContractModel):
    """A physical PDF page paired with its Markdown and rendered image."""

    original_page_number: int = Field(ge=1)
    pdf_page_label: str | None = None
    markdown: ArtifactRef
    image: ArtifactRef
    extraction_status: ExtractionStatus
    extracted_character_count: int = Field(ge=0)
    extraction_warnings: list[str] = Field(default_factory=list)
