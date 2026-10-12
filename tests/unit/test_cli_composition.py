from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, Self, cast

import pytest
from typer.testing import CliRunner

import transcribl.cli as cli
import transcribl.composition as composition
import transcribl.executable as executable
from transcribl.application.pipeline import TranslationPipeline
from transcribl.config import ProjectConfig, load_project_config
from transcribl.domain.models import (
    DocumentTranslation,
    MarkdownExportSettings,
    TranslationSettings,
)


class RecordingPipeline:
    def __init__(self) -> None:
        self.prepared_with: tuple[Path, Path, int, bool] | None = None
        self.translated_with: tuple[Path, TranslationSettings, object, bool] | None = None
        self.compiled_with: tuple[Path, MarkdownExportSettings] | None = None

    def prepare_document(
        self,
        source_pdf: Path,
        *,
        artifacts_dir: Path,
        image_dpi: int,
        force: bool,
    ) -> Path:
        self.prepared_with = (source_pdf, artifacts_dir, image_dpi, force)
        return Path("resolved-job")

    def translate_document(
        self,
        job_dir: Path,
        *,
        settings: TranslationSettings,
        translator: object,
        force: bool,
    ) -> DocumentTranslation:
        self.translated_with = (job_dir, settings, translator, force)
        return cast(DocumentTranslation, SimpleNamespace(pages=[object()]))

    def compile_document(
        self,
        job_dir: Path,
        *,
        settings: MarkdownExportSettings,
    ) -> Path:
        self.compiled_with = (job_dir, settings)
        return job_dir / "output" / "document.md"


class RecordingGeminiTranslator:
    constructor: ClassVar[dict[str, object]] = {}

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        api_version: str,
        timeout_seconds: int,
        attempts: int,
        max_inline_request_bytes: int,
        thinking_level: str,
    ) -> None:
        type(self).constructor = {
            "api_key": api_key,
            "model": model,
            "api_version": api_version,
            "timeout_seconds": timeout_seconds,
            "attempts": attempts,
            "max_inline_request_bytes": max_inline_request_bytes,
        }

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_full_run_wires_path_extraction_and_export_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_project_config(Path("config/default.toml"))
    pipeline = RecordingPipeline()
    translated: dict[str, object] = {}

    def fake_translate(
        runtime_config: ProjectConfig,
        job_dir: Path,
        *,
        force: bool,
        pipeline: object,
    ) -> DocumentTranslation:
        translated.update(
            {
                "config": runtime_config,
                "job_dir": job_dir,
                "force": force,
                "pipeline": pipeline,
            }
        )
        return cast(DocumentTranslation, SimpleNamespace(pages=[object()]))

    monkeypatch.setattr(cli, "_pipeline", lambda: pipeline)
    monkeypatch.setattr(cli, "_translate", fake_translate)

    result = CliRunner().invoke(
        cli.app,
        ["--config", "config/default.toml", "run", "example.pdf", "--force"],
    )

    assert result.exit_code == 0, result.output
    assert pipeline.prepared_with == (
        Path("example.pdf"),
        config.paths.artifacts_dir,
        config.extraction.image_dpi,
        True,
    )
    assert translated == {
        "config": config,
        "job_dir": Path("resolved-job"),
        "force": True,
        "pipeline": pipeline,
    }
    assert pipeline.compiled_with == (Path("resolved-job"), config.export)


def test_provider_and_translation_settings_are_composed_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_project_config(Path("config/default.toml"))
    pipeline = RecordingPipeline()
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-key")
    monkeypatch.setattr(
        composition,
        "GeminiPageTranslator",
        RecordingGeminiTranslator,
    )

    cli._translate(
        config,
        Path("job"),
        force=False,
        pipeline=cast(TranslationPipeline, pipeline),
    )

    gemini = config.provider.gemini
    assert RecordingGeminiTranslator.constructor == {
        "api_key": "test-only-key",
        "model": gemini.model,
        "api_version": gemini.api_version,
        "timeout_seconds": gemini.request_timeout_seconds,
        "attempts": gemini.request_attempts,
        "max_inline_request_bytes": gemini.max_inline_request_bytes,
    }
    assert pipeline.translated_with is not None
    assert pipeline.translated_with[1] == config.translation


def test_short_app_launcher_prefers_personal_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = load_project_config(Path("config/default.toml"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    personal = config_dir / "personal.local.toml"
    personal.touch()
    loaded: list[Path] = []
    served: list[ProjectConfig] = []

    def fake_load(path: Path) -> ProjectConfig:
        loaded.append(path)
        return config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_project_config", fake_load)
    monkeypatch.setattr(cli, "_launch_desktop", served.append)

    cli.launch_app()

    assert loaded == [Path("config/personal.local.toml")]
    assert served == [config]


def test_short_app_launcher_falls_back_to_checked_in_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = load_project_config(Path("config/default.toml"))
    loaded: list[Path] = []

    def fake_load(path: Path) -> ProjectConfig:
        loaded.append(path)
        return config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_project_config", fake_load)
    monkeypatch.setattr(cli, "_launch_desktop", lambda _: None)

    cli.launch_app()

    assert loaded == [Path("config/default.toml")]


def test_frozen_entry_launches_workbench_without_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched: list[bool] = []
    monkeypatch.setattr(cli, "launch_app", lambda: launched.append(True))
    monkeypatch.setattr(executable.sys, "argv", ["Transcribl"])

    executable.main()

    assert launched == [True]


def test_frozen_entry_retains_complete_cli_with_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocations: list[str] = []
    monkeypatch.setattr(cli, "app", lambda *, prog_name: invocations.append(prog_name))
    monkeypatch.setattr(executable.sys, "argv", ["Transcribl", "--help"])

    executable.main()

    assert invocations == ["Transcribl"]


@pytest.mark.parametrize(
    "provider,adapter_name",
    [("openai", "OpenAIPageTranslator"), ("anthropic", "AnthropicPageTranslator")],
)
def test_new_provider_composition_loads_only_its_saved_cache_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    adapter_name: str,
) -> None:
    from transcribl.adapters.secrets import DotenvSecretStore
    from transcribl.config import StructuredProviderConfig

    for variable in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    store = DotenvSecretStore(tmp_path / ".env")
    for name in ("gemini", "openai", "anthropic"):
        store.save_api_key(name, f"test-{name}")
    observed: dict[str, object] = {}

    class Adapter:
        def __init__(self, *, api_key: str, config: StructuredProviderConfig) -> None:
            observed.update(key=api_key, config=config)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_: object) -> None:
            observed["closed"] = True

    monkeypatch.setattr(composition, adapter_name, Adapter)
    config = load_project_config(Path("config/default.toml"))
    config = config.model_copy(
        update={"provider": config.provider.model_copy(update={"name": provider})}
    )
    with composition.provider_translator(config, secret_path=store.path):
        assert observed["key"] == f"test-{provider}"
        assert observed["config"] == config.provider.selected
    assert observed["closed"] is True
