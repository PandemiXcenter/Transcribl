from __future__ import annotations

import json
from functools import partial
from importlib.resources import files
from typing import Any

from fastapi import FastAPI
from nicegui import events, ui
from nicegui.elements.upload_files import FileUpload

from transcribl.config import ProjectConfig, resolve_workbench_preferences
from transcribl.domain.preferences import WorkbenchPreferences
from transcribl.interfaces.desktop.session import DesktopRequestError, DesktopSession


def asset(name: str) -> str:
    return files("transcribl.interfaces.desktop").joinpath("static", name).read_text("utf-8")


class LanguageField:
    select: ui.select
    custom: ui.input

    def __init__(self, label: str, value: str, choices: list[str]) -> None:
        custom = value not in choices
        with ui.column().classes("w-full gap-1"):
            self.select = (
                ui.select(
                    [*choices, "Custom"],
                    label=label,
                    value="Custom" if custom else value,
                    on_change=lambda: self.custom.set_visibility(self.select.value == "Custom"),
                )
                .props("outlined dense")
                .classes("w-full")
            )
            self.custom = (
                ui.input(f"Custom {label.lower()}", value=value if custom else "")
                .props("outlined dense maxlength=100")
                .classes("w-full")
            )
            self.custom.set_visibility(custom)

    @property
    def value(self) -> str:
        return str(
            self.custom.value if self.select.value == "Custom" else self.select.value
        ).strip()


class Workbench:
    """One window's controls and ephemeral state; never a second canonical dataset."""

    def __init__(
        self, config: ProjectConfig, session: DesktopSession, public: dict[str, Any]
    ) -> None:
        self.preferences = WorkbenchPreferences.model_validate(public["preferences"]["values"])
        config = resolve_workbench_preferences(config, self.preferences)
        self.config = config
        self.settings_revision = public["preferences"]["revision"]
        self.style_prompts = dict(self.preferences.style_prompts)
        self.session = session
        self.public = public
        self.client = ui.context.client
        self.file: FileUpload | None = None
        self.job: dict[str, Any] | None = None
        self.glossaries: list[dict[str, Any]] = []
        self.editing: dict[str, Any] | None = None
        self.rows: list[dict[str, str]] = []
        self.dirty = False
        self.busy = False
        self.glossary_busy = False
        self.polling = False
        self.editor_ready = False
        self.model = config.provider.selected.model
        self.style = self.preferences.default_style
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
                        self.translation_controls()
                    elif name == "Glossaries":
                        self.glossary_controls()
                    elif name == "Settings":
                        self.settings_controls()
                    else:
                        ui.html(asset("editor.html"), sanitize=False).classes("research-editor")
        self.tabs.set_value("Translate")
        ui.on("transcribl-tab", lambda event: self.tabs.set_value(event.args))
        self.timer = ui.timer(config.web.status_poll_interval_ms / 1000, self.poll_job)
        self.client.on_delete(self.close)

    def tab_changed(self, event: events.ValueChangeEventArguments[Any]) -> None:
        for name, section in self.sections.items():
            section.set_visibility(name == event.value)
        if event.value == "Articles" and self.editor_ready:
            ui.run_javascript(
                'window.transcriblEditor.refresh(); window.dispatchEvent(new Event("resize"));'
            )

    async def initialize(self) -> None:
        await self.refresh_glossaries()
        await self.refresh_recoverable()
        await self.client.connected()
        # The only injected HTML/JS is a checked-in component. Document text is
        # populated with textContent by that component, never interpolated here.
        await ui.run_javascript(asset("editor.js"), timeout=20)
        self.editor_ready = True
        job_id = self.client.request.query_params.get("job") if self.client.request else None
        if job_id:
            try:
                self.job = await self.session.request("GET", f"/api/jobs/{job_id}")
                self.render_progress()
                if self.job["status"] in ("ready", "completed"):
                    await self.open_review()
            except DesktopRequestError as exc:
                ui.notify(str(exc), type="negative")

    async def close(self) -> None:
        self.timer.cancel()
        self.file = None
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

    def translation_controls(self) -> None:
        with ui.column().classes("workbench-section"):
            ui.label("Translate PDF").classes("workbench-title-small")
            with ui.card().classes("workbench-card gap-5"):
                self.upload = (
                    ui.upload(
                        label="Choose or drop a PDF",
                        auto_upload=True,
                        max_files=1,
                        max_file_size=self.config.web.max_upload_bytes,
                        on_upload=self.uploaded,
                        on_rejected=lambda: ui.notify(
                            "Choose one PDF within the upload limit.", type="negative"
                        ),
                    )
                    .props('accept=.pdf tabindex=0 aria-label="Choose or drop a PDF"')
                    .classes("workbench-upload")
                )
                # Keep the picker in the browser's user gesture; a Python round trip
                # can lose permission to open it. Let existing uploader buttons work.
                self.upload.on(
                    "click",
                    js_handler=f"""event => {{
                        if (!event.target.closest('button, input, a'))
                            runMethod({self.upload.id}, 'pickFiles', []);
                    }}""",
                )
                self.upload.on(
                    "keydown",
                    js_handler=f"""event => {{
                        if (event.target === event.currentTarget &&
                            ['Enter', ' '].includes(event.key)) {{
                            event.preventDefault();
                            runMethod({self.upload.id}, 'pickFiles', []);
                        }}
                    }}""",
                )
                self.upload.on("removed", self.remove_file)
                self.file_label = ui.label("No PDF selected").classes("workbench-subtle")
                with ui.element("div").classes("workbench-grid"):
                    self.source = LanguageField(
                        "Source language",
                        self.config.translation.source_language,
                        self.config.web.language_choices,
                    )
                    self.target = LanguageField(
                        "Target language",
                        self.config.translation.target_language,
                        self.config.web.language_choices,
                    )
                    self.job_model = ui.select(
                        self.model_options(),
                        value=self.model,
                        label="Model",
                        on_change=self.model_changed,
                    ).props("outlined dense")
                    self.job_style = ui.select(
                        list(self.preferences.style_prompts),
                        value=self.style,
                        label="Style",
                        on_change=self.style_changed,
                    ).props("outlined dense")
                self.glossary_choice = (
                    ui.select({"none": "No glossary"}, value="none", label="Glossary")
                    .props("outlined dense")
                    .classes("w-full")
                )
                self.glossary_choice.disable()
                with ui.expansion("Translation options", icon="tune").classes("w-full"):
                    with ui.element("div").classes("workbench-grid py-3"):
                        self.context_count = ui.number(
                            "Previous pages for continuity",
                            value=self.config.translation.previous_page_context_count,
                            min=0,
                            max=10,
                            step=1,
                            precision=0,
                        ).props("outlined dense")
                        self.dpi = ui.number(
                            "Page image DPI",
                            value=self.config.extraction.image_dpi,
                            min=72,
                            max=600,
                            step=1,
                            precision=0,
                        ).props("outlined dense")
                        level = (
                            self.config.translation.uncertainty_level.value
                            if self.config.translation.mark_uncertain_terms
                            else "off"
                        )
                        self.uncertainty = ui.select(
                            self.config.web.uncertainty_level_choices,
                            value=level,
                            label="Mark uncertain terms",
                        ).props("outlined dense")
                    self.uncertainty_instructions = (
                        ui.textarea(
                            "Uncertainty guidance",
                            value=self.config.translation.uncertainty_instructions or "",
                        )
                        .props(
                            "outlined autogrow "
                            f"maxlength={self.config.web.max_instruction_characters}"
                        )
                        .classes("w-full")
                    )
                    self.uncertainty_instructions.bind_visibility_from(
                        self.uncertainty, "value", backward=lambda v: v != "off"
                    )
                    self.footnotes = (
                        ui.textarea(
                            "Footnote appearance guidance",
                            value=self.config.translation.footnote_appearance_instructions or "",
                        )
                        .props(
                            "outlined autogrow "
                            f"maxlength={self.config.web.max_instruction_characters}"
                        )
                        .classes("w-full")
                    )
                    self.auto_continue = ui.checkbox(
                        "Auto continue", value=self.config.web.auto_continue_default
                    )
                    ui.label(
                        f"Up to {self.config.web.auto_continue_attempts} "
                        "extra attempts per failed page."
                    ).classes("workbench-subtle")
                self.translate_error = ui.label().classes("text-negative").props("role=alert")
                self.start = ui.button(
                    "Translate", icon="translate", on_click=self.start_translation
                )
                ui.label(
                    "The selected provider receives each page image and its extracted text, "
                    "plus the selected number of prior finalized pages. Table pages are "
                    "sent twice. Files and review edits stay local."
                ).classes("workbench-subtle")
            with ui.card().classes("workbench-card") as self.progress_card:
                self.progress_title = ui.label().classes("workbench-title-small")
                self.progress_status = ui.label().props("role=status aria-live=polite")
                self.progress = ui.linear_progress(value=0).classes("w-full")
                self.progress_error = ui.label().classes("text-negative").props("role=alert")
                with ui.row():
                    self.continue_button = ui.button("Continue", on_click=self.continue_job)
                    self.cancel_button = ui.button("Cancel", on_click=self.cancel_job).props("flat")
                    self.review_button = ui.button("Open article", on_click=self.open_review).props(
                        "flat"
                    )
            self.progress_card.set_visibility(False)
            with ui.column().classes("w-full") as self.recoverable_box:
                pass

    async def uploaded(self, event: events.UploadEventArguments) -> None:
        if (
            not event.file.name.lower().endswith(".pdf")
            or event.file.size() > self.config.web.max_upload_bytes
        ):
            ui.notify("Choose a PDF within the upload limit.", type="negative")
            return
        self.file = event.file
        self.file_label.set_text(f"{event.file.name} · {event.file.size() / 1_000_000:.1f} MB")

    def remove_file(self) -> None:
        self.file = None
        self.file_label.set_text("No PDF selected")

    def model_changed(self, event: events.ValueChangeEventArguments[Any]) -> None:
        self.model = str(event.value)

    def style_changed(self, event: events.ValueChangeEventArguments[Any]) -> None:
        self.style = str(event.value)

    async def start_translation(self) -> None:
        if self.busy:
            return
        self.translate_error.set_text("")
        if self.file is None:
            self.translate_error.set_text("Choose a PDF first.")
            return
        if not self.source.value or not self.target.value:
            self.translate_error.set_text("Enter both languages.")
            return
        if self.glossary_busy or not self.glossary_choice.enabled:
            self.translate_error.set_text("Wait for the glossary library to load.")
            return
        selected = next(
            (g for g in self.glossaries if g["glossary_id"] == self.glossary_choice.value), None
        )
        if (
            selected
            and self.editing
            and selected["glossary_id"] == self.editing["glossary_id"]
            and self.dirty
        ):
            self.translate_error.set_text("Save or discard changes to the selected glossary.")
            return
        provider = self.provider_for(self.model)
        key = self.key_for(provider)
        if not key and not self.public["api_keys"][provider]["api_key_configured"]:
            self.translate_error.set_text("Enter an API key in Settings.")
            self.tabs.set_value("Settings")
            return
        self.busy = True
        self.start.disable()
        try:
            settings = {
                "model": self.model,
                "style": self.style,
                "source_language": self.source.value,
                "target_language": self.target.value,
                "previous_page_context_count": self.context_count.value,
                "image_dpi": self.dpi.value,
                "footnote_appearance_instructions": self.footnotes.value,
                "uncertainty_level": self.uncertainty.value,
                "uncertainty_instructions": self.uncertainty_instructions.value,
                "auto_continue": self.auto_continue.value,
            }
            data = {"settings": json.dumps(settings)}
            if selected:
                data.update(
                    glossary_id=selected["glossary_id"], glossary_revision=str(selected["revision"])
                )
            elif self.glossary_choice.value == "none":
                data["glossary_id"] = "none"
            elif self.glossary_choice.value == "configured":
                data["glossary_id"] = "configured"
            if key:
                data["api_key"] = key
            self.job = await self.session.request(
                "POST",
                "/api/jobs",
                data=data,
                files={"pdf": (self.file.name, await self.file.read(), "application/pdf")},
            )
            self.render_progress()
            if key:
                self.session.keys[provider] = key
                self.key_inputs[provider].set_value("")
                self.refresh_key_status(provider)
            self.file = None
            self.upload.reset()
            self.file_label.set_text("No PDF selected")
            ui.run_javascript(f'history.replaceState({{}}, "", "/?job={self.job["job_id"]}")')
        except DesktopRequestError as exc:
            self.translate_error.set_text(str(exc))
        finally:
            self.busy = False
            self.start.enable()

    def render_progress(self) -> None:
        if not self.job:
            self.progress_card.set_visibility(False)
            return
        job = self.job
        self.progress_card.set_visibility(True)
        self.progress_title.set_text(job.get("filename", "Translation"))
        current, total = job.get("current_page", 0), job.get("total_pages")
        self.progress_status.set_text(
            f"{job['status'].replace('_', ' ').title()} · Page {current} / {total or '…'}"
        )
        self.progress.set_value(current / total if total else 0)
        self.progress_error.set_text(job.get("error") or "")
        self.continue_button.set_visibility(job["status"] in ("failed", "cancelled"))
        self.cancel_button.set_visibility(job["status"] == "failed")
        self.review_button.set_visibility(job["status"] in ("ready", "completed"))

    async def poll_job(self) -> None:
        if (
            self.polling
            or not self.job
            or self.job["status"] in ("ready", "completed", "failed", "cancelled")
        ):
            return
        self.polling = True
        try:
            self.job = await self.session.request("GET", f"/api/jobs/{self.job['job_id']}")
            self.render_progress()
            if self.job["status"] in ("ready", "completed"):
                await self.open_review()
        except DesktopRequestError as exc:
            self.progress_error.set_text(str(exc))
        finally:
            self.polling = False

    async def continue_job(self) -> None:
        if not self.job or self.busy:
            return
        self.busy = True
        try:
            provider = self.job.get("provider") or self.provider_for(self.model)
            self.job = await self.session.request(
                "POST",
                f"/api/jobs/{self.job['job_id']}/continue",
                json={"api_key": self.key_for(provider) or None},
            )
            self.render_progress()
            await self.refresh_recoverable()
        except DesktopRequestError as exc:
            self.progress_error.set_text(str(exc))
        finally:
            self.busy = False

    async def cancel_job(self) -> None:
        if not self.job or self.busy:
            return
        try:
            self.job = await self.session.request("POST", f"/api/jobs/{self.job['job_id']}/cancel")
            self.render_progress()
            await self.refresh_recoverable()
        except DesktopRequestError as exc:
            self.progress_error.set_text(str(exc))

    async def refresh_recoverable(self) -> None:
        try:
            payload = await self.session.request("GET", "/api/jobs/recoverable")
            self.recoverable_box.clear()
            with self.recoverable_box:
                for job in payload["jobs"]:
                    ui.button(
                        f"Continue {job['filename']} · page {job.get('current_page', 0)}",
                        on_click=lambda j=job: self.select_stopped(j),
                    ).props("flat")
        except DesktopRequestError as exc:
            ui.notify(str(exc), type="negative")

    def select_stopped(self, job: dict[str, Any]) -> None:
        self.job = job
        self.render_progress()

    async def open_review(self) -> None:
        if self.job and self.editor_ready:
            self.tabs.set_value("Articles")
            await ui.run_javascript(
                f"window.transcriblEditor.open({json.dumps(self.job['job_id'])});", timeout=20
            )

    def settings_controls(self) -> None:
        with ui.column().classes("workbench-section"):
            ui.label("Settings").classes("workbench-title-small")
            with ui.card().classes("workbench-card gap-5"):
                with ui.element("div").classes("workbench-grid"):
                    self.settings_model = ui.select(
                        self.model_options(),
                        value=self.preferences.default_model,
                        label="Default model",
                    ).props("outlined dense")
                    self.settings_style = ui.select(
                        list(self.preferences.style_prompts),
                        value=self.preferences.default_style,
                        label="Default style",
                    ).props("outlined dense")
                self.settings_glossary = (
                    ui.select({"none": "None"}, value="none", label="Default glossary")
                    .props("outlined dense")
                    .classes("w-full")
                )
                self.api_key_controls()
                ui.button("API Keys", icon="key", on_click=self.api_keys_dialog.open)
                with ui.expansion("Advanced settings", icon="tune").classes("w-full"):
                    self.advanced_settings_controls()
                with ui.row():
                    ui.button("Save settings", on_click=self.save_settings)
                    ui.button("Reload saved settings", on_click=self.reload_settings).props("flat")
                self.settings_message = ui.label().props("role=status")

    def advanced_settings_controls(self) -> None:
        self.thinking: dict[str, ui.select] = {}
        with ui.column().classes("w-full gap-4 pt-4"):
            ui.label("Thinking level").classes("text-base font-medium")
            ui.label(
                "Provider default leaves thinking unchanged. "
                "Higher levels can use more time and tokens."
            ).classes("workbench-subtle")
            with ui.element("div").classes("workbench-grid"):
                for provider, choices in self.public["thinking_choices"].items():
                    self.thinking[provider] = ui.select(
                        {
                            level: "Provider default" if level == "default" else level.title()
                            for level in choices
                        },
                        value=self.preferences.thinking_levels[provider],
                        label={
                            "gemini": "Google (Gemini)",
                            "openai": "OpenAI",
                            "anthropic": "Anthropic",
                        }[provider],
                    ).props("outlined dense")
                self.default_context = ui.number(
                    "Default continuity pages",
                    value=self.preferences.previous_page_context_count,
                    min=0,
                    max=10,
                    precision=0,
                ).props("outlined dense")
                self.default_dpi = ui.number(
                    "Default image DPI",
                    value=self.preferences.image_dpi,
                    min=72,
                    max=600,
                    precision=0,
                ).props("outlined dense")
                self.default_uncertainty = ui.select(
                    self.config.web.uncertainty_level_choices,
                    value=self.preferences.uncertainty_level,
                    label="Default uncertainty marking",
                ).props("outlined dense")
            self.default_auto_continue = ui.checkbox(
                "Auto continue by default", value=self.preferences.auto_continue
            )
            ui.separator()
            ui.label("Style instructions").classes("text-base font-medium")
            self.style_editor_choice = (
                ui.select(
                    list(self.style_prompts),
                    value=self.preferences.default_style,
                    label="Edit style",
                    on_change=self.show_style_prompt,
                )
                .props("outlined dense")
                .classes("w-full")
            )
            self.style_prompt = (
                ui.textarea(
                    "Style prompt",
                    value=self.style_prompts[self.preferences.default_style],
                    on_change=self.edit_style_prompt,
                )
                .props(
                    f"outlined rows=5 maxlength={self.config.workbench.max_style_prompt_characters}"
                )
                .classes("w-full")
            )
            with ui.row().classes("w-full items-center"):
                self.new_style_name = (
                    ui.input("New style name").props("outlined dense maxlength=100").classes("grow")
                )
                ui.button("Add style", icon="add", on_click=self.add_style).props("flat")
            with ui.row():
                ui.button("Reset built-in style", on_click=self.reset_style).props("flat")
                ui.button("Delete custom style", on_click=self.delete_style).props(
                    "flat color=negative"
                )
            self.style_message = ui.label().props("role=status")
            with ui.expansion("Translation prompts", icon="description").classes("w-full"):
                ui.label(
                    "Verbatim instructions for both passes. Each request also appends resolved "
                    "settings, the physical page number, prior-page context and complete page "
                    "Markdown. The table pass adds its region targets and first-pass segmentation. "
                    "The page image is sent separately."
                ).classes("workbench-subtle")
                prompts = self.public["prompts"]
                for name, key in (
                    ("Translation", "translation"),
                    ("Table reconstruction", "table"),
                ):
                    ui.textarea(f"{name} · {prompts[key + '_version']}", value=prompts[key]).props(
                        "outlined readonly rows=12"
                    ).classes("w-full font-mono")
                self.prompt_settings = (
                    ui.textarea(
                        "Saved default translation settings",
                        value=json.dumps(self.public["translation"], ensure_ascii=False, indent=2),
                    )
                    .props("outlined readonly rows=8")
                    .classes("w-full font-mono")
                )

    def show_style_prompt(self) -> None:
        if hasattr(self, "style_prompt"):
            self.style_prompt.set_value(self.style_prompts[str(self.style_editor_choice.value)])

    def edit_style_prompt(self) -> None:
        self.style_prompts[str(self.style_editor_choice.value)] = self.style_prompt.value

    def add_style(self) -> None:
        name = self.new_style_name.value.strip()
        if not name or name.casefold() in {s.casefold() for s in self.style_prompts}:
            self.style_message.set_text("Enter a unique style name.")
            return
        if len(self.style_prompts) >= self.config.workbench.max_styles:
            self.style_message.set_text("The style library is full.")
            return
        self.style_prompts[name] = self.style_prompt.value
        self.style_editor_choice.set_options(list(self.style_prompts), value=name)
        self.settings_style.set_options(list(self.style_prompts))
        self.new_style_name.set_value("")
        self.style_message.set_text("Style added. Edit its instructions, then save settings.")

    def reset_style(self) -> None:
        name = str(self.style_editor_choice.value)
        original = self.public["settings_defaults"]["style_prompts"].get(name)
        if original is None:
            self.style_message.set_text("This is a custom style.")
            return
        self.style_prompt.set_value(original)
        self.style_message.set_text("Style reset. Save settings to keep this change.")

    def delete_style(self) -> None:
        name = str(self.style_editor_choice.value)
        if name in {"faithful", "balanced", "readable"}:
            self.style_message.set_text("Built-in styles can be edited or reset.")
            return
        if name == self.settings_style.value:
            self.style_message.set_text("Choose another default style before deleting this one.")
            return
        del self.style_prompts[name]
        self.style_editor_choice.set_options(
            list(self.style_prompts), value=self.settings_style.value
        )
        self.settings_style.set_options(list(self.style_prompts))
        self.style_message.set_text("Style removed. Save settings to keep this change.")

    async def save_settings(self) -> None:
        try:
            values = {
                "default_model": self.settings_model.value,
                "default_style": self.settings_style.value,
                "default_glossary": self.settings_glossary.value,
                "thinking_levels": {p: field.value for p, field in self.thinking.items()},
                "style_prompts": self.style_prompts,
                "previous_page_context_count": self.default_context.value,
                "image_dpi": self.default_dpi.value,
                "uncertainty_level": self.default_uncertainty.value,
                "auto_continue": self.default_auto_continue.value,
            }
            public = await self.session.request(
                "PUT",
                "/api/settings",
                json={"values": values, "expected_revision": self.settings_revision},
            )
            self.apply_saved_settings(public)
            self.settings_message.set_text(
                "Settings saved for new translations. Existing runs are unchanged."
            )
        except DesktopRequestError as exc:
            self.settings_message.set_text(str(exc))

    async def reload_settings(self) -> None:
        try:
            self.apply_saved_settings(await self.session.request("GET", "/api/config"))
            self.settings_message.set_text("Saved settings loaded.")
        except DesktopRequestError as exc:
            self.settings_message.set_text(str(exc))

    def apply_saved_settings(self, public: dict[str, Any]) -> None:
        previous = self.preferences
        self.public = public
        self.preferences = WorkbenchPreferences.model_validate(public["preferences"]["values"])
        self.settings_revision = public["preferences"]["revision"]
        saved = self.preferences
        self.style_prompts = dict(saved.style_prompts)
        self.settings_model.set_value(saved.default_model)
        self.settings_style.set_options(list(self.style_prompts), value=saved.default_style)
        self.style_editor_choice.set_options(list(self.style_prompts), value=saved.default_style)
        self.show_style_prompt()
        self.render_glossary_choices()
        self.settings_glossary.set_value(saved.default_glossary)
        self.default_context.set_value(saved.previous_page_context_count)
        self.default_dpi.set_value(saved.image_dpi)
        self.default_uncertainty.set_value(saved.uncertainty_level)
        self.default_auto_continue.set_value(saved.auto_continue)
        for provider, field in self.thinking.items():
            field.set_value(saved.thinking_levels[provider])
        # Preserve deliberate per-job overrides while advancing untouched defaults.
        updates: list[tuple[Any, object, object]] = [
            (self.job_model, previous.default_model, saved.default_model),
            (self.glossary_choice, previous.default_glossary, saved.default_glossary),
            (
                self.context_count,
                previous.previous_page_context_count,
                saved.previous_page_context_count,
            ),
            (self.dpi, previous.image_dpi, saved.image_dpi),
            (self.uncertainty, previous.uncertainty_level, saved.uncertainty_level),
            (self.auto_continue, previous.auto_continue, saved.auto_continue),
        ]
        for job_field, old, new in updates:
            if job_field.value == old:
                job_field.set_value(new)
        style = (
            self.style
            if self.style in saved.style_prompts and self.style != previous.default_style
            else saved.default_style
        )
        self.job_style.set_options(list(saved.style_prompts), value=style)
        self.prompt_settings.set_value(
            json.dumps(public["translation"], ensure_ascii=False, indent=2)
        )

    def api_key_controls(self) -> None:
        self.key_inputs: dict[str, ui.input] = {}
        self.save_keys: dict[str, ui.checkbox] = {}
        self.key_statuses: dict[str, ui.label] = {}
        self.key_messages: dict[str, ui.label] = {}
        self.clear_keys: dict[str, ui.button] = {}
        company_names = {"gemini": "Google (Gemini)", "openai": "OpenAI", "anthropic": "Anthropic"}
        with (
            ui.dialog() as self.api_keys_dialog,
            ui.card().classes("w-full gap-4").style("max-width: 640px"),
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("API Keys").classes("workbench-title-small")
                ui.button(icon="close", on_click=self.api_keys_dialog.close).props(
                    'flat round aria-label="Close API Keys"'
                )
            ui.label(
                "Unchecked keys last for this window only. Saved keys are never displayed."
            ).classes("workbench-subtle")
            for provider in self.public["api_keys"]:
                ui.separator()
                with ui.column().classes("w-full gap-2"):
                    self.key_inputs[provider] = (
                        ui.input(
                            f"{company_names.get(provider, provider.title())} API key",
                            password=True,
                            password_toggle_button=True,
                        )
                        .props("outlined dense autocomplete=off maxlength=4000")
                        .classes("w-full")
                    )
                    self.key_statuses[provider] = (
                        ui.label().classes("workbench-subtle").props("role=status")
                    )
                    with ui.row().classes("w-full items-center"):
                        self.save_keys[provider] = ui.checkbox(
                            "Save on this computer", value=False
                        ).classes("mr-auto")
                        ui.button("Save key", on_click=partial(self.save_api_key, provider))
                        self.clear_keys[provider] = ui.button(
                            "Clear saved key", on_click=partial(self.clear_api_key, provider)
                        ).props("flat color=negative")
                    self.key_messages[provider] = ui.label().props("role=status")
                    self.refresh_key_status(provider)

    def key_for(self, provider: str) -> str:
        entered = self.key_inputs[provider].value.strip()
        return entered or self.session.keys.get(provider, "")

    def refresh_key_status(self, provider: str) -> None:
        status = self.public["api_keys"][provider]
        message = (
            "Available for this window"
            if self.session.keys.get(provider)
            else "Saved on this computer"
            if status["saved_on_computer"]
            else "Configured in environment"
            if status["api_key_configured"]
            else "No key configured"
        )
        self.key_statuses[provider].set_text(message)
        self.clear_keys[provider].set_visibility(status["saved_on_computer"])

    async def save_api_key(self, provider: str) -> None:
        key, save = self.key_inputs[provider].value.strip(), self.save_keys[provider].value
        if not key:
            self.key_messages[provider].set_text("Enter an API key.")
            return
        try:
            status = await self.session.request(
                "POST",
                "/api/settings/api-key",
                json={"provider": provider, "api_key": key, "save_on_computer": save},
            )
            if save:
                self.session.keys.pop(provider, None)
            else:
                self.session.keys[provider] = key
            self.public["api_keys"][provider] = status
            self.key_inputs[provider].set_value("")
            self.key_messages[provider].set_text(
                "Key saved." if save else "Key available for this window."
            )
            self.refresh_key_status(provider)
        except DesktopRequestError as exc:
            self.key_messages[provider].set_text(str(exc))

    async def clear_api_key(self, provider: str) -> None:
        try:
            self.public["api_keys"][provider] = await self.session.request(
                "DELETE", "/api/settings/api-key", params={"provider": provider}
            )
            self.session.keys.pop(provider, None)
            self.key_inputs[provider].set_value("")
            self.refresh_key_status(provider)
            self.key_messages[provider].set_text("Saved key cleared.")
        except DesktopRequestError as exc:
            self.key_messages[provider].set_text(str(exc))

    def glossary_controls(self) -> None:
        with ui.column().classes("workbench-section"):
            ui.label("Glossaries").classes("workbench-title-small")
            with ui.card().classes("workbench-card gap-4") as self.glossary_card:
                with ui.row().classes("w-full items-center"):
                    self.glossary_select = (
                        ui.select(
                            {"": "New glossary"},
                            value="",
                            label="Edit glossary",
                            on_change=self.change_glossary,
                        )
                        .props("outlined dense")
                        .classes("grow")
                    )
                    ui.button("New", icon="add", on_click=lambda: self.choose_glossary("")).props(
                        "flat"
                    )
                    ui.button("Refresh", icon="refresh", on_click=self.refresh_glossaries).props(
                        "flat"
                    )
                self.glossary_name = (
                    ui.input("Glossary name", on_change=self.mark_dirty)
                    .props(
                        f"outlined dense maxlength={self.config.web.max_glossary_name_characters}"
                    )
                    .classes("w-full")
                )
                self.term_table = (
                    ui.table(
                        columns=[
                            {
                                "name": "source_term",
                                "label": "Source term",
                                "field": "source_term",
                                "align": "left",
                            },
                            {
                                "name": "target_translation",
                                "label": "Required translation",
                                "field": "target_translation",
                                "align": "left",
                            },
                            {"name": "remove", "label": "", "field": "row_id"},
                        ],
                        rows=[],
                        row_key="row_id",
                        pagination=0,
                    )
                    .classes("w-full")
                    .props("flat hide-bottom")
                )
                for field in ("source_term", "target_translation"):
                    self.term_table.add_slot(
                        f"body-cell-{field}",
                        '<q-td :props="props"><q-input dense outlined '
                        f'v-model="props.row.{field}" '
                        f'maxlength="{self.config.web.max_term_characters}" '
                        f'aria-label="{field.replace("_", " ")}" '
                        "@update:model-value=\"value => $parent.$emit('term-edit', "
                        f"{{index: props.row.row_id, field: '{field}', value}})\" /></q-td>",
                    )
                self.term_table.add_slot(
                    "body-cell-remove",
                    '<q-td :props="props"><q-btn flat round icon="delete_outline" '
                    'aria-label="Remove term" '
                    "@click=\"$parent.$emit('term-remove', props.row.row_id)\" /></q-td>",
                )
                self.term_table.on("term-edit", self.edit_term)
                self.term_table.on("term-remove", self.remove_term)

                with ui.row():
                    ui.button("Add term", icon="add", on_click=self.add_term).props("flat")
                    ui.button("Save glossary", on_click=self.save_glossary)
                    self.delete_glossary_button = ui.button(
                        "Delete", on_click=self.delete_glossary
                    ).props("flat color=negative")
                    self.delete_glossary_button.set_visibility(False)
                self.glossary_message = ui.label().props("role=status")

    def set_glossary_busy(self, busy: bool) -> None:
        self.glossary_busy = busy
        if busy:
            self.glossary_card.props("inert")
        else:
            self.glossary_card.props(remove="inert")

    def mark_dirty(self) -> None:
        self.dirty = True
        self.glossary_message.set_text("Unsaved changes")
        ui.run_javascript("window.transcriblGlossaryDirty = true;")

    async def confirm(self, message: str) -> bool:
        with ui.dialog() as dialog, ui.card():
            ui.label(message)
            with ui.row():
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Confirm", on_click=lambda: dialog.submit(True))
        return bool(await dialog)

    async def change_glossary(self, event: events.ValueChangeEventArguments[Any]) -> None:
        expected = self.editing["glossary_id"] if self.editing else ""
        if str(event.value) != expected:
            await self.choose_glossary(str(event.value))

    async def choose_glossary(self, glossary_id: str) -> None:
        if self.dirty and not await self.confirm("Discard unsaved glossary changes?"):
            self.glossary_select.set_value(self.editing["glossary_id"] if self.editing else "")
            return
        self.edit_glossary(glossary_id)

    def edit_glossary(self, glossary_id: str) -> None:
        self.editing = next((g for g in self.glossaries if g["glossary_id"] == glossary_id), None)
        self.rows = [dict(row) for row in self.editing["entries"]] if self.editing else []
        self.glossary_select.set_value(glossary_id if self.editing else "")
        self.glossary_name.set_value(self.editing["name"] if self.editing else "")
        self.render_rows()
        self.dirty = False
        ui.run_javascript("window.transcriblGlossaryDirty = false;")
        self.glossary_message.set_text("")
        self.delete_glossary_button.set_visibility(self.editing is not None)

    def render_rows(self) -> None:
        self.term_table.rows = [{**row, "row_id": index} for index, row in enumerate(self.rows)]
        self.term_table.update()

    def edit_term(self, event: events.GenericEventArguments) -> None:
        index, field = event.args.get("index"), event.args.get("field")
        if (
            isinstance(index, int)
            and 0 <= index < len(self.rows)
            and field in ("source_term", "target_translation")
        ):
            self.rows[index][field] = str(event.args.get("value", ""))
            self.mark_dirty()

    def add_term(self) -> None:
        if len(self.rows) >= self.config.web.max_glossary_entries:
            self.glossary_message.set_text("Glossary entry limit reached.")
            return
        self.rows.append({"source_term": "", "target_translation": ""})
        self.render_rows()
        self.mark_dirty()

    def remove_term(self, event: events.GenericEventArguments) -> None:
        index = event.args
        if isinstance(index, int) and 0 <= index < len(self.rows):
            self.rows.pop(index)
            self.render_rows()
            self.mark_dirty()

    def render_glossary_choices(self) -> None:
        options = {g["glossary_id"]: g["name"] for g in self.glossaries}
        self.glossary_select.set_options({"": "New glossary", **options})
        job_options = {"none": "No glossary"}
        if self.config.translation.glossary:
            job_options["configured"] = "Configured defaults"
        job_options.update(options)
        default = self.preferences.default_glossary
        if default not in job_options:
            job_options[default] = "Deleted glossary — choose another"
        self.glossary_choice.set_options(job_options)
        settings_options = {**job_options, "none": "None"}
        self.settings_glossary.set_options(settings_options)
        if self.glossary_choice.value not in job_options:
            self.glossary_choice.set_value("none")
        self.glossary_choice.enable()

    async def refresh_glossaries(self) -> None:
        if self.glossary_busy:
            return
        if self.dirty and not await self.confirm("Discard unsaved glossary changes?"):
            return
        self.set_glossary_busy(True)
        try:
            first_load = not self.glossary_choice.enabled
            self.glossaries = (await self.session.request("GET", "/api/glossaries"))["glossaries"]
            self.render_glossary_choices()
            if first_load:
                default = self.preferences.default_glossary
                self.settings_glossary.set_value(default)
                if default in self.glossary_choice.options:
                    self.glossary_choice.set_value(default)
            self.edit_glossary(self.editing["glossary_id"] if self.editing else "")
        except DesktopRequestError as exc:
            self.glossary_message.set_text(str(exc))
        finally:
            self.set_glossary_busy(False)

    async def save_glossary(self) -> None:
        if self.glossary_busy:
            return
        self.set_glossary_busy(True)
        try:
            glossary_id = self.editing["glossary_id"] if self.editing else None
            saved = await self.session.request(
                "PUT" if glossary_id else "POST",
                f"/api/glossaries/{glossary_id}" if glossary_id else "/api/glossaries",
                json={
                    "name": self.glossary_name.value,
                    "entries": self.rows,
                    "expected_revision": self.editing["revision"] if self.editing else None,
                },
            )
            self.glossaries = sorted(
                [g for g in self.glossaries if g["glossary_id"] != saved["glossary_id"]] + [saved],
                key=lambda g: g["name"].casefold(),
            )
            self.render_glossary_choices()
            self.edit_glossary(saved["glossary_id"])
            if glossary_id is None:
                self.glossary_choice.set_value(saved["glossary_id"])
            self.glossary_message.set_text("Glossary saved.")
        except DesktopRequestError as exc:
            self.glossary_message.set_text(str(exc))
        finally:
            self.set_glossary_busy(False)

    async def delete_glossary(self) -> None:
        if not self.editing or self.glossary_busy:
            return
        selected = dict(self.editing)
        if not await self.confirm(
            "Delete this glossary? Existing translations keep their original terms."
        ):
            return
        self.set_glossary_busy(True)
        try:
            await self.session.request(
                "DELETE",
                f"/api/glossaries/{selected['glossary_id']}",
                params={"expected_revision": selected["revision"]},
            )
            self.glossaries = [
                g for g in self.glossaries if g["glossary_id"] != selected["glossary_id"]
            ]
            self.edit_glossary("")
            self.render_glossary_choices()
            self.glossary_message.set_text("Glossary deleted.")
        except DesktopRequestError as exc:
            self.glossary_message.set_text(str(exc))
        finally:
            self.set_glossary_busy(False)


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
