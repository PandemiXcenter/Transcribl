import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import ValidationError

from transcribl.adapters.storage.glossaries import FilesystemGlossaryRepository
from transcribl.application.glossaries import GlossaryService
from transcribl.domain.glossaries import (
    GlossaryConflictError,
    GlossaryEntry,
    GlossaryError,
    GlossaryLibrary,
    GlossaryNotFoundError,
    GlossaryStorageError,
    SavedGlossary,
)


def service(root: Path) -> GlossaryService:
    return GlossaryService(
        FilesystemGlossaryRepository(root),
        max_entries=2,
        max_term_characters=30,
        max_name_characters=20,
    )


def entries(target: str = "Dropsy") -> list[GlossaryEntry]:
    return [GlossaryEntry(source_term="Vattersot", target_translation=target)]


def test_named_glossaries_survive_restart_and_resolved_values_are_snapshots(tmp_path: Path) -> None:
    original = service(tmp_path)
    first = original.save(source_language="Danish", name="Historical medicine", entries=entries())
    second = original.save(
        source_language="Danish", name="Modern medicine", entries=entries("Edema")
    )
    snapshot = original.resolve(first.glossary_id, source_language="Danish", expected_revision=1)
    restarted = service(tmp_path)
    assert restarted.list_glossaries() == [first, second]
    renamed = restarted.save(
        source_language="Danish",
        glossary_id=first.glossary_id,
        expected_revision=1,
        name="Archive",
        entries=entries("Oedema"),
    )
    assert renamed.revision == 2
    assert snapshot == {"Vattersot": "Dropsy"}
    assert restarted.resolve(second.glossary_id, source_language="Danish", expected_revision=1) == {
        "Vattersot": "Edema"
    }
    with pytest.raises(GlossaryConflictError):
        original.resolve(first.glossary_id, source_language="Danish", expected_revision=1)
    with pytest.raises(GlossaryConflictError):
        original.delete(first.glossary_id, expected_revision=1)
    restarted.delete(first.glossary_id, expected_revision=2)
    assert service(tmp_path).list_glossaries() == [second]
    assert snapshot == {"Vattersot": "Dropsy"}
    with pytest.raises(GlossaryNotFoundError):
        original.resolve(first.glossary_id, source_language="Danish", expected_revision=2)


def test_unicode_roundtrip_and_strict_catalog_contract(tmp_path: Path) -> None:
    saved = service(tmp_path).save(
        source_language="Danish",
        name="Ældre ord",
        entries=[GlossaryEntry(source_term="a\u030a", target_translation="Å")],
    )
    assert service(tmp_path).get(saved.glossary_id) == saved
    assert saved.entries[0].source_term == "a\u030a"
    assert SavedGlossary.model_validate_json(saved.model_dump_json()) == saved
    payload = saved.model_dump()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        SavedGlossary.model_validate(payload)
    with pytest.raises(ValidationError):
        GlossaryLibrary(glossaries=[saved, saved])
    with pytest.raises(ValidationError):
        SavedGlossary.model_validate({**saved.model_dump(), "glossary_id": "../outside"})


@pytest.mark.parametrize(
    "name,terms",
    [
        ("", entries()),
        ("x" * 21, entries()),
        ("Name", []),
        ("Name", entries() * 2),
        ("Name", [GlossaryEntry(source_term=str(i), target_translation="x") for i in range(3)]),
        ("Name", [GlossaryEntry(source_term="x" * 31, target_translation="x")]),
    ],
)
def test_invalid_glossaries_do_not_write_files(
    tmp_path: Path, name: str, terms: list[GlossaryEntry]
) -> None:
    with pytest.raises(GlossaryError):
        service(tmp_path).save(source_language="Danish", name=name, entries=terms)
    assert not list(tmp_path.iterdir())


def test_duplicate_names_and_casefolded_source_terms_are_rejected(tmp_path: Path) -> None:
    library = service(tmp_path)
    library.save(source_language="Danish", name="Medical", entries=entries())
    with pytest.raises(GlossaryConflictError):
        library.save(source_language="Danish", name="medical", entries=entries("Edema"))
    with pytest.raises(GlossaryError):
        library.save(
            source_language="Danish",
            name="Other",
            entries=[
                *entries(),
                GlossaryEntry(source_term="vattersot", target_translation="Edema"),
            ],
        )


def test_concurrent_updates_allow_only_one_writer(tmp_path: Path) -> None:
    saved = service(tmp_path).save(source_language="Danish", name="Medical", entries=entries())
    barrier = Barrier(2)

    def update(target: str) -> str:
        current = service(tmp_path)
        barrier.wait(timeout=5)
        try:
            current.save(
                source_language="Danish",
                glossary_id=saved.glossary_id,
                expected_revision=1,
                name="Medical",
                entries=entries(target),
            )
            return "saved"
        except GlossaryConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(update, ["Edema", "Oedema"])) == ["conflict", "saved"]
    assert service(tmp_path).get(saved.glossary_id).revision == 2


def test_atomic_failure_preserves_catalog_and_cleans_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import transcribl.adapters.storage.atomic as storage

    library = service(tmp_path)
    saved = library.save(source_language="Danish", name="Medical", entries=entries())
    before = (tmp_path / ".glossaries.json").read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("synthetic failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(GlossaryStorageError):
        library.save(
            source_language="Danish",
            glossary_id=saved.glossary_id,
            expected_revision=1,
            name="Medical",
            entries=entries("Edema"),
        )
    assert (tmp_path / ".glossaries.json").read_bytes() == before
    assert [path.name for path in tmp_path.iterdir()] == [".glossaries.json"]


def test_corrupt_catalog_is_not_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / ".glossaries.json"
    path.write_text('{"schema_version":"unknown"}')
    with pytest.raises(GlossaryStorageError):
        service(tmp_path).save(source_language="Danish", name="New", entries=entries())
    assert path.read_text() == '{"schema_version":"unknown"}'


def test_language_filter_and_legacy_catalog_migration_preserve_terms(tmp_path: Path) -> None:
    library = service(tmp_path)
    saved = library.save(name="Old language", source_language="Old Danish", entries=entries())
    assert library.list_glossaries(" old DANISH ") == [saved]
    assert library.resolve(saved.glossary_id, expected_revision=1, source_language="old danish")
    with pytest.raises(GlossaryError, match="source language"):
        library.resolve(saved.glossary_id, expected_revision=1, source_language="German")
    path = tmp_path / ".glossaries.json"
    legacy = json.loads(path.read_text())
    legacy["schema_version"] = "1.0"
    del legacy["glossaries"][0]["source_language"]
    path.write_text(json.dumps(legacy))
    before = path.read_bytes()
    migrated = service(tmp_path)
    assert migrated.get(saved.glossary_id).source_language is None
    assert migrated.list_glossaries("Old Danish") == []
    assert path.read_bytes() == before
    with pytest.raises(GlossaryError, match="source language"):
        migrated.resolve(saved.glossary_id, expected_revision=1, source_language="Old Danish")
    assigned = migrated.save(
        name=saved.name,
        source_language="Old Danish",
        entries=saved.entries,
        glossary_id=saved.glossary_id,
        expected_revision=1,
    )
    assert assigned.entries == saved.entries
    assert service(tmp_path).list_glossaries("Old Danish") == [assigned]
    assert json.loads(path.read_text())["schema_version"] == "2.0"
