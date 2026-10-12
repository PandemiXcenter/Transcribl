from __future__ import annotations

from typing import TYPE_CHECKING

from transcribl.domain.enums import TranslationStyle, UncertaintyLevel
from transcribl.domain.preferences import (
    WorkbenchPreferences,
)
from transcribl.domain.providers import SUPPORTED_PROVIDERS

if TYPE_CHECKING:
    from transcribl.config.project import ProjectConfig


def workbench_defaults(config: ProjectConfig) -> WorkbenchPreferences:
    return WorkbenchPreferences(
        currency=config.costs.default_currency,
        default_model=config.provider.selected.model,
        default_style=config.translation.style_name or config.translation.style.value,
        default_glossary=config.workbench.default_glossary,
        style_prompts=config.workbench.style_prompts,
        thinking_levels={
            name: config.provider.settings_for(name).thinking_level for name in SUPPORTED_PROVIDERS
        },
        previous_page_context_count=config.translation.previous_page_context_count,
        image_dpi=config.extraction.image_dpi,
        uncertainty_level=(
            config.translation.uncertainty_level.value
            if config.translation.mark_uncertain_terms
            else "off"
        ),
        auto_continue=config.web.auto_continue_default,
    )


def resolve_workbench_preferences(
    config: ProjectConfig, preferences: WorkbenchPreferences
) -> ProjectConfig:
    """Resolve validated saved defaults into an isolated per-job configuration."""
    if preferences.currency not in config.costs.currency_choices:
        raise ValueError("Select a configured currency")
    name = config.provider.provider_for_model(preferences.default_model)
    provider = config.provider.model_copy(deep=True)
    provider.name = name
    provider.settings_for(name).model = preferences.default_model
    for company in SUPPORTED_PROVIDERS:
        settings = provider.settings_for(company)
        level = preferences.thinking_levels[company]
        if level not in settings.thinking_level_choices:
            raise ValueError(f"Unsupported thinking level for {company}")
        settings.thinking_level = level
    if preferences.uncertainty_level not in config.web.uncertainty_level_choices:
        raise ValueError("Select a configured uncertainty level")
    if any(
        len(p) > config.workbench.max_style_prompt_characters
        for p in preferences.style_prompts.values()
    ):
        raise ValueError("Style instructions exceed the configured character limit")
    if len(preferences.style_prompts) > config.workbench.max_styles:
        raise ValueError("Too many styles")
    style = preferences.default_style
    translation = config.translation.model_copy(
        update={
            "style": TranslationStyle(style)
            if style in {s.value for s in TranslationStyle}
            else TranslationStyle.CUSTOM,
            "style_name": style,
            "style_prompt": preferences.style_prompts[style],
            "previous_page_context_count": preferences.previous_page_context_count,
            "mark_uncertain_terms": preferences.uncertainty_level != "off",
            "uncertainty_level": UncertaintyLevel(preferences.uncertainty_level)
            if preferences.uncertainty_level != "off"
            else config.translation.uncertainty_level,
        }
    )
    return config.model_copy(
        update={
            "costs": config.costs.model_copy(update={"default_currency": preferences.currency}),
            "provider": provider,
            "translation": translation,
            "extraction": config.extraction.model_copy(update={"image_dpi": preferences.image_dpi}),
            "web": config.web.model_copy(
                update={"auto_continue_default": preferences.auto_continue}
            ),
            "workbench": config.workbench.model_copy(
                update={
                    "default_glossary": preferences.default_glossary,
                    "style_prompts": preferences.style_prompts,
                }
            ),
        }
    )
