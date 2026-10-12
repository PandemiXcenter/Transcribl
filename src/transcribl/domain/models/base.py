from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
)

SCHEMA_VERSION: Literal["6.0"] = "6.0"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

TranslationRunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]

BlockId = Annotated[str, StringConstraints(pattern=r"^p\d{4,}-b\d{4,}$")]

FootnoteIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^fn-p[1-9]\d*-n[1-9]\d*$"),
]

FootnoteEntrypointToken = Annotated[
    str,
    StringConstraints(pattern=r"^\[\[FOOTNOTE:fn-p[1-9]\d*-n[1-9]\d*\]\]$"),
]

ProviderSetting = str | int | float | bool


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContractModel(BaseModel):
    """Base for persisted and provider-facing contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
