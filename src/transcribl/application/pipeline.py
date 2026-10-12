from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from transcribl.application.exporters.latex import compile_latex
from transcribl.application.exporters.markdown import compile_markdown
from transcribl.application.preparation import prepare_document
from transcribl.application.prompting import (
    PROMPT_VERSION,
    TABLE_PROMPT_VERSION,
)
from transcribl.application.translation.checkpoints import translate_page_checkpoint
from transcribl.application.translation.provenance import validate_document_for_manifest
from transcribl.domain.enums import (
    JobStatus,
)
from transcribl.domain.errors import (
    IncompleteDocumentError,
)
from transcribl.domain.models import (
    DocumentTranslation,
    MarkdownExportSettings,
    PageTranslation,
    TranslationSettings,
    utc_now,
)
from transcribl.ports.artifacts import ArtifactRepository
from transcribl.ports.extraction import PageExtractor
from transcribl.ports.translation import (
    PageTranslator,
)

RepositoryFactory = Callable[[Path], ArtifactRepository]


class TranslationPipeline:
    """Provider-neutral use cases shared by the CLI and local web interface."""

    def __init__(
        self,
        *,
        extractor: PageExtractor,
        repository_factory: RepositoryFactory,
    ) -> None:
        self._extractor = extractor
        self._repository_factory = repository_factory

    def prepare_document(
        self, source_pdf: Path, *, artifacts_dir: Path, image_dpi: int, force: bool = False
    ) -> Path:
        return prepare_document(
            self._extractor,
            self._repository_factory,
            source_pdf,
            artifacts_dir=artifacts_dir,
            image_dpi=image_dpi,
            force=force,
        )

    def translate_document(
        self,
        job_dir: Path,
        *,
        settings: TranslationSettings,
        translator: PageTranslator,
        force: bool = False,
    ) -> DocumentTranslation:
        repository = self._repository_factory(job_dir)
        manifest = repository.read_manifest()
        descriptor = translator.descriptor
        if force or manifest.translation_run_id is None:
            translation_run_id = _new_translation_run_id(manifest.translation_run_ids)
            translation_run_ids = [*manifest.translation_run_ids, translation_run_id]
        else:
            translation_run_id = manifest.translation_run_id
            translation_run_ids = manifest.translation_run_ids
        manifest = manifest.model_copy(
            update={
                "status": JobStatus.TRANSLATING,
                "translation_run_id": translation_run_id,
                "translation_run_ids": translation_run_ids,
                "translation_settings": settings,
                "provider_name": descriptor.provider,
                "provider_model": descriptor.model,
                "provider_configuration": dict(descriptor.configuration),
                "provider_semantic_configuration": dict(descriptor.semantic_configuration),
                "prompt_version": PROMPT_VERSION,
                "table_prompt_version": TABLE_PROMPT_VERSION,
                "updated_at": utc_now(),
            }
        )
        repository.write_manifest(manifest)

        translated_pages: list[PageTranslation] = []
        for page in manifest.pages:
            translated_pages.append(
                translate_page_checkpoint(
                    repository,
                    manifest,
                    page,
                    settings,
                    translator,
                    translated_pages,
                    translation_run_id,
                )
            )

        document = DocumentTranslation(
            translation_run_id=translation_run_id,
            document_id=manifest.document_id,
            job_id=manifest.job_id,
            source_file_name=manifest.source_file_name,
            source_file_sha256=manifest.source_file_sha256,
            page_count=manifest.page_count,
            translation_settings=settings,
            pages=translated_pages,
            created_at=manifest.created_at,
        )
        repository.write_document(translation_run_id, document)
        manifest = manifest.model_copy(
            update={"status": JobStatus.TRANSLATED, "updated_at": utc_now()}
        )
        repository.write_manifest(manifest)
        return document

    def compile_document(
        self,
        job_dir: Path,
        *,
        settings: MarkdownExportSettings,
    ) -> Path:
        repository = self._repository_factory(job_dir)
        manifest = repository.read_manifest()
        if manifest.status not in {JobStatus.TRANSLATED, JobStatus.COMPILED}:
            raise IncompleteDocumentError(
                f"Job status is {manifest.status.value!r}; complete translation before compiling"
            )
        if manifest.translation_run_id is None:
            raise IncompleteDocumentError("Job has no active translation run to compile")
        translation_run_id = manifest.translation_run_id
        document = repository.read_document(translation_run_id)
        validate_document_for_manifest(document, manifest)
        repository.write_markdown(
            translation_run_id,
            compile_markdown(document, settings),
        )
        output = repository.write_latex(
            translation_run_id,
            compile_latex(document, settings),
        )
        manifest = manifest.model_copy(
            update={
                "status": JobStatus.COMPILED,
                "export_settings": settings,
                "updated_at": utc_now(),
            }
        )
        repository.write_manifest(manifest)
        return output


def _new_translation_run_id(existing_run_ids: list[str]) -> str:
    run_id = uuid4().hex
    while run_id in existing_run_ids:
        run_id = uuid4().hex
    return run_id
