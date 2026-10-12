from __future__ import annotations

import re
import shutil
from pathlib import Path

from transcribl.adapters.storage.atomic import atomic_create_model, atomic_write, read, write_model
from transcribl.adapters.storage.migrations import (
    read_core_payload,
)
from transcribl.domain.editorial import BlockRevision, ReviewPosition
from transcribl.domain.errors import ArtifactError
from transcribl.domain.models import (
    ArtifactRef,
    DocumentTranslation,
    JobManifest,
    PageFailure,
    PageTranslation,
)
from transcribl.hashing import sha256_file


class FilesystemArtifactRepository:
    """Human-inspectable JSON artifacts with atomic checkpoint writes."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def has_manifest(self) -> bool:
        return self._manifest_path.is_file()

    def read_manifest(self) -> JobManifest:
        return JobManifest.model_validate(read_core_payload(self._manifest_path))

    def write_manifest(self, manifest: JobManifest) -> None:
        write_model(self._manifest_path, manifest)

    def resolve(self, reference: ArtifactRef) -> Path:
        candidate = (self._root / reference.path).resolve()
        if not candidate.is_relative_to(self._root):
            raise ArtifactError(f"Artifact path escapes job directory: {reference.path}")
        if not candidate.is_file():
            raise ArtifactError(f"Artifact is missing: {reference.path}")
        if sha256_file(candidate) != reference.sha256:
            raise ArtifactError(f"Artifact hash mismatch: {reference.path}")
        return candidate

    def read_text(self, reference: ArtifactRef) -> str:
        return self.resolve(reference).read_text(encoding="utf-8")

    def has_page_translation(self, translation_run_id: str, page_number: int) -> bool:
        return self._translation_path(translation_run_id, page_number).is_file()

    def read_page_translation(
        self,
        translation_run_id: str,
        page_number: int,
    ) -> PageTranslation:
        path = self._translation_path(translation_run_id, page_number)
        translation = PageTranslation.model_validate(read_core_payload(path))
        if translation.translation_run_id != translation_run_id:
            raise ArtifactError("Page translation belongs to a different translation run")
        return translation

    def write_page_translation(
        self,
        translation_run_id: str,
        translation: PageTranslation,
    ) -> None:
        if translation.translation_run_id != translation_run_id:
            raise ArtifactError("Page translation belongs to a different translation run")
        write_model(
            self._translation_path(translation_run_id, translation.original_page_number),
            translation,
        )

    def write_page_failure(self, translation_run_id: str, failure: PageFailure) -> None:
        write_model(
            self._failure_path(translation_run_id, failure.original_page_number),
            failure,
        )

    def has_page_failure(self, translation_run_id: str, page_number: int) -> bool:
        return self._failure_path(translation_run_id, page_number).is_file()

    def read_page_failure(
        self,
        translation_run_id: str,
        page_number: int,
    ) -> PageFailure:
        path = self._failure_path(translation_run_id, page_number)
        return PageFailure.model_validate(read_core_payload(path))

    def clear_page_failure(self, translation_run_id: str, page_number: int) -> None:
        self._failure_path(translation_run_id, page_number).unlink(missing_ok=True)

    def write_document(
        self,
        translation_run_id: str,
        document: DocumentTranslation,
    ) -> Path:
        if document.translation_run_id != translation_run_id:
            raise ArtifactError("Document belongs to a different translation run")
        path = self._document_path(translation_run_id)
        write_model(path, document)
        return path

    def read_document(self, translation_run_id: str) -> DocumentTranslation:
        document = DocumentTranslation.model_validate(
            read_core_payload(self._document_path(translation_run_id))
        )
        if document.translation_run_id != translation_run_id:
            raise ArtifactError("Document belongs to a different translation run")
        return document

    def write_markdown(self, translation_run_id: str, markdown: str) -> Path:
        path = self._markdown_path(translation_run_id)
        atomic_write(path, markdown)
        return path

    def write_latex(self, translation_run_id: str, latex: str) -> Path:
        path = self._latex_path(translation_run_id)
        atomic_write(path, latex)
        return path

    def delete_translation_run(self, translation_run_id: str) -> None:
        """Delete one explicitly identified run without touching sibling runs."""

        run_root = self._run_root(translation_run_id)
        if run_root.is_symlink():
            raise ArtifactError("Translation run directory cannot be a symbolic link")
        if not run_root.is_dir():
            raise ArtifactError("Translation run artifacts were not found")
        shutil.rmtree(run_root)

    def list_block_revisions(
        self,
        document_id: str,
        translation_run_id: str,
        block_id: str,
    ) -> list[BlockRevision]:
        directory = self._revision_directory(translation_run_id, block_id)
        if not directory.is_dir():
            return []
        revisions: list[BlockRevision] = []
        for path in sorted(directory.glob("*.json")):
            revision = BlockRevision.model_validate_json(read(path))
            if (
                revision.document_id != document_id
                or revision.translation_run_id != translation_run_id
                or revision.block_id != block_id
            ):
                raise ArtifactError(f"Editorial revision has incorrect scope: {path}")
            expected_name = f"{revision.revision_number:04d}.json"
            if path.name != expected_name:
                raise ArtifactError(f"Editorial revision has an invalid filename: {path}")
            revisions.append(revision)
        expected_numbers = list(range(1, len(revisions) + 1))
        if [revision.revision_number for revision in revisions] != expected_numbers:
            raise ArtifactError(f"Editorial revision history is not contiguous: {block_id}")
        return revisions

    def append_block_revision(self, revision: BlockRevision) -> None:
        existing = self.list_block_revisions(
            revision.document_id,
            revision.translation_run_id,
            revision.block_id,
        )
        expected_number = len(existing) + 1
        if (
            revision.revision_number != expected_number
            or revision.base_revision != expected_number - 1
        ):
            raise ArtifactError(
                f"Editorial revision is stale for block {revision.block_id}; "
                f"expected revision {expected_number}"
            )
        path = (
            self._revision_directory(
                revision.translation_run_id,
                revision.block_id,
            )
            / f"{revision.revision_number:04d}.json"
        )
        atomic_create_model(path, revision)

    def read_review_position(
        self,
        document_id: str,
        translation_run_id: str,
    ) -> ReviewPosition | None:
        path = self._review_position_path(translation_run_id)
        if not path.is_file():
            return None
        position = ReviewPosition.model_validate_json(read(path))
        if position.document_id != document_id or position.translation_run_id != translation_run_id:
            raise ArtifactError(f"Review position has incorrect scope: {path}")
        return position

    def write_review_position(self, position: ReviewPosition) -> None:
        write_model(
            self._review_position_path(position.translation_run_id),
            position,
        )

    @property
    def _manifest_path(self) -> Path:
        return self._root / "manifest.json"

    def _document_path(self, translation_run_id: str) -> Path:
        return self._run_root(translation_run_id) / "output" / "document.json"

    def _markdown_path(self, translation_run_id: str) -> Path:
        return self._run_root(translation_run_id) / "output" / "document.md"

    def _latex_path(self, translation_run_id: str) -> Path:
        return self._run_root(translation_run_id) / "output" / "document.tex"

    def _translation_path(self, translation_run_id: str, page_number: int) -> Path:
        if page_number < 1:
            raise ArtifactError("Page number must be positive")
        return (
            self._run_root(translation_run_id) / "pages" / f"{page_number:04d}" / "translation.json"
        )

    def _failure_path(self, translation_run_id: str, page_number: int) -> Path:
        if page_number < 1:
            raise ArtifactError("Page number must be positive")
        return self._run_root(translation_run_id) / "pages" / f"{page_number:04d}" / "failure.json"

    def _revision_directory(self, translation_run_id: str, block_id: str) -> Path:
        if re.fullmatch(r"p\d{4,}-b\d{4,}", block_id) is None:
            raise ArtifactError("Block ID is not a safe persisted block identifier")
        return self._run_root(translation_run_id) / "revisions" / block_id

    def _review_position_path(self, translation_run_id: str) -> Path:
        return self._run_root(translation_run_id) / "review" / "position.json"

    def _run_root(self, translation_run_id: str) -> Path:
        if len(translation_run_id) != 32 or any(
            character not in "0123456789abcdef" for character in translation_run_id
        ):
            raise ArtifactError("Translation run ID must be a lowercase UUID hex value")
        return self._root / "runs" / translation_run_id
