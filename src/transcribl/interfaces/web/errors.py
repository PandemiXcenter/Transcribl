from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from transcribl.application.jobs.records import JobNotReadyError
from transcribl.domain.errors import (
    ArtifactError,
    EditorialError,
    EditorialTargetError,
    PdfExportError,
    ReplaceAllUnavailableError,
    RevisionConflictError,
)
from transcribl.domain.glossaries import (
    GlossaryConflictError,
    GlossaryError,
    GlossaryNotFoundError,
    GlossaryStorageError,
)
from transcribl.domain.preferences import PreferencesConflictError, PreferencesStorageError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PreferencesConflictError)
    @app.exception_handler(PreferencesStorageError)
    async def preferences_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(GlossaryError)
    def glossary_command_failed(_: Request, exc: GlossaryError) -> JSONResponse:
        status = 422
        if isinstance(exc, GlossaryNotFoundError):
            status = 404
        elif isinstance(exc, GlossaryConflictError):
            status = 409
        elif isinstance(exc, GlossaryStorageError):
            status = 503
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @app.exception_handler(JobNotReadyError)
    def job_not_ready(_: Request, exc: JobNotReadyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": "Request validation failed"}, status_code=422)

    @app.exception_handler(RevisionConflictError)
    def revision_conflict(_: Request, exc: RevisionConflictError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ReplaceAllUnavailableError)
    def replace_all_unavailable(
        _: Request,
        exc: ReplaceAllUnavailableError,
    ) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(EditorialTargetError)
    def editorial_target_missing(_: Request, exc: EditorialTargetError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(EditorialError)
    def editorial_command_failed(_: Request, exc: EditorialError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(PdfExportError)
    def pdf_export_failed(_: Request, __: PdfExportError) -> JSONResponse:
        return JSONResponse(
            {"detail": "The reviewed PDF could not be generated on this computer"},
            status_code=503,
        )

    @app.exception_handler(ArtifactError)
    def review_artifact_failed(_: Request, __: ArtifactError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Review artifacts are unavailable or invalid"},
            status_code=409,
        )
