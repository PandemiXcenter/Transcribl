from __future__ import annotations

import re

from transcribl.domain.enums import (
    BlockType,
    SegmentContinuation,
    SegmentHandling,
)
from transcribl.domain.models import (
    GeneratedBlockVariant,
    GeneratedFootnoteBlock,
    GeneratedManualInsertionBlock,
    GeneratedTextBlock,
    PageTranslation,
    TranslatedBlock,
)


def to_translated_blocks(
    original_page_number: int,
    generated_blocks: list[GeneratedBlockVariant],
    *,
    previous_page: PageTranslation | None,
) -> list[TranslatedBlock]:
    previous_body = (
        next(
            (block for block in reversed(previous_page.blocks) if block.type is BlockType.BODY),
            None,
        )
        if previous_page is not None
        else None
    )
    previous_footnotes_by_id = (
        {
            block.footnote_id.id: block
            for block in previous_page.blocks
            if block.type is BlockType.FOOTNOTE and block.footnote_id is not None
        }
        if previous_page is not None
        else {}
    )
    translated_text_by_order: dict[int, str] = {}
    owner_by_token: dict[str, tuple[str, int]] = {}
    for generated in generated_blocks:
        if not isinstance(generated, GeneratedTextBlock):
            continue
        translated_text, token_offsets = _strip_footnote_reference_tokens(generated.translated_text)
        translated_text_by_order[generated.order] = translated_text
        generated_owner_block_id = f"p{original_page_number:04d}-b{generated.order:04d}"
        for token, offset in token_offsets.items():
            owner_by_token[token] = (generated_owner_block_id, offset)

    translated: list[TranslatedBlock] = []
    for block in generated_blocks:
        continues_from_block_id = None
        if (
            not isinstance(block, (GeneratedManualInsertionBlock, GeneratedFootnoteBlock))
            and block.type is BlockType.BODY
            and block.paragraph_continuation
            in {
                SegmentContinuation.FROM_PREVIOUS_PAGE,
                SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
            }
        ):
            if previous_body is None:
                raise ValueError(
                    "A previous-page paragraph continuation has no preceding body block"
                )
            continues_from_block_id = previous_body.block_id
        owner_block_id = None
        owner_offset = None
        owner_review_required = None
        footnote_continues_from_block_id = None
        if isinstance(block, GeneratedFootnoteBlock):
            starting_page = int(block.footnote_id.id.split("-", 2)[1][1:])
            if _continues_from_previous_page(block.continuation):
                if starting_page >= original_page_number:
                    raise ValueError(
                        "A continued footnote ID must retain its earlier starting page"
                    )
                previous_footnote = previous_footnotes_by_id.get(block.footnote_id.id)
                if previous_footnote is None or previous_footnote.footnote_id != block.footnote_id:
                    raise ValueError(
                        "A continued footnote must reuse the same ID and reference text from "
                        "the immediately previous page"
                    )
                if previous_footnote.continuation not in {
                    SegmentContinuation.TO_NEXT_PAGE,
                    SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
                    SegmentContinuation.UNKNOWN,
                }:
                    raise ValueError(
                        "A continued footnote follows a fragment that was marked complete"
                    )
                owner_block_id = previous_footnote.footnote_owner_block_id
                owner_offset = previous_footnote.footnote_anchor_offset
                owner_review_required = previous_footnote.footnote_owner_review_required
                footnote_continues_from_block_id = previous_footnote.block_id
            elif starting_page != original_page_number:
                raise ValueError("A new footnote ID must name the current physical page")
            elif block.entrypoint_token is not None:
                owner_block_id, owner_offset = owner_by_token[block.entrypoint_token]
                owner_review_required = False
            else:
                owner_review_required = block.owner_review_required
        translated.append(
            _to_translated_block(
                original_page_number,
                block,
                continues_from_block_id=continues_from_block_id,
                translated_text_override=translated_text_by_order.get(block.order),
                footnote_owner_block_id=owner_block_id,
                footnote_anchor_offset=owner_offset,
                footnote_owner_review_required=owner_review_required,
                footnote_continues_from_block_id=footnote_continues_from_block_id,
            )
        )
    return translated


def _strip_footnote_reference_tokens(value: str) -> tuple[str, dict[str, int]]:
    """Remove provider-only anchor tokens while retaining trusted Unicode offsets."""

    parts: list[str] = []
    offsets: dict[str, int] = {}
    cursor = 0
    rendered_length = 0
    for match in re.finditer(r"\[\[FOOTNOTE:fn-p[1-9]\d*-n[1-9]\d*\]\]", value):
        prefix = value[cursor : match.start()]
        parts.append(prefix)
        rendered_length += len(prefix)
        offsets[match.group()] = rendered_length
        cursor = match.end()
    parts.append(value[cursor:])
    translated_text = "".join(parts)
    if not translated_text.strip():
        raise ValueError("a footnote reference token cannot be the owner's entire translation")
    return translated_text, offsets


def _to_translated_block(
    original_page_number: int,
    block: GeneratedBlockVariant,
    *,
    continues_from_block_id: str | None = None,
    translated_text_override: str | None = None,
    footnote_owner_block_id: str | None = None,
    footnote_anchor_offset: int | None = None,
    footnote_owner_review_required: bool | None = None,
    footnote_continues_from_block_id: str | None = None,
) -> TranslatedBlock:
    block_id = f"p{original_page_number:04d}-b{block.order:04d}"
    if isinstance(block, GeneratedManualInsertionBlock):
        return TranslatedBlock(
            block_id=block_id,
            original_page_number=original_page_number,
            order=block.order,
            type=block.type,
            source_text=None,
            translated_text=None,
            segment_handling=SegmentHandling.MANUAL_INSERTION,
            manual_insertion_reason=block.manual_insertion_reason,
            continuation=block.continuation,
            classification_review_required=block.classification_review_required,
        )
    if isinstance(block, GeneratedFootnoteBlock):
        return TranslatedBlock(
            block_id=block_id,
            original_page_number=original_page_number,
            order=block.order,
            type=block.type,
            source_text=block.source_text,
            translated_text=block.translated_text,
            segment_handling=SegmentHandling.TRANSLATE,
            footnote_id=block.footnote_id,
            footnote_description=block.description,
            footnote_owner_block_id=footnote_owner_block_id,
            footnote_anchor_offset=footnote_anchor_offset,
            footnote_owner_review_required=(
                block.owner_review_required
                if footnote_owner_review_required is None
                else footnote_owner_review_required
            ),
            continuation=block.continuation,
            footnote_continues_from_block_id=footnote_continues_from_block_id,
            uncertainties=block.uncertainties,
            classification_review_required=block.classification_review_required,
        )
    return TranslatedBlock(
        block_id=block_id,
        original_page_number=original_page_number,
        order=block.order,
        type=block.type,
        source_text=block.source_text,
        translated_text=translated_text_override or block.translated_text,
        heading_level=block.heading_level,
        paragraph_continuation=block.paragraph_continuation,
        continues_from_block_id=continues_from_block_id,
        uncertainties=block.uncertainties,
        segment_handling=SegmentHandling.TRANSLATE,
        classification_review_required=block.classification_review_required,
    )


def _continues_from_previous_page(value: SegmentContinuation) -> bool:
    return value in {
        SegmentContinuation.FROM_PREVIOUS_PAGE,
        SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
    }
