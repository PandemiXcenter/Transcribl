from __future__ import annotations

from collections import defaultdict

from transcribl.application.paragraphs import project_paragraphs
from transcribl.application.review.history import validated_revisions
from transcribl.application.review.queries import assert_document_run, iter_machine_blocks
from transcribl.application.review.uncertainties import (
    UncertaintySpec,
    locate_unresolved_specs,
    machine_uncertainty_specs,
    to_fallback,
)
from transcribl.domain.editorial import (
    ReviewBlock,
    ReviewDocument,
    ReviewPage,
    ReviewParagraphGroup,
    UncertaintyFallback,
    UncertaintyHighlight,
)
from transcribl.domain.enums import BlockType, ReviewStatus, SegmentHandling
from transcribl.domain.models import (
    DocumentTranslation,
)
from transcribl.ports.editorial import EditorialRepository


def build_review_document(
    repository: EditorialRepository,
    document: DocumentTranslation,
    translation_run_id: str,
) -> ReviewDocument:
    assert_document_run(document, translation_run_id)
    block_states: dict[
        str,
        tuple[
            str,
            int,
            ReviewStatus,
            set[str],
            BlockType,
            str | None,
            int | None,
            bool,
        ],
    ] = {}
    specs_by_block: dict[str, list[UncertaintySpec]] = {}
    fallbacks_by_block: dict[str, list[UncertaintyFallback]] = {}

    for block in iter_machine_blocks(document):
        revisions = validated_revisions(
            repository.list_block_revisions(
                document.document_id,
                translation_run_id,
                block.block_id,
            ),
            document.document_id,
            translation_run_id,
            block.block_id,
        )
        if revisions:
            latest = revisions[-1]
            effective_text = latest.editorial_text
            latest_number = latest.revision_number
            status = latest.status
            resolved_ids = set(latest.resolved_uncertainty_ids)
            effective_type = latest.effective_type or block.type
            if latest.effective_type is None:
                owner_block_id = block.footnote_owner_block_id
                owner_offset = block.footnote_anchor_offset
                owner_review_required = block.footnote_owner_review_required
            else:
                owner_block_id = latest.footnote_owner_block_id
                owner_offset = latest.footnote_anchor_offset
                owner_review_required = bool(latest.footnote_owner_review_required)
        else:
            effective_text = block.translated_text or ""
            latest_number = 0
            status = ReviewStatus.UNREVIEWED
            resolved_ids = set()
            effective_type = block.type
            owner_block_id = block.footnote_owner_block_id
            owner_offset = block.footnote_anchor_offset
            owner_review_required = block.footnote_owner_review_required
        block_states[block.block_id] = (
            effective_text,
            latest_number,
            status,
            resolved_ids,
            effective_type,
            owner_block_id,
            owner_offset,
            owner_review_required,
        )
        specs, fallbacks = machine_uncertainty_specs(block)
        specs_by_block[block.block_id] = specs
        fallbacks_by_block[block.block_id] = [
            to_fallback(fallback)
            for fallback in fallbacks
            if fallback.uncertainty_id not in resolved_ids
        ]

    highlights_by_block: dict[str, list[UncertaintyHighlight]] = {}
    all_highlights: list[UncertaintyHighlight] = []
    for block in iter_machine_blocks(document):
        effective_text, _, _, resolved_ids, _, _, _, _ = block_states[block.block_id]
        highlights, newly_unlocated = locate_unresolved_specs(
            block.translated_text or "",
            effective_text,
            specs_by_block[block.block_id],
            resolved_ids,
        )
        highlights_by_block[block.block_id] = highlights
        fallbacks_by_block[block.block_id].extend(
            to_fallback(fallback) for fallback in newly_unlocated
        )
        all_highlights.extend(highlights)

    occurrence_counts: dict[str, int] = defaultdict(int)
    for highlight in all_highlights:
        occurrence_counts[highlight.term_group_id] += 1
    for block_id, highlights in highlights_by_block.items():
        highlights_by_block[block_id] = [
            highlight.model_copy(
                update={
                    "matching_occurrence_count": occurrence_counts[highlight.term_group_id],
                    "can_replace_all": occurrence_counts[highlight.term_group_id] > 1,
                }
            )
            for highlight in highlights
        ]

    pages: list[ReviewPage] = []
    for page in document.pages:
        review_blocks: list[ReviewBlock] = []
        for block in page.blocks:
            (
                effective_text,
                revision_number,
                status,
                _,
                effective_type,
                owner_block_id,
                owner_offset,
                owner_review_required,
            ) = block_states[block.block_id]
            effective_is_footnote = effective_type is BlockType.FOOTNOTE
            review_blocks.append(
                ReviewBlock(
                    document_id=document.document_id,
                    translation_run_id=translation_run_id,
                    block_id=block.block_id,
                    original_page_number=block.original_page_number,
                    order=block.order,
                    machine_type=block.type,
                    type=effective_type,
                    segment_handling=block.segment_handling,
                    source_text=block.source_text,
                    machine_translated_text=block.translated_text,
                    effective_translated_text=effective_text,
                    manual_insertion_reason=block.manual_insertion_reason,
                    footnote_id=(block.footnote_id if effective_is_footnote else None),
                    footnote_description=(
                        block.footnote_description if effective_is_footnote else None
                    ),
                    footnote_owner_block_id=owner_block_id,
                    footnote_anchor_offset=owner_offset,
                    footnote_owner_review_required=owner_review_required,
                    continuation=(
                        block.continuation
                        if effective_is_footnote
                        or block.segment_handling is not SegmentHandling.TRANSLATE
                        else None
                    ),
                    footnote_continues_from_block_id=(
                        block.footnote_continues_from_block_id if effective_is_footnote else None
                    ),
                    paragraph_continuation=(
                        block.paragraph_continuation if effective_type is BlockType.BODY else None
                    ),
                    continues_from_block_id=(
                        block.continues_from_block_id if effective_type is BlockType.BODY else None
                    ),
                    classification_review_required=block.classification_review_required,
                    latest_revision_number=revision_number,
                    review_status=status,
                    uncertainty_highlights=highlights_by_block[block.block_id],
                    uncertainty_fallbacks=fallbacks_by_block[block.block_id],
                )
            )
        pages.append(
            ReviewPage(
                original_page_number=page.original_page_number,
                pdf_page_label=page.pdf_page_label,
                detected_printed_page_label=page.detected_printed_page_label,
                blocks=review_blocks,
            )
        )
    effective_text_by_id = {block_id: state[0] for block_id, state in block_states.items()}
    effective_types = {block_id: state[4] for block_id, state in block_states.items()}
    paragraph_groups = [
        ReviewParagraphGroup(
            paragraph_id=projection.paragraph_id,
            fragment_block_ids=list(projection.fragment_block_ids),
            original_page_numbers=list(projection.original_page_numbers),
        )
        for projection in project_paragraphs(
            iter_machine_blocks(document),
            effective_text_by_id=effective_text_by_id,
            type_overrides=effective_types,
        )
        if len(projection.fragments) > 1
    ]
    return ReviewDocument(
        document_id=document.document_id,
        translation_run_id=translation_run_id,
        source_file_name=document.source_file_name,
        page_count=document.page_count,
        pages=pages,
        paragraph_groups=paragraph_groups,
    )
