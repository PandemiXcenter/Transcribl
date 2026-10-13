from __future__ import annotations

import re
from typing import Literal, Self, TypeAlias

from pydantic import (
    Field,
    field_validator,
    model_validator,
)

from transcribl.domain.enums import (
    BlockType,
    ManualInsertionReason,
    SegmentContinuation,
)
from transcribl.domain.models.annotations import (
    FootnoteDescription,
    FootnoteIdentity,
    UncertainTerm,
)
from transcribl.domain.models.base import ContractModel, FootnoteEntrypointToken, NonEmptyText
from transcribl.domain.models.block_rules import (
    _continues_from_previous,
    _continues_to_next,
    _validate_manual_reason,
)
from transcribl.domain.models.paragraphs import ParagraphFragmentRevision

OrdinaryBlockType: TypeAlias = Literal[  # noqa: UP040
    BlockType.TITLE,
    BlockType.SUBTITLE,
    BlockType.BYLINE,
    BlockType.HEADING,
    BlockType.BODY,
    BlockType.LIST_ITEM,
    BlockType.QUOTE,
    BlockType.CAPTION,
    BlockType.PAGE_NUMBER,
    BlockType.HEADER,
    BlockType.FOOTER,
    BlockType.EQUATION,
    BlockType.OTHER,
]


class GeneratedTextBlock(ContractModel):
    """Ordinary provider text that is transcribed and translated."""

    order: int = Field(ge=1)
    type: OrdinaryBlockType
    source_text: NonEmptyText
    translated_text: NonEmptyText
    heading_level: int | None = Field(default=None, ge=1, le=6)
    paragraph_continuation: SegmentContinuation | None
    uncertainties: list[UncertainTerm] = Field(default_factory=list)
    classification_review_required: bool = False

    @model_validator(mode="after")
    def paragraph_continuation_applies_only_to_body_text(self) -> Self:
        if self.type is BlockType.BODY and self.paragraph_continuation is None:
            raise ValueError("body blocks must state their paragraph continuation")
        if self.type is not BlockType.BODY and self.paragraph_continuation is not None:
            raise ValueError("paragraph continuation is valid only for body blocks")
        return self


class GeneratedFootnoteBlock(ContractModel):
    """A functional footnote, regardless of its size or position on the page."""

    order: int = Field(ge=1)
    type: Literal[BlockType.FOOTNOTE]
    source_text: NonEmptyText
    translated_text: NonEmptyText
    footnote_id: FootnoteIdentity
    entrypoint_token: FootnoteEntrypointToken | None
    description: FootnoteDescription
    owner_review_required: bool
    continuation: SegmentContinuation
    uncertainties: list[UncertainTerm] = Field(default_factory=list)
    classification_review_required: bool = False

    @model_validator(mode="after")
    def entrypoint_must_match_identity(self) -> Self:
        if self.entrypoint_token is not None and self.entrypoint_token != (
            f"[[FOOTNOTE:{self.footnote_id.id}]]"
        ):
            raise ValueError("footnote entrypoint token must contain its footnote ID")
        if _continues_from_previous(self.continuation) and self.entrypoint_token is not None:
            raise ValueError("a continued footnote must reuse its earlier entrypoint")
        return self


class GeneratedManualInsertionBlock(ContractModel):
    """A text-free first-pass table tag or figure requiring manual insertion."""

    order: int = Field(ge=1)
    type: Literal[BlockType.TABLE, BlockType.FIGURE]
    manual_insertion_reason: ManualInsertionReason
    continuation: SegmentContinuation
    classification_review_required: bool = False

    @model_validator(mode="after")
    def reason_must_match_block_type(self) -> Self:
        _validate_manual_reason(self.type, self.manual_insertion_reason)
        return self


GeneratedBlock = GeneratedTextBlock

GeneratedBlockVariant: TypeAlias = (  # noqa: UP040
    GeneratedTextBlock | GeneratedFootnoteBlock | GeneratedManualInsertionBlock
)


class GeneratedPagePayload(ContractModel):
    """Provider output before trusted provenance is attached."""

    detected_printed_page_label: str | None = None
    blocks: list[GeneratedBlockVariant] = Field(default_factory=list)
    paragraph_revisions: list[ParagraphFragmentRevision] = Field(default_factory=list)

    @model_validator(mode="after")
    def block_order_must_be_unique_and_contiguous(self) -> Self:
        orders = [block.order for block in self.blocks]
        expected = list(range(1, len(orders) + 1))
        if orders != expected:
            raise ValueError(f"block order must be contiguous and ordered; expected {expected}")
        body_blocks = [block for block in self.blocks if block.type is BlockType.BODY]
        incoming = [
            block
            for block in body_blocks
            if isinstance(block, GeneratedTextBlock)
            and _continues_from_previous(block.paragraph_continuation)
        ]
        outgoing = [
            block
            for block in body_blocks
            if isinstance(block, GeneratedTextBlock)
            and _continues_to_next(block.paragraph_continuation)
        ]
        if self.paragraph_revisions and not incoming:
            raise ValueError("paragraph revisions require an incoming body continuation")
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
        footnotes = [block for block in self.blocks if isinstance(block, GeneratedFootnoteBlock)]
        footnote_ids = [block.footnote_id.id for block in footnotes]
        if len(footnote_ids) != len(set(footnote_ids)):
            raise ValueError("a footnote ID may occur only once on one physical page")
        declared_tokens = [
            block.entrypoint_token for block in footnotes if block.entrypoint_token is not None
        ]
        if len(declared_tokens) != len(set(declared_tokens)):
            raise ValueError("footnote owner reference tokens must be unique")
        translated_owner_text = [
            block.translated_text for block in self.blocks if isinstance(block, GeneratedTextBlock)
        ]
        all_translated_text = [
            block.translated_text
            for block in self.blocks
            if isinstance(block, (GeneratedTextBlock, GeneratedFootnoteBlock))
        ]
        for footnote in footnotes:
            token = footnote.entrypoint_token
            if token is None:
                if (
                    not _continues_from_previous(footnote.continuation)
                    and not footnote.owner_review_required
                ):
                    raise ValueError("an unowned footnote must require owner review")
                continue
            if footnote.owner_review_required:
                raise ValueError("a resolved footnote owner cannot require owner review")
            if sum(text.count(token) for text in translated_owner_text) != 1:
                raise ValueError(
                    "a footnote owner reference token must occur exactly once in ordinary "
                    "translated text"
                )
        embedded_tokens = {
            token
            for text in all_translated_text
            for token in re.findall(r"\[\[FOOTNOTE:fn-p[1-9]\d*-n[1-9]\d*\]\]", text)
        }
        if embedded_tokens != set(declared_tokens):
            raise ValueError("translated text contains an undeclared footnote reference token")
        return self


class GeneratedTableMarkdown(ContractModel):
    """One table reconstructed in target-language GitHub-flavored Markdown."""

    order: int = Field(ge=1)
    translated_markdown: NonEmptyText
    uncertainties: list[UncertainTerm] = Field(default_factory=list)

    @field_validator("translated_markdown")
    @classmethod
    def markdown_must_be_an_unfenced_gfm_table(cls, value: str) -> str:
        if "```" in value:
            raise ValueError("table Markdown must not use a code fence")
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError("table Markdown must contain a header, delimiter, and data row")
        rows = [_split_gfm_row(line) for line in lines]
        if any(row is None for row in rows):
            raise ValueError("every table Markdown line must be a pipe-delimited row")
        parsed_rows = [row for row in rows if row is not None]
        column_count = len(parsed_rows[0])
        if column_count < 1 or any(len(row) != column_count for row in parsed_rows[1:]):
            raise ValueError("table Markdown rows must have matching column counts")
        if not _is_gfm_delimiter_row(parsed_rows[1]):
            raise ValueError("table Markdown must contain a GitHub-flavored table delimiter row")
        return value


class GeneratedTablePayload(ContractModel):
    """Atomic reconstruction output for every table tagged in one page pass."""

    tables: list[GeneratedTableMarkdown] = Field(min_length=1)

    @model_validator(mode="after")
    def table_orders_must_be_unique_and_ascending(self) -> Self:
        orders = [table.order for table in self.tables]
        if orders != sorted(set(orders)):
            raise ValueError("table orders must be unique and ascending")
        return self


def _split_gfm_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if "|" not in stripped:
        return None
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_gfm_delimiter_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell) is not None for cell in cells)
