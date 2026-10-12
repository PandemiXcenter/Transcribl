from __future__ import annotations

from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.adapters.secrets.environment import SecretSettings
from transcribl.config import ProviderName
from transcribl.interfaces.web.schemas import (
    ApiKeySettingsRequest,
)


def parse_session_api_key(raw: str | None) -> SecretStr | None:
    if raw is None or not raw.strip():
        return None
    try:
        return ApiKeySettingsRequest(
            api_key=raw,
            save_on_computer=False,
        ).api_key
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="API key must be a nonblank single-line value",
        ) from exc


def api_key_status(secret_store: DotenvSecretStore, provider: ProviderName) -> dict[str, bool]:
    return {
        "api_key_configured": (
            environment_api_key_configured(provider) or secret_store.has_api_key(provider)
        ),
        "saved_on_computer": secret_store.has_api_key(provider),
    }


def environment_api_key_configured(provider: ProviderName) -> bool:
    try:
        return SecretSettings(_env_file=None).for_provider(provider) is not None
    except ValidationError:
        return False
