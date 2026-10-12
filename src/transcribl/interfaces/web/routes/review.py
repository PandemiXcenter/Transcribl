from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Header,
    HTTPException,
)
from fastapi.responses import FileResponse

from transcribl.application.costs import recorded_cost
from transcribl.application.editorial import EditorialService
from transcribl.domain.errors import (
    ArtifactError,
)
from transcribl.interfaces.web.review_context import document_context, review_context
from transcribl.interfaces.web.review_payloads import default_continue_page, review_payload
from transcribl.interfaces.web.schemas import (
    BlockRevisionRequest,
    ParagraphRevisionRequest,
    ReviewPositionRequest,
    UncertaintyReplacementRequest,
)
from transcribl.interfaces.web.security import require_csrf
from transcribl.interfaces.web.services import WebServices


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    config = services.config
    manager = services.jobs

    @router.get("/api/jobs/{job_id}/review")
    def review_document(job_id: str) -> dict[str, object]:
        document, translation_run_id, service, review = review_context(manager, job_id)
        position = service.get_review_position(document, translation_run_id)
        payload = review_payload(review)
        payload["cost"] = recorded_cost(document, config.costs).model_dump(mode="json")
        payload["continue_page"] = (
            position.original_page_number if position is not None else default_continue_page(review)
        )
        return payload

    @router.get("/api/jobs/{job_id}/pages/{page_number}/image")
    def review_page_image(job_id: str, page_number: int) -> FileResponse:
        repository, document, _ = document_context(manager, job_id)
        if page_number < 1 or page_number > document.page_count:
            raise HTTPException(status_code=404, detail="Physical page was not found")
        page = document.pages[page_number - 1]
        if page.original_page_number != page_number:
            raise ArtifactError("Canonical document pages are not in physical order")
        if page.source_image.media_type != "image/png":
            raise ArtifactError("Review page image has an unsupported media type")
        return FileResponse(repository.resolve(page.source_image), media_type="image/png")

    @router.put("/api/jobs/{job_id}/review-position")
    def save_review_position(
        job_id: str,
        command: ReviewPositionRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        repository, document, translation_run_id = document_context(manager, job_id)
        service = EditorialService(repository)
        position = service.save_review_position(
            document,
            translation_run_id,
            command.original_page_number,
        )
        return {
            "translation_run_id": position.translation_run_id,
            "original_page_number": position.original_page_number,
            "updated_at": position.updated_at,
        }

    @router.post("/api/jobs/{job_id}/revisions")
    def revise_block(
        job_id: str,
        command: BlockRevisionRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        document, translation_run_id, service, _ = review_context(manager, job_id)
        service.revise_block(
            document,
            translation_run_id,
            command.block_id,
            command.editorial_text,
            block_type=command.type,
            footnote_owner_block_id=command.footnote_owner_block_id,
            footnote_anchor_offset=command.footnote_anchor_offset,
            expected_base_revision=command.expected_base_revision,
            status=command.status,
        )
        return review_payload(service.review_document(document, translation_run_id))

    @router.post("/api/jobs/{job_id}/paragraph-revisions")
    def revise_paragraph(
        job_id: str,
        command: ParagraphRevisionRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        document, translation_run_id, service, _ = review_context(manager, job_id)
        service.revise_paragraph(
            document,
            translation_run_id,
            command.paragraph_id,
            [
                (
                    fragment.block_id,
                    fragment.editorial_text,
                    fragment.expected_base_revision,
                )
                for fragment in command.fragments
            ],
            status=command.status,
        )
        return review_payload(service.review_document(document, translation_run_id))

    @router.post("/api/jobs/{job_id}/uncertainties/{uncertainty_id}/replace")
    def replace_uncertainty(
        job_id: str,
        uncertainty_id: str,
        command: UncertaintyReplacementRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        document, translation_run_id, service, _ = review_context(manager, job_id)
        service.replace_uncertainty(
            document,
            translation_run_id,
            uncertainty_id,
            command.replacement,
            replace_all=command.scope == "all",
            expected_base_revisions=command.expected_versions,
        )
        return review_payload(service.review_document(document, translation_run_id))

    return router
