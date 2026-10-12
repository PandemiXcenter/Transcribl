from __future__ import annotations

import re
from pathlib import Path

from transcribl.application.jobs.records import JobNotFoundError, JobNotReadyError
from transcribl.application.prompting import PROMPT_VERSION, TABLE_PROMPT_VERSION
from transcribl.config import ProjectConfig
from transcribl.domain.enums import JobStatus
from transcribl.domain.errors import ArtifactError, TranscriblError
from transcribl.domain.models import (
    DocumentTranslation,
    JobManifest,
    TranslationSettings,
)
from transcribl.domain.providers import SUPPORTED_PROVIDERS
from transcribl.ports.translation import (
    ProviderDescriptor,
)

SAFE_JOB_DIRECTORY = re.compile(r"[a-z0-9][a-z0-9-]{0,59}[a-z0-9]")


def validate_web_identifier(job_id: str) -> None:
    if len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
        raise JobNotFoundError("Translation job was not found")


def safe_direct_job_directory(artifacts_root: Path, candidate: Path) -> Path | None:
    if (
        candidate.name.startswith(".")
        or SAFE_JOB_DIRECTORY.fullmatch(candidate.name) is None
        or candidate.is_symlink()
    ):
        return None
    try:
        if not candidate.is_dir():
            return None
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.parent == artifacts_root else None


def validate_completed_document(
    document: DocumentTranslation,
    manifest: JobManifest,
    translation_run_id: str,
) -> None:
    document_identity = (
        document.job_id,
        document.document_id,
        document.source_file_name,
        document.source_file_sha256,
        document.page_count,
    )
    manifest_identity = (
        manifest.job_id,
        manifest.document_id,
        manifest.source_file_name,
        manifest.source_file_sha256,
        manifest.page_count,
    )
    if document_identity != manifest_identity:
        raise ArtifactError("Completed document identity does not match its manifest")
    if (
        document.translation_run_id != translation_run_id
        or translation_run_id not in manifest.translation_run_ids
    ):
        raise ArtifactError("Completed document run is not indexed by its manifest")


def runtime_config_for_failed_manifest(
    base_config: ProjectConfig,
    manifest: JobManifest,
) -> ProjectConfig:
    """Restore output choices while retaining current operational limits."""

    if manifest.translation_settings is None or manifest.provider_model is None:
        raise ArtifactError("Failed translation manifest is missing resume settings")
    translation = base_config.translation.model_copy(
        update=manifest.translation_settings.model_dump(mode="python")
    )
    extraction = base_config.extraction.model_copy(update={"image_dpi": manifest.image_dpi})
    name = manifest.provider_name
    if name not in SUPPORTED_PROVIDERS:
        raise ArtifactError("Failed translation uses an unsupported provider")
    selected = base_config.provider.settings_for(name).model_copy(
        update={"model": manifest.provider_model}
    )
    provider = base_config.provider.model_copy(update={"name": name, name: selected})
    return base_config.model_copy(
        update={
            "translation": translation,
            "extraction": extraction,
            "provider": provider,
        }
    )


def validate_resume_inputs(
    manifest: JobManifest,
    translation_run_id: str,
    settings: TranslationSettings,
    descriptor: ProviderDescriptor,
) -> None:
    """Refuse to mutate a stopped run when output semantics no longer match."""

    if manifest.status is not JobStatus.FAILED:
        raise JobNotReadyError("The translation run is not stopped at a failed page")
    if manifest.translation_run_id != translation_run_id:
        raise ArtifactError("The stopped translation is no longer the active run")
    if manifest.translation_settings != settings:
        raise ArtifactError("Resume settings no longer match the stopped translation")
    if (
        manifest.provider_name != descriptor.provider
        or manifest.provider_model != descriptor.model
        or (manifest.provider_semantic_configuration or {})
        != dict(descriptor.semantic_configuration)
        or manifest.prompt_version != PROMPT_VERSION
        or manifest.table_prompt_version != TABLE_PROMPT_VERSION
    ):
        raise ArtifactError(
            "Provider or prompt semantics changed since this translation stopped; "
            "the existing run was left unchanged"
        )


def public_error_message(exc: Exception) -> str:
    if isinstance(exc, TranscriblError):
        return " ".join(str(exc).split())[:1_000]
    if isinstance(exc, ValueError):
        return "Translation settings or provider configuration were rejected"
    return f"{type(exc).__name__}: translation failed; private details were not exposed"
