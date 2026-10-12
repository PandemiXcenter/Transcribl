from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from transcribl.application.jobs.records import (
    JobRecord,
    LocalJobStatus,
    RepositoryFactory,
)
from transcribl.application.jobs.validation import (
    runtime_config_for_failed_manifest,
    safe_direct_job_directory,
    validate_completed_document,
)
from transcribl.config import ProjectConfig
from transcribl.domain.enums import JobStatus
from transcribl.domain.errors import TranscriblError
from transcribl.domain.models import (
    DocumentTranslation,
)
from transcribl.domain.providers import SUPPORTED_PROVIDERS


def discover_completed_runs(
    config: ProjectConfig, repository_factory: RepositoryFactory
) -> Iterator[tuple[Path, DocumentTranslation]]:

    artifacts_root = config.paths.artifacts_dir.resolve()

    if not artifacts_root.is_dir():
        return

    try:
        candidates = sorted(artifacts_root.iterdir(), key=lambda path: path.name)

    except OSError:
        return

    for candidate in candidates:
        job_dir = safe_direct_job_directory(artifacts_root, candidate)

        if job_dir is None:
            continue

        try:
            repository = repository_factory(job_dir)

            manifest = repository.read_manifest()

            if manifest.job_id != candidate.name:
                continue

        except (TranscriblError, OSError, ValueError):
            continue

        for translation_run_id in manifest.translation_run_ids:
            try:
                document = repository.read_document(translation_run_id)

                validate_completed_document(document, manifest, translation_run_id)

            except (TranscriblError, OSError, ValueError):
                continue

            yield job_dir, document


def discover_failed_jobs(
    config: ProjectConfig, repository_factory: RepositoryFactory
) -> Iterator[JobRecord]:

    artifacts_root = config.paths.artifacts_dir.resolve()

    if not artifacts_root.is_dir():
        return

    try:
        candidates = sorted(artifacts_root.iterdir(), key=lambda path: path.name)

    except OSError:
        return

    for candidate in candidates:
        job_dir = safe_direct_job_directory(artifacts_root, candidate)

        if job_dir is None:
            continue

        try:
            repository = repository_factory(job_dir)

            manifest = repository.read_manifest()

            translation_run_id = manifest.translation_run_id

            if (
                manifest.status is not JobStatus.FAILED
                or translation_run_id is None
                or manifest.translation_settings is None
                or manifest.provider_name not in SUPPORTED_PROVIDERS
                or manifest.provider_model is None
            ):
                continue

            failure = next(
                (
                    repository.read_page_failure(translation_run_id, page_number)
                    for page_number in range(1, manifest.page_count + 1)
                    if repository.has_page_failure(translation_run_id, page_number)
                ),
                None,
            )

            current_page = failure.original_page_number if failure is not None else 1

            error = (
                f"Page {current_page}: {failure.message}"
                if failure is not None
                else "Translation stopped before the document was complete."
            )

            runtime_config = runtime_config_for_failed_manifest(config, manifest)

        except (TranscriblError, OSError, ValueError):
            continue

        yield JobRecord(
            job_id=translation_run_id,
            filename=manifest.source_file_name,
            upload_path=None,
            settings=manifest.translation_settings,
            runtime_config=runtime_config,
            api_key=None,
            auto_continue=manifest.auto_continue,
            auto_continue_attempts=manifest.auto_continue_attempts,
            status=LocalJobStatus.FAILED,
            current_page=current_page,
            total_pages=manifest.page_count,
            error=error,
            job_dir=job_dir,
            translation_run_id=translation_run_id,
        )
