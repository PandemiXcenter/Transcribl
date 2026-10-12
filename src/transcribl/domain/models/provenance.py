from __future__ import annotations

from datetime import datetime

from pydantic import (
    Field,
    field_validator,
)

from transcribl.domain.models.base import (
    ContractModel,
    NonEmptyText,
    ProviderSetting,
    Sha256,
    utc_now,
)


class ProviderMetadata(ContractModel):
    provider: NonEmptyText
    model: NonEmptyText
    prompt_version: NonEmptyText
    configuration: dict[str, ProviderSetting] = Field(default_factory=dict)
    semantic_configuration: dict[str, ProviderSetting] = Field(default_factory=dict)
    response_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class TableReconstructionMetadata(ContractModel):
    """Bounded provenance for the optional second provider pass on one page."""

    input_fingerprint: Sha256
    block_ids: list[NonEmptyText] = Field(min_length=1)
    provider: ProviderMetadata
    reconstructed_at: datetime = Field(default_factory=utc_now)

    @field_validator("block_ids")
    @classmethod
    def block_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("table reconstruction block IDs must be unique")
        return value
