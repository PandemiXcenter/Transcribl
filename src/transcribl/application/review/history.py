from __future__ import annotations

from uuid import uuid4

from transcribl.domain.editorial import (
    BlockRevision,
    ReviewBlock,
)
from transcribl.domain.enums import BlockType, ReviewStatus
from transcribl.domain.errors import (
    EditorialError,
)
from transcribl.domain.models import (
    DocumentTranslation,
)
from transcribl.ports.editorial import RevisionRepository


def validated_revisions(
    revisions: list[BlockRevision],
    document_id: str,
    translation_run_id: str,
    block_id: str,
) -> list[BlockRevision]:
    ordered = sorted(revisions, key=lambda revision: revision.revision_number)
    previous_number = 0
    previous_resolved: set[str] = set()
    for revision in ordered:
        if (
            revision.document_id != document_id
            or revision.translation_run_id != translation_run_id
            or revision.block_id != block_id
        ):
            raise EditorialError("Revision repository returned an incorrectly scoped revision")
        if (
            revision.base_revision != previous_number
            or revision.revision_number != previous_number + 1
        ):
            raise EditorialError(f"Revision history is not contiguous for block {block_id}")
        resolved = set(revision.resolved_uncertainty_ids)
        if not previous_resolved.issubset(resolved):
            raise EditorialError(f"Resolved uncertainties regressed for block {block_id}")
        previous_number = revision.revision_number
        previous_resolved = resolved
    return ordered


def resolved_ids_for_block(
    repository: RevisionRepository,
    document_id: str,
    translation_run_id: str,
    block_id: str,
) -> set[str]:
    revisions = validated_revisions(
        repository.list_block_revisions(document_id, translation_run_id, block_id),
        document_id,
        translation_run_id,
        block_id,
    )
    return set(revisions[-1].resolved_uncertainty_ids) if revisions else set()


def make_revision(
    *,
    document: DocumentTranslation,
    translation_run_id: str,
    block: ReviewBlock,
    editorial_text: str,
    effective_type: BlockType | None = None,
    footnote_owner_block_id: str | None = None,
    footnote_anchor_offset: int | None = None,
    footnote_owner_review_required: bool | None = None,
    status: ReviewStatus,
    editor: str | None,
    note: str | None,
    resolved_uncertainty_ids: set[str],
) -> BlockRevision:
    return BlockRevision(
        schema_version="2.0",
        revision_id=f"revision-{uuid4()}",
        document_id=document.document_id,
        translation_run_id=translation_run_id,
        block_id=block.block_id,
        revision_number=block.latest_revision_number + 1,
        base_revision=block.latest_revision_number,
        editorial_text=editorial_text,
        effective_type=effective_type or block.type,
        footnote_owner_block_id=(
            footnote_owner_block_id if effective_type is not None else block.footnote_owner_block_id
        ),
        footnote_anchor_offset=(
            footnote_anchor_offset if effective_type is not None else block.footnote_anchor_offset
        ),
        footnote_owner_review_required=(
            footnote_owner_review_required
            if effective_type is not None
            else block.footnote_owner_review_required
        ),
        status=status,
        editor=editor,
        note=note,
        resolved_uncertainty_ids=sorted(resolved_uncertainty_ids),
    )
