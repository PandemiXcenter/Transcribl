from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Header,
    HTTPException,
)
from fastapi.responses import JSONResponse

from transcribl.application.prompting import prompt_templates
from transcribl.config import (
    ProviderName,
    resolve_workbench_preferences,
    workbench_defaults,
)
from transcribl.domain.preferences import PreferencesConflictError, PreferencesStorageError
from transcribl.domain.providers import SUPPORTED_PROVIDERS
from transcribl.interfaces.web.credentials import api_key_status, environment_api_key_configured
from transcribl.interfaces.web.schemas import (
    ApiKeySettingsRequest,
    WorkbenchSettingsRequest,
)
from transcribl.interfaces.web.security import require_csrf
from transcribl.interfaces.web.services import WebServices


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    config = services.config
    glossary_service = services.glossaries
    settings_service = services.settings
    local_secret_store = services.secrets

    @router.get("/")
    @router.get("/session")
    def session() -> JSONResponse:
        response = JSONResponse({"application": "Transcribl"})
        response.set_cookie(
            "at_csrf",
            secrets.token_urlsafe(32),
            httponly=False,
            samesite="strict",
            secure=False,
        )
        return response

    @router.get("/api/config")
    def public_config() -> dict[str, object]:
        saved = settings_service.read()
        effective = resolve_workbench_preferences(config, saved.values)
        return {
            "translation": effective.translation.model_dump(mode="json"),
            "preferences": saved.model_dump(mode="json"),
            "settings_defaults": workbench_defaults(config).model_dump(mode="json"),
            "thinking_choices": {
                name: config.provider.settings_for(name).thinking_level_choices
                for name in SUPPORTED_PROVIDERS
            },
            "prompts": prompt_templates(),
            "provider": {
                "name": effective.provider.name,
                "model": effective.provider.selected.model,
                "selectable_models": [
                    model
                    for name in SUPPORTED_PROVIDERS
                    for model in config.provider.settings_for(name).selectable_models
                ],
                "models": [
                    {"id": model, "provider": name}
                    for name in SUPPORTED_PROVIDERS
                    for model in config.provider.settings_for(name).selectable_models
                ],
            },
            "language_choices": config.web.language_choices,
            "api_keys": {
                name: api_key_status(local_secret_store, name) for name in SUPPORTED_PROVIDERS
            },
            "extraction": effective.extraction.model_dump(mode="json"),
            "automation": {
                "auto_continue_default": effective.web.auto_continue_default,
                "auto_continue_attempts": config.web.auto_continue_attempts,
            },
            "review": {
                "zoom_levels": config.web.review_zoom_levels,
                "zoom_default_percent": config.web.review_zoom_default_percent,
            },
            "uncertainty": {
                "level_choices": config.web.uncertainty_level_choices,
            },
            "api_key_configured": (
                environment_api_key_configured(effective.provider.name)
                or local_secret_store.has_api_key(effective.provider.name)
            ),
            "api_key_saved_on_computer": local_secret_store.has_api_key(effective.provider.name),
            "limits": {
                "max_upload_bytes": config.web.max_upload_bytes,
                "max_pdf_pages": config.web.max_pdf_pages,
                "max_glossary_name_characters": config.web.max_glossary_name_characters,
                "max_glossary_entries": config.web.max_glossary_entries,
                "max_term_characters": config.web.max_term_characters,
                "max_instruction_characters": config.web.max_instruction_characters,
                "status_poll_interval_ms": config.web.status_poll_interval_ms,
            },
        }

    @router.put("/api/settings")
    def save_workbench_settings(
        command: WorkbenchSettingsRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        if command.values.default_glossary not in {"none", "configured"} and not any(
            g.glossary_id == command.values.default_glossary
            for g in glossary_service.list_glossaries()
        ):
            raise HTTPException(status_code=422, detail="Select an existing default glossary")
        if command.values.default_glossary == "configured" and not config.translation.glossary:
            raise HTTPException(status_code=422, detail="No configured glossary is available")
        try:
            settings_service.save(command.values, expected_revision=command.expected_revision)
        except (PreferencesConflictError, PreferencesStorageError):
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return public_config()

    @router.post("/api/settings/api-key")
    def save_api_key(
        command: ApiKeySettingsRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        require_csrf(at_csrf, x_csrf_token)
        provider = command.provider or config.provider.provider_for_model(
            settings_service.read().values.default_model
        )
        if command.save_on_computer:
            local_secret_store.save_api_key(provider, command.api_key)
        return api_key_status(local_secret_store, provider)

    @router.delete("/api/settings/api-key")
    def clear_saved_api_key(
        provider: ProviderName | None = None,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, bool]:
        require_csrf(at_csrf, x_csrf_token)
        provider = provider or config.provider.provider_for_model(
            settings_service.read().values.default_model
        )
        local_secret_store.clear_api_key(provider)
        return api_key_status(local_secret_store, provider)

    return router
