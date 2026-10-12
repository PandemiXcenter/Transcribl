from __future__ import annotations

from fastapi import (
    APIRouter,
)
from fastapi.responses import Response

from transcribl.interfaces.web.review_context import review_context
from transcribl.interfaces.web.services import WebServices


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    config = services.config
    manager = services.jobs
    local_pdf_compiler = services.pdf_compiler

    @router.get("/api/jobs/{job_id}/export.md")
    def export_reviewed_markdown(job_id: str) -> Response:
        document, translation_run_id, service, _ = review_context(manager, job_id)
        markdown = service.compile_reviewed_markdown(
            document,
            translation_run_id,
            config.export,
        )
        return Response(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="reviewed-translation.md"'},
        )

    @router.get("/api/jobs/{job_id}/export.txt")
    def export_reviewed_text(job_id: str) -> Response:
        document, translation_run_id, service, _ = review_context(manager, job_id)
        plain_text = service.compile_reviewed_text(
            document,
            translation_run_id,
            config.export,
        )
        return Response(
            plain_text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="reviewed-translation.txt"'},
        )

    @router.get("/api/jobs/{job_id}/export.pdf")
    def export_reviewed_pdf(job_id: str) -> Response:
        document, translation_run_id, service, _ = review_context(manager, job_id)
        latex = service.compile_reviewed_latex(
            document,
            translation_run_id,
            config.export,
        )
        return Response(
            local_pdf_compiler.compile(latex),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="reviewed-translation.pdf"'},
        )

    @router.get("/api/jobs/{job_id}/export.tex")
    def export_reviewed_latex(job_id: str) -> Response:
        document, translation_run_id, service, _ = review_context(manager, job_id)
        latex = service.compile_reviewed_latex(
            document,
            translation_run_id,
            config.export,
        )
        return Response(
            latex,
            media_type="application/x-tex; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="reviewed-translation.tex"'},
        )

    return router
