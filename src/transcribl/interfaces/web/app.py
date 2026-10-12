"""Small FastAPI composition root; feature behavior lives in routes/."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.application.jobs.manager import JobManager
from transcribl.config import ProjectConfig
from transcribl.interfaces.web.errors import register_error_handlers
from transcribl.interfaces.web.routes import costs, exports, glossaries, jobs, review, settings
from transcribl.interfaces.web.security import install_private_headers
from transcribl.interfaces.web.services import build_services
from transcribl.ports.export import PdfCompiler


def create_app(
    config: ProjectConfig,
    *,
    job_manager: JobManager | None = None,
    secret_store: DotenvSecretStore | None = None,
    pdf_compiler: PdfCompiler | None = None,
) -> FastAPI:
    services = build_services(
        config, job_manager=job_manager, secret_store=secret_store, pdf_compiler=pdf_compiler
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if job_manager is None:
            services.jobs.shutdown()

    app = FastAPI(
        title="Transcribl", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.project_config = config
    app.state.job_manager = services.jobs
    install_private_headers(app)
    register_error_handlers(app)
    for feature in (settings, glossaries, costs, jobs, review, exports):
        app.include_router(feature.create_router(services))
    return app
