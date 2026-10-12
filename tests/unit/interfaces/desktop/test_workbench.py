from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import pytest
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing.user_simulation import user_simulation

from transcribl.adapters.secrets import DotenvSecretStore
from transcribl.application.jobs.manager import JobManager
from transcribl.application.jobs.records import JobSnapshot, LocalJobStatus
from transcribl.config import ProjectConfig, load_project_config
from transcribl.interfaces.desktop.assets import asset
from transcribl.interfaces.desktop.session import DesktopRequestError, DesktopSession
from transcribl.interfaces.desktop.workbench import Workbench
from transcribl.interfaces.web import create_app


class FakeManager:
    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []

    def submit(self, **kwargs: Any) -> JobSnapshot:
        self.submissions.append(kwargs)
        return JobSnapshot("a" * 32, LocalJobStatus.QUEUED, "study.pdf", 0, 2, None, None)

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
        config_for(tmp_path), job_manager=cast(JobManager, FakeManager()), secret_store=store
    )
    session = DesktopSession(api)
    await session.initialize()
    with pytest.raises(DesktopRequestError, match="Invalid request token"):
        session.client.cookies.clear()
        await session.request(
            "POST",
            "/api/glossaries",
            json={"source_language": "Danish", "name": "Test", "entries": []},
        )
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
        job_manager=cast(JobManager, manager),
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
            workbench.translation.source.set_value("Old Danish")
            await workbench.glossaries.refresh_glossaries()
            await workbench.translation.start_translation()
            assert workbench.translation.translate_error.text == "Choose a PDF first."
            workbench.tabs.set_value("Glossaries")
        await user.should_see("Glossary name")
        with user:
            workbench.glossaries.glossary_name.set_value("Historical medicine")
            workbench.glossaries.rows = [
                {"source_term": "Vattersot", "target_translation": "Dropsy"}
            ]
            await workbench.glossaries.save_glossary()
            assert workbench.glossaries.editing is not None
            selected_id = workbench.glossaries.editing["glossary_id"]
            assert workbench.translation.glossary_choice.value == selected_id
            workbench.translation.source.set_value("German")
            assert selected_id not in workbench.translation.glossary_choice.options
            assert workbench.translation.glossary_choice.value == "none"
            workbench.translation.source.set_value(" old danish ")
            assert selected_id in workbench.translation.glossary_choice.options
            workbench.translation.glossary_choice.set_value(selected_id)
            workbench.tabs.set_value("Settings")
            workbench.settings.settings_model.set_value("gpt-6-astra")
            await workbench.settings.save_settings()
            assert workbench.translation.job_model.value == "gpt-6-astra"
            workbench.credentials.key_inputs["openai"].set_value("test-window-key")
            await workbench.credentials.save_api_key("openai")
            assert workbench.credentials.key_inputs["openai"].value == ""
            assert workbench.session.keys["openai"] == "test-window-key"
            workbench.tabs.set_value("Translate")
            workbench.translation.source.select.set_value("Custom")
            workbench.translation.source.custom.set_value("Old Danish")
            workbench.translation.target.select.set_value("English")
            workbench.translation.file = SmallFileUpload(
                name="study.pdf", content_type="application/pdf", _data=b"%PDF-1.7\nsynthetic"
            )
            workbench.glossaries.mark_dirty()
            await workbench.translation.start_translation()
            assert "Save or discard" in workbench.translation.translate_error.text
            assert not manager.submissions
            workbench.glossaries.dirty = False
            await workbench.translation.start_translation()
            assert len(manager.submissions) == 1
            submitted = manager.submissions[0]
            assert submitted["glossary"] == {"Vattersot": "Dropsy"}
            assert submitted["runtime_config"].translation.source_language == "Old Danish"
            assert submitted["runtime_config"].provider.name == "openai"
            assert submitted["api_key"].get_secret_value() == "test-window-key"
            assert workbench.translation.file is None
            await workbench.close()


@pytest.mark.asyncio
async def test_api_keys_dialog_manages_providers_independently(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    api = create_app(
        config,
        job_manager=cast(JobManager, FakeManager()),
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
        assert not workbench.credentials.api_keys_dialog.value
        user.find(kind=ui.button, content="API Keys").click()
        await user.should_see("Google (Gemini) API key")
        await user.should_see("OpenAI API key")
        await user.should_see("Anthropic API key")
        assert workbench.credentials.api_keys_dialog.value
        with user:
            await workbench.credentials.save_api_key("anthropic")
            assert workbench.credentials.key_messages["anthropic"].text == "Enter an API key."
            for provider in ("gemini", "openai", "anthropic"):
                workbench.credentials.key_inputs[provider].set_value(f"test-{provider}-key")
                workbench.credentials.save_keys[provider].set_value(provider != "openai")
            workbench.settings.settings_model.set_value("gpt-6-astra")
            for provider in ("gemini", "openai", "anthropic"):
                assert workbench.credentials.key_for(provider) == f"test-{provider}-key"
                await workbench.credentials.save_api_key(provider)
                assert workbench.credentials.key_inputs[provider].value == ""
            assert workbench.session.keys == {"openai": "test-openai-key"}
            assert workbench.credentials.key_statuses["openai"].text == "Available for this window"
            assert workbench.credentials.key_statuses["anthropic"].text == "Saved on this computer"
            await workbench.credentials.clear_api_key("anthropic")
            public = await workbench.session.request("GET", "/api/config")
            assert public["api_keys"]["gemini"]["saved_on_computer"]
            assert not public["api_keys"]["anthropic"]["saved_on_computer"]
            assert workbench.credentials.key_for("openai") == "test-openai-key"
            assert "test-" not in str(public)
            workbench.credentials.api_keys_dialog.close()
        user.find(kind=ui.button, content="API Keys").click()
        await user.should_see("Google (Gemini) API key")
        assert all(field.value == "" for field in workbench.credentials.key_inputs.values())
        assert workbench.settings.settings_model.value == "gpt-6-astra"
        assert workbench.translation.model == "gemini-3.8-flash"
        with user:
            await workbench.close()


@pytest.mark.asyncio
async def test_settings_icon_custom_styles_and_separate_defaults(tmp_path: Path) -> None:
    config = config_for(tmp_path)
    api = create_app(
        config,
        job_manager=cast(JobManager, FakeManager()),
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
            await workbench.glossaries.refresh_glossaries()
            workbench.translation.job_model.set_value("claude-sonnet-5-5")
            workbench.settings.settings_model.set_value("gpt-6-luna")
            workbench.settings.new_style_name.set_value("Historical prose")
            workbench.settings.add_style()
            workbench.settings.style_prompt.set_value("Preserve historical idioms and quotations.")
            workbench.settings.settings_style.set_value("Historical prose")
            workbench.settings.thinking["openai"].set_value("high")
            await workbench.settings.save_settings()
            assert workbench.settings.settings_revision == 1
            assert workbench.translation.job_model.value == "claude-sonnet-5-5"
            assert workbench.translation.job_style.value == "Historical prose"
            assert workbench.preferences.default_model == "gpt-6-luna"
            workbench.settings.settings_model.set_value("gpt-6-astra")
            await workbench.settings.reload_settings()
            assert workbench.settings.settings_model.value == "gpt-6-luna"
            assert (
                workbench.settings.style_prompt.value
                == "Preserve historical idioms and quotations."
            )
            assert "Historical prose" in workbench.settings.prompt_settings.value
            workbench.settings.style_editor_choice.set_value("balanced")
            workbench.settings.style_prompt.set_value("Edited built-in instructions.")
            workbench.settings.reset_style()
            assert (
                workbench.settings.style_prompt.value == config.workbench.style_prompts["balanced"]
            )
            await workbench.close()


def test_editor_component_keeps_complete_review_and_delegated_events() -> None:
    from importlib.resources import files

    components = files("transcribl.interfaces.desktop").joinpath("static", "editor")
    script = "\n".join(p.read_text("utf-8") for p in components.iterdir() if p.name.endswith(".js"))
    html = asset("editor.html")
    css = "\n".join(
        p.read_text("utf-8")
        for p in files("transcribl.interfaces.desktop").joinpath("static", "styles").iterdir()
    )
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
        "editorDisplayOnly",
        "paragraph-page-boundary page-sync-anchor",
    ):
        assert feature in script
    assert "for (const page of state.reviewPages)" in script
    assert "translationContent.addEventListener('paste', handleReviewPaste)" in script
    for name in ("blocks.js", "paragraphs.js"):
        assert ".addEventListener" not in components.joinpath(name).read_text("utf-8")
    assert "Translate All" in html
    assert 'id="translate-all"' in html
    assert "/backend/api/jobs/" in script
    assert ".research-editor .source-scroll" in css
    assert "overflow: hidden" in css
    assert "<iframe" not in html


@pytest.mark.asyncio
async def test_upload_estimate_model_change_and_removed_file(tmp_path: Path) -> None:
    from io import BytesIO

    from nicegui import events
    from pypdf import PdfWriter

    from transcribl.domain.costs import CostSummary

    class CostManager(FakeManager):
        def estimate_cost(self, *, model: str, page_count: int, thinking_level: str) -> CostSummary:
            price = 0.1 if model == "gpt-6-astra" else 0.01
            return CostSummary(
                kind="estimate",
                page_count=page_count,
                total_usd=price * page_count,
                per_page_usd=price,
                sample_pages=120,
                basis="all models",
            )

    config = config_for(tmp_path)
    api = create_app(
        config,
        job_manager=cast(JobManager, CostManager()),
        secret_store=DotenvSecretStore(tmp_path / ".env"),
    )
    windows: list[Workbench] = []

    async def root() -> None:
        session = DesktopSession(api)
        windows.append(Workbench(config, session, await session.initialize()))

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    buffer = BytesIO()
    writer.write(buffer)
    async with user_simulation(root) as user:
        user.javascript_rules[re.compile(".*", re.S)] = lambda _: None
        await user.open("/")
        workbench = windows[0]
        with user:
            await workbench.translation.uploaded(
                events.UploadEventArguments(
                    sender=workbench.translation.upload,
                    client=workbench.client,
                    file=SmallFileUpload(
                        name="two.pdf", content_type="application/pdf", _data=buffer.getvalue()
                    ),
                )
            )
            assert workbench.translation.pdf_page_count == 2
            assert "0.1337 DKK" in workbench.translation.estimate_label.text
            assert "120 completed pages" in workbench.translation.estimate_details.text
            workbench.translation.job_model.set_value("gpt-6-astra")
        await user.should_see("Estimated cost ≈ 1.3371 DKK · 2 pages at 0.6685 DKK/page")
        with user:
            workbench.translation.remove_file()
            assert workbench.translation.estimate_label.text == ""
            assert workbench.translation.pdf_page_count is None
            assert not workbench.translation.cost_details.visible
            workbench.translation.job = {
                "filename": "two.pdf",
                "status": "ready",
                "total_pages": 2,
                "current_page": 2,
                "cost": {"total_usd": 0.025, "total": 0.1671, "currency": "DKK"},
            }
            workbench.translation.render_progress()
            assert "0.1671 DKK" in workbench.translation.progress_cost.text
            await workbench.close()
