from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from uuid import uuid4

from transcribl.domain.enums import (
    JobStatus,
)
from transcribl.domain.errors import (
    ArtifactError,
)
from transcribl.domain.models import (
    ArtifactRef,
    JobManifest,
    PreparedPage,
    utc_now,
)
from transcribl.hashing import sha256_file
from transcribl.ports.artifacts import ArtifactRepository
from transcribl.ports.extraction import PageExtractor


def _job_id(source_pdf: Path, source_hash: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source_pdf.stem.lower()).strip("-")
    return f"{(slug or 'document')[:48]}-{source_hash[:12]}"


def _prefix_artifact(reference: ArtifactRef, prefix: Path) -> ArtifactRef:
    return reference.model_copy(update={"path": (prefix / reference.path).as_posix()})


def prepare_document(
    extractor: PageExtractor,
    repository_factory: Callable[[Path], ArtifactRepository],
    source_pdf: Path,
    *,
    artifacts_dir: Path,
    image_dpi: int,
    force: bool = False,
) -> Path:
    source_pdf = source_pdf.resolve()
    if not source_pdf.is_file():
        raise ArtifactError(f"Source PDF does not exist: {source_pdf}")
    artifacts_dir = artifacts_dir.resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        dir=artifacts_dir,
        prefix=".source-snapshot-",
    ) as snapshot_directory:
        source_snapshot = Path(snapshot_directory) / "source.pdf"
        shutil.copyfile(source_pdf, source_snapshot)
        source_hash = sha256_file(source_snapshot)
        job_id = _job_id(source_pdf, source_hash)
        job_dir = (artifacts_dir / job_id).resolve()
        repository = repository_factory(job_dir)
        existing_manifest = repository.read_manifest() if repository.has_manifest() else None

        if existing_manifest is not None:
            if existing_manifest.source_file_sha256 != source_hash:
                raise ArtifactError("Existing job manifest belongs to a different source file")
            if not force and existing_manifest.image_dpi == image_dpi:
                for page in existing_manifest.pages:
                    repository.resolve(page.markdown)
                    repository.resolve(page.image)
                return job_dir

        preparation_id, pages = prepare_pages_transactionally(
            extractor,
            source_snapshot,
            job_dir,
            image_dpi=image_dpi,
        )
        now = utc_now()
        manifest = JobManifest(
            job_id=job_id,
            preparation_id=preparation_id,
            document_id=source_hash,
            source_file_name=source_pdf.name,
            source_file_sha256=source_hash,
            image_dpi=image_dpi,
            page_count=len(pages),
            pages=pages,
            status=JobStatus.PREPARED,
            translation_run_id=None,
            translation_run_ids=(
                list(existing_manifest.translation_run_ids) if existing_manifest is not None else []
            ),
            created_at=existing_manifest.created_at if existing_manifest is not None else now,
            updated_at=now,
        )
        repository.write_manifest(manifest)
        return job_dir


def prepare_pages_transactionally(
    extractor: PageExtractor,
    source_snapshot: Path,
    job_dir: Path,
    *,
    image_dpi: int,
) -> tuple[str, list[PreparedPage]]:
    prepared_root = job_dir / "prepared"
    prepared_root.mkdir(parents=True, exist_ok=True)
    staging_root = Path(mkdtemp(dir=prepared_root, prefix=".staging-"))
    try:
        pages = extractor.extract_pages(
            source_snapshot,
            staging_root,
            image_dpi=image_dpi,
        )
        preparation_id = uuid4().hex
        preparation_root = prepared_root / preparation_id
        os.replace(staging_root, preparation_root)
        prefix = preparation_root.relative_to(job_dir)
        return preparation_id, [
            page.model_copy(
                update={
                    "markdown": _prefix_artifact(page.markdown, prefix),
                    "image": _prefix_artifact(page.image, prefix),
                }
            )
            for page in pages
        ]
    finally:
        if staging_root.is_dir() and staging_root.parent == prepared_root:
            shutil.rmtree(staging_root)
