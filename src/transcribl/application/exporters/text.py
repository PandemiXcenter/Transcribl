from __future__ import annotations

from collections.abc import Mapping

from transcribl.application.exporters.gfm import parse_gfm_table
from transcribl.application.exporters.policy import manual_insertion_label, should_include
from transcribl.application.footnotes import project_footnotes
from transcribl.application.paragraphs import ParagraphProjection, project_paragraphs
from transcribl.domain.enums import BlockType, SegmentHandling
from transcribl.domain.models import (
    DocumentTranslation,
    MarkdownExportSettings,
    TranslatedBlock,
)


def compile_text(
    document: DocumentTranslation,
    settings: MarkdownExportSettings,
    *,
    editorial_overrides: Mapping[str, str] | None = None,
    type_overrides: Mapping[str, BlockType] | None = None,
) -> str:
    """Project canonical blocks and effective revisions into readable plain text."""

    overrides = editorial_overrides or {}
    resolved_types = type_overrides or {}
    blocks = [block for page in document.pages for block in page.blocks]
    effective_text_by_id = {
        block.block_id: overrides.get(block.block_id, block.translated_text) for block in blocks
    }
    footnote_projections = project_footnotes(
        blocks,
        effective_text_by_id=effective_text_by_id,
        type_overrides=resolved_types,
    )
    merged_footnote_ids = {
        fragment_id
        for projection in footnote_projections
        for fragment_id in projection.fragment_ids[1:]
    }
    merged_text_by_first_id = {
        projection.first_block.block_id: projection.text for projection in footnote_projections
    }
    paragraph_projections = project_paragraphs(
        blocks,
        effective_text_by_id=effective_text_by_id,
        type_overrides=resolved_types,
    )
    merged_paragraph_ids = {
        fragment.block.block_id
        for projection in paragraph_projections
        for fragment in projection.fragments[1:]
    }
    merged_paragraph_text_by_first_id = {
        projection.paragraph_id: _plain_paragraph(projection)
        for projection in paragraph_projections
        if len(projection.fragments) > 1
    }
    parts: list[str] = []
    list_items: list[str] = []
    for page in document.pages:
        for block in page.blocks:
            block_type = resolved_types.get(block.block_id, block.type)
            if not should_include(block, settings, block_type=block_type):
                continue
            effective_text = overrides.get(block.block_id, block.translated_text)
            if block.block_id in merged_footnote_ids:
                continue
            if block.block_id in merged_paragraph_ids:
                continue
            if block.block_id in merged_text_by_first_id:
                effective_text = merged_text_by_first_id[block.block_id]
            if block.block_id in merged_paragraph_text_by_first_id:
                effective_text = merged_paragraph_text_by_first_id[block.block_id]
            if block_type is BlockType.LIST_ITEM:
                if effective_text is not None and effective_text.strip():
                    list_items.append(f"- {_plain_text(effective_text)}")
                continue
            _flush_plain_list(parts, list_items)
            rendered = _render_text_block(block, effective_text, block_type=block_type)
            if not rendered:
                continue
            parts.append(rendered)
        _flush_plain_list(parts, list_items)

    rendered_document = "\n\n".join(parts).rstrip()
    return f"{rendered_document}\n" if rendered_document else ""


def _render_text_block(
    block: TranslatedBlock,
    effective_text: str | None,
    *,
    block_type: BlockType | None = None,
) -> str:
    resolved_type = block_type or block.type
    if block.segment_handling is SegmentHandling.MANUAL_INSERTION:
        if effective_text is not None and effective_text.strip():
            return (
                _plain_table(effective_text)
                if resolved_type is BlockType.TABLE
                else _plain_text(effective_text)
            )
        return manual_insertion_label(block)
    if effective_text is None or not effective_text.strip():
        return ""
    if resolved_type is BlockType.TABLE:
        return _plain_table(effective_text)
    if resolved_type is BlockType.FOOTNOTE:
        marker = (
            f" {block.footnote_id.text}"
            if block.footnote_id is not None and block.footnote_id.text
            else ""
        )
        return f"Footnote{marker}: {_plain_text(effective_text)}"
    return _plain_text(effective_text)


def _plain_paragraph(projection: ParagraphProjection) -> str:
    return " ".join(_plain_text(fragment.text).strip() for fragment in projection.fragments)


def _plain_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def _flush_plain_list(parts: list[str], items: list[str]) -> None:
    if items:
        parts.append("\n".join(items))
        items.clear()


def _plain_table(value: str) -> str:
    parsed = parse_gfm_table(value)
    if parsed is None:
        return _plain_text(value)
    _, rows, _ = parsed
    return "\n".join("\t".join(cell.strip() for cell in row) for row in rows)
