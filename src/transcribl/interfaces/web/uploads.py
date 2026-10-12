from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from transcribl.config import (
    ProjectConfig,
)


async def stage_upload(
    upload: UploadFile,
    config: ProjectConfig,
) -> tuple[Path, str]:
    display_filename = _safe_pdf_filename(upload.filename)
    uploads_root = config.paths.artifacts_dir / ".uploads"
    staging_directory = uploads_root / uuid4().hex
    staging_directory.mkdir(parents=True, exist_ok=False)
    upload_path = staging_directory / display_filename
    byte_count = 0
    first_bytes = bytearray()
    try:
        with upload_path.open("xb") as destination:
            while chunk := await upload.read(1024 * 1024):
                byte_count += len(chunk)
                if byte_count > config.web.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF exceeds the configured upload limit",
                    )
                if len(first_bytes) < 1024:
                    first_bytes.extend(chunk[: 1024 - len(first_bytes)])
                destination.write(chunk)
        if byte_count == 0 or b"%PDF-" not in bytes(first_bytes):
            raise HTTPException(status_code=415, detail="Selected file is not a valid PDF")
        return upload_path, display_filename
    except Exception:
        remove_upload_directory(upload_path, config.paths.artifacts_dir)
        raise
    finally:
        await upload.close()


def _safe_pdf_filename(filename: str | None) -> str:
    candidate = (filename or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    candidate = "".join(character for character in candidate if character.isprintable())
    candidate = candidate.strip().strip(".")[:180]
    if not candidate.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Select a file with a .pdf extension")
    return candidate or "document.pdf"


def remove_upload_directory(upload_path: Path, artifacts_dir: Path) -> None:
    uploads_root = (artifacts_dir / ".uploads").resolve()
    staging_directory = upload_path.parent.resolve()
    if staging_directory.parent == uploads_root and staging_directory.is_dir():
        shutil.rmtree(staging_directory)
