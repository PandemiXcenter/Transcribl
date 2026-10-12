from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from transcribl.domain.providers import ProviderName


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
