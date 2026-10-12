import pytest

import transcribl.application.fingerprints as fingerprints
from transcribl.domain.enums import (
    BlockType,
    ExtractionStatus,
    ManualInsertionReason,
    SegmentContinuation,
    SegmentHandling,
    UncertaintyLevel,
)
from transcribl.domain.models import (
    ArtifactRef,
    PreparedPage,
    TranslatedBlock,
    TranslationSettings,
)
from transcribl.ports.translation import ProviderDescriptor

HASH = "a" * 64


@pytest.mark.parametrize("change", ["style", "thinking"])
def test_style_and_thinking_changes_invalidate_both_passes(change: str) -> None:
    page_hashes, table_hashes = set(), set()
    for value in ("low", "high"):
        settings = TranslationSettings(
            style_name="Research", style_prompt=value if change == "style" else "Preserve register."
        )
        provider = ProviderDescriptor(
            provider="fake",
            model="fake-v1",
            semantic_configuration={"thinking_level": value if change == "thinking" else "default"},
        )
        page_hashes.add(
            fingerprints.page_input_fingerprint(
                page=_page(), settings=settings, provider=provider, prompt="same prompt"
            )
        )
        table_hashes.add(
            fingerprints.table_input_fingerprint(
                page=_page(),
                settings=settings,
                provider=provider,
                prompt="same prompt",
                first_pass_fingerprint=HASH,
                table_blocks=[_table(SegmentContinuation.COMPLETE)],
            )
        )
    assert len(page_hashes) == len(table_hashes) == 2


def _page() -> PreparedPage:
    markdown = ArtifactRef(
        path="prepared/0001/source.md",
        sha256=HASH,
        media_type="text/markdown",
        byte_count=10,
    )
    return PreparedPage(
        original_page_number=1,
        markdown=markdown,
        image=markdown.model_copy(
            update={"path": "prepared/0001/page.png", "media_type": "image/png"}
        ),
        extraction_status=ExtractionStatus.EXTRACTED,
        extracted_character_count=10,
    )


def _table(continuation: SegmentContinuation) -> TranslatedBlock:
    return TranslatedBlock(
        block_id="p0001-b0002",
        original_page_number=1,
        order=2,
        type=BlockType.TABLE,
        source_text=None,
        translated_text=None,
        segment_handling=SegmentHandling.MANUAL_INSERTION,
        manual_insertion_reason=ManualInsertionReason.TABLE_LIKE,
        continuation=continuation,
    )


def test_page_fingerprint_includes_table_prompt_contract_even_without_a_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _page()
    settings = TranslationSettings()
    provider = ProviderDescriptor(provider="fake", model="fake-v1")
    original = fingerprints.page_input_fingerprint(
        page=page,
        settings=settings,
        provider=provider,
        prompt="page prompt",
    )

    monkeypatch.setattr(fingerprints, "table_prompt_contract_sha256", lambda: "b" * 64)
    changed = fingerprints.page_input_fingerprint(
        page=page,
        settings=settings,
        provider=provider,
        prompt="page prompt",
    )

    assert changed != original


def test_page_fingerprint_changes_with_footnote_appearance_guidance() -> None:
    page = _page()
    provider = ProviderDescriptor(provider="fake", model="fake-v1")
    original = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(),
        provider=provider,
        prompt="page prompt",
    )
    changed = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(
            footnote_appearance_instructions="Small type below a short rule."
        ),
        provider=provider,
        prompt="page prompt",
    )

    assert changed != original


def test_selected_glossary_content_invalidates_both_translation_passes() -> None:
    provider = ProviderDescriptor(provider="fake", model="fake-v1")
    page_hashes = set()
    table_hashes = set()
    for glossary in ({}, {"Vatersot": "Dropsy"}, {"Vatersot": "Edema"}):
        settings = TranslationSettings(glossary=glossary)
        page_hashes.add(
            fingerprints.page_input_fingerprint(
                page=_page(), settings=settings, provider=provider, prompt="page prompt"
            )
        )
        table_hashes.add(
            fingerprints.table_input_fingerprint(
                page=_page(),
                settings=settings,
                provider=provider,
                prompt="table prompt",
                first_pass_fingerprint=HASH,
                table_blocks=[_table(SegmentContinuation.COMPLETE)],
            )
        )

    assert len(page_hashes) == len(table_hashes) == 3


def test_page_fingerprint_changes_with_uncertainty_policy() -> None:
    page = _page()
    provider = ProviderDescriptor(provider="fake", model="fake-v1")
    original = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(),
        provider=provider,
        prompt="page prompt",
    )
    high = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(uncertainty_level=UncertaintyLevel.HIGH),
        provider=provider,
        prompt="page prompt",
    )
    instructed = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(uncertainty_instructions="Mark all numbers."),
        provider=provider,
        prompt="page prompt",
    )
    disabled = fingerprints.page_input_fingerprint(
        page=page,
        settings=TranslationSettings(mark_uncertain_terms=False),
        provider=provider,
        prompt="page prompt",
    )

    assert len({original, high, instructed, disabled}) == 4


def test_table_fingerprint_includes_prompt_first_pass_and_target_metadata() -> None:
    page = _page()
    settings = TranslationSettings(previous_page_context_count=2)
    provider = ProviderDescriptor(provider="fake", model="fake-v1")
    base = fingerprints.table_input_fingerprint(
        page=page,
        settings=settings,
        provider=provider,
        prompt="table prompt with preceding translations",
        first_pass_fingerprint=HASH,
        table_blocks=[_table(SegmentContinuation.COMPLETE)],
    )
    changed_prompt = fingerprints.table_input_fingerprint(
        page=page,
        settings=settings,
        provider=provider,
        prompt="changed table prompt",
        first_pass_fingerprint=HASH,
        table_blocks=[_table(SegmentContinuation.COMPLETE)],
    )
    changed_target = fingerprints.table_input_fingerprint(
        page=page,
        settings=settings,
        provider=provider,
        prompt="table prompt with preceding translations",
        first_pass_fingerprint=HASH,
        table_blocks=[_table(SegmentContinuation.TO_NEXT_PAGE)],
    )

    assert len({base, changed_prompt, changed_target}) == 3


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_new_provider_semantics_invalidate_both_passes_but_transport_does_not(
    provider: str,
) -> None:
    from pathlib import Path

    from transcribl.adapters.llm.structured import AnthropicPageTranslator, OpenAIPageTranslator
    from transcribl.config import load_project_config

    config = load_project_config(Path("config/default.toml"))
    settings = config.provider.openai if provider == "openai" else config.provider.anthropic
    cls = OpenAIPageTranslator if provider == "openai" else AnthropicPageTranslator
    descriptors = [
        cls(api_key="unused", config=current, client=object()).descriptor
        for current in (
            settings,
            settings.model_copy(
                update={
                    "request_timeout_seconds": 900,
                    "request_attempts": 1,
                    "max_inline_request_bytes": 1_000_000,
                }
            ),
            settings.model_copy(update={"max_output_tokens": 4096}),
            settings.model_copy(update={"model": "other-model"}),
        )
    ]
    for table in (False, True):
        hashes = []
        for descriptor in descriptors:
            hashes.append(
                fingerprints.table_input_fingerprint(
                    page=_page(),
                    settings=TranslationSettings(),
                    provider=descriptor,
                    prompt="prompt",
                    first_pass_fingerprint=HASH,
                    table_blocks=[_table(SegmentContinuation.COMPLETE)],
                )
                if table
                else fingerprints.page_input_fingerprint(
                    page=_page(),
                    settings=TranslationSettings(),
                    provider=descriptor,
                    prompt="prompt",
                )
            )
        assert hashes[0] == hashes[1]
        assert len({hashes[0], hashes[2], hashes[3]}) == 3
