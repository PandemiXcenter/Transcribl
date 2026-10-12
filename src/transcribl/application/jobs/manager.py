from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import SecretStr

from transcribl.application.costs import estimate_cost, recorded_cost
from transcribl.application.jobs.catalog import review_snapshot
from transcribl.application.jobs.discovery import discover_completed_runs, discover_failed_jobs
from transcribl.application.jobs.records import (
    CompletedRun,
    JobNotFoundError,
    JobNotReadyError,
    JobRecord,
    JobSnapshot,
    LocalJobStatus,
    PipelineFactory,
    RepositoryFactory,
    ReviewSnapshot,
    TranslatorFactory,
)
from transcribl.application.jobs.runner import JobRunner
from transcribl.application.jobs.validation import (
    SAFE_JOB_DIRECTORY,
    validate_completed_document,
    validate_web_identifier,
)
from transcribl.config import ProjectConfig
from transcribl.domain.costs import CostSummary
from transcribl.domain.enums import JobStatus
from transcribl.domain.errors import ArtifactError
from transcribl.domain.models import (
    DocumentTranslation,
    TranslationSettings,
    utc_now,
)


class JobManager:
    """Bounded local runner with durable discovery of stopped translation runs."""

    def __init__(
        self,
        *,
        config: ProjectConfig,
        pipeline_factory: PipelineFactory,
        repository_factory: RepositoryFactory,
        translator_factory: TranslatorFactory,
    ) -> None:
        self._config = config
        self._repository_factory = repository_factory
        self._records: dict[str, JobRecord] = {}
        self._completed_reviews: dict[str, CompletedRun] = {}
        self._ambiguous_review_ids: set[str] = set()
        self._records_lock = RLock()
        for job_dir, document in discover_completed_runs(config, repository_factory):
            self._register_completed_document(job_dir, document)
        for record in discover_failed_jobs(config, repository_factory):
            self._records.setdefault(record.job_id, record)
        self._runner = JobRunner(
            config,
            pipeline_factory,
            repository_factory,
            translator_factory,
            self._register_completed_document,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=config.web.max_concurrent_jobs,
            thread_name_prefix="transcribl",
        )

    def submit(
        self,
        *,
        upload_path: Path,
        display_filename: str,
        glossary: dict[str, str],
        runtime_config: ProjectConfig | None = None,
        api_key: SecretStr | None = None,
        auto_continue: bool | None = None,
    ) -> JobSnapshot:
        resolved_config = runtime_config or self._config
        resolved_auto_continue = (
            resolved_config.web.auto_continue_default if auto_continue is None else auto_continue
        )
        resolved_glossary = dict(resolved_config.translation.glossary)
        resolved_glossary.update(glossary)
        settings = TranslationSettings.model_validate(
            resolved_config.translation.model_copy(
                update={"glossary": resolved_glossary}
            ).model_dump(mode="python")
        )
        job_id = uuid4().hex
        record = JobRecord(
            job_id=job_id,
            filename=display_filename,
            upload_path=upload_path,
            settings=settings,
            runtime_config=resolved_config,
            api_key=api_key,
            auto_continue=resolved_auto_continue,
            auto_continue_attempts=resolved_config.web.auto_continue_attempts,
            automatic_continuations_remaining=(
                resolved_config.web.auto_continue_attempts if resolved_auto_continue else 0
            ),
        )
        with self._records_lock:
            self._records[job_id] = record
        try:
            self._executor.submit(self._runner.run, record)
        except Exception:
            with self._records_lock:
                self._records.pop(job_id, None)
            with record.lock:
                record.api_key = None
            raise
        return record.snapshot()

    def get(self, job_id: str) -> JobSnapshot:
        validate_web_identifier(job_id)
        with self._records_lock:
            record = self._records.get(job_id)
            completed = self._completed_reviews.get(job_id)
        if record is not None:
            snapshot = record.snapshot()
            if snapshot.status is LocalJobStatus.READY:
                with self._records_lock:
                    completed = self._completed_reviews.get(snapshot.translation_run_id or "")
                if completed is not None:
                    snapshot = replace(
                        snapshot,
                        cost=recorded_cost(completed.document, self._config.costs).model_dump(
                            mode="json"
                        ),
                    )
            return snapshot
        if completed is not None:
            return JobSnapshot(
                job_id=completed.translation_run_id,
                status=LocalJobStatus.READY,
                filename=completed.filename,
                current_page=completed.page_count,
                total_pages=completed.page_count,
                error=None,
                translation_run_id=completed.translation_run_id,
                cost=recorded_cost(completed.document, self._config.costs).model_dump(mode="json"),
            )
        raise JobNotFoundError("Translation job was not found")

    def estimate_cost(self, *, model: str, page_count: int, thinking_level: str) -> CostSummary:
        provider = self._config.provider.provider_for_model(model)
        with self._records_lock:
            documents = [record.document for record in self._completed_reviews.values()]
        return estimate_cost(
            documents,
            self._config.costs,
            model=model,
            provider=provider,
            thinking_level=thinking_level,
            page_count=page_count,
        )

    def list_reviews(self) -> list[ReviewSnapshot]:
        """List every validated completed run known under the artifact root."""

        with self._records_lock:
            completed = list(self._completed_reviews.values())
        snapshots = [
            review_snapshot(record, self._config, self._repository_factory) for record in completed
        ]
        return sorted(
            snapshots,
            key=lambda snapshot: (snapshot.updated_at, snapshot.translation_run_id),
            reverse=True,
        )

    def list_recoverable_jobs(self) -> list[JobSnapshot]:
        """List failed or dismissed active runs whose page checkpoints remain on disk."""

        with self._records_lock:
            records = list(self._records.values())
        snapshots = [record.snapshot() for record in records]
        return sorted(
            (
                snapshot
                for snapshot in snapshots
                if snapshot.status in {LocalJobStatus.FAILED, LocalJobStatus.CANCELLED}
                and snapshot.translation_run_id is not None
            ),
            key=lambda snapshot: snapshot.translation_run_id or "",
        )

    def continue_job(
        self,
        job_id: str,
        *,
        api_key: SecretStr | None = None,
    ) -> JobSnapshot:
        """Resume the same failed run; successful page checkpoints are validated and reused."""

        validate_web_identifier(job_id)
        with self._records_lock:
            record = self._records.get(job_id)
        if record is None:
            raise JobNotFoundError("Translation job was not found")
        with record.lock:
            if record.status not in {LocalJobStatus.FAILED, LocalJobStatus.CANCELLED}:
                raise JobNotReadyError("Only a stopped translation can be continued")
            if record.job_dir is None or record.translation_run_id is None:
                raise JobNotReadyError("The stopped translation has no resumable run")
            previous_status = record.status
            previous_error = record.error
            record.status = LocalJobStatus.QUEUED
            record.error = None
            record.api_key = api_key
            record.automatic_continuations_remaining = (
                record.auto_continue_attempts if record.auto_continue else 0
            )
        try:
            self._executor.submit(self._runner.resume, record)
        except Exception:
            with record.lock:
                record.status = previous_status
                record.error = previous_error
                record.api_key = None
            raise
        return record.snapshot()

    def cancel_job(self, job_id: str) -> JobSnapshot:
        """Dismiss a stopped attempt without deleting its run or page checkpoints."""

        validate_web_identifier(job_id)
        with self._records_lock:
            record = self._records.get(job_id)
        if record is None:
            raise JobNotFoundError("Translation job was not found")
        with record.lock:
            if record.status is LocalJobStatus.CANCELLED:
                return record.snapshot()
            if record.status is not LocalJobStatus.FAILED:
                raise JobNotReadyError("Only a failed translation can be cancelled")
            record.status = LocalJobStatus.CANCELLED
            record.error = "Translation paused. Completed page checkpoints were kept."
            record.api_key = None
            return record.snapshot()

    def ready_context(self, job_id: str) -> tuple[Path, str]:
        validate_web_identifier(job_id)
        with self._records_lock:
            record = self._records.get(job_id)
            completed = self._completed_reviews.get(job_id)
        if record is not None:
            with record.lock:
                if (
                    record.status is not LocalJobStatus.READY
                    or record.job_dir is None
                    or record.translation_run_id is None
                ):
                    raise JobNotReadyError("Translation is not ready for review")
                return record.job_dir, record.translation_run_id
        if completed is not None:
            return completed.job_dir, completed.translation_run_id
        raise JobNotFoundError("Translation job was not found")

    def delete_review(self, translation_run_id: str) -> None:
        """Delete one completed article run and remove it from the durable run index."""

        validate_web_identifier(translation_run_id)
        with self._records_lock:
            completed = self._completed_reviews.get(translation_run_id)
        if completed is None:
            raise JobNotFoundError("Translation job was not found")

        repository = self._repository_factory(completed.job_dir)
        manifest = repository.read_manifest()
        validate_completed_document(
            completed.document,
            manifest,
            translation_run_id,
        )
        remaining_run_ids = [
            run_id for run_id in manifest.translation_run_ids if run_id != translation_run_id
        ]
        changes: dict[str, object] = {
            "translation_run_ids": remaining_run_ids,
            "updated_at": utc_now(),
        }
        if manifest.translation_run_id == translation_run_id:
            changes.update(
                {
                    "status": JobStatus.PREPARED,
                    "translation_run_id": None,
                    "translation_settings": None,
                    "provider_name": None,
                    "provider_model": None,
                    "provider_configuration": None,
                    "provider_semantic_configuration": None,
                    "prompt_version": None,
                    "table_prompt_version": None,
                    "export_settings": None,
                    "auto_continue": False,
                    "auto_continue_attempts": 1,
                }
            )
        updated_manifest = manifest.model_copy(update=changes)
        repository.write_manifest(updated_manifest)
        try:
            repository.delete_translation_run(translation_run_id)
        except Exception:
            repository.write_manifest(manifest)
            raise

        with self._records_lock:
            self._completed_reviews.pop(translation_run_id, None)
            stale_aliases = [
                job_id
                for job_id, record in self._records.items()
                if record.translation_run_id == translation_run_id
            ]
            for job_id in stale_aliases:
                self._records.pop(job_id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _register_completed_document(
        self,
        job_dir: Path,
        document: DocumentTranslation,
    ) -> None:
        if job_dir.is_symlink():
            raise ArtifactError("Completed review directory cannot be a symbolic link")
        resolved_job_dir = job_dir.resolve()
        artifacts_root = self._config.paths.artifacts_dir.resolve()
        if (
            resolved_job_dir.parent != artifacts_root
            or SAFE_JOB_DIRECTORY.fullmatch(resolved_job_dir.name) is None
        ):
            raise ArtifactError("Completed review directory is outside the artifact root")
        translation_run_id = document.translation_run_id
        completed_at = max(page.translated_at for page in document.pages)
        completed = CompletedRun(
            job_dir=resolved_job_dir,
            document=document,
            translation_run_id=translation_run_id,
            document_id=document.document_id,
            filename=document.source_file_name,
            page_count=document.page_count,
            completed_at=completed_at,
        )
        with self._records_lock:
            if translation_run_id in self._ambiguous_review_ids:
                return
            existing = self._completed_reviews.get(translation_run_id)
            if existing is not None and existing.job_dir != resolved_job_dir:
                self._completed_reviews.pop(translation_run_id, None)
                self._ambiguous_review_ids.add(translation_run_id)
                return
            self._completed_reviews[translation_run_id] = completed
