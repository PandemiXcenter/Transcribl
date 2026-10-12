"""Atomic, process-locked local glossary catalog; no translation artifacts are changed."""

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from pydantic import ValidationError

from transcribl.domain.glossaries import (
    GlossaryConflictError,
    GlossaryLibrary,
    GlossaryNotFoundError,
    GlossaryStorageError,
    SavedGlossary,
)

_LOCK = RLock()


class FilesystemGlossaryRepository:
    def __init__(self, root: Path) -> None:
        self._path = root / ".glossaries.json"

    def list_glossaries(self) -> list[SavedGlossary]:
        with _LOCK:
            return self._read().glossaries

    def save(self, glossary: SavedGlossary, *, expected_revision: int | None) -> None:
        with _LOCK:
            library = self._read()
            current = next(
                (item for item in library.glossaries if item.glossary_id == glossary.glossary_id),
                None,
            )
            if expected_revision is not None and current is None:
                raise GlossaryNotFoundError("Glossary was not found; refresh the glossary list")
            if (current.revision if current else None) != expected_revision:
                raise GlossaryConflictError("Glossary changed; reload before saving")
            if glossary.revision != (expected_revision or 0) + 1:
                raise GlossaryConflictError("Glossary revision must advance by one")
            if any(
                item.glossary_id != glossary.glossary_id
                and item.name.casefold() == glossary.name.casefold()
                for item in library.glossaries
            ):
                raise GlossaryConflictError("A glossary with that name already exists")
            remaining = [
                item for item in library.glossaries if item.glossary_id != glossary.glossary_id
            ]
            self._write(GlossaryLibrary(glossaries=[*remaining, glossary]))

    def delete(self, glossary_id: str, *, expected_revision: int) -> None:
        with _LOCK:
            library = self._read()
            current = next(
                (item for item in library.glossaries if item.glossary_id == glossary_id), None
            )
            if current is None:
                raise GlossaryNotFoundError("Glossary was not found; refresh the glossary list")
            if current.revision != expected_revision:
                raise GlossaryConflictError("Glossary changed; reload before deleting")
            self._write(
                GlossaryLibrary(
                    glossaries=[
                        item for item in library.glossaries if item.glossary_id != glossary_id
                    ]
                )
            )

    def _read(self) -> GlossaryLibrary:
        try:
            if not self._path.exists():
                return GlossaryLibrary()
            return GlossaryLibrary.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise GlossaryStorageError(
                "The local glossary library is unavailable or invalid"
            ) from None

    def _write(self, library: GlossaryLibrary) -> None:
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=".glossaries-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(library.model_dump_json(indent=2))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._path)
        except (OSError, ValidationError):
            raise GlossaryStorageError("The local glossary library could not be saved") from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
