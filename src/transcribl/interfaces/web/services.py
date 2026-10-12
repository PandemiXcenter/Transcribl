from __future__ import annotations

from dataclasses import dataclass

from transcribl.adapters.export import LatexPdfCompiler
from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.adapters.storage import FilesystemArtifactRepository
from transcribl.adapters.storage.glossaries import FilesystemGlossaryRepository
from transcribl.adapters.storage.preferences import FilesystemPreferencesRepository
from transcribl.application.glossaries import GlossaryService
from transcribl.application.jobs.manager import JobManager
from transcribl.application.workbench_settings import WorkbenchSettingsService
from transcribl.composition import build_pipeline, provider_translator
from transcribl.config import (
    ProjectConfig,
)
from transcribl.ports.export import PdfCompiler
from transcribl.runtime import default_secret_path


@dataclass(frozen=True)
class WebServices:
    config: ProjectConfig
    jobs: JobManager
    secrets: DotenvSecretStore
    glossaries: GlossaryService
    settings: WorkbenchSettingsService
    pdf_compiler: PdfCompiler


def build_services(
    config: ProjectConfig,
    *,
    job_manager: JobManager | None,
    secret_store: DotenvSecretStore | None,
    pdf_compiler: PdfCompiler | None,
) -> WebServices:
    local_secret_store = secret_store or DotenvSecretStore(default_secret_path())
    manager = job_manager or JobManager(
        config=config,
        pipeline_factory=build_pipeline,
        repository_factory=FilesystemArtifactRepository,
        translator_factory=lambda runtime_config, api_key: provider_translator(
            runtime_config,
            api_key=api_key,
            secret_path=local_secret_store.path,
        ),
    )
    glossary_service = GlossaryService(
        FilesystemGlossaryRepository(config.paths.artifacts_dir),
        max_entries=config.web.max_glossary_entries,
        max_term_characters=config.web.max_term_characters,
        max_name_characters=config.web.max_glossary_name_characters,
    )
    settings_service = WorkbenchSettingsService(
        config, FilesystemPreferencesRepository(config.paths.artifacts_dir)
    )
    local_pdf_compiler = pdf_compiler or LatexPdfCompiler(
        engine=config.pdf_export.latex_engine,
        timeout_seconds=config.pdf_export.compile_timeout_seconds,
    )

    return WebServices(
        config, manager, local_secret_store, glossary_service, settings_service, local_pdf_compiler
    )
