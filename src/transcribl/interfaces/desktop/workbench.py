from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from nicegui import events, ui

from transcribl.config import ProjectConfig, resolve_workbench_preferences
from transcribl.domain.preferences import WorkbenchPreferences
from transcribl.interfaces.desktop.assets import asset
from transcribl.interfaces.desktop.credentials import ApiKeysDialog
from transcribl.interfaces.desktop.glossaries import GlossariesPanel
from transcribl.interfaces.desktop.session import DesktopRequestError, DesktopSession
from transcribl.interfaces.desktop.settings import SettingsPanel
from transcribl.interfaces.desktop.translation import TranslationPanel


class Workbench:
    """Coordinates mounted panels and the lifetime of one desktop session."""

    def __init__(
        self, config: ProjectConfig, session: DesktopSession, public: dict[str, Any]
    ) -> None:
        self.preferences = WorkbenchPreferences.model_validate(public["preferences"]["values"])
        config = resolve_workbench_preferences(config, self.preferences)
        self.config = config
        self.session = session
        self.public = public
        self.client = ui.context.client
        self.editor_ready = False
        self.translation = TranslationPanel(self)
        self.settings = SettingsPanel(self)
        self.credentials = ApiKeysDialog(self)
        self.glossaries = GlossariesPanel(self)
        ui.colors(primary="#365e70", secondary="#687b82", negative="#a23832")
        ui.add_css(asset("editor.css"))
        ui.add_css(asset("desktop.css"))
        with ui.header().classes("workbench-header items-center px-8 py-0 gap-0"):
            ui.label("Transcribl").classes("workbench-title")
            with ui.tabs(on_change=self.tab_changed).classes("workbench-tabs") as self.tabs:
                for name in ("Translate", "Glossaries", "Articles"):
                    ui.tab(name)
            ui.space()
            ui.button(icon="settings", on_click=lambda: self.tabs.set_value("Settings")).props(
                'flat round aria-label="Settings"'
            ).tooltip("Settings").mark("open-settings")
        self.sections: dict[str, ui.column] = {}
        # All four sections stay mounted. The editorial document must retain focus,
        # drafts and scroll state across navigation.
        with ui.column().classes("workbench-body"):
            for name in ("Translate", "Glossaries", "Settings", "Articles"):
                with ui.column().classes("w-full gap-0") as section:
                    self.sections[name] = section
                    section.set_visibility(name == "Translate")
                    if name == "Translate":
                        self.translation.translation_controls()
                    elif name == "Glossaries":
                        self.glossaries.glossary_controls()
                    elif name == "Settings":
                        self.settings.settings_controls()
                    else:
                        ui.html(asset("editor.html"), sanitize=False).classes("research-editor")
        self.translation.source.select.on_value_change(self.glossaries.render_glossary_choices)
        self.translation.source.custom.on_value_change(self.glossaries.render_glossary_choices)
        self.tabs.set_value("Translate")
        ui.on("transcribl-tab", lambda event: self.tabs.set_value(event.args))
        self.timer = ui.timer(config.web.status_poll_interval_ms / 1000, self.translation.poll_job)
        self.client.on_delete(self.close)

    def tab_changed(self, event: events.ValueChangeEventArguments[Any]) -> None:
        for name, section in self.sections.items():
            section.set_visibility(name == event.value)
        if event.value == "Articles" and self.editor_ready:
            ui.run_javascript(
                'window.transcriblEditor.refreshCosts(); window.dispatchEvent(new Event("resize"));'
            )

    async def initialize(self) -> None:
        await self.glossaries.refresh_glossaries()
        await self.translation.refresh_recoverable()
        await self.client.connected()
        # The only injected HTML/JS is a checked-in component. Document text is
        # populated with textContent by that component, never interpolated here.
        await ui.run_javascript(asset("editor.js"), timeout=20)
        self.editor_ready = True
        job_id = self.client.request.query_params.get("job") if self.client.request else None
        if job_id:
            try:
                self.translation.job = await self.session.request("GET", f"/api/jobs/{job_id}")
                self.translation.render_progress()
                if self.translation.job["status"] in ("ready", "completed"):
                    await self.translation.open_review()
            except DesktopRequestError as exc:
                ui.notify(str(exc), type="negative")

    async def close(self) -> None:
        self.timer.cancel()
        self.translation.file = None
        await self.session.close()

    def model_options(self) -> dict[str, str]:
        return {
            item["id"]: f"{item['id']} · {item['provider'].title()}"
            for item in self.public["provider"]["models"]
        }

    def provider_for(self, model: str) -> str:
        return str(
            next(
                item["provider"]
                for item in self.public["provider"]["models"]
                if item["id"] == model
            )
        )

    async def confirm(self, message: str) -> bool:
        with ui.dialog() as dialog, ui.card():
            ui.label(message)
            with ui.row():
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Confirm", on_click=lambda: dialog.submit(True))
        return bool(await dialog)


async def create_workbench(config: ProjectConfig, api: FastAPI) -> Workbench:
    session = DesktopSession(api)
    try:
        public = await session.initialize()
        workbench = Workbench(config, session, public)
    except Exception:
        await session.close()
        raise
    ui.timer(0, workbench.initialize, once=True)
    return workbench
