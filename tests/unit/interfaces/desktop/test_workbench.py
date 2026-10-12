from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user_simulation import user_simulation

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.application.web_jobs import WebJobManager, WebJobSnapshot, WebJobStatus
from transcribl.config import ProjectConfig, load_project_config
from transcribl.interfaces.desktop.session import DesktopRequestError, DesktopSession
from transcribl.interfaces.desktop.workbench import Workbench, asset
from transcribl.interfaces.web import create_app


class FakeManager:
    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []

    def submit(self, **kwargs: Any) -> WebJobSnapshot:
        self.submissions.append(kwargs)
        return WebJobSnapshot("a" * 32, WebJobStatus.QUEUED, "study.pdf", 0, 2, None, None)

    def list_recoverable(self) -> list[object]:
        return []

    def shutdown(self) -> None:
        pass


def config_for(tmp_path: Path) -> ProjectConfig:
    config = load_project_config(Path("config/default.toml"))
    return config.model_copy(
        update={"paths": config.paths.model_copy(update={"artifacts_dir": tmp_path / "artifacts"})}
    )


@pytest.mark.asyncio
async def test_desktop_session_preserves_csrf_validation_and_key_redaction(tmp_path: Path) -> None:
    store = DotenvSecretStore(tmp_path / ".env")
    api = create_app(
        config_for(tmp_path), job_manager=cast(WebJobManager, FakeManager()), secret_store=store
    )
    session = DesktopSession(api)
    await session.initialize()
    with pytest.raises(DesktopRequestError, match="Invalid request token"):
        session.client.cookies.clear()
        await session.request("POST", "/api/glossaries", json={"name": "Test", "entries": []})
    await session.initialize()
    status = await session.request(
        "POST",
        "/api/settings/api-key",
        json={"provider": "openai", "api_key": "test-not-a-live-key", "save_on_computer": True},
    )
    assert status == {"api_key_configured": True, "saved_on_computer": True}
    public = await session.request("GET", "/api/config")
    assert "test-not-a-live-key" not in str(public)
    session.keys["anthropic"] = "test-ephemeral"
    await session.close()
    assert session.keys == {}
    assert session.client.is_closed


@pytest.mark.asyncio
async def test_nicegui_glossary_language_settings_and_submission(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    manager = FakeManager()
    api = create_app(
        config,
        job_manager=cast(WebJobManager, manager),
        secret_store=DotenvSecretStore(tmp_path / ".env"),
    )
    windows: list[Workbench] = []

    async def root() -> None:
        session = DesktopSession(api)
        public = await session.initialize()
        windows.append(Workbench(config, session, public))

    async with user_simulation(root) as user:
        user.javascript_rules[re.compile(".*", re.S)] = lambda _: None
        await user.open("/")
        await user.should_see("Translate PDF")
        workbench = windows[0]
        with user:
            await workbench.refresh_glossaries()
            await workbench.start_translation()
            assert workbench.translate_error.text == "Choose a PDF first."
            workbench.tabs.set_value("Glossaries")
        await user.should_see("Glossary name")
        with user:
            workbench.glossary_name.set_value("Historical medicine")
            workbench.rows = [{"source_term": "Vattersot", "target_translation": "Dropsy"}]
            await workbench.save_glossary()
            assert workbench.editing is not None
            selected_id = workbench.editing["glossary_id"]
            assert workbench.glossary_choice.value == selected_id
            workbench.tabs.set_value("Settings")
            workbench.settings_model.set_value("gpt-6-astra")
            await workbench.save_settings()
            assert workbench.job_model.value == "gpt-6-astra"
            workbench.key_inputs["openai"].set_value("test-window-key")
            await workbench.save_api_key("openai")
            assert workbench.key_inputs["openai"].value == ""
            assert workbench.session.keys["openai"] == "test-window-key"
            workbench.tabs.set_value("Translate")
            workbench.source.select.set_value("Custom")
            workbench.source.custom.set_value("Old Danish")
            workbench.target.select.set_value("English")
            workbench.file = SmallFileUpload(
                name="study.pdf", content_type="application/pdf", _data=b"%PDF-1.7\nsynthetic"
            )
            workbench.mark_dirty()
            await workbench.start_translation()
            assert "Save or discard" in workbench.translate_error.text
            assert not manager.submissions
            workbench.dirty = False
            await workbench.start_translation()
            assert len(manager.submissions) == 1
            submitted = manager.submissions[0]
            assert submitted["glossary"] == {"Vattersot": "Dropsy"}
            assert submitted["runtime_config"].translation.source_language == "Old Danish"
            assert submitted["runtime_config"].provider.name == "openai"
            assert submitted["api_key"].get_secret_value() == "test-window-key"
            assert workbench.file is None
            await workbench.close()


@pytest.mark.asyncio
async def test_api_keys_dialog_manages_providers_independently(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    api = create_app(
        config,
        job_manager=cast(WebJobManager, FakeManager()),
        secret_store=DotenvSecretStore(tmp_path / ".env"),
    )
    windows: list[Workbench] = []

    async def root() -> None:
        session = DesktopSession(api)
        windows.append(Workbench(config, session, await session.initialize()))

    async with user_simulation(root) as user:
        user.javascript_rules[re.compile(".*", re.S)] = lambda _: None
        await user.open("/")
        workbench = windows[0]
        with user:
            workbench.tabs.set_value("Settings")
        assert not workbench.api_keys_dialog.value
        user.find(kind=ui.button, content="API Keys").click()
        await user.should_see("Google (Gemini) API key")
        await user.should_see("OpenAI API key")
        await user.should_see("Anthropic API key")
        assert workbench.api_keys_dialog.value
        with user:
            await workbench.save_api_key("anthropic")
            assert workbench.key_messages["anthropic"].text == "Enter an API key."
            for provider in ("gemini", "openai", "anthropic"):
                workbench.key_inputs[provider].set_value(f"test-{provider}-key")
                workbench.save_keys[provider].set_value(provider != "openai")
            workbench.settings_model.set_value("gpt-6-astra")
            for provider in ("gemini", "openai", "anthropic"):
                assert workbench.key_for(provider) == f"test-{provider}-key"
                await workbench.save_api_key(provider)
                assert workbench.key_inputs[provider].value == ""
            assert workbench.session.keys == {"openai": "test-openai-key"}
            assert workbench.key_statuses["openai"].text == "Available for this window"
            assert workbench.key_statuses["anthropic"].text == "Saved on this computer"
            await workbench.clear_api_key("anthropic")
            public = await workbench.session.request("GET", "/api/config")
            assert public["api_keys"]["gemini"]["saved_on_computer"]
            assert not public["api_keys"]["anthropic"]["saved_on_computer"]
            assert workbench.key_for("openai") == "test-openai-key"
            assert "test-" not in str(public)
            workbench.api_keys_dialog.close()
        user.find(kind=ui.button, content="API Keys").click()
        await user.should_see("Google (Gemini) API key")
        assert all(field.value == "" for field in workbench.key_inputs.values())
        assert workbench.settings_model.value == "gpt-6-astra"
        assert workbench.model == "gemini-3.8-flash"
        with user:
            await workbench.close()


@pytest.mark.asyncio
async def test_settings_icon_custom_styles_and_separate_defaults(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    api = create_app(
        config,
        job_manager=cast(WebJobManager, FakeManager()),
        secret_store=DotenvSecretStore(tmp_path / ".env"),
    )
    windows: list[Workbench] = []

    async def root() -> None:
        session = DesktopSession(api)
        windows.append(Workbench(config, session, await session.initialize()))

    async with user_simulation(root) as user:
        user.javascript_rules[re.compile(".*", re.S)] = lambda _: None
        await user.open("/")
        workbench = windows[0]
        assert "Settings" not in [tab.props["name"] for tab in user.find(ui.tab).elements]
        user.find(marker="open-settings").click()
        await user.should_see("Default model")
        await user.should_see("Default style")
        await user.should_see("Default glossary")
        with user:
            await workbench.refresh_glossaries()
            workbench.job_model.set_value("claude-sonnet-5-5")
            workbench.settings_model.set_value("gpt-6-luna")
            workbench.new_style_name.set_value("Historical prose")
            workbench.add_style()
            workbench.style_prompt.set_value("Preserve historical idioms and quotations.")
            workbench.settings_style.set_value("Historical prose")
            workbench.thinking["openai"].set_value("high")
            await workbench.save_settings()
            assert workbench.settings_revision == 1
            assert workbench.job_model.value == "claude-sonnet-5-5"
            assert workbench.job_style.value == "Historical prose"
            assert workbench.preferences.default_model == "gpt-6-luna"
            workbench.settings_model.set_value("gpt-6-astra")
            await workbench.reload_settings()
            assert workbench.settings_model.value == "gpt-6-luna"
            assert workbench.style_prompt.value == "Preserve historical idioms and quotations."
            assert "Historical prose" in workbench.prompt_settings.value
            workbench.style_editor_choice.set_value("balanced")
            workbench.style_prompt.set_value("Edited built-in instructions.")
            workbench.reset_style()
            assert workbench.style_prompt.value == config.workbench.style_prompts["balanced"]
            await workbench.close()


def test_editor_component_keeps_complete_review_and_delegated_events() -> None:
    script, html, css = asset("editor.js"), asset("editor.html"), asset("editor.css")
    for feature in (
        "renderAllReviewPages",
        "showSourcePage",
        "persistReviewPosition",
        "saveBlock",
        "saveParagraphGroup",
        "replaceUncertainty",
        "deleteLibraryReview",
        "makeExportMenu",
        "setReviewZoom",
    ):
        assert f"function {feature}" in script
    for feature in (
        "section-type-select",
        "footnote-owner-select",
        "footnote-anchor-input",
        "data-editor-display-only",
        "paragraph-page-boundary page-sync-anchor",
    ):
        assert feature in script
    assert "for (const page of state.reviewPages)" in script
    assert "translationContent.addEventListener('paste', handleReviewPaste)" in script
    factory = script.split("function makeTranslationBlock", 1)[1].split(
        "function captureDrafts", 1
    )[0]
    assert ".addEventListener" not in factory
    assert "Translate All" in html
    assert 'id="translate-all"' in html
    assert "/backend/api/jobs/" in script
    assert ".research-editor .source-scroll" in css
    assert "overflow: hidden" in css
    assert "<iframe" not in html
