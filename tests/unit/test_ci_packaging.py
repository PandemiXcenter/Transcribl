from __future__ import annotations

import platform
import runpy
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

hooks = import_module("PyInstaller.utils.hooks")
SPEC = Path(".github/packaging/transcribl.spec")


@pytest.mark.parametrize(("system", "machine"), [("darwin", "arm64"), ("win32", "AMD64")])
def test_ci_spec_collects_only_application_resources(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    packages: list[str] = []
    calls: dict[str, dict[str, Any]] = {}

    def collect(name: str) -> tuple[list[Any], list[Any], list[Any]]:
        packages.append(name)
        return [], [], []

    class Analysis:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls["analysis"] = kwargs
            self.pure: list[Any] = []
            self.scripts: list[Any] = []
            self.binaries: list[Any] = []
            self.datas: list[Any] = []

    def executable(*args: Any, **kwargs: Any) -> object:
        calls["executable"] = kwargs
        return object()

    def bundle(*args: Any, **kwargs: Any) -> object:
        calls["bundle"] = kwargs
        return object()

    monkeypatch.setattr(hooks, "collect_all", collect)
    monkeypatch.setattr(hooks, "collect_data_files", lambda _: [])
    monkeypatch.setattr(hooks, "copy_metadata", lambda _: [])
    runpy.run_path(
        str(SPEC),
        init_globals={
            "SPECPATH": str(SPEC.parent),
            "Analysis": Analysis,
            "PYZ": lambda _: object(),
            "EXE": executable,
            "COLLECT": lambda *args, **kwargs: object(),
            "BUNDLE": bundle,
        },
    )
    assert packages == ["nicegui", "webview", "markitdown", "magika", "pypdfium2"]
    assert calls["analysis"]["datas"] == [(str(Path("config/default.toml").resolve()), "config")]
    assert calls["executable"]["console"] is True
    assert calls["executable"]["target_arch"] == ("arm64" if system == "darwin" else None)
    assert ("bundle" in calls) is (system == "darwin")


def test_ci_spec_rejects_local_or_unsupported_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(SystemExit, match="GitHub Actions only"):
        runpy.run_path(str(SPEC))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(platform, "machine", lambda: "unsupported")
    with pytest.raises(SystemExit, match="Supported build hosts"):
        runpy.run_path(str(SPEC))


def test_workflow_builds_and_smokes_both_native_targets() -> None:
    workflow = Path(".github/workflows/desktop-build.yml").read_text()
    for required in (
        "macos-15",
        "windows-2025",
        "macos-arm64",
        "windows-x64",
        "uv sync --locked --all-groups",
        ".github/packaging/smoke.py",
        "uv run python -m pytest",
        "if-no-files-found: error",
    ):
        assert required in workflow
    assert "compile --mac" not in Path("pyproject.toml").read_text()
    assert not Path("src/transcribl/build_executable.py").exists()
