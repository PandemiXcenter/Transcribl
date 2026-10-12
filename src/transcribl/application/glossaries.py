from uuid import uuid4

from pydantic import ValidationError

from transcribl.domain.glossaries import (
    GlossaryConflictError,
    GlossaryEntry,
    GlossaryError,
    GlossaryNotFoundError,
    SavedGlossary,
)
from transcribl.domain.languages import same_language
from transcribl.ports.glossaries import GlossaryRepository


class GlossaryService:
    def __init__(
        self,
        repository: GlossaryRepository,
        *,
        max_entries: int,
        max_term_characters: int,
        max_name_characters: int,
    ) -> None:
        self._repository = repository
        self._max_entries = max_entries
        self._max_term_characters = max_term_characters
        self._max_name_characters = max_name_characters

    def list_glossaries(self, source_language: str | None = None) -> list[SavedGlossary]:
        return sorted(
            [
                g
                for g in self._repository.list_glossaries()
                if source_language is None or same_language(g.source_language, source_language)
            ],
            key=lambda item: (item.name.casefold(), item.glossary_id),
        )

    def get(self, glossary_id: str) -> SavedGlossary:
        for glossary in self._repository.list_glossaries():
            if glossary.glossary_id == glossary_id:
                return glossary
        raise GlossaryNotFoundError("Glossary was not found; refresh the glossary list")

    def save(
        self,
        *,
        name: str,
        source_language: str,
        entries: list[GlossaryEntry],
        glossary_id: str | None = None,
        expected_revision: int | None = None,
    ) -> SavedGlossary:
        if (glossary_id is None) != (expected_revision is None):
            raise GlossaryError("Updating a glossary requires its current revision")
        try:
            glossary = SavedGlossary(
                glossary_id=glossary_id or uuid4().hex,
                name=name,
                source_language=source_language,
                revision=(expected_revision or 0) + 1,
                entries=entries,
            )
        except ValidationError:
            raise GlossaryError(
                "Use a name, source language and at least one complete mapping, "
                "with unique source terms"
            ) from None
        if glossary.source_language is None:
            raise GlossaryError("Choose a source language")
        self._validate_limits(glossary)
        self._repository.save(glossary, expected_revision=expected_revision)
        return glossary

    def resolve(
        self, glossary_id: str, *, expected_revision: int, source_language: str
    ) -> dict[str, str]:
        glossary = self.get(glossary_id)
        if glossary.revision != expected_revision:
            raise GlossaryConflictError(
                "The selected glossary changed; refresh and select it again"
            )
        if not same_language(glossary.source_language, source_language):
            raise GlossaryError("Select a glossary matching the source language")
        self._validate_limits(glossary)
        return glossary.mappings()

    def delete(self, glossary_id: str, *, expected_revision: int) -> None:
        self._repository.delete(glossary_id, expected_revision=expected_revision)

    def _validate_limits(self, glossary: SavedGlossary) -> None:
        if len(glossary.name) > self._max_name_characters:
            raise GlossaryError("Glossary name exceeds the configured character limit")
        if len(glossary.entries) > self._max_entries:
            raise GlossaryError("Glossary exceeds the configured entry limit")
        if any(
            len(entry.source_term) > self._max_term_characters
            or len(entry.target_translation) > self._max_term_characters
            for entry in glossary.entries
        ):
            raise GlossaryError("A glossary term exceeds the configured character limit")
