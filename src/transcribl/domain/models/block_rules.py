from __future__ import annotations

from transcribl.domain.enums import (
    BlockType,
    ManualInsertionReason,
    SegmentContinuation,
)


def _continues_from_previous(value: SegmentContinuation | None) -> bool:
    return value in {
        SegmentContinuation.FROM_PREVIOUS_PAGE,
        SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
    }


def _continues_to_next(value: SegmentContinuation | None) -> bool:
    return value in {
        SegmentContinuation.TO_NEXT_PAGE,
        SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
    }


def _validate_manual_reason(
    block_type: BlockType,
    reason: ManualInsertionReason,
) -> None:
    if block_type is BlockType.FIGURE and reason is not ManualInsertionReason.FIGURE:
        raise ValueError("figure blocks must use the figure manual insertion reason")
    if block_type is BlockType.TABLE and reason is ManualInsertionReason.FIGURE:
        raise ValueError("table blocks must use a table or table-like insertion reason")
