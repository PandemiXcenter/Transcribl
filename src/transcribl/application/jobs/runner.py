from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from transcribl.application.jobs.records import (
    JobRecord,
    LocalJobStatus,
    PipelineFactory,
    RepositoryFactory,
    TranslatorFactory,
    update_record,
)
from transcribl.application.jobs.validation import public_error_message, validate_resume_inputs
from transcribl.application.prompting import PROMPT_VERSION, TABLE_PROMPT_VERSION
from transcribl.config import ProjectConfig
from transcribl.domain.enums import JobStatus
from transcribl.domain.errors import ArtifactError, TranscriblError
from transcribl.domain.models import (
    DocumentTranslation,
    utc_now,
)
from transcribl.ports.translation import (
    PageTranslationRequest,
    PageTranslator,
    ProviderDescriptor,
    ProviderResult,
    TableReconstructionRequest,
    TableReconstructionResult,
)


class ProgressTranslator:
    def __init__(
        self,
        inner: PageTranslator,
        page_started: Callable[[int], None],
    ) -> None:
        self._inner = inner
        self._page_started = page_started

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._inner.descriptor

    def translate_page(self, request: PageTranslationRequest) -> ProviderResult:
        self._page_started(request.original_page_number)
        return self._inner.translate_page(request)

    def reconstruct_tables(
        self,
        request: TableReconstructionRequest,
    ) -> TableReconstructionResult:
        return self._inner.reconstruct_tables(request)


def _remove_staged_upload(upload_path: Path, artifacts_dir: Path) -> None:
    uploads_root = (artifacts_dir / ".uploads").resolve()
    staging_directory = upload_path.parent.resolve()
    if (
        staging_directory.parent == uploads_root
        and staging_directory.is_dir()
        and upload_path.resolve().is_relative_to(staging_directory)
    ):
        shutil.rmtree(staging_directory)


class JobRunner:
    """Executes preparation, translation and bounded inline retries for one record."""

    def __init__(
        self,
        config: ProjectConfig,
        pipeline_factory: PipelineFactory,
        repository_factory: RepositoryFactory,
        translator_factory: TranslatorFactory,
        completed: Callable[[Path, DocumentTranslation], None],
    ) -> None:
        self._config = config
        self._pipeline_factory = pipeline_factory
        self._repository_factory = repository_factory
        self._translator_factory = translator_factory
        self._completed = completed

    def run(self, record: JobRecord) -> None:
        self._execute(record, resume=False)

    def resume(self, record: JobRecord) -> None:
        self._execute(record, resume=True)

    def _execute(self, record: JobRecord, *, resume: bool) -> None:
        try:
            pipeline = self._pipeline_factory()
            if resume:
                if record.job_dir is None or record.translation_run_id is None:
                    raise ArtifactError("The stopped translation has no resumable run")
                job_dir = record.job_dir
                manifest = self._repository_factory(job_dir).read_manifest()
                update_record(record, status=LocalJobStatus.TRANSLATING)
            else:
                if record.upload_path is None:
                    raise ArtifactError("A new translation requires a staged PDF upload")
                update_record(record, status=LocalJobStatus.PREPARING)
                job_dir = pipeline.prepare_document(
                    record.upload_path,
                    artifacts_dir=record.runtime_config.paths.artifacts_dir,
                    image_dpi=record.runtime_config.extraction.image_dpi,
                )
                repository = self._repository_factory(job_dir)
                manifest = repository.read_manifest()
                if manifest.page_count > record.runtime_config.web.max_pdf_pages:
                    raise ArtifactError(
                        f"PDF has {manifest.page_count} pages; configured maximum is "
                        f"{record.runtime_config.web.max_pdf_pages}"
                    )
                manifest = manifest.model_copy(
                    update={
                        "auto_continue": record.auto_continue,
                        "auto_continue_attempts": record.auto_continue_attempts,
                        "updated_at": utc_now(),
                    }
                )
                repository.write_manifest(manifest)
                update_record(
                    record,
                    status=LocalJobStatus.TRANSLATING,
                    total_pages=manifest.page_count,
                    job_dir=job_dir,
                )

            with self._translator_factory(record.runtime_config, record.api_key) as translator:
                descriptor = translator.descriptor
                if resume:
                    assert record.translation_run_id is not None
                    validate_resume_inputs(
                        manifest, record.translation_run_id, record.settings, descriptor
                    )
                    force_translation = False
                else:
                    force_translation = manifest.translation_run_id is not None and (
                        manifest.translation_settings != record.settings
                        or manifest.provider_name != descriptor.provider
                        or manifest.provider_model != descriptor.model
                        or manifest.provider_semantic_configuration
                        != dict(descriptor.semantic_configuration)
                        or manifest.prompt_version != PROMPT_VERSION
                        or manifest.table_prompt_version != TABLE_PROMPT_VERSION
                    )
                progress = ProgressTranslator(
                    translator, lambda page: update_record(record, current_page=page)
                )
                document = pipeline.translate_document(
                    job_dir, settings=record.settings, translator=progress, force=force_translation
                )
            pipeline.compile_document(job_dir, settings=record.runtime_config.export)
            self._completed(job_dir, document)
            update_record(
                record,
                status=LocalJobStatus.READY,
                current_page=document.page_count,
                total_pages=document.page_count,
                error=None,
                translation_run_id=document.translation_run_id,
            )
        except Exception as exc:
            self._capture_failed_run(record)
            if self._continue_automatically(record):
                return
            update_record(record, status=LocalJobStatus.FAILED, error=public_error_message(exc))
        finally:
            with record.lock:
                record.api_key = None
            if not resume and record.upload_path is not None:
                _remove_staged_upload(record.upload_path, self._config.paths.artifacts_dir)

    def _continue_automatically(self, record: JobRecord) -> bool:
        """Retry a failed page inline without deadlocking the bounded executor."""

        with record.lock:
            if (
                not record.auto_continue
                or record.automatic_continuations_remaining <= 0
                or record.job_dir is None
                or record.translation_run_id is None
            ):
                return False
            job_dir = record.job_dir
        try:
            manifest = self._repository_factory(job_dir).read_manifest()
        except (TranscriblError, OSError, ValueError):
            return False
        if (
            manifest.status is not JobStatus.FAILED
            or manifest.translation_run_id != record.translation_run_id
        ):
            return False
        with record.lock:
            if record.automatic_continuations_remaining <= 0:
                return False
            record.automatic_continuations_remaining -= 1
            record.status = LocalJobStatus.QUEUED
            record.error = None
        self.resume(record)
        return True

    def _capture_failed_run(self, record: JobRecord) -> None:
        if record.job_dir is None:
            return
        try:
            manifest = self._repository_factory(record.job_dir).read_manifest()
        except (TranscriblError, OSError, ValueError):
            return
        if manifest.translation_run_id is not None:
            update_record(
                record,
                translation_run_id=manifest.translation_run_id,
                total_pages=manifest.page_count,
            )
