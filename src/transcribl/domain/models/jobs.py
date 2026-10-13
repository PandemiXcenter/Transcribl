from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import (
    Field,
    model_validator,
)

from transcribl.domain.enums import (
    JobStatus,
)
from transcribl.domain.models.base import (
    SCHEMA_VERSION,
    ContractModel,
    NonEmptyText,
    ProviderSetting,
    Sha256,
    TranslationRunId,
    utc_now,
)
from transcribl.domain.models.extraction import PreparedPage
from transcribl.domain.models.settings import MarkdownExportSettings, TranslationSettings


class JobManifest(ContractModel):
    """Mutable run index; page artifacts remain the recovery source of truth."""

    schema_version: Literal["7.0"] = SCHEMA_VERSION
    job_id: NonEmptyText
    preparation_id: NonEmptyText
    document_id: Sha256
    source_file_name: NonEmptyText
    source_file_sha256: Sha256
    image_dpi: int = Field(ge=72, le=600)
    page_count: int = Field(ge=1)
    pages: list[PreparedPage] = Field(min_length=1)
    status: JobStatus = JobStatus.PREPARED
    translation_run_id: TranslationRunId | None = None
    translation_run_ids: list[TranslationRunId] = Field(default_factory=list)
    translation_settings: TranslationSettings | None = None
    provider_name: str | None = None
    provider_model: str | None = None
    provider_configuration: dict[str, ProviderSetting] | None = None
    provider_semantic_configuration: dict[str, ProviderSetting] | None = None
    prompt_version: str | None = None
    table_prompt_version: str | None = None
    export_settings: MarkdownExportSettings | None = None
    auto_continue: bool = False
    auto_continue_attempts: int = Field(default=1, ge=1, le=10)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def pages_must_match_manifest(self) -> Self:
        numbers = [page.original_page_number for page in self.pages]
        expected = list(range(1, self.page_count + 1))
        if numbers != expected:
            raise ValueError(f"manifest pages must be physical pages {expected}")
        if len(self.translation_run_ids) != len(set(self.translation_run_ids)):
            raise ValueError("manifest translation run IDs must be unique")
        if (
            self.translation_run_id is not None
            and self.translation_run_id not in self.translation_run_ids
        ):
            raise ValueError("active translation run must appear in the ordered run index")
        return self


class PageFailure(ContractModel):
    schema_version: Literal["7.0"] = SCHEMA_VERSION
    original_page_number: int = Field(ge=1)
    input_fingerprint: Sha256 | None = None
    stage: Literal["page_translation", "table_reconstruction"] = "page_translation"
    error_type: NonEmptyText
    message: NonEmptyText
    occurred_at: datetime = Field(default_factory=utc_now)
