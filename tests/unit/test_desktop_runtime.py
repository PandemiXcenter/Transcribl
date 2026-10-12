from pathlib import Path
from typing import Any

import pytest
from nicegui import app, ui

from transcribl.config import load_project_config
from transcribl.interfaces.desktop import app as desktop


@pytest.mark.parametrize("native", [True, False])
def test_nicegui_runtime_is_loopback_and_preserves_native_downloads(
    monkeypatch: pytest.MonkeyPatch,
    native: bool,
) -> None:
    config = load_project_config(Path("config/default.toml"))
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(desktop, "register_desktop", lambda _: None)
    monkeypatch.setattr(ui, "run", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(app.native, "settings", {})
    monkeypatch.setattr(app.native, "window_args", {})
    desktop.run_desktop(config, native=native)
    assert calls[0]["host"] == config.web.host
    assert calls[0]["port"] == config.web.port
    assert calls[0]["native"] is native
    assert calls[0]["reload"] is False
    assert calls[0]["message_history_length"] == 0
    assert calls[0]["window_size"] == ((1440, 1000) if native else None)
    assert app.native.settings["ALLOW_DOWNLOADS"] is True
    assert app.native.window_args["confirm_close"] is True
