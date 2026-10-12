from __future__ import annotations

from dataclasses import dataclass, field

from transcribl.domain.editorial import (
    ReviewDocument,
    UncertaintyFallback,
    UncertaintyHighlight,
)


def review_payload(review: ReviewDocument) -> dict[str, object]:
    return {
        "document_id": review.document_id,
        "translation_run_id": review.translation_run_id,
        "source_file_name": review.source_file_name,
        "page_count": review.page_count,
        "uncertainty_groups": _uncertainty_group_payload(review),
        "paragraph_groups": [group.model_dump(mode="json") for group in review.paragraph_groups],
        "pages": [
            {
                "original_page_number": page.original_page_number,
                "pdf_page_label": page.pdf_page_label,
                "detected_printed_page_label": page.detected_printed_page_label,
                "blocks": [
                    {
                        "block_id": block.block_id,
                        "original_page_number": block.original_page_number,
                        "order": block.order,
                        "machine_type": block.machine_type.value,
                        "type": block.type.value,
                        "segment_handling": block.segment_handling.value,
                        "source_text": block.source_text,
                        "machine_text": block.machine_translated_text,
                        "effective_text": block.effective_translated_text,
                        "manual_insertion_reason": (
                            block.manual_insertion_reason.value
                            if block.manual_insertion_reason is not None
                            else None
                        ),
                        "footnote_id": (
                            block.footnote_id.model_dump(mode="json")
                            if block.footnote_id is not None
                            else None
                        ),
                        "footnote_description": (
                            block.footnote_description.model_dump(mode="json")
                            if block.footnote_description is not None
                            else None
                        ),
                        "footnote_owner_block_id": block.footnote_owner_block_id,
                        "footnote_anchor_offset": block.footnote_anchor_offset,
                        "footnote_owner_review_required": (block.footnote_owner_review_required),
                        "continuation": (
                            block.continuation.value if block.continuation is not None else None
                        ),
                        "footnote_continues_from_block_id": (
                            block.footnote_continues_from_block_id
                        ),
                        "paragraph_continuation": (
                            block.paragraph_continuation.value
                            if block.paragraph_continuation is not None
                            else None
                        ),
                        "continues_from_block_id": block.continues_from_block_id,
                        "classification_review_required": (block.classification_review_required),
                        "base_revision": block.latest_revision_number,
                        "review_status": block.review_status.value,
                        "uncertainties": [
                            *[
                                _range_uncertainty_payload(highlight)
                                for highlight in block.uncertainty_highlights
                            ],
                            *[
                                _fallback_uncertainty_payload(fallback)
                                for fallback in block.uncertainty_fallbacks
                            ],
                        ],
                    }
                    for block in page.blocks
                ],
            }
            for page in review.pages
        ],
    }


@dataclass(slots=True)
class _UncertaintyGroup:
    term_group_id: str
    source_term: str
    proposed_translation: str | None
    reason: str
    alternatives: list[str]
    occurrence_count: int = 0
    page_numbers: set[int] = field(default_factory=set)
    uncertainty_ids: list[str] = field(default_factory=list)


def _uncertainty_group_payload(review: ReviewDocument) -> list[dict[str, object]]:
    groups: dict[str, _UncertaintyGroup] = {}
    for page in review.pages:
        for block in page.blocks:
            uncertainties: list[UncertaintyHighlight | UncertaintyFallback] = [
                *block.uncertainty_highlights,
                *block.uncertainty_fallbacks,
            ]
            for uncertainty in uncertainties:
                group = groups.setdefault(
                    uncertainty.term_group_id,
                    _UncertaintyGroup(
                        term_group_id=uncertainty.term_group_id,
                        source_term=uncertainty.source_term,
                        proposed_translation=uncertainty.proposed_translation,
                        reason=uncertainty.reason,
                        alternatives=list(uncertainty.alternatives),
                    ),
                )
                group.occurrence_count += 1
                group.page_numbers.add(page.original_page_number)
                group.uncertainty_ids.append(uncertainty.uncertainty_id)
                for alternative in uncertainty.alternatives:
                    if alternative not in group.alternatives:
                        group.alternatives.append(alternative)

    ordered = sorted(
        groups.values(),
        key=lambda group: (
            -group.occurrence_count,
            group.source_term.casefold(),
            (group.proposed_translation or "").casefold(),
            group.term_group_id,
        ),
    )
    return [
        {
            "term_group_id": group.term_group_id,
            "source_term": group.source_term,
            "proposed_translation": group.proposed_translation,
            "reason": group.reason,
            "alternatives": group.alternatives,
            "occurrence_count": group.occurrence_count,
            "page_numbers": sorted(group.page_numbers),
            "first_uncertainty_id": group.uncertainty_ids[0],
        }
        for group in ordered
    ]


def default_continue_page(review: ReviewDocument) -> int:
    for page in review.pages:
        if any(block.review_status.value != "accepted" for block in page.blocks):
            return page.original_page_number
    return review.pages[-1].original_page_number


def _range_uncertainty_payload(
    highlight: UncertaintyHighlight,
) -> dict[str, object]:
    return {
        "uncertainty_id": highlight.uncertainty_id,
        "term_group_id": highlight.term_group_id,
        "source_term": highlight.source_term,
        "proposed_translation": highlight.proposed_translation,
        "reason": highlight.reason,
        "alternatives": highlight.alternatives,
        "highlight_text": highlight.proposed_translation,
        "highlight_mode": highlight.highlight_mode,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "matching_occurrence_count": highlight.matching_occurrence_count,
        "can_replace_all": highlight.can_replace_all,
        "resolved": False,
    }


def _fallback_uncertainty_payload(
    fallback: UncertaintyFallback,
) -> dict[str, object]:
    return {
        "uncertainty_id": fallback.uncertainty_id,
        "term_group_id": fallback.term_group_id,
        "source_term": fallback.source_term,
        "proposed_translation": fallback.proposed_translation,
        "reason": fallback.reason,
        "alternatives": fallback.alternatives,
        "highlight_text": fallback.proposed_translation or fallback.source_term,
        "highlight_mode": fallback.highlight_mode,
        "matching_occurrence_count": 1,
        "can_replace_all": False,
        "resolved": False,
    }
