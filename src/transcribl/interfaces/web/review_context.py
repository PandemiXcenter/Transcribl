from __future__ import annotations

from fastapi import HTTPException

from transcribl.adapters.storage import FilesystemArtifactRepository
from transcribl.application.editorial import EditorialService
from transcribl.application.jobs.manager import JobManager
from transcribl.application.jobs.records import JobNotFoundError
from transcribl.domain.editorial import (
    ReviewDocument,
)
from transcribl.domain.models import DocumentTranslation


def review_context(
    manager: JobManager,
    job_id: str,
) -> tuple[DocumentTranslation, str, EditorialService, ReviewDocument]:
    repository, document, translation_run_id = document_context(manager, job_id)
    service = EditorialService(repository)
    review = service.review_document(document, translation_run_id)
    return document, translation_run_id, service, review


def document_context(
    manager: JobManager,
    job_id: str,
) -> tuple[FilesystemArtifactRepository, DocumentTranslation, str]:
    try:
        job_dir, translation_run_id = manager.ready_context(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    repository = FilesystemArtifactRepository(job_dir)
    document = repository.read_document(translation_run_id)
    return repository, document, translation_run_id
