from pathlib import Path
from tomllib import TOMLDecodeError, load
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from transcribl.domain.enums import TranslationStyle, UncertaintyLevel
from transcribl.domain.errors import ConfigurationError
from transcribl.domain.models import (
    MarkdownExportSettings,
    NonEmptyText,
    TranslationSettings,
)

ProviderName = Literal["gemini", "openai", "anthropic"]


class SecretSettings(BaseSettings):
    """Secrets only. Every non-secret setting belongs in TOML."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    gemini_api_key: SecretStr | None = Field(
        default=None,
        min_length=1,
        validation_alias="GEMINI_API_KEY",
    )

    openai_api_key: SecretStr | None = Field(
        default=None, min_length=1, validation_alias="OPENAI_API_KEY"
    )
    anthropic_api_key: SecretStr | None = Field(
        default=None, min_length=1, validation_alias="ANTHROPIC_API_KEY"
    )

    def for_provider(self, provider: ProviderName) -> SecretStr | None:
        return {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }[provider]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsConfig(ConfigModel):
    artifacts_dir: Path


class ExtractionConfig(ConfigModel):
    image_dpi: int = Field(ge=72, le=600)


class ModelProviderConfig(ConfigModel):
    model: NonEmptyText
    selectable_models: list[NonEmptyText]
    request_timeout_seconds: int = Field(ge=1, le=900)
    request_attempts: int = Field(ge=1, le=10)
    max_inline_request_bytes: int = Field(ge=1_000_000, le=20_000_000)

    @model_validator(mode="after")
    def default_model_must_be_selectable(self) -> Self:
        if len(self.selectable_models) != len(set(self.selectable_models)):
            raise ValueError("selectable_models must be unique")
        if self.model not in self.selectable_models:
            raise ValueError("default model must appear in selectable_models")
        return self


class GeminiConfig(ModelProviderConfig):
    api_version: NonEmptyText


class StructuredProviderConfig(ModelProviderConfig):
    max_output_tokens: int = Field(ge=1024, le=128_000)


class ProviderConfig(ConfigModel):
    name: ProviderName
    gemini: GeminiConfig
    openai: StructuredProviderConfig
    anthropic: StructuredProviderConfig

    def settings_for(self, name: ProviderName) -> ModelProviderConfig:
        return {"gemini": self.gemini, "openai": self.openai, "anthropic": self.anthropic}[name]

    @property
    def selected(self) -> ModelProviderConfig:
        return self.settings_for(self.name)

    def provider_for_model(self, model: str) -> ProviderName:
        for name in ("gemini", "openai", "anthropic"):
            if model in self.settings_for(name).selectable_models:
                return name
        raise ValueError("Select a model allowed by the project configuration")

    @model_validator(mode="after")
    def model_names_are_unambiguous(self) -> Self:
        models = [
            model
            for name in ("gemini", "openai", "anthropic")
            for model in self.settings_for(name).selectable_models
        ]
        if len(models) != len(set(models)):
            raise ValueError("selectable model IDs must be unique across providers")
        return self


class WebConfig(ConfigModel):
    language_choices: list[NonEmptyText] = Field(min_length=1)
    host: Literal["127.0.0.1", "::1", "localhost"]
    port: int = Field(ge=1, le=65_535)
    open_browser_on_start: bool
    max_upload_bytes: int = Field(ge=1_000_000, le=1_000_000_000)
    max_concurrent_jobs: int = Field(ge=1, le=4)
    max_pdf_pages: int = Field(ge=1, le=10_000)
    max_glossary_entries: int = Field(ge=0, le=10_000)
    max_term_characters: int = Field(ge=1, le=4_000)
    max_instruction_characters: int = Field(ge=1, le=4_000)
    uncertainty_level_choices: list[Literal["off", "low", "standard", "high"]]
    status_poll_interval_ms: int = Field(ge=250, le=30_000)
    review_zoom_levels: list[int]
    review_zoom_default_percent: int = Field(ge=50, le=400)
    auto_continue_default: bool
    auto_continue_attempts: int = Field(ge=1, le=10)

    @model_validator(mode="after")
    def web_choices_are_selectable_and_bounded(self) -> Self:
        if len(self.language_choices) != len(set(self.language_choices)):
            raise ValueError("language_choices must be unique")
        if any(
            language.casefold() in {"custom", "__custom__"} or len(language) > 100
            for language in self.language_choices
        ):
            raise ValueError("language choices must be at most 100 characters and cannot be Custom")
        if not self.uncertainty_level_choices:
            raise ValueError("uncertainty_level_choices must not be empty")
        if len(self.uncertainty_level_choices) != len(set(self.uncertainty_level_choices)):
            raise ValueError("uncertainty_level_choices must be unique")
        if "off" not in self.uncertainty_level_choices:
            raise ValueError("uncertainty_level_choices must include off")
        if not self.review_zoom_levels:
            raise ValueError("review_zoom_levels must not be empty")
        if len(self.review_zoom_levels) != len(set(self.review_zoom_levels)):
            raise ValueError("review_zoom_levels must be unique")
        if any(level < 50 or level > 400 for level in self.review_zoom_levels):
            raise ValueError("review_zoom_levels must contain values from 50 to 400")
        if self.review_zoom_levels != sorted(self.review_zoom_levels):
            raise ValueError("review_zoom_levels must be in ascending order")
        if self.review_zoom_default_percent not in self.review_zoom_levels:
            raise ValueError("review_zoom_default_percent must appear in review_zoom_levels")
        return self


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


class ProjectConfig(ConfigModel):
    """Fully resolved, non-secret application configuration."""

    config_version: Literal[1]
    paths: PathsConfig
    extraction: ExtractionConfig
    provider: ProviderConfig
    translation: ConfiguredTranslationSettings
    export: ConfiguredMarkdownExportSettings
    pdf_export: PdfExportConfig
    web: WebConfig

    @model_validator(mode="after")
    def default_uncertainty_level_must_be_selectable(self) -> Self:
        default_choice = (
            self.translation.uncertainty_level.value
            if self.translation.mark_uncertain_terms
            else "off"
        )
        if default_choice not in self.web.uncertainty_level_choices:
            raise ValueError(
                "the configured uncertainty default must appear in uncertainty_level_choices"
            )
        return self


def load_project_config(path: Path) -> ProjectConfig:
    if not path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {path}")
    try:
        with path.open("rb") as handle:
            data = load(handle)
        config = ProjectConfig.model_validate(data)
        artifacts_dir = config.paths.artifacts_dir
        if not artifacts_dir.is_absolute():
            artifacts_dir = (path.resolve().parent / artifacts_dir).resolve()
            config = config.model_copy(
                update={"paths": config.paths.model_copy(update={"artifacts_dir": artifacts_dir})}
            )
        return config
    except TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {path}: {exc}") from exc
