"""Offline Articles workbench for browser regression checks.

Run from the repository root with ``uv run python tests/browser/review_fixture.py``.
All PDFs, images, runs, revisions and local settings live in a temporary directory.
No real provider adapter is used, including for uploads submitted through the UI.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from struct import unpack
from tempfile import TemporaryDirectory
from textwrap import wrap

from PIL import Image
from pydantic import SecretStr
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.adapters.storage import FilesystemArtifactRepository
from transcribl.application.jobs.manager import JobManager
from transcribl.composition import build_pipeline
from transcribl.config import ProjectConfig, load_project_config
from transcribl.domain.enums import BlockType, SegmentContinuation
from transcribl.domain.models import (
    DocumentTranslation,
    FootnoteDescription,
    FootnoteIdentity,
    GeneratedBlock,
    GeneratedFootnoteBlock,
    GeneratedPagePayload,
    UncertainTerm,
)
from transcribl.ports.translation import (
    PageTranslationRequest,
    PageTranslator,
    ProviderDescriptor,
    ProviderResult,
    TableReconstructionRequest,
    TableReconstructionResult,
)


class ReviewTranslator:
    """Deterministic content with real pipeline-owned IDs, links and annotations."""

    # Simulated token usage exercises the configured pricing display as well.
    descriptor = ProviderDescriptor(
        provider="gemini",
        model="gemini-3.8-flash",
        configuration={"output_token_accounting": "includes_reasoning"},
    )

    def __init__(self, article: str = "Uploaded review sample") -> None:
        self.article = article

    def translate_page(self, request: PageTranslationRequest) -> ProviderResult:
        page = request.original_page_number
        blocks: list[GeneratedBlock | GeneratedFootnoteBlock] = []

        def body(
            text: str,
            *,
            continuation: SegmentContinuation = SegmentContinuation.COMPLETE,
            uncertainty: str | None = None,
        ) -> None:
            blocks.append(
                GeneratedBlock(
                    order=len(blocks) + 1,
                    type=BlockType.BODY,
                    source_text=f"Synthetic source: {text}",
                    translated_text=text,
                    paragraph_continuation=continuation,
                    uncertainties=(
                        [
                            UncertainTerm(
                                source_term="gammel" if uncertainty == "olde" else "noteret",
                                proposed_translation=uncertainty,
                                reason="Synthetic annotation for review controls.",
                                alternatives=["old" if uncertainty == "olde" else "documented"],
                            )
                        ]
                        if uncertainty
                        else []
                    ),
                )
            )

        if page == 2:
            body(
                "continues on the second physical page, with a separate editable fragment.",
                continuation=SegmentContinuation.FROM_PREVIOUS_PAGE,
            )
        blocks.append(
            GeneratedBlock(
                order=len(blocks) + 1,
                type=BlockType.HEADING,
                source_text=f"{self.article}, source page {page}",
                translated_text=f"{self.article} — observations on page {page}",
                paragraph_continuation=None,
                heading_level=2,
            )
        )
        body(
            f"The olde condition is discussed on physical page {page}. "
            "This marked word occurs once on each page; Translate All should initially show two.",
            uncertainty="olde",
        )
        if page == 1:
            body(
                "😀 Evidence[[FOOTNOTE:fn-p1-n1]] precedes this footnote marker. "
                "The marker belongs at Unicode character offset 10, not UTF-16 offset 11."
            )
            blocks.append(
                GeneratedFootnoteBlock(
                    order=len(blocks) + 1,
                    type=BlockType.FOOTNOTE,
                    source_text="Synthetic note attached to the evidence sentence.",
                    translated_text="A note for checking owner selection and marker placement.",
                    footnote_id=FootnoteIdentity(id="fn-p1-n1", text="*"),
                    entrypoint_token="[[FOOTNOTE:fn-p1-n1]]",
                    description=FootnoteDescription(
                        appearance="A starred note beneath a separator.",
                        handling="Begins and ends on the first page.",
                    ),
                    owner_review_required=False,
                    continuation=SegmentContinuation.COMPLETE,
                )
            )
        else:
            body(
                "One recorded observation has a unique annotation; offer only one replacement.",
                uncertainty="recorded",
            )
        for section in range(1, 7):
            body(
                f"{self.article}, page {page}, section {section}. "
                "Compare the source image with the translated passage while retaining your place. "
                "A reviewer may select text, edit wording, validate a section, or inspect a note. "
                "The source page includes marks at all four edges to make zoom and pan visible. "
                "Scrolling the translation should select the corresponding physical source page."
            )
        if page == 1:
            body(
                "This linked paragraph starts near the end of physical page one and",
                continuation=SegmentContinuation.TO_NEXT_PAGE,
            )
        return ProviderResult(
            payload=GeneratedPagePayload(blocks=blocks),
            input_tokens=7_000,
            output_tokens=1_500,
        )

    def reconstruct_tables(self, request: TableReconstructionRequest) -> TableReconstructionResult:
        raise AssertionError(f"Fixture has no tables on page {request.original_page_number}")


@contextmanager
def review_translator(config: ProjectConfig, api_key: SecretStr | None) -> Iterator[PageTranslator]:
    del config, api_key
    yield ReviewTranslator()


def pdf_line(text: str, x: int, y: int) -> str:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"1 0 0 1 {x} {y} Tm ({escaped}) Tj"


def write_source_pdf(path: Path, article: str) -> None:
    """Create legible source pages using the PDF standard font, without new deps."""
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for number in (1, 2):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        commands = ["0.25 w 18 18 576 756 re S", "BT /F1 11 Tf 15 TL"]

        commands.append(pdf_line(f"TOP LEFT - {article}", 24, 756))
        commands.append(pdf_line(f"TOP RIGHT - PAGE {number}", 435, 756))
        commands.append(pdf_line(f"{article}: source evidence, physical page {number}", 48, 720))
        y = 690
        for section in range(1, 7):
            paragraph = (
                f"Section {section}. The olde condition is documented on source page {number}. "
                "These synthetic research notes help compare the original page and translation. "
                "Inspect the page edges after zooming. Drag or scroll to read the enlarged image."
            )
            for text in wrap(paragraph, width=80):
                commands.append(pdf_line(text, 48, y))
                y -= 15
            y -= 15
        commands.append(
            pdf_line(
                "* Source note: this is generated test content, never a user document.", 48, 96
            )
        )
        commands.append(pdf_line("BOTTOM LEFT - END OF PAGE", 24, 34))
        commands.append(pdf_line(f"BOTTOM RIGHT - {number}", 447, 34))
        commands.append("ET")
        stream = DecodedStreamObject()
        stream.set_data("\n".join(commands).encode("ascii"))
        # Content streams must be indirect PDF objects for PDFium to render them.
        page.replace_contents(stream.flate_encode())
    writer.write(path)


def seed_articles(config: ProjectConfig, directory: Path) -> list[DocumentTranslation]:
    documents = []
    for article in ("Review sample A", "Review sample B"):
        source = directory / f"{article}.pdf"
        write_source_pdf(source, article)
        pipeline = build_pipeline()
        job = pipeline.prepare_document(
            source, artifacts_dir=config.paths.artifacts_dir, image_dpi=config.extraction.image_dpi
        )
        document = pipeline.translate_document(
            job, settings=config.translation, translator=ReviewTranslator(article)
        )
        documents.append(document)
        for page in document.pages:
            image_path = job / page.source_image.path
            image = image_path.read_bytes()
            assert image.startswith(b"\x89PNG\r\n\x1a\n")
            assert unpack(">II", image[16:24]) == (1_224, 1_584)
            with Image.open(image_path) as rendered:
                assert rendered.convert("L").getextrema() == (0, 255), "Source page is blank"
            assert "BOTTOM RIGHT" in page.source_markdown
        assert any(block.continues_from_block_id for block in document.pages[1].blocks)
        note = next(block for block in document.pages[0].blocks if block.type is BlockType.FOOTNOTE)
        assert note.footnote_anchor_offset == len("😀 Evidence") == 10
        print(f"Ready: {source.name} ({document.translation_run_id})")
    return documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--check", action="store_true", help="Seed and validate, then exit.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    with TemporaryDirectory(prefix="transcribl-review-fixture-") as directory:
        root = Path(directory)
        config = load_project_config(Path(__file__).resolve().parents[2] / "config/default.toml")
        config = config.model_copy(
            update={
                "paths": config.paths.model_copy(update={"artifacts_dir": root / "artifacts"}),
                "extraction": config.extraction.model_copy(update={"image_dpi": 144}),
                "web": config.web.model_copy(
                    update={"port": args.port, "open_browser_on_start": False}
                ),
            }
        )
        documents = seed_articles(config, root)
        assert len({document.translation_run_id for document in documents}) == 2
        if args.check:
            return

        # Import NiceGUI only for interactive mode, keeping --check fast and silent.
        from nicegui import ui

        from transcribl.interfaces.desktop.app import register_desktop
        from transcribl.interfaces.web import create_app

        manager = JobManager(
            config=config,
            pipeline_factory=build_pipeline,
            repository_factory=FilesystemArtifactRepository,
            translator_factory=review_translator,
        )
        api = create_app(config, job_manager=manager, secret_store=DotenvSecretStore(root / ".env"))
        register_desktop(config, api=api)
        print(f"Offline review fixture: http://127.0.0.1:{args.port}")
        print(f"Synthetic PDFs for upload checks: {root}")
        try:
            ui.run(
                host="127.0.0.1",
                port=args.port,
                show=False,
                reload=False,
                show_welcome_message=False,
                message_history_length=0,
            )
        finally:
            manager.shutdown()


if __name__ == "__main__":
    main()
