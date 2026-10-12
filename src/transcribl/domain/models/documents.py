from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import (
    Field,
    model_validator,
)

from transcribl.domain.enums import (
    BlockType,
    SegmentContinuation,
    SegmentHandling,
)
from transcribl.domain.models.base import (
    SCHEMA_VERSION,
    ContractModel,
    NonEmptyText,
    Sha256,
    TranslationRunId,
)
from transcribl.domain.models.pages import PageTranslation
from transcribl.domain.models.settings import TranslationSettings


class DocumentTranslation(ContractModel):
    """Canonical dataset consumed by the future editor and all exporters."""

    schema_version: Literal["6.0"] = SCHEMA_VERSION
    translation_run_id: TranslationRunId
    document_id: Sha256
    job_id: NonEmptyText
    source_file_name: NonEmptyText
    source_file_sha256: Sha256
    page_count: int = Field(ge=1)
    translation_settings: TranslationSettings
    pages: list[PageTranslation] = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def translated_pages_must_be_complete(self) -> Self:
        numbers = [page.original_page_number for page in self.pages]
        expected = list(range(1, self.page_count + 1))
        if numbers != expected:
            raise ValueError(f"document must contain translated physical pages {expected}")
        if any(page.translation_run_id != self.translation_run_id for page in self.pages):
            raise ValueError("every page must belong to the document translation run")
        unresolved_tables = [
            block.block_id
            for page in self.pages
            for block in page.blocks
            if block.type is BlockType.TABLE
            and block.segment_handling is SegmentHandling.MANUAL_INSERTION
            and not block.legacy_manual_table
        ]
        if unresolved_tables:
            raise ValueError("document contains tables awaiting reconstruction")
        blocks_by_id = {block.block_id: block for page in self.pages for block in page.blocks}
        for page in self.pages:
            for block in page.blocks:
                if block.continues_from_block_id is None:
                    continue
                previous = blocks_by_id.get(block.continues_from_block_id)
                if previous is None:
                    raise ValueError("paragraph continuation links an unknown block")
                if (
                    previous.type is not BlockType.BODY
                    or previous.original_page_number != block.original_page_number - 1
                ):
                    raise ValueError(
                        "paragraph continuation must link a body block on the previous page"
                    )
                previous_bodies = [
                    candidate
                    for candidate in self.pages[block.original_page_number - 2].blocks
                    if candidate.type is BlockType.BODY
                ]
                if not previous_bodies or previous_bodies[-1].block_id != previous.block_id:
                    raise ValueError(
                        "paragraph continuation must link the previous page's final body block"
                    )
        for block in blocks_by_id.values():
            previous_footnote_id = block.footnote_continues_from_block_id
            if previous_footnote_id is None:
                continue
            previous = blocks_by_id.get(previous_footnote_id)
            if previous is None:
                raise ValueError("footnote continuation links an unknown block")
            if (
                block.type is not BlockType.FOOTNOTE
                or previous.type is not BlockType.FOOTNOTE
                or previous.original_page_number != block.original_page_number - 1
                or previous.footnote_id != block.footnote_id
                or previous.continuation
                not in {
                    SegmentContinuation.TO_NEXT_PAGE,
                    SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
                    SegmentContinuation.UNKNOWN,
                }
            ):
                raise ValueError(
                    "footnote continuation must reuse the same ID from the previous page"
                )
            if (
                block.footnote_owner_block_id != previous.footnote_owner_block_id
                or block.footnote_anchor_offset != previous.footnote_anchor_offset
                or block.footnote_owner_review_required != previous.footnote_owner_review_required
            ):
                raise ValueError("continued footnotes must retain their original entrypoint")
        return self
