from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from threading import RLock

from pydantic import SecretStr

from transcribl.application.pipeline import TranslationPipeline
from transcribl.config import ProjectConfig
from transcribl.domain.errors import TranscriblError
from transcribl.domain.models import (
    DocumentTranslation,
    TranslationSettings,
)
from transcribl.ports.artifacts import ArtifactRepository
from transcribl.ports.translation import (
    PageTranslator,
)

PipelineFactory = Callable[[], TranslationPipeline]

RepositoryFactory = Callable[[Path], ArtifactRepository]

TranslatorFactory = Callable[
    [ProjectConfig, SecretStr | None],
    AbstractContextManager[PageTranslator],
]


class LocalJobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    TRANSLATING = "translating"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobNotFoundError(TranscriblError):
    """An opaque browser job ID or stable completed-run ID was not found."""


class JobNotReadyError(TranscriblError):
    """Review data was requested before translation completed."""


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    status: LocalJobStatus
    filename: str
    current_page: int
    total_pages: int | None
    error: str | None
    translation_run_id: str | None
    provider: str | None = None
    cost: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ReviewSnapshot:
    """One completed translation run available in the Articles catalog."""

    job_id: str
    status: LocalJobStatus
    filename: str
    page_count: int
    continue_page: int
    accepted_blocks: int
    total_blocks: int
    review_complete: bool
    translation_run_id: str
    updated_at: datetime
    cost: dict[str, object] | None = None


@dataclass(slots=True)
class JobRecord:
    job_id: str
    filename: str
    upload_path: Path | None
    settings: TranslationSettings
    runtime_config: ProjectConfig
    api_key: SecretStr | None
    auto_continue: bool
    auto_continue_attempts: int
    automatic_continuations_remaining: int = 0
    status: LocalJobStatus = LocalJobStatus.QUEUED
    current_page: int = 0
    total_pages: int | None = None
    error: str | None = None
    job_dir: Path | None = None
    translation_run_id: str | None = None
    lock: RLock = field(default_factory=RLock)

    def snapshot(self) -> JobSnapshot:
        with self.lock:
            return JobSnapshot(
                job_id=self.job_id,
                status=self.status,
                filename=self.filename,
                current_page=self.current_page,
                total_pages=self.total_pages,
                error=self.error,
                translation_run_id=self.translation_run_id,
                provider=self.runtime_config.provider.name,
            )


@dataclass(frozen=True, slots=True)
class CompletedRun:
    job_dir: Path
    document: DocumentTranslation
    translation_run_id: str
    document_id: str
    filename: str
    page_count: int
    completed_at: datetime


def update_record(record: JobRecord, **changes: object) -> None:
    with record.lock:
        for name, value in changes.items():
            setattr(record, name, value)
