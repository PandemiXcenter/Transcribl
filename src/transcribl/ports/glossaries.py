from typing import Protocol

from transcribl.domain.glossaries import SavedGlossary


class GlossaryRepository(Protocol):
    def list_glossaries(self) -> list[SavedGlossary]: ...

    def save(self, glossary: SavedGlossary, *, expected_revision: int | None) -> None: ...

    def delete(self, glossary_id: str, *, expected_revision: int) -> None: ...
