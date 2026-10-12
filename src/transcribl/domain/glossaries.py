"""Named, local glossaries, separate from immutable translation snapshots."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from transcribl.domain.errors import TranscriblError
from transcribl.domain.models import ContractModel, NonEmptyText

GlossaryId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]


class GlossaryEntry(ContractModel):
    source_term: NonEmptyText
    target_translation: NonEmptyText


class SavedGlossary(ContractModel):
    glossary_id: GlossaryId
    name: NonEmptyText
    revision: int = Field(ge=1)
    entries: list[GlossaryEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def terms_are_unique(self) -> Self:
        sources = [entry.source_term.casefold() for entry in self.entries]
        if len(sources) != len(set(sources)):
            raise ValueError("Each source term can appear only once")
        return self

    def mappings(self) -> dict[str, str]:
        return {entry.source_term: entry.target_translation for entry in self.entries}


class GlossaryLibrary(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    glossaries: list[SavedGlossary] = Field(default_factory=list)

    @model_validator(mode="after")
    def identities_are_unique(self) -> Self:
        ids = [item.glossary_id for item in self.glossaries]
        names = [item.name.casefold() for item in self.glossaries]
        if len(ids) != len(set(ids)) or len(names) != len(set(names)):
            raise ValueError("Glossary IDs and names must be unique")
        return self


class GlossaryError(TranscriblError):
    """A glossary command is invalid."""


class GlossaryNotFoundError(GlossaryError):
    """The selected glossary no longer exists."""


class GlossaryConflictError(GlossaryError):
    """A glossary changed or a name is already used."""


class GlossaryStorageError(GlossaryError):
    """The local library cannot be read or written safely."""
