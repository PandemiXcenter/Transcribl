from __future__ import annotations

from transcribl.application.costs import recorded_cost
from transcribl.application.editorial import EditorialService
from transcribl.application.jobs.records import (
    CompletedRun,
    LocalJobStatus,
    RepositoryFactory,
    ReviewSnapshot,
)
from transcribl.config import ProjectConfig
from transcribl.domain.errors import TranscriblError


def review_snapshot(
    record: CompletedRun, config: ProjectConfig, repository_factory: RepositoryFactory
) -> ReviewSnapshot:
    continue_page = 1
    accepted_blocks = 0
    total_blocks = 0
    review_complete = False
    updated_at = record.completed_at
    try:
        repository = repository_factory(record.job_dir)
        review = EditorialService(repository).review_document(
            record.document,
            record.translation_run_id,
        )
        blocks = [block for page in review.pages for block in page.blocks]
        total_blocks = len(blocks)
        accepted_blocks = sum(block.review_status.value == "accepted" for block in blocks)
        review_complete = accepted_blocks == total_blocks
        position = repository.read_review_position(
            record.document_id,
            record.translation_run_id,
        )
        if position is not None and position.original_page_number <= record.page_count:
            continue_page = position.original_page_number
            updated_at = max(updated_at, position.updated_at)
    except (TranscriblError, OSError, ValueError):
        pass
    return ReviewSnapshot(
        job_id=record.translation_run_id,
        status=LocalJobStatus.READY,
        filename=record.filename,
        page_count=record.page_count,
        continue_page=continue_page,
        accepted_blocks=accepted_blocks,
        total_blocks=total_blocks,
        review_complete=review_complete,
        translation_run_id=record.translation_run_id,
        updated_at=updated_at,
        cost=recorded_cost(record.document, config.costs).model_dump(mode="json"),
    )
