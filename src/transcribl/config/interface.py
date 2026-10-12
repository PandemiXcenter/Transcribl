from typing import Literal, Self

from pydantic import Field, model_validator

from transcribl.config.base import ConfigModel
from transcribl.domain.models import (
    NonEmptyText,
)
from transcribl.domain.preferences import (
    StyleName,
    StylePrompt,
)


class DesktopConfig(ConfigModel):
    window_width: int = Field(ge=800, le=7680)
    window_height: int = Field(ge=600, le=4320)
    minimum_width: int = Field(ge=640, le=7680)
    minimum_height: int = Field(ge=480, le=4320)

    @model_validator(mode="after")
    def minimum_fits_window(self) -> Self:
        if self.minimum_width > self.window_width or self.minimum_height > self.window_height:
            raise ValueError("Desktop minimum dimensions must fit the initial window")
        return self


class WebConfig(ConfigModel):
    language_choices: list[NonEmptyText] = Field(min_length=1)
    host: Literal["127.0.0.1", "::1", "localhost"]
    port: int = Field(ge=1, le=65_535)
    open_browser_on_start: bool
    max_upload_bytes: int = Field(ge=1_000_000, le=1_000_000_000)
    max_concurrent_jobs: int = Field(ge=1, le=4)
    max_pdf_pages: int = Field(ge=1, le=10_000)
    max_glossary_name_characters: int = Field(ge=1, le=500)
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


class WorkbenchConfig(ConfigModel):
    default_glossary: NonEmptyText
    max_styles: int = Field(ge=3, le=50)
    max_style_prompt_characters: int = Field(ge=1, le=4000)
    style_prompts: dict[StyleName, StylePrompt] = Field(min_length=3, max_length=50)
