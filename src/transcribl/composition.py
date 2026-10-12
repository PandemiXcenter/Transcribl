from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import SecretStr

from transcribl.adapters.extraction import MarkItDownPageExtractor
from transcribl.adapters.llm import GeminiPageTranslator
from transcribl.adapters.llm.structured import AnthropicPageTranslator, OpenAIPageTranslator
from transcribl.adapters.storage import FilesystemArtifactRepository
from transcribl.application.pipeline import TranslationPipeline
from transcribl.config import ProjectConfig, SecretSettings
from transcribl.domain.models import DocumentTranslation
from transcribl.ports.translation import PageTranslator
from transcribl.runtime import default_secret_path


def build_pipeline() -> TranslationPipeline:
    """Compose provider-neutral application services with local adapters."""

    return TranslationPipeline(
        extractor=MarkItDownPageExtractor(),
        repository_factory=lambda root: FilesystemArtifactRepository(root),
    )


@contextmanager
def provider_translator(
    config: ProjectConfig,
    *,
    api_key: SecretStr | None = None,
    secret_path: Path | None = None,
) -> Iterator[PageTranslator]:
    """Build one configured provider adapter without leaking its secret."""

    name = config.provider.name
    key_path = secret_path or default_secret_path()
    if name != "gemini":
        key_path = key_path.with_name(".provider-keys")
    secret = api_key or SecretSettings(_env_file=key_path).for_provider(name)
    if secret is None:
        raise ValueError(
            f"{name.upper()}_API_KEY is required in the environment or saved in Settings"
        )
    if name in ("openai", "anthropic"):
        adapter = OpenAIPageTranslator if name == "openai" else AnthropicPageTranslator
        settings = config.provider.openai if name == "openai" else config.provider.anthropic
        with adapter(api_key=secret.get_secret_value(), config=settings) as structured_translator:
            yield structured_translator
        return
    gemini = config.provider.gemini
    with GeminiPageTranslator(
        api_key=secret.get_secret_value(),
        model=gemini.model,
        api_version=gemini.api_version,
        timeout_seconds=gemini.request_timeout_seconds,
        attempts=gemini.request_attempts,
        max_inline_request_bytes=gemini.max_inline_request_bytes,
        thinking_level=gemini.thinking_level,
    ) as translator:
        yield translator


def translate_with_config(
    config: ProjectConfig,
    job_dir: Path,
    *,
    force: bool,
    pipeline: TranslationPipeline | None = None,
) -> DocumentTranslation:
    """Translate through the same composition boundary for CLI and web."""

    active_pipeline = pipeline or build_pipeline()
    with provider_translator(config) as translator:
        return active_pipeline.translate_document(
            job_dir,
            settings=config.translation,
            translator=translator,
            force=force,
        )


# Retain the previous composition entry point for local integrations.
gemini_translator = provider_translator
