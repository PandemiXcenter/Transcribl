from __future__ import annotations

from pydantic import ValidationError

from transcribl.application.fingerprints import (
    page_input_fingerprint,
    table_input_fingerprint,
)
from transcribl.application.prompting import (
    PROMPT_VERSION,
    build_page_prompt,
    build_table_prompt,
)
from transcribl.application.translation.blocks import to_translated_blocks
from transcribl.application.translation.paragraph_repair import apply_paragraph_revisions
from transcribl.application.translation.tables import (
    apply_table_reconstruction,
    pending_table_blocks,
    refresh_page_evidence,
    validate_completed_table_checkpoint,
)
from transcribl.domain.enums import (
    JobStatus,
)
from transcribl.domain.errors import (
    ArtifactError,
    PageTranslationError,
    StaleCheckpointError,
)
from transcribl.domain.models import (
    JobManifest,
    PageFailure,
    PageTranslation,
    PreparedPage,
    ProviderMetadata,
    TranslationSettings,
    utc_now,
)
from transcribl.ports.artifacts import ArtifactRepository
from transcribl.ports.translation import (
    PageTranslationRequest,
    PageTranslator,
    TableReconstructionRequest,
)


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:5]:
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}")
        return f"Structured output validation failed: {'; '.join(details)}"[:1_000]
    if not isinstance(
        exc,
        (ArtifactError, ConnectionError, OSError, TimeoutError, ValueError),
    ):
        return f"{type(exc).__name__}: operation failed; raw provider details were not persisted"
    message = " ".join(str(exc).split())
    return (message or type(exc).__name__)[:1_000]


def translate_page_checkpoint(
    repository: ArtifactRepository,
    manifest: JobManifest,
    page: PreparedPage,
    settings: TranslationSettings,
    translator: PageTranslator,
    translated_pages: list[PageTranslation],
    translation_run_id: str,
) -> PageTranslation:
    """Resume/execute both passes of one page, recording the exact failed stage."""
    descriptor = translator.descriptor
    fingerprint: str | None = None
    failure_stage = "page_translation"
    try:
        markdown = repository.read_text(page.markdown)
        image_path = repository.resolve(page.image)
        prompt = build_page_prompt(
            page_number=page.original_page_number,
            markdown=markdown,
            settings=settings,
            previous_pages=translated_pages,
        )
        fingerprint = page_input_fingerprint(
            page=page,
            settings=settings,
            provider=descriptor,
            prompt=prompt,
        )

        translation: PageTranslation | None = None
        if repository.has_page_translation(
            translation_run_id,
            page.original_page_number,
        ):
            checkpoint = repository.read_page_translation(
                translation_run_id,
                page.original_page_number,
            )
            if checkpoint.input_fingerprint != fingerprint:
                raise StaleCheckpointError(
                    f"Page {page.original_page_number} has a checkpoint from different "
                    "inputs, config, prompt, provider, or model; rerun with --force"
                )
            translation = refresh_page_evidence(checkpoint, page, markdown)
            apply_paragraph_revisions(
                translated_pages, translation, enabled=settings.previous_page_context_count > 0
            )
            if not pending_table_blocks(translation):
                validate_completed_table_checkpoint(
                    translation=translation,
                    page=page,
                    markdown=markdown,
                    settings=settings,
                    descriptor=descriptor,
                    previous_pages=translated_pages,
                )
                repository.write_page_translation(translation_run_id, translation)
                repository.clear_page_failure(
                    translation_run_id,
                    page.original_page_number,
                )
                return translation

        if translation is None:
            result = translator.translate_page(
                PageTranslationRequest(
                    original_page_number=page.original_page_number,
                    markdown=markdown,
                    image_path=image_path,
                    image_media_type=page.image.media_type,
                    prompt=prompt,
                    settings=settings,
                )
            )
            blocks = to_translated_blocks(
                page.original_page_number,
                result.payload.blocks,
                previous_page=translated_pages[-1] if translated_pages else None,
            )
            translation = PageTranslation(
                translation_run_id=translation_run_id,
                original_page_number=page.original_page_number,
                pdf_page_label=page.pdf_page_label,
                detected_printed_page_label=result.payload.detected_printed_page_label,
                extraction_status=page.extraction_status,
                extracted_character_count=page.extracted_character_count,
                extraction_warnings=page.extraction_warnings,
                source_markdown=markdown,
                source_markdown_artifact=page.markdown,
                source_image=page.image,
                blocks=blocks,
                paragraph_revisions=result.payload.paragraph_revisions,
                input_fingerprint=fingerprint,
                provider=ProviderMetadata(
                    provider=descriptor.provider,
                    model=descriptor.model,
                    prompt_version=PROMPT_VERSION,
                    configuration=dict(descriptor.configuration),
                    semantic_configuration=dict(descriptor.semantic_configuration),
                    response_id=result.response_id,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                ),
            )
            apply_paragraph_revisions(
                translated_pages, translation, enabled=settings.previous_page_context_count > 0
            )
            # The first-pass result is a durable stage checkpoint. If the
            # table call fails, resume starts here instead of paying for
            # and potentially changing the page segmentation again.
            repository.write_page_translation(translation_run_id, translation)

        table_blocks = pending_table_blocks(translation)
        if table_blocks:
            failure_stage = "table_reconstruction"
            table_prompt = build_table_prompt(
                page_translation=translation,
                markdown=markdown,
                settings=settings,
                previous_pages=translated_pages,
            )
            fingerprint = table_input_fingerprint(
                page=page,
                settings=settings,
                provider=descriptor,
                prompt=table_prompt,
                first_pass_fingerprint=translation.input_fingerprint,
                table_blocks=table_blocks,
            )
            table_result = translator.reconstruct_tables(
                TableReconstructionRequest(
                    original_page_number=page.original_page_number,
                    markdown=markdown,
                    image_path=image_path,
                    image_media_type=page.image.media_type,
                    prompt=table_prompt,
                    settings=settings,
                    expected_block_orders=tuple(block.order for block in table_blocks),
                )
            )
            translation = apply_table_reconstruction(
                translation,
                table_result.payload.tables,
                table_fingerprint=fingerprint,
                descriptor=descriptor,
                response_id=table_result.response_id,
                input_tokens=table_result.input_tokens,
                output_tokens=table_result.output_tokens,
            )
        repository.write_page_translation(translation_run_id, translation)
        repository.clear_page_failure(
            translation_run_id,
            page.original_page_number,
        )
        return translation
    except StaleCheckpointError:
        mark_failed(repository, manifest)
        raise
    except Exception as exc:
        safe_message = _safe_error_message(exc)
        repository.write_page_failure(
            translation_run_id,
            PageFailure(
                original_page_number=page.original_page_number,
                input_fingerprint=fingerprint,
                stage=failure_stage,
                error_type=type(exc).__name__,
                message=safe_message,
            ),
        )
        mark_failed(repository, manifest)
        raise PageTranslationError(page.original_page_number, safe_message) from exc


def mark_failed(repository: ArtifactRepository, manifest: JobManifest) -> None:
    repository.write_manifest(
        manifest.model_copy(update={"status": JobStatus.FAILED, "updated_at": utc_now()})
    )
