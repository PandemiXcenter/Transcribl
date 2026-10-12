from __future__ import annotations

from pydantic import (
    Field,
    field_validator,
)

from transcribl.domain.enums import (
    TranslationStyle,
    UncertaintyLevel,
)
from transcribl.domain.models.base import ContractModel, NonEmptyText


class TranslationSettings(ContractModel):
    """Provider-neutral choices that affect translation meaning."""

    source_language: NonEmptyText = "auto"
    target_language: NonEmptyText = "English"
    style: TranslationStyle = TranslationStyle.BALANCED
    style_name: str | None = Field(default=None, min_length=1, max_length=100)
    style_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    custom_instructions: str | None = Field(default=None, max_length=4_000)
    footnote_appearance_instructions: str | None = Field(default=None, max_length=4_000)
    glossary: dict[str, str] = Field(default_factory=dict)
    preserve_names: bool = True
    preserve_citations: bool = True
    mark_uncertain_terms: bool = True
    uncertainty_level: UncertaintyLevel = UncertaintyLevel.STANDARD
    uncertainty_instructions: str | None = Field(default=None, max_length=4_000)
    previous_page_context_count: int = Field(default=0, ge=0, le=10)

    @field_validator(
        "custom_instructions",
        "footnote_appearance_instructions",
        "uncertainty_instructions",
    )
    @classmethod
    def normalize_optional_instructions(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("glossary")
    @classmethod
    def glossary_must_not_have_blank_entries(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for source, target in value.items():
            source_term = source.strip()
            target_term = target.strip()
            if not source_term or not target_term:
                raise ValueError("glossary terms and translations must not be blank")
            normalized[source_term] = target_term
        return normalized


class MarkdownExportSettings(ContractModel):
    """Choices for the derived, human-facing Markdown projection."""

    include_page_comments: bool = True
    include_headers: bool = False
    include_footers: bool = False
    include_page_numbers: bool = False
