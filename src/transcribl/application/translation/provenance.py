from __future__ import annotations

from transcribl.domain.errors import (
    IncompleteDocumentError,
)
from transcribl.domain.models import (
    DocumentTranslation,
    JobManifest,
)


def validate_document_for_manifest(
    document: DocumentTranslation,
    manifest: JobManifest,
) -> None:
    document_identity = (
        document.document_id,
        document.job_id,
        document.source_file_sha256,
        document.page_count,
    )
    manifest_identity = (
        manifest.document_id,
        manifest.job_id,
        manifest.source_file_sha256,
        manifest.page_count,
    )
    if document_identity != manifest_identity:
        raise IncompleteDocumentError(
            "Canonical document identity does not match the current job manifest"
        )
    if (
        manifest.translation_run_id is None
        or document.translation_run_id != manifest.translation_run_id
    ):
        raise IncompleteDocumentError(
            "Canonical document does not belong to the active translation run"
        )
    if (
        manifest.translation_settings is None
        or document.translation_settings != manifest.translation_settings
    ):
        raise IncompleteDocumentError(
            "Canonical document settings do not match the current job manifest"
        )
    for page in document.pages:
        provider = page.provider
        if (
            provider.provider != manifest.provider_name
            or provider.model != manifest.provider_model
            or provider.semantic_configuration != (manifest.provider_semantic_configuration or {})
            or provider.prompt_version != manifest.prompt_version
        ):
            raise IncompleteDocumentError(
                "Canonical page provenance does not match the current job manifest"
            )
        table_metadata = page.table_reconstruction
        if table_metadata is not None and (
            manifest.table_prompt_version is None
            or table_metadata.provider.prompt_version != manifest.table_prompt_version
            or table_metadata.provider.provider != manifest.provider_name
            or table_metadata.provider.model != manifest.provider_model
            or table_metadata.provider.semantic_configuration
            != (manifest.provider_semantic_configuration or {})
        ):
            raise IncompleteDocumentError(
                "Canonical table-pass provenance does not match the current job manifest"
            )
