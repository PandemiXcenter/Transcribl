"""Stable provider identities shared by configuration, services and interfaces."""

from typing import Literal

ProviderName = Literal["gemini", "openai", "anthropic"]
SUPPORTED_PROVIDERS: tuple[ProviderName, ...] = ("gemini", "openai", "anthropic")
PROVIDER_LABELS: dict[ProviderName, str] = {
    "gemini": "Google (Gemini)",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
}
