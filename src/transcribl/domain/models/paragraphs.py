"""Provider-proposed repairs scoped to an unfinished, cross-page paragraph."""

from pydantic import Field

from transcribl.domain.models.annotations import UncertainTerm
from transcribl.domain.models.base import ContractModel, NonEmptyText


class ParagraphFragmentRevision(ContractModel):
    """Replacement wording for one earlier fragment, identified by page and order.

    Source text, block identity and continuation links remain pipeline-owned.
    Footnote entrypoint tokens must be preserved and are stripped on application.
    """

    original_page_number: int = Field(ge=1)
    order: int = Field(ge=1)
    translated_text: NonEmptyText
    uncertainties: list[UncertainTerm] = Field(default_factory=list)
