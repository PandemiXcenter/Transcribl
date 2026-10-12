from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Header,
    Query,
)
from fastapi.responses import Response

from transcribl.domain.glossaries import (
    GlossaryId,
)
from transcribl.domain.languages import LanguageName
from transcribl.interfaces.web.schemas import (
    GlossaryWriteRequest,
)
from transcribl.interfaces.web.security import require_csrf
from transcribl.interfaces.web.services import WebServices


def create_router(services: WebServices) -> APIRouter:
    router = APIRouter()
    glossary_service = services.glossaries

    @router.get("/api/glossaries")
    def list_glossaries(source_language: LanguageName | None = None) -> dict[str, object]:
        return {
            "glossaries": [
                item.model_dump(mode="json")
                for item in glossary_service.list_glossaries(source_language)
            ]
        }

    @router.post("/api/glossaries", status_code=201)
    def create_glossary(
        command: GlossaryWriteRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        return glossary_service.save(
            name=command.name,
            source_language=command.source_language,
            entries=command.entries,
            expected_revision=command.expected_revision,
        ).model_dump(mode="json")

    @router.put("/api/glossaries/{glossary_id}")
    def update_glossary(
        glossary_id: GlossaryId,
        command: GlossaryWriteRequest,
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        require_csrf(at_csrf, x_csrf_token)
        return glossary_service.save(
            name=command.name,
            source_language=command.source_language,
            entries=command.entries,
            glossary_id=glossary_id,
            expected_revision=command.expected_revision,
        ).model_dump(mode="json")

    @router.delete("/api/glossaries/{glossary_id}", status_code=204)
    def delete_glossary(
        glossary_id: GlossaryId,
        expected_revision: Annotated[int, Query(ge=1)],
        at_csrf: Annotated[str | None, Cookie()] = None,
        x_csrf_token: Annotated[str | None, Header()] = None,
    ) -> Response:
        require_csrf(at_csrf, x_csrf_token)
        glossary_service.delete(glossary_id, expected_revision=expected_revision)
        return Response(status_code=204)

    return router
