from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
)
from fastapi.responses import JSONResponse, Response

from transcribl.application.jobs.records import JobNotFoundError
from transcribl.domain.errors import (
    ArtifactError,
)
from transcribl.domain.languages import same_language
from transcribl.interfaces.web.cost_payloads import job_payload
from transcribl.interfaces.web.credentials import parse_session_api_key
from transcribl.interfaces.web.job_settings import parse_glossary, parse_job_settings
from transcribl.interfaces.web.schemas import (
    ContinueJobRequest,
)
from transcribl.interfaces.web.security import require_csrf
from transcribl.interfaces.web.services import WebServices
from transcribl.interfaces.web.uploads import remove_upload_directory, stage_upload


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    config = services.config
    manager = services.jobs
    glossary_service = services.glossaries
    settings_service = services.settings

    @router.get("/api/jobs")
    def list_review_jobs() -> dict[str, object]:
        return {
            "jobs": [job_payload(snapshot, settings_service) for snapshot in manager.list_reviews()]
        }

    @router.get("/api/jobs/recoverable")
    def list_recoverable_jobs() -> dict[str, object]:
        return {
            "jobs": [
                job_payload(snapshot, settings_service)
                for snapshot in manager.list_recoverable_jobs()
            ]
        }

    @router.delete("/api/jobs/{job_id}", status_code=204)
    def delete_review_job(
        job_id: str,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> Response:
        require_csrf(at_csrf, x_csrf_token)
        try:
            manager.delete_review(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ArtifactError, OSError) as exc:
            raise HTTPException(
                status_code=409, detail="Article could not be deleted safely"
            ) from exc
        return Response(status_code=204)

    @router.post("/api/jobs", status_code=202)
    async def create_job(
        pdf: Annotated[UploadFile, File()],
        glossary: Annotated[str, Form()] = "[]",
        glossary_id: Annotated[str | None, Form()] = None,
        glossary_revision: Annotated[int | None, Form()] = None,
        settings: Annotated[str | None, Form()] = None,
        gemini_api_key: Annotated[str | None, Form()] = None,
        api_key: Annotated[str | None, Form()] = None,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_csrf(at_csrf, x_csrf_token)
        resolved_glossary = parse_glossary(glossary, config)
        runtime_config, auto_continue = parse_job_settings(settings, settings_service.resolved())
        if glossary_id is None and not resolved_glossary:
            default_glossary = runtime_config.workbench.default_glossary
            if default_glossary == "none":
                glossary_id = "none"
            elif default_glossary != "configured":
                selected = next(
                    (
                        g
                        for g in glossary_service.list_glossaries()
                        if g.glossary_id == default_glossary
                    ),
                    None,
                )
                if selected is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Default glossary was deleted; choose another in Settings",
                    )
                if same_language(
                    selected.source_language, runtime_config.translation.source_language
                ):
                    glossary_id, glossary_revision = selected.glossary_id, selected.revision
                else:
                    glossary_id = "none"
        configured_matches = same_language(
            config.translation.source_language, runtime_config.translation.source_language
        )
        if not configured_matches:
            runtime_config = runtime_config.model_copy(
                update={
                    "translation": runtime_config.translation.model_copy(update={"glossary": {}})
                }
            )
        if glossary_id is None and not resolved_glossary and not configured_matches:
            glossary_id = "none"
        if glossary_id == "configured":
            if not configured_matches:
                raise HTTPException(
                    status_code=422, detail="Configured glossary does not match the source language"
                )
            if glossary_revision is not None or resolved_glossary:
                raise HTTPException(
                    status_code=422,
                    detail="Configured glossary cannot have a revision or inline terms",
                )
        elif glossary_id:
            if resolved_glossary:
                raise HTTPException(
                    status_code=422,
                    detail="Select one saved glossary or submit inline mappings, not both",
                )
            if glossary_id == "none":
                if glossary_revision is not None:
                    raise HTTPException(
                        status_code=422, detail="No glossary cannot have a revision"
                    )
                resolved_glossary = {}
            else:
                if glossary_revision is None or glossary_revision < 1:
                    raise HTTPException(
                        status_code=422, detail="Select a current glossary revision"
                    )
                resolved_glossary = glossary_service.resolve(
                    glossary_id,
                    expected_revision=glossary_revision,
                    source_language=runtime_config.translation.source_language,
                )
            # A named glossary (or None) replaces the configured glossary in full.
            runtime_config = runtime_config.model_copy(
                update={
                    "translation": runtime_config.translation.model_copy(update={"glossary": {}})
                }
            )
        elif glossary_revision is not None:
            raise HTTPException(status_code=422, detail="A glossary revision requires a glossary")
        if gemini_api_key and runtime_config.provider.name != "gemini":
            raise HTTPException(
                status_code=422, detail="Gemini key cannot be used for another provider"
            )
        session_api_key = parse_session_api_key(api_key or gemini_api_key)
        upload_path, display_filename = await stage_upload(pdf, config)
        try:
            snapshot = manager.submit(
                upload_path=upload_path,
                display_filename=display_filename,
                glossary=resolved_glossary,
                runtime_config=runtime_config,
                api_key=session_api_key,
                auto_continue=auto_continue,
            )
        except Exception:
            remove_upload_directory(upload_path, config.paths.artifacts_dir)
            raise
        return JSONResponse(job_payload(snapshot, settings_service), status_code=202)

    @router.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, object]:
        try:
            return job_payload(manager.get(job_id), settings_service)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/api/jobs/{job_id}/continue", status_code=202)
    def continue_job(
        job_id: str,
        command: ContinueJobRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        require_csrf(at_csrf, x_csrf_token)
        try:
            snapshot = manager.continue_job(job_id, api_key=command.api_key)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(job_payload(snapshot, settings_service), status_code=202)

    @router.post("/api/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        try:
            return job_payload(manager.cancel_job(job_id), settings_service)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
