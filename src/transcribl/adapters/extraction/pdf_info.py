from pathlib import Path

from pypdf import PdfReader


def pdf_page_count(path: Path, maximum: int) -> int:
    """Read physical page count locally without extracting or sending page contents."""
    try:
        with path.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("Choose an unencrypted PDF")
            count = len(reader.pages)
    except Exception as exc:
        raise ValueError("Cannot read this PDF; choose a valid, unencrypted PDF") from exc
    if not 1 <= count <= maximum:
        raise ValueError(f"Choose a PDF with 1 to {maximum} pages")
    return count
