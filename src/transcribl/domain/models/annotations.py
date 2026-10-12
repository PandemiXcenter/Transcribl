from __future__ import annotations

from pydantic import (
    Field,
    field_validator,
)

from transcribl.domain.models.base import ContractModel, FootnoteIdentifier, NonEmptyText


class UncertainTerm(ContractModel):
    """Qualitative uncertainty without a fabricated probability."""

    source_term: NonEmptyText
    proposed_translation: str | None = None
    reason: NonEmptyText
    alternatives: list[str] = Field(default_factory=list)


class FootnoteIdentity(ContractModel):
    """Cross-page note identity plus the source's printed reference text."""

    id: FootnoteIdentifier
    text: str | None = Field(default=None, max_length=64)

    @field_validator("text")
    @classmethod
    def normalize_reference_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if any(character in stripped for character in "\r\n\0"):
            raise ValueError("footnote reference text must be a single line")
        return stripped


class FootnoteDescription(ContractModel):
    """Observable appearance and the model's page-continuation handling."""

    appearance: NonEmptyText
    handling: NonEmptyText
