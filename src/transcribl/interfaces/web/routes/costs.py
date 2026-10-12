from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    File,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool

from transcribl.adapters.extraction.pdf_info import pdf_page_count
from transcribl.interfaces.web.cost_payloads import cost_payload
from transcribl.interfaces.web.security import require_csrf
from transcribl.interfaces.web.services import WebServices
from transcribl.interfaces.web.uploads import remove_upload_directory, stage_upload


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    config = services.config
    manager = services.jobs
    settings_service = services.settings

    @router.post("/api/pdf-info")
    async def inspect_pdf(
        pdf: Annotated[UploadFile, File()],
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, int]:
        require_csrf(at_csrf, x_csrf_token)
        path, _ = await stage_upload(pdf, config)
        try:
            count = await run_in_threadpool(pdf_page_count, path, config.web.max_pdf_pages)
            return {"page_count": count}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            remove_upload_directory(path, config.paths.artifacts_dir)

    @router.get("/api/cost-estimate")
    def cost_estimate(model: str, page_count: Annotated[int, Query(ge=1)]) -> dict[str, object]:
        if page_count > config.web.max_pdf_pages:
            raise HTTPException(status_code=422, detail="PDF exceeds the configured page limit")
        try:
            provider = config.provider.provider_for_model(model)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        level = settings_service.resolved().provider.settings_for(provider).thinking_level
        return cost_payload(
            manager.estimate_cost(model=model, page_count=page_count, thinking_level=level),
            settings_service,
        )

    return router
