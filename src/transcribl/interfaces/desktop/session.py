from __future__ import annotations

from typing import Any

import httpx
from fastapi import FastAPI


class DesktopRequestError(ValueError):
    """A validated local application command failed."""


class DesktopSession:
    """Per-window transport to the same strict API used by the editorial component.

    ASGITransport makes no network calls. It preserves HTTP validation, upload
    cleanup, error redaction and CSRF checks without duplicating application rules.
    Credentials never enter NiceGUI storage or a public response.
    """

    def __init__(self, api: FastAPI) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url="http://127.0.0.1"
        )
        self.keys: dict[str, str] = {}

    async def initialize(self) -> dict[str, Any]:
        await self.client.get("/session")
        return await self.request("GET", "/api/config")

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(
            method,
            path,
            headers={"X-CSRF-Token": self.client.cookies.get("at_csrf", "") or ""},
            **kwargs,
        )
        if response.is_error:
            payload = response.json()
            detail = payload.get("detail", "The local request failed")
            if isinstance(detail, list):
                detail = "; ".join(str(item.get("msg", "Invalid input")) for item in detail)
            raise DesktopRequestError(str(detail))
        return response.json() if response.content else {}

    async def close(self) -> None:
        self.keys.clear()
        await self.client.aclose()
