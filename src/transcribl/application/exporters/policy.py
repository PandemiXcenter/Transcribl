from __future__ import annotations

from difflib import SequenceMatcher

from transcribl.domain.enums import BlockType, ManualInsertionReason
from transcribl.domain.models import (
    MarkdownExportSettings,
    TranslatedBlock,
)


def should_include(
    block: TranslatedBlock,
    settings: MarkdownExportSettings,
    *,
    block_type: BlockType | None = None,
) -> bool:
    resolved_type = block_type or block.type
    if resolved_type is BlockType.HEADER:
        return settings.include_headers
    if resolved_type is BlockType.FOOTER:
        return settings.include_footers
    if resolved_type is BlockType.PAGE_NUMBER:
        return settings.include_page_numbers
    return True


def map_anchor_offset(machine_text: str, effective_text: str, offset: int) -> int:
    """Keep an inline marker aligned when surrounding owner text was edited."""

    bounded = min(max(offset, 0), len(machine_text))
    if machine_text == effective_text:
        return min(bounded, len(effective_text))
    matcher = SequenceMatcher(a=machine_text, b=effective_text, autojunk=False)
    for tag, machine_start, machine_end, effective_start, effective_end in matcher.get_opcodes():
        if machine_start <= bounded <= machine_end:
            if tag == "equal":
                return effective_start + min(
                    bounded - machine_start, effective_end - effective_start
                )
            return effective_end
    return len(effective_text)


def manual_insertion_label(block: TranslatedBlock) -> str:
    reason = {
        ManualInsertionReason.TABLE: "table",
        ManualInsertionReason.TABLE_LIKE: "table-like material",
        ManualInsertionReason.FIGURE: "figure",
        None: "material",
    }[block.manual_insertion_reason]
    return f"Manual insertion required: {reason} on original page {block.original_page_number}."
