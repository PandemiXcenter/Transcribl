from __future__ import annotations

from transcribl.application.fingerprints import (
    table_input_fingerprint,
)
from transcribl.application.prompting import (
    TABLE_PROMPT_VERSION,
    build_table_prompt,
)
from transcribl.domain.enums import (
    BlockType,
    SegmentHandling,
)
from transcribl.domain.errors import (
    StaleCheckpointError,
)
from transcribl.domain.models import (
    GeneratedTableMarkdown,
    PageTranslation,
    PreparedPage,
    ProviderMetadata,
    TableReconstructionMetadata,
    TranslatedBlock,
    TranslationSettings,
)
from transcribl.ports.translation import (
    ProviderDescriptor,
)


def pending_table_blocks(translation: PageTranslation) -> list[TranslatedBlock]:
    return [
        block
        for block in translation.blocks
        if block.type is BlockType.TABLE
        and block.segment_handling is SegmentHandling.MANUAL_INSERTION
        and not block.legacy_manual_table
    ]


def validate_completed_table_checkpoint(
    *,
    translation: PageTranslation,
    page: PreparedPage,
    markdown: str,
    settings: TranslationSettings,
    descriptor: ProviderDescriptor,
    previous_pages: list[PageTranslation],
) -> None:
    metadata = translation.table_reconstruction
    if metadata is None:
        return
    first_pass = _restore_first_pass_table_tags(translation)
    table_blocks = pending_table_blocks(first_pass)
    table_prompt = build_table_prompt(
        page_translation=first_pass,
        markdown=markdown,
        settings=settings,
        previous_pages=previous_pages,
    )
    expected_fingerprint = table_input_fingerprint(
        page=page,
        settings=settings,
        provider=descriptor,
        prompt=table_prompt,
        first_pass_fingerprint=translation.input_fingerprint,
        table_blocks=table_blocks,
    )
    if metadata.input_fingerprint != expected_fingerprint:
        raise StaleCheckpointError(
            f"Page {page.original_page_number} has a table checkpoint from different "
            "inputs, context, targets, config, prompt, provider, or model; rerun with --force"
        )


def _restore_first_pass_table_tags(translation: PageTranslation) -> PageTranslation:
    blocks: list[TranslatedBlock] = []
    for block in translation.blocks:
        if block.segment_handling is not SegmentHandling.TABLE_RECONSTRUCTION:
            blocks.append(block)
            continue
        blocks.append(
            TranslatedBlock.model_validate(
                {
                    **block.model_dump(mode="python"),
                    "translated_text": None,
                    "uncertainties": [],
                    "segment_handling": SegmentHandling.MANUAL_INSERTION,
                }
            )
        )
    return PageTranslation.model_validate(
        {
            **translation.model_dump(mode="python"),
            "blocks": blocks,
            "table_reconstruction": None,
        }
    )


def refresh_page_evidence(
    checkpoint: PageTranslation,
    page: PreparedPage,
    markdown: str,
) -> PageTranslation:
    return PageTranslation.model_validate(
        {
            **checkpoint.model_dump(mode="python"),
            "pdf_page_label": page.pdf_page_label,
            "extraction_status": page.extraction_status,
            "extracted_character_count": page.extracted_character_count,
            "extraction_warnings": page.extraction_warnings,
            "source_markdown": markdown,
            "source_markdown_artifact": page.markdown,
            "source_image": page.image,
        }
    )


def apply_table_reconstruction(
    translation: PageTranslation,
    generated_tables: list[GeneratedTableMarkdown],
    *,
    table_fingerprint: str,
    descriptor: ProviderDescriptor,
    response_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
) -> PageTranslation:
    table_blocks = pending_table_blocks(translation)
    expected_orders = [block.order for block in table_blocks]
    returned_orders = [table.order for table in generated_tables]
    if returned_orders != expected_orders:
        raise ValueError(
            "Table reconstruction must return exactly the requested block orders; "
            f"expected {expected_orders}, received {returned_orders}"
        )
    generated_by_order = {table.order: table for table in generated_tables}
    reconstructed_blocks: list[TranslatedBlock] = []
    reconstructed_ids: list[str] = []
    for block in translation.blocks:
        generated = generated_by_order.get(block.order)
        if generated is None:
            reconstructed_blocks.append(block)
            continue
        reconstructed_ids.append(block.block_id)
        reconstructed_blocks.append(
            TranslatedBlock.model_validate(
                {
                    **block.model_dump(mode="python"),
                    "source_text": None,
                    "translated_text": generated.translated_markdown,
                    "uncertainties": generated.uncertainties,
                    "segment_handling": SegmentHandling.TABLE_RECONSTRUCTION,
                }
            )
        )
    metadata = TableReconstructionMetadata(
        input_fingerprint=table_fingerprint,
        block_ids=reconstructed_ids,
        provider=ProviderMetadata(
            provider=descriptor.provider,
            model=descriptor.model,
            prompt_version=TABLE_PROMPT_VERSION,
            configuration=dict(descriptor.configuration),
            semantic_configuration=dict(descriptor.semantic_configuration),
            response_id=response_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    )
    return PageTranslation.model_validate(
        {
            **translation.model_dump(mode="python"),
            "blocks": reconstructed_blocks,
            "table_reconstruction": metadata,
        }
    )
