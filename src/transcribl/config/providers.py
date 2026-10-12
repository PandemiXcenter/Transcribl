from typing import Self

from pydantic import Field, model_validator

from transcribl.config.base import ConfigModel
from transcribl.domain.models import (
    NonEmptyText,
)
from transcribl.domain.preferences import (
    ThinkingLevel,
)
from transcribl.domain.providers import SUPPORTED_PROVIDERS, ProviderName


class ModelProviderConfig(ConfigModel):
    model: NonEmptyText
    selectable_models: list[NonEmptyText]
    request_timeout_seconds: int = Field(ge=1, le=900)
    request_attempts: int = Field(ge=1, le=10)
    max_inline_request_bytes: int = Field(ge=1_000_000, le=20_000_000)
    thinking_level: ThinkingLevel
    thinking_level_choices: list[ThinkingLevel] = Field(min_length=1)

    @model_validator(mode="after")
    def default_model_must_be_selectable(self) -> Self:
        if len(self.selectable_models) != len(set(self.selectable_models)):
            raise ValueError("selectable_models must be unique")
        if self.model not in self.selectable_models:
            raise ValueError("default model must appear in selectable_models")
        if self.thinking_level not in self.thinking_level_choices:
            raise ValueError("thinking_level must appear in thinking_level_choices")
        if len(self.thinking_level_choices) != len(set(self.thinking_level_choices)):
            raise ValueError("thinking_level_choices must be unique")
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
        for name in SUPPORTED_PROVIDERS:
            if model in self.settings_for(name).selectable_models:
                return name
        raise ValueError("Select a model allowed by the project configuration")

    @model_validator(mode="after")
    def model_names_are_unambiguous(self) -> Self:
        models = [
            model
            for name in SUPPORTED_PROVIDERS
            for model in self.settings_for(name).selectable_models
        ]
        if len(models) != len(set(models)):
            raise ValueError("selectable model IDs must be unique across providers")
        return self
