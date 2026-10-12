from __future__ import annotations

from typing import Self

from pydantic import (
    Field,
    model_validator,
)

from transcribl.domain.enums import (
    BlockType,
    ManualInsertionReason,
    SegmentContinuation,
    SegmentHandling,
)
from transcribl.domain.models.annotations import (
    FootnoteDescription,
    FootnoteIdentity,
    UncertainTerm,
)
from transcribl.domain.models.base import BlockId, ContractModel, NonEmptyText
from transcribl.domain.models.block_rules import _continues_from_previous, _validate_manual_reason


class TranslatedBlock(ContractModel):
    """Validated model output enriched with pipeline-owned identity."""

    block_id: BlockId
    original_page_number: int = Field(ge=1)
    order: int = Field(ge=1)
    type: BlockType
    source_text: NonEmptyText | None
    translated_text: NonEmptyText | None
    heading_level: int | None = Field(default=None, ge=1, le=6)
    uncertainties: list[UncertainTerm] = Field(default_factory=list)
    segment_handling: SegmentHandling = SegmentHandling.TRANSLATE
    manual_insertion_reason: ManualInsertionReason | None = None
    footnote_id: FootnoteIdentity | None = None
    footnote_description: FootnoteDescription | None = None
    footnote_owner_block_id: BlockId | None = None
    footnote_anchor_offset: int | None = Field(default=None, ge=0)
    footnote_owner_review_required: bool = False
    continuation: SegmentContinuation | None = None
    footnote_continues_from_block_id: BlockId | None = None
    paragraph_continuation: SegmentContinuation | None = None
    continues_from_block_id: BlockId | None = None
    classification_review_required: bool = False
    legacy_translated_table: bool = False
    legacy_manual_table: bool = False

    @model_validator(mode="after")
    def segment_contract_must_be_consistent(self) -> Self:
        _validate_segment_contract(self)
        return self


def _validate_segment_contract(block: TranslatedBlock) -> None:
    if block.segment_handling is SegmentHandling.MANUAL_INSERTION:
        if block.legacy_translated_table:
            raise ValueError("manual insertion blocks cannot be legacy translated tables")
        if block.legacy_manual_table and block.type is not BlockType.TABLE:
            raise ValueError("legacy manual-table compatibility applies only to table blocks")
        if block.type not in {BlockType.TABLE, BlockType.FIGURE}:
            raise ValueError("manual insertion is valid only for table and figure blocks")
        if block.manual_insertion_reason is None:
            raise ValueError("manual insertion blocks must state a reason")
        _validate_manual_reason(block.type, block.manual_insertion_reason)
        if block.source_text is not None or block.translated_text is not None:
            raise ValueError("manual insertion blocks must not contain source or translated text")
        if block.heading_level is not None:
            raise ValueError("manual insertion blocks cannot have a heading level")
        if block.uncertainties:
            raise ValueError("manual insertion blocks cannot contain text uncertainties")
        if (
            block.footnote_id is not None
            or block.footnote_description is not None
            or block.footnote_owner_block_id is not None
            or block.footnote_anchor_offset is not None
            or block.footnote_owner_review_required
            or block.footnote_continues_from_block_id is not None
        ):
            raise ValueError("manual insertion blocks cannot contain footnote metadata")
        if block.continuation is None:
            raise ValueError("manual insertion blocks must state their continuation relationship")
        if block.paragraph_continuation is not None or block.continues_from_block_id is not None:
            raise ValueError("manual insertion blocks cannot contain paragraph continuity")
        return

    if block.segment_handling is SegmentHandling.TABLE_RECONSTRUCTION:
        if block.type is not BlockType.TABLE:
            raise ValueError("table reconstruction handling is valid only for table blocks")
        if block.source_text is not None or block.translated_text is None:
            raise ValueError("reconstructed tables must contain only translated Markdown")
        if block.manual_insertion_reason not in {
            ManualInsertionReason.TABLE,
            ManualInsertionReason.TABLE_LIKE,
        }:
            raise ValueError("reconstructed tables must retain their table-region reason")
        if block.continuation is None:
            raise ValueError("reconstructed tables must retain continuation metadata")
        if (
            block.heading_level is not None
            or block.footnote_id is not None
            or block.footnote_description is not None
            or block.footnote_owner_block_id is not None
            or block.footnote_anchor_offset is not None
            or block.footnote_owner_review_required
            or block.footnote_continues_from_block_id is not None
        ):
            raise ValueError("reconstructed tables cannot contain heading or footnote metadata")
        if block.legacy_translated_table or block.legacy_manual_table:
            raise ValueError("reconstructed tables cannot use legacy compatibility markers")
        if block.paragraph_continuation is not None or block.continues_from_block_id is not None:
            raise ValueError("reconstructed tables cannot contain paragraph continuity")
        return

    if block.manual_insertion_reason is not None:
        raise ValueError("translated blocks cannot state a manual insertion reason")
    if block.source_text is None or block.translated_text is None:
        raise ValueError("translated blocks must contain source and translated text")
    if block.type is BlockType.FIGURE:
        raise ValueError("figure blocks must use manual insertion handling")
    if block.type is BlockType.TABLE and not block.legacy_translated_table:
        raise ValueError("new table blocks must use table reconstruction handling")
    if block.type is not BlockType.TABLE and block.legacy_translated_table:
        raise ValueError("legacy translated table compatibility applies only to table blocks")
    if block.legacy_manual_table:
        raise ValueError("translated blocks cannot be legacy manual tables")
    footnote_metadata_present = (
        block.footnote_id is not None
        or block.footnote_description is not None
        or block.continuation is not None
        or block.footnote_owner_block_id is not None
        or block.footnote_anchor_offset is not None
        or block.footnote_owner_review_required
        or block.footnote_continues_from_block_id is not None
    )
    if block.type is not BlockType.FOOTNOTE and footnote_metadata_present:
        raise ValueError("footnote metadata is valid only for footnote blocks")
    if block.type is BlockType.FOOTNOTE:
        if block.footnote_id is None or block.footnote_description is None:
            raise ValueError("footnotes must retain identity and description metadata")
        has_owner = block.footnote_owner_block_id is not None
        if has_owner != (block.footnote_anchor_offset is not None):
            raise ValueError("a footnote owner block and anchor offset must be stored together")
        if has_owner and block.footnote_owner_review_required:
            raise ValueError("a resolved footnote owner cannot require owner review")
        if not has_owner and not block.footnote_owner_review_required:
            raise ValueError("an unowned footnote must require owner review")
        incoming = _continues_from_previous(block.continuation)
        if incoming != (block.footnote_continues_from_block_id is not None):
            raise ValueError("incoming footnotes must link their previous-page fragment")
    if block.type is BlockType.BODY:
        if _continues_from_previous(block.paragraph_continuation):
            if block.continues_from_block_id is None:
                raise ValueError("incoming paragraph continuations must link a previous block")
        elif block.continues_from_block_id is not None:
            raise ValueError("only incoming paragraph continuations may link a previous block")
    elif block.paragraph_continuation is not None or block.continues_from_block_id is not None:
        raise ValueError("paragraph continuity is valid only for body blocks")
