"""Non-secret workbench defaults, separate from immutable translation runs."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ThinkingLevel = Literal["default", "minimal", "low", "medium", "high", "xhigh", "max"]
StyleName = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")]
StylePrompt = Annotated[str, Field(min_length=1, max_length=4000)]


class WorkbenchPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_model: str = Field(min_length=1, max_length=200)
    default_style: StyleName
    default_glossary: str = Field(min_length=1, max_length=100)
    style_prompts: dict[StyleName, StylePrompt] = Field(min_length=3, max_length=50)
    thinking_levels: dict[str, ThinkingLevel]
    previous_page_context_count: int = Field(ge=0, le=10)
    image_dpi: int = Field(ge=72, le=600)
    uncertainty_level: Literal["off", "low", "standard", "high"]
    auto_continue: bool

    @model_validator(mode="after")
    def choices_exist(self) -> Self:
        if not {"faithful", "balanced", "readable"}.issubset(self.style_prompts):
            raise ValueError("Keep the faithful, balanced, and readable styles")
        if len({name.casefold() for name in self.style_prompts}) != len(self.style_prompts):
            raise ValueError("Style names must be unique, ignoring case")
        if any(not prompt.strip() for prompt in self.style_prompts.values()):
            raise ValueError("Style instructions cannot be blank")
        if self.default_style not in self.style_prompts:
            raise ValueError("Select an existing default style")
        if set(self.thinking_levels) != {"gemini", "openai", "anthropic"}:
            raise ValueError("Configure thinking for each provider")
        return self


class SavedPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    values: WorkbenchPreferences


class PreferencesConflictError(ValueError):
    pass


class PreferencesStorageError(ValueError):
    pass
