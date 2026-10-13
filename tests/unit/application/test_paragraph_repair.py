from copy import deepcopy

import pytest
from pydantic import ValidationError

from transcribl.application.fingerprints import page_input_fingerprint, table_input_fingerprint
from transcribl.application.prompting import build_page_prompt
from transcribl.application.translation.paragraph_repair import (
    apply_paragraph_revisions,
    paragraph_repair_context,
)
from transcribl.domain.enums import BlockType, ExtractionStatus, SegmentContinuation
from transcribl.domain.models import (
    ArtifactRef,
    FootnoteDescription,
    FootnoteIdentity,
    GeneratedPagePayload,
    PageTranslation,
    PreparedPage,
    ProviderMetadata,
    TranslatedBlock,
    TranslationSettings,
    UncertainTerm,
)
from transcribl.domain.models.paragraphs import ParagraphFragmentRevision
from transcribl.ports.translation import ProviderDescriptor


def _page(number: int, text: str, *, continued: bool = False) -> PageTranslation:
    artifact = ArtifactRef(
        path=f"page-{number}", sha256="a" * 64, media_type="image/png", byte_count=1
    )
    return PageTranslation(
        translation_run_id="1" * 32,
        original_page_number=number,
        extraction_status=ExtractionStatus.EXTRACTED,
        extracted_character_count=1,
        source_markdown="source",
        source_markdown_artifact=artifact,
        source_image=artifact,
        input_fingerprint="a" * 64,
        provider=ProviderMetadata(provider="fake", model="fake", prompt_version="test"),
        blocks=[
            TranslatedBlock(
                block_id=f"p{number:04d}-b0001",
                original_page_number=number,
                order=1,
                type=BlockType.BODY,
                source_text="original wording",
                translated_text=text,
                paragraph_continuation=(
                    SegmentContinuation.FROM_PREVIOUS_AND_TO_NEXT_PAGE
                    if continued
                    else SegmentContinuation.TO_NEXT_PAGE
                ),
                continues_from_block_id=f"p{number - 1:04d}-b0001" if continued else None,
            )
        ],
    )


def _revision(
    text: str = "The inflammation", *, page: int = 1, order: int = 1
) -> ParagraphFragmentRevision:
    return ParagraphFragmentRevision(original_page_number=page, order=order, translated_text=text)


def test_repair_replaces_annotations_and_preserves_footnote_entrypoint() -> None:
    earlier = _page(1, "😀 The inflam-")
    earlier.blocks.append(
        TranslatedBlock(
            block_id="p0001-b0002",
            original_page_number=1,
            order=2,
            type=BlockType.FOOTNOTE,
            source_text="note",
            translated_text="A note",
            footnote_id=FootnoteIdentity(id="fn-p1-n1", text="*"),
            footnote_description=FootnoteDescription(
                appearance="Small type", handling="Owned note"
            ),
            continuation=SegmentContinuation.TO_NEXT_PAGE,
            footnote_owner_block_id="p0001-b0001",
            footnote_anchor_offset=5,
        )
    )
    current = _page(2, "subsided.", continued=True)
    current.blocks.append(
        earlier.blocks[1].model_copy(
            update={
                "block_id": "p0002-b0002",
                "original_page_number": 2,
                "continuation": SegmentContinuation.FROM_PREVIOUS_PAGE,
                "footnote_continues_from_block_id": "p0001-b0002",
            }
        )
    )
    current.paragraph_revisions = [_revision("😀 The inflammation[[FOOTNOTE:fn-p1-n1]]")]
    current.paragraph_revisions[0].uncertainties = [
        UncertainTerm(
            source_term="betændelse",
            proposed_translation="inflammation",
            reason="Check term",
            alternatives=["inflammatory condition"],
        )
    ]
    before = deepcopy(earlier)
    context = paragraph_repair_context([earlier])
    assert context[0]["translated_text"] == "😀 The[[FOOTNOTE:fn-p1-n1]] inflam-"
    resolved = apply_paragraph_revisions([earlier], current, enabled=True)
    assert earlier == before
    assert resolved[0].blocks[0].translated_text == "😀 The inflammation"
    assert resolved[0].blocks[0].source_text == "original wording"
    assert resolved[0].blocks[0].uncertainties == current.paragraph_revisions[0].uncertainties
    for page in resolved:
        assert page.blocks[1].footnote_anchor_offset == len("😀 The inflammation")
    assert PageTranslation.model_validate_json(current.model_dump_json()) == current


@pytest.mark.parametrize(
    "revisions",
    [
        [_revision(page=2)],
        [_revision(order=2)],
        [_revision(), _revision()],
        [_revision(), _revision(page=3)],
    ],
)
def test_repair_rejects_out_of_scope_or_duplicate_targets(
    revisions: list[ParagraphFragmentRevision],
) -> None:
    previous = _page(1, "The inflam-")
    current = _page(2, "subsided.", continued=True)
    current = current.model_copy(update={"paragraph_revisions": revisions})
    with pytest.raises(ValueError, match="exactly the linked unfinished paragraph"):
        apply_paragraph_revisions([previous], current, enabled=True)


def test_repair_requires_entire_chain_and_context_enabled() -> None:
    pages = [_page(1, "The inflam-"), _page(2, "subsided after treat-", continued=True)]
    current = _page(3, "was effective.", continued=True)
    current.paragraph_revisions = [_revision("the treatment", page=2)]
    with pytest.raises(ValueError, match="exactly the linked"):
        apply_paragraph_revisions(pages, current, enabled=True)
    with pytest.raises(ValueError, match="require previous-page context"):
        apply_paragraph_revisions(pages, current, enabled=False)
    prompt = build_page_prompt(
        page_number=3,
        markdown="data",
        previous_pages=pages,
        settings=TranslationSettings(previous_page_context_count=0),
    )
    assert "UNFINISHED_PARAGRAPH_START\n[]\nUNFINISHED_PARAGRAPH_END" in prompt
    assert "PREVIOUS_TRANSLATED_PAGES_START\n[]\nPREVIOUS_TRANSLATED_PAGES_END" in prompt


@pytest.mark.parametrize(
    "replacement",
    [
        "Reworded",
        "Reworded[[FOOTNOTE:fn-p1-n2]]",
        "Reworded[[FOOTNOTE:fn-p1-n1]][[FOOTNOTE:fn-p1-n1]]",
    ],
)
def test_repair_rejects_lost_changed_or_duplicate_footnote_tokens(replacement: str) -> None:
    earlier = _page(1, "Old text")
    earlier.blocks.append(
        TranslatedBlock(
            block_id="p0001-b0002",
            original_page_number=1,
            order=2,
            type=BlockType.FOOTNOTE,
            source_text="note",
            translated_text="note",
            footnote_id=FootnoteIdentity(id="fn-p1-n1", text="*"),
            footnote_description=FootnoteDescription(
                appearance="Small type", handling="Owned note"
            ),
            continuation=SegmentContinuation.COMPLETE,
            footnote_owner_block_id="p0001-b0001",
            footnote_anchor_offset=3,
        )
    )
    current = _page(2, "continued", continued=True)
    current.paragraph_revisions = [_revision(replacement)]
    with pytest.raises(ValueError, match="preserve every existing footnote"):
        apply_paragraph_revisions([earlier], current, enabled=True)


def test_generated_repair_requires_incoming_body_and_strict_fields() -> None:
    with pytest.raises(ValidationError, match="require an incoming body"):
        GeneratedPagePayload(paragraph_revisions=[_revision()])
    with pytest.raises(ValidationError, match="Extra inputs"):
        ParagraphFragmentRevision.model_validate({**_revision().model_dump(), "source_text": "new"})
    current = _page(2, "continues", continued=True)
    current = current.model_copy(update={"paragraph_revisions": [_revision(page=2)]})
    with pytest.raises(ValidationError, match="unique earlier fragments"):
        PageTranslation.model_validate(current.model_dump())


def test_older_paragraph_fragment_changes_both_fingerprints_beyond_general_context() -> None:
    pages = [_page(1, "Original earlier wording"), _page(2, "continues", continued=True)]
    settings = TranslationSettings(previous_page_context_count=1)
    before = build_page_prompt(
        page_number=3, markdown="same OCR", settings=settings, previous_pages=pages
    )
    pages[0].blocks[0].translated_text = "Revised earlier wording"
    after = build_page_prompt(
        page_number=3, markdown="same OCR", settings=settings, previous_pages=pages
    )

    def general_context(prompt: str) -> str:
        return prompt.split("PREVIOUS_TRANSLATED_PAGES_START\n", 1)[1].split(
            "\nPREVIOUS_TRANSLATED_PAGES_END", 1
        )[0]

    assert general_context(before) == general_context(after)
    artifact = pages[0].source_image
    prepared = PreparedPage(
        original_page_number=3,
        markdown=artifact,
        image=artifact,
        extraction_status=ExtractionStatus.EXTRACTED,
        extracted_character_count=1,
    )
    provider = ProviderDescriptor(provider="fake", model="fake")
    first = page_input_fingerprint(
        page=prepared, settings=settings, provider=provider, prompt=before
    )
    second = page_input_fingerprint(
        page=prepared, settings=settings, provider=provider, prompt=after
    )
    assert first != second

    def table_fingerprint(fingerprint: str) -> str:
        return table_input_fingerprint(
            page=prepared,
            settings=settings,
            provider=provider,
            prompt="same table prompt",
            first_pass_fingerprint=fingerprint,
            table_blocks=[],
        )

    assert table_fingerprint(first) != table_fingerprint(second)
