from __future__ import annotations

from transcribl.domain.editorial import (
    ReviewBlock,
    ReviewDocument,
    ReviewParagraphGroup,
    UncertaintyHighlight,
)
from transcribl.domain.errors import (
    EditorialTargetError,
)
from transcribl.domain.models import (
    DocumentTranslation,
    TranslatedBlock,
)


def assert_document_run(
    document: DocumentTranslation,
    translation_run_id: str,
) -> None:
    if document.translation_run_id != translation_run_id:
        raise EditorialTargetError(
            f"Document belongs to translation run {document.translation_run_id}, "
            f"not {translation_run_id}"
        )


def assert_review_page(
    document: DocumentTranslation,
    original_page_number: int,
) -> None:
    if original_page_number < 1 or original_page_number > document.page_count:
        raise EditorialTargetError(
            f"Physical page {original_page_number} is outside this "
            f"{document.page_count}-page document"
        )


def iter_machine_blocks(document: DocumentTranslation) -> list[TranslatedBlock]:
    return [block for page in document.pages for block in page.blocks]


def iter_review_blocks(document: ReviewDocument) -> list[ReviewBlock]:
    return [block for page in document.pages for block in page.blocks]


def effective_text_by_block(document: ReviewDocument) -> dict[str, str]:
    return {
        block.block_id: block.effective_translated_text for block in iter_review_blocks(document)
    }


def find_review_block(document: ReviewDocument, block_id: str) -> ReviewBlock:
    matches = [block for block in iter_review_blocks(document) if block.block_id == block_id]
    if len(matches) != 1:
        raise EditorialTargetError(f"Review block not found: {block_id}")
    return matches[0]


def find_review_paragraph(
    document: ReviewDocument,
    paragraph_id: str,
) -> ReviewParagraphGroup:
    matches = [
        paragraph
        for paragraph in document.paragraph_groups
        if paragraph.paragraph_id == paragraph_id
    ]
    if len(matches) != 1:
        raise EditorialTargetError(f"Review paragraph not found: {paragraph_id}")
    return matches[0]


def find_highlight(document: ReviewDocument, uncertainty_id: str) -> UncertaintyHighlight:
    matches = [
        highlight
        for block in iter_review_blocks(document)
        for highlight in block.uncertainty_highlights
        if highlight.uncertainty_id == uncertainty_id
    ]
    if len(matches) != 1:
        raise EditorialTargetError(f"Uncertainty highlight not found: {uncertainty_id}")
    return matches[0]
