from __future__ import annotations

import json

from fastapi import HTTPException

from transcribl.config import (
    ProjectConfig,
)
from transcribl.domain.enums import TranslationStyle, UncertaintyLevel
from transcribl.domain.glossaries import (
    GlossaryEntry,
)
from transcribl.interfaces.web.schemas import (
    JobTranslationSettings,
)


def parse_glossary(raw: str, config: ProjectConfig) -> dict[str, str]:
    try:
        decoded = json.loads(raw)
        if not isinstance(decoded, list):
            raise TypeError
        entries = [GlossaryEntry.model_validate(item) for item in decoded]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="Glossary must contain valid term mappings"
        ) from exc

    if len(entries) > config.web.max_glossary_entries:
        raise HTTPException(
            status_code=413,
            detail=f"Glossary exceeds the configured {config.web.max_glossary_entries}-entry limit",
        )

    glossary: dict[str, str] = {}
    normalized_sources: set[str] = set()
    for entry in entries:
        source = entry.source_term.strip()
        target = entry.target_translation.strip()
        if (
            len(source) > config.web.max_term_characters
            or len(target) > config.web.max_term_characters
        ):
            raise HTTPException(
                status_code=422,
                detail="A glossary term exceeds the configured character limit",
            )
        normalized = source.casefold()
        if normalized in normalized_sources:
            raise HTTPException(status_code=422, detail=f"Duplicate glossary term: {source}")
        normalized_sources.add(normalized)
        glossary[source] = target
    return glossary


def parse_job_settings(
    raw: str | None,
    config: ProjectConfig,
) -> tuple[ProjectConfig, bool]:
    if raw is None or not raw.strip():
        requested = JobTranslationSettings(
            model=config.provider.selected.model,
            source_language=config.translation.source_language,
            target_language=config.translation.target_language,
            style=config.translation.style_name or config.translation.style.value,
            footnote_appearance_instructions=(config.translation.footnote_appearance_instructions),
            uncertainty_level=(
                config.translation.uncertainty_level.value
                if config.translation.mark_uncertain_terms
                else "off"
            ),
            uncertainty_instructions=config.translation.uncertainty_instructions,
            previous_page_context_count=config.translation.previous_page_context_count,
            image_dpi=config.extraction.image_dpi,
            auto_continue=config.web.auto_continue_default,
        )
    else:
        try:
            requested = JobTranslationSettings.model_validate_json(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="Translation settings are invalid",
            ) from exc

    try:
        selected_provider = config.provider.provider_for_model(requested.model)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Select a model allowed by the project configuration",
        ) from None
    if requested.style not in config.workbench.style_prompts:
        raise HTTPException(status_code=422, detail="Select a configured translation style")
    if len(requested.footnote_appearance_instructions or "") > (
        config.web.max_instruction_characters
    ):
        raise HTTPException(
            status_code=422,
            detail="Footnote appearance guidance exceeds the configured character limit",
        )
    selected_uncertainty_level = requested.uncertainty_level or (
        config.translation.uncertainty_level.value
        if config.translation.mark_uncertain_terms
        else "off"
    )
    if selected_uncertainty_level not in config.web.uncertainty_level_choices:
        raise HTTPException(
            status_code=422,
            detail="Select an uncertainty level allowed by the project configuration",
        )
    if len(requested.uncertainty_instructions or "") > config.web.max_instruction_characters:
        raise HTTPException(
            status_code=422,
            detail="Uncertainty instructions exceed the configured character limit",
        )

    provider = config.provider.model_copy(
        update={
            "name": selected_provider,
            selected_provider: config.provider.settings_for(selected_provider).model_copy(
                update={"model": requested.model}
            ),
        }
    )
    translation = config.translation.model_copy(
        update={
            "source_language": requested.source_language,
            "target_language": requested.target_language,
            "style": (
                TranslationStyle(requested.style)
                if requested.style in {style.value for style in TranslationStyle}
                else TranslationStyle.CUSTOM
            ),
            "style_name": requested.style,
            "style_prompt": config.workbench.style_prompts[requested.style],
            "footnote_appearance_instructions": (
                requested.footnote_appearance_instructions
                if "footnote_appearance_instructions" in requested.model_fields_set
                else config.translation.footnote_appearance_instructions
            ),
            "mark_uncertain_terms": selected_uncertainty_level != "off",
            "uncertainty_level": (
                UncertaintyLevel(selected_uncertainty_level)
                if selected_uncertainty_level != "off"
                else config.translation.uncertainty_level
            ),
            "uncertainty_instructions": (
                requested.uncertainty_instructions
                if "uncertainty_instructions" in requested.model_fields_set
                else config.translation.uncertainty_instructions
            ),
            "previous_page_context_count": requested.previous_page_context_count,
        }
    )
    extraction = config.extraction.model_copy(update={"image_dpi": requested.image_dpi})
    return (
        config.model_copy(
            update={
                "provider": provider,
                "translation": translation,
                "extraction": extraction,
            }
        ),
        requested.auto_continue,
    )
