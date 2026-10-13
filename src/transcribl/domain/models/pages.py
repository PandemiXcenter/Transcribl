from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import (
    Field,
    model_validator,
)

from transcribl.domain.enums import (
    BlockType,
    ExtractionStatus,
    SegmentHandling,
)
from transcribl.domain.models.base import (
    SCHEMA_VERSION,
    ContractModel,
    Sha256,
    TranslationRunId,
    utc_now,
)
from transcribl.domain.models.block_rules import _continues_from_previous, _continues_to_next
from transcribl.domain.models.blocks import TranslatedBlock
from transcribl.domain.models.extraction import ArtifactRef
from transcribl.domain.models.paragraphs import ParagraphFragmentRevision
from transcribl.domain.models.provenance import ProviderMetadata, TableReconstructionMetadata


class PageTranslation(ContractModel):
    """One independently retriable and cacheable page result."""

    schema_version: Literal["7.0"] = SCHEMA_VERSION
    translation_run_id: TranslationRunId
    original_page_number: int = Field(ge=1)
    pdf_page_label: str | None = None
    detected_printed_page_label: str | None = None
    extraction_status: ExtractionStatus
    extracted_character_count: int = Field(ge=0)
    extraction_warnings: list[str] = Field(default_factory=list)
    source_markdown: str
    source_markdown_artifact: ArtifactRef
    source_image: ArtifactRef
    blocks: list[TranslatedBlock] = Field(default_factory=list)
    paragraph_revisions: list[ParagraphFragmentRevision] = Field(default_factory=list)
    input_fingerprint: Sha256
    provider: ProviderMetadata
    table_reconstruction: TableReconstructionMetadata | None = None
    translated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def blocks_must_belong_to_page(self) -> Self:
        orders = [block.order for block in self.blocks]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("translated blocks must be in contiguous reading order")
        if any(block.original_page_number != self.original_page_number for block in self.blocks):
            raise ValueError("every block must belong to its containing page")
        body_blocks = [block for block in self.blocks if block.type is BlockType.BODY]
        incoming = [
            block for block in body_blocks if _continues_from_previous(block.paragraph_continuation)
        ]
        outgoing = [
            block for block in body_blocks if _continues_to_next(block.paragraph_continuation)
        ]
        if self.paragraph_revisions:
            if not incoming:
                raise ValueError("paragraph revisions require an incoming body continuation")
            targets = [(item.original_page_number, item.order) for item in self.paragraph_revisions]
            if targets != sorted(set(targets)) or any(
                number >= self.original_page_number for number, _ in targets
            ):
                raise ValueError("paragraph revisions must name unique earlier fragments in order")
        if incoming and incoming != body_blocks[:1]:
            raise ValueError("only the first body block may continue a previous-page paragraph")
        if outgoing and outgoing != body_blocks[-1:]:
            raise ValueError("only the last body block may continue onto the next page")
        incoming_flow_blocks = [
            block
            for block in self.blocks
            if block.type
            not in {
                BlockType.HEADER,
                BlockType.FOOTER,
                BlockType.PAGE_NUMBER,
            }
        ]
        outgoing_flow_blocks = [
            block for block in incoming_flow_blocks if block.type is not BlockType.FOOTNOTE
        ]
        if incoming and incoming_flow_blocks[:1] != incoming:
            raise ValueError(
                "a previous-page paragraph continuation must be the first main-flow block"
            )
        if outgoing and outgoing_flow_blocks[-1:] != outgoing:
            raise ValueError(
                "an unfinished paragraph must be the final main-flow block on its page"
            )
        blocks_by_id = {block.block_id: block for block in self.blocks}
        for footnote in (block for block in self.blocks if block.type is BlockType.FOOTNOTE):
            if footnote.footnote_continues_from_block_id is not None:
                previous_page_number = int(
                    footnote.footnote_continues_from_block_id.split("-", 1)[0][1:]
                )
                if previous_page_number != self.original_page_number - 1:
                    raise ValueError("footnote continuation must link the previous physical page")
            if footnote.footnote_owner_block_id is None:
                continue
            owner = blocks_by_id.get(footnote.footnote_owner_block_id)
            if owner is None and footnote.footnote_continues_from_block_id is not None:
                continue
            if owner is None or owner.type is BlockType.FOOTNOTE:
                raise ValueError("a footnote owner must be a non-footnote block on the same page")
            if (
                owner.translated_text is None
                or footnote.footnote_anchor_offset is None
                or footnote.footnote_anchor_offset > len(owner.translated_text)
            ):
                raise ValueError("a footnote anchor offset must fall within its owner text")
        reconstructed_ids = [
            block.block_id
            for block in self.blocks
            if block.segment_handling is SegmentHandling.TABLE_RECONSTRUCTION
        ]
        if reconstructed_ids:
            if self.table_reconstruction is None:
                raise ValueError("reconstructed table blocks require table-pass provenance")
            if self.table_reconstruction.block_ids != reconstructed_ids:
                raise ValueError("table-pass provenance must name every reconstructed table block")
        elif self.table_reconstruction is not None:
            raise ValueError("table-pass provenance requires reconstructed table blocks")
        return self
