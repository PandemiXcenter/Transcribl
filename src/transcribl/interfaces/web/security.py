from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from starlette.middleware.base import RequestResponseEndpoint


def require_csrf(cookie_token: str | None, header_token: str | None) -> None:
    if (
        cookie_token is None
        or header_token is None
        or not secrets.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(status_code=403, detail="Invalid request token")


def install_private_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def private_response_headers(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
