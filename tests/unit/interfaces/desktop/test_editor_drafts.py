"""Exercise the shipped editor modules with a small DOM and transport test double."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "scenario",
    [
        "native_line_breaks",
        "metadata_drafts",
        "selection_restore",
        "failed_save",
        "inflight_drafts",
        "concurrent_save",
        "uncertainty_drafts",
        "unicode_footnote_offset",
        "merged_page_navigation",
        "short_final_page",
    ],
)
def test_editor_draft_regression(scenario: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the dependency-free editor module checks")
    harness = Path(__file__).with_name("editor_drafts.mjs")
    assets = Path("src/transcribl/interfaces/desktop/static/editor").resolve()
    result = subprocess.run(
        [node, "--experimental-vm-modules", str(harness), str(assets), scenario],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
