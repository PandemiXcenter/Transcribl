from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from threading import RLock

from transcribl.application.exporters.latex import compile_latex
from transcribl.application.exporters.markdown import compile_markdown
from transcribl.application.exporters.text import compile_text
from transcribl.application.review.history import make_revision, resolved_ids_for_block
from transcribl.application.review.projection import build_review_document
from transcribl.application.review.queries import (
    assert_document_run,
    assert_review_page,
    effective_text_by_block,
    find_highlight,
    find_review_block,
    find_review_paragraph,
    iter_review_blocks,
)
from transcribl.application.review.uncertainties import replace_highlight_offsets
from transcribl.domain.editorial import (
    BlockRevision,
    ReviewBlock,
    ReviewDocument,
    ReviewPosition,
    UncertaintyHighlight,
)
from transcribl.domain.enums import BlockType, ReviewStatus, SegmentHandling
from transcribl.domain.errors import (
    EditorialError,
    EditorialTargetError,
    ReplaceAllUnavailableError,
    RevisionConflictError,
)
from transcribl.domain.models import (
    DocumentTranslation,
    MarkdownExportSettings,
)
from transcribl.ports.editorial import EditorialRepository

_REVISION_LOCK = RLock()


class EditorialService:
    """Build effective review views and append optimistic editorial revisions."""

    def __init__(self, repository: EditorialRepository) -> None:
        self._repository = repository
        self._lock = _REVISION_LOCK

    def get_review_position(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
    ) -> ReviewPosition | None:
        with self._lock:
            assert_document_run(document, translation_run_id)
            position = self._repository.read_review_position(
                document.document_id,
                translation_run_id,
            )
            if position is not None:
                assert_review_page(document, position.original_page_number)
            return position

    def save_review_position(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        original_page_number: int,
    ) -> ReviewPosition:
        with self._lock:
            assert_document_run(document, translation_run_id)
            assert_review_page(document, original_page_number)
            position = ReviewPosition(
                document_id=document.document_id,
                translation_run_id=translation_run_id,
                original_page_number=original_page_number,
            )
            self._repository.write_review_position(position)
            return position

    def review_document(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
    ) -> ReviewDocument:
        with self._lock:
            return build_review_document(self._repository, document, translation_run_id)

    def revise_block(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        block_id: str,
        editorial_text: str,
        *,
        expected_base_revision: int,
        block_type: BlockType | None = None,
        footnote_owner_block_id: str | None = None,
        footnote_anchor_offset: int | None = None,
        status: ReviewStatus = ReviewStatus.IN_REVIEW,
        editor: str | None = None,
        note: str | None = None,
    ) -> BlockRevision:
        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            block = find_review_block(review, block_id)
            self._assert_base_revision(block, expected_base_revision)
            preserve_metadata = block_type is None
            block_type = block_type or block.type
            if preserve_metadata:
                footnote_owner_block_id = block.footnote_owner_block_id
            if block.segment_handling is not SegmentHandling.TRANSLATE and block_type != block.type:
                raise EditorialTargetError(
                    "Table and manual-insertion block types cannot be changed in this editor"
                )
            if block_type in {BlockType.TABLE, BlockType.FIGURE} and block_type != block.type:
                raise EditorialTargetError(
                    "Use the dedicated table or figure workflow for that section type"
                )
            if block_type is BlockType.FOOTNOTE and any(
                candidate.block_id != block.block_id
                and candidate.footnote_owner_block_id == block.block_id
                for page in review.pages
                for candidate in page.blocks
            ):
                raise EditorialTargetError(
                    "Reassign this section's owned footnotes before changing it to a footnote"
                )
            owner_offset = None
            owner_review_required = False
            if block_type is BlockType.FOOTNOTE:
                if footnote_owner_block_id is None:
                    owner_review_required = True
                else:
                    owner = find_review_block(review, footnote_owner_block_id)
                    if owner.block_id == block.block_id or owner.type is BlockType.FOOTNOTE:
                        raise EditorialTargetError(
                            "A footnote owner must be a different, non-footnote text section"
                        )
                    if owner.segment_handling is not SegmentHandling.TRANSLATE:
                        raise EditorialTargetError(
                            "A footnote owner must be an ordinary translated text section"
                        )
                    if footnote_anchor_offset is not None:
                        if footnote_anchor_offset > len(owner.effective_translated_text):
                            raise EditorialTargetError(
                                "The footnote marker position is outside the owner text"
                            )
                        owner_offset = footnote_anchor_offset
                    else:
                        owner_offset = (
                            block.footnote_anchor_offset
                            if footnote_owner_block_id == block.footnote_owner_block_id
                            and block.footnote_anchor_offset is not None
                            else len(owner.effective_translated_text)
                        )
            resolved_ids = resolved_ids_for_block(
                self._repository,
                document.document_id,
                translation_run_id,
                block_id,
            )
            revision = make_revision(
                document=document,
                translation_run_id=translation_run_id,
                block=block,
                editorial_text=editorial_text,
                effective_type=block_type,
                footnote_owner_block_id=footnote_owner_block_id,
                footnote_anchor_offset=owner_offset,
                footnote_owner_review_required=owner_review_required,
                status=status,
                editor=editor,
                note=note,
                resolved_uncertainty_ids=resolved_ids,
            )
            self._repository.append_block_revision(revision)
            return revision

    def revise_paragraph(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        paragraph_id: str,
        fragments: list[tuple[str, str, int]],
        *,
        status: ReviewStatus = ReviewStatus.IN_REVIEW,
        editor: str | None = None,
        note: str | None = None,
    ) -> list[BlockRevision]:
        """Append one fragment-scoped revision for every part of a visual paragraph."""

        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            paragraph = find_review_paragraph(review, paragraph_id)
            requested_ids = [block_id for block_id, _, _ in fragments]
            if requested_ids != paragraph.fragment_block_ids:
                raise EditorialTargetError(
                    "Paragraph revisions must contain every fragment in trusted order"
                )

            review_blocks = [find_review_block(review, block_id) for block_id in requested_ids]
            for block, (_, editorial_text, expected_base_revision) in zip(
                review_blocks,
                fragments,
                strict=True,
            ):
                if block.type is not BlockType.BODY:
                    raise EditorialTargetError("Paragraph revisions may contain only body text")
                if not editorial_text.strip():
                    raise EditorialError("Paragraph fragments must not be blank")
                self._assert_base_revision(block, expected_base_revision)

            revisions: list[BlockRevision] = []
            for block, (_, editorial_text, _) in zip(
                review_blocks,
                fragments,
                strict=True,
            ):
                resolved_ids = resolved_ids_for_block(
                    self._repository,
                    document.document_id,
                    translation_run_id,
                    block.block_id,
                )
                revisions.append(
                    make_revision(
                        document=document,
                        translation_run_id=translation_run_id,
                        block=block,
                        editorial_text=editorial_text,
                        effective_type=BlockType.BODY,
                        footnote_owner_review_required=False,
                        status=status,
                        editor=editor,
                        note=note,
                        resolved_uncertainty_ids=resolved_ids,
                    )
                )

            for revision in revisions:
                self._repository.append_block_revision(revision)
            return revisions

    def replace_uncertainty(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        uncertainty_id: str,
        replacement: str,
        *,
        replace_all: bool,
        expected_base_revisions: Mapping[str, int],
        status: ReviewStatus = ReviewStatus.IN_REVIEW,
        editor: str | None = None,
        note: str | None = None,
    ) -> list[BlockRevision]:
        """Replace one highlight or every matching annotated occurrence.

        The command never calls ``str.replace`` over an entire block. It uses only
        the exact offsets exposed in the current review projection, so identical
        text introduced by a reviewer is not silently treated as model uncertainty.
        """

        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            selected = find_highlight(review, uncertainty_id)
            matches = [
                (block, highlight)
                for block in iter_review_blocks(review)
                for highlight in block.uncertainty_highlights
                if highlight.term_group_id == selected.term_group_id
            ]
            if replace_all:
                if len(matches) <= 1:
                    raise ReplaceAllUnavailableError(
                        "Translate All requires at least two unresolved annotated occurrences"
                    )
                targets = matches
            else:
                targets = [
                    (block, highlight)
                    for block, highlight in matches
                    if highlight.uncertainty_id == uncertainty_id
                ]

            targets_by_block: dict[str, list[UncertaintyHighlight]] = defaultdict(list)
            blocks: dict[str, ReviewBlock] = {}
            for block, highlight in targets:
                targets_by_block[block.block_id].append(highlight)
                blocks[block.block_id] = block

            for block_id, block in blocks.items():
                self._assert_base_revision(
                    block,
                    expected_base_revisions.get(block_id),
                )

            revisions: list[BlockRevision] = []
            for block_id, highlights in targets_by_block.items():
                block = blocks[block_id]
                editorial_text = replace_highlight_offsets(
                    block.effective_translated_text,
                    highlights,
                    replacement,
                )
                resolved_ids = resolved_ids_for_block(
                    self._repository,
                    document.document_id,
                    translation_run_id,
                    block_id,
                )
                resolved_ids.update(highlight.uncertainty_id for highlight in highlights)
                revisions.append(
                    make_revision(
                        document=document,
                        translation_run_id=translation_run_id,
                        block=block,
                        editorial_text=editorial_text,
                        status=status,
                        editor=editor,
                        note=note,
                        resolved_uncertainty_ids=resolved_ids,
                    )
                )

            for revision in revisions:
                self._repository.append_block_revision(revision)
            return revisions

    def compile_reviewed_markdown(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        settings: MarkdownExportSettings,
    ) -> str:
        """Render the latest editorial text without mutating canonical machine data."""

        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            effective_text = {
                block.block_id: block.effective_translated_text
                for block in iter_review_blocks(review)
            }
            return compile_markdown(
                document,
                settings,
                editorial_overrides=effective_text,
                type_overrides={block.block_id: block.type for block in iter_review_blocks(review)},
                footnote_owner_overrides={
                    block.block_id: (
                        block.footnote_owner_block_id,
                        block.footnote_anchor_offset,
                        block.footnote_owner_review_required,
                    )
                    for block in iter_review_blocks(review)
                    if block.type is BlockType.FOOTNOTE and block.latest_revision_number > 0
                },
            )

    def compile_reviewed_text(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        settings: MarkdownExportSettings,
    ) -> str:
        """Render the latest editorial text directly as plain text."""

        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            return compile_text(
                document,
                settings,
                editorial_overrides=effective_text_by_block(review),
                type_overrides={block.block_id: block.type for block in iter_review_blocks(review)},
            )

    def compile_reviewed_latex(
        self,
        document: DocumentTranslation,
        translation_run_id: str,
        settings: MarkdownExportSettings,
    ) -> str:
        """Render the latest editorial text directly as safe XeLaTeX source."""

        with self._lock:
            review = build_review_document(self._repository, document, translation_run_id)
            return compile_latex(
                document,
                settings,
                editorial_overrides=effective_text_by_block(review),
                type_overrides={block.block_id: block.type for block in iter_review_blocks(review)},
                footnote_owner_overrides={
                    block.block_id: (
                        block.footnote_owner_block_id,
                        block.footnote_anchor_offset,
                        block.footnote_owner_review_required,
                    )
                    for block in iter_review_blocks(review)
                    if block.type is BlockType.FOOTNOTE and block.latest_revision_number > 0
                },
            )

    @staticmethod
    def _assert_base_revision(
        block: ReviewBlock,
        expected_base_revision: int | None,
    ) -> None:
        if expected_base_revision != block.latest_revision_number:
            raise RevisionConflictError(
                block.block_id,
                expected_base_revision,
                block.latest_revision_number,
            )
