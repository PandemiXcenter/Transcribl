"""Scope and replay next-page paragraph repairs without rewriting checkpoints."""

from collections.abc import Sequence

from transcribl.application.translation.blocks import strip_footnote_reference_tokens
from transcribl.domain.enums import BlockType, SegmentContinuation
from transcribl.domain.models import PageTranslation, TranslatedBlock


def unfinished_paragraph(pages: Sequence[PageTranslation]) -> list[TranslatedBlock]:
    """Return the complete linked tail, even when it exceeds general context depth."""
    if not pages:
        return []
    tail = next(
        (block for block in reversed(pages[-1].blocks) if block.type is BlockType.BODY), None
    )
    if tail is None or tail.paragraph_continuation not in {
        SegmentContinuation.TO_NEXT_PAGE,
        SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE,
        SegmentContinuation.UNKNOWN,
    }:
        return []
    by_id = {block.block_id: block for page in pages for block in page.blocks}
    chain = [tail]
    while (previous_id := chain[-1].continues_from_block_id) is not None:
        previous = by_id.get(previous_id)
        if (
            previous is None
            or previous.type is not BlockType.BODY
            or previous.original_page_number != chain[-1].original_page_number - 1
        ):
            raise ValueError("unfinished paragraph contains an invalid continuation link")
        chain.append(previous)
    return list(reversed(chain))


def _owner_tokens(pages: Sequence[PageTranslation], owner_id: str) -> dict[str, int]:
    return {
        f"[[FOOTNOTE:{block.footnote_id.id}]]": block.footnote_anchor_offset
        for page in pages
        for block in page.blocks
        if block.footnote_owner_block_id == owner_id
        and block.footnote_id is not None
        and block.footnote_anchor_offset is not None
    }


def paragraph_repair_context(pages: Sequence[PageTranslation]) -> list[dict[str, object]]:
    """Project only eligible paragraph text and movable semantic note entrypoints."""
    projection: list[dict[str, object]] = []
    for block in unfinished_paragraph(pages):
        text = block.translated_text or ""
        for token, offset in sorted(
            _owner_tokens(pages, block.block_id).items(),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        ):
            text = text[:offset] + token + text[offset:]
        projection.append(
            {
                "original_page_number": block.original_page_number,
                "order": block.order,
                "source_text": block.source_text,
                "translated_text": text,
                "uncertainties": [item.model_dump(mode="json") for item in block.uncertainties],
            }
        )
    return projection


def apply_paragraph_revisions(
    previous_pages: Sequence[PageTranslation],
    current: PageTranslation,
    *,
    enabled: bool,
) -> list[PageTranslation]:
    """Validate and materialize repairs in memory; never mutate the input pages.

    Each later page checkpoint retains the proposal. Replaying ordered checkpoints
    reconstructs the same final wording and the same subsequent request fingerprints.
    """
    pages = [*previous_pages, current]
    revisions = current.paragraph_revisions
    if not revisions:
        return pages
    if not enabled:
        raise ValueError("paragraph revisions require previous-page context")
    chain = unfinished_paragraph(previous_pages)
    expected = [(block.original_page_number, block.order) for block in chain]
    actual = [(item.original_page_number, item.order) for item in revisions]
    incoming = next((block for block in current.blocks if block.type is BlockType.BODY), None)
    if (
        not chain
        or actual != expected
        or incoming is None
        or incoming.continues_from_block_id != chain[-1].block_id
        or chain[-1].original_page_number != current.original_page_number - 1
        or any(page.translation_run_id != current.translation_run_id for page in previous_pages)
    ):
        raise ValueError("paragraph revisions must cover exactly the linked unfinished paragraph")

    replacements: dict[str, TranslatedBlock] = {}
    owner_offsets: dict[str, dict[str, int]] = {}
    for block, revision in zip(chain, revisions, strict=True):
        expected_tokens = _owner_tokens(previous_pages, block.block_id)
        text, offsets = strip_footnote_reference_tokens(revision.translated_text)
        if offsets.keys() != expected_tokens.keys() or any(
            revision.translated_text.count(token) != 1 for token in expected_tokens
        ):
            raise ValueError("paragraph revisions must preserve every existing footnote entrypoint")
        replacements[block.block_id] = block.model_copy(
            update={"translated_text": text, "uncertainties": revision.uncertainties}
        )
        owner_offsets[block.block_id] = offsets

    resolved: list[PageTranslation] = []
    for page in pages:
        blocks = []
        for original in page.blocks:
            block = replacements.get(original.block_id, original)
            if block.footnote_owner_block_id in owner_offsets and block.footnote_id is not None:
                offsets = owner_offsets[block.footnote_owner_block_id]
                block = block.model_copy(
                    update={
                        "footnote_anchor_offset": offsets[f"[[FOOTNOTE:{block.footnote_id.id}]]"]
                    }
                )
            blocks.append(block)
        resolved.append(PageTranslation.model_validate({**page.model_dump(), "blocks": blocks}))
    return resolved
