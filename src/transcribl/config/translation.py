from typing import Literal

from pydantic import Field

from transcribl.config.base import ConfigModel
from transcribl.domain.enums import TranslationStyle, UncertaintyLevel
from transcribl.domain.models import (
    MarkdownExportSettings,
    NonEmptyText,
    TranslationSettings,
)


class ConfiguredTranslationSettings(TranslationSettings):
    """A complete TOML section with no fallback to Python defaults."""

    source_language: NonEmptyText
    target_language: NonEmptyText
    style: TranslationStyle
    custom_instructions: str | None
    footnote_appearance_instructions: str | None
    glossary: dict[str, str]
    preserve_names: bool
    preserve_citations: bool
    mark_uncertain_terms: bool
    uncertainty_level: UncertaintyLevel
    uncertainty_instructions: str | None
    previous_page_context_count: int = Field(ge=0, le=10)


class ConfiguredMarkdownExportSettings(MarkdownExportSettings):
    """A complete TOML section with no fallback to Python defaults."""

    include_page_comments: bool
    include_headers: bool
    include_footers: bool
    include_page_numbers: bool


class PdfExportConfig(ConfigModel):
    """Local XeLaTeX compilation settings for reviewed PDF downloads."""

    latex_engine: Literal["xelatex"]
    compile_timeout_seconds: int = Field(ge=1, le=300)
