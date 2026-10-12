from __future__ import annotations

from fastapi import FastAPI, Request, Response
from nicegui import app, ui
from starlette.middleware.base import RequestResponseEndpoint

from transcribl.config import ProjectConfig
from transcribl.interfaces.desktop.workbench import create_workbench
from transcribl.interfaces.web import create_app


def register_desktop(config: ProjectConfig, *, api: FastAPI | None = None) -> FastAPI:
    """Compose a single NiceGUI app and the existing loopback application API."""
    backend = api or create_app(config)
    app.mount("/backend", backend)
    app.on_shutdown(backend.state.job_manager.shutdown)

    @app.middleware("http")
    async def private_response_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @ui.page("/")
    async def index() -> None:
        await create_workbench(config, backend)

    return backend


def run_desktop(config: ProjectConfig, *, native: bool = True) -> None:
    register_desktop(config)
    # pywebview otherwise ignores the editor's reviewed-export download links.
    app.native.settings["ALLOW_DOWNLOADS"] = True
    app.native.window_args["min_size"] = (
        config.desktop.minimum_width,
        config.desktop.minimum_height,
    )
    app.native.window_args["confirm_close"] = True
    ui.run(
        host=config.web.host,
        port=config.web.port,
        title="Transcribl",
        native=native,
        window_size=(config.desktop.window_width, config.desktop.window_height) if native else None,
        show=config.web.open_browser_on_start if not native else False,
        reload=False,
        show_welcome_message=False,
        # Keys are cleared from input widgets after submission. Do not retain their
        # earlier UI values in the reconnect message history.
        message_history_length=0,
    )
