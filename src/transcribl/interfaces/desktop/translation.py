from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nicegui import background_tasks, events, ui
from nicegui.elements.upload_files import FileUpload

from transcribl.interfaces.desktop.session import DesktopRequestError
from transcribl.interfaces.desktop.widgets import LanguageField

if TYPE_CHECKING:
    from transcribl.interfaces.desktop.workbench import Workbench


class TranslationPanel:
    """Translation controls and state for one desktop window."""

    def __init__(self, workbench: Workbench) -> None:
        self.workbench = workbench
        self.file: FileUpload | None = None
        self.pdf_page_count: int | None = None
        self.estimate_generation = 0
        self.job: dict[str, Any] | None = None
        self.busy = False
        self.polling = False
        self.model = workbench.config.provider.selected.model
        self.style = self.workbench.preferences.default_style

    def translation_controls(self) -> None:
        with ui.column().classes("workbench-section"):
            ui.label("Translate PDF").classes("workbench-title-small")
            with ui.card().classes("workbench-card gap-5"):
                self.upload = (
                    ui.upload(
                        label="Choose or drop a PDF",
                        auto_upload=True,
                        max_files=1,
                        max_file_size=self.workbench.config.web.max_upload_bytes,
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
                        self.workbench.config.translation.source_language,
                        self.workbench.config.web.language_choices,
                    )
                    self.target = LanguageField(
                        "Target language",
                        self.workbench.config.translation.target_language,
                        self.workbench.config.web.language_choices,
                    )
                    self.job_model = ui.select(
                        self.workbench.model_options(),
                        value=self.model,
                        label="Model",
                        on_change=self.model_changed,
                    ).props("outlined dense")
                    self.job_style = ui.select(
                        list(self.workbench.preferences.style_prompts),
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
                            value=self.workbench.config.translation.previous_page_context_count,
                            min=0,
                            max=10,
                            step=1,
                            precision=0,
                        ).props("outlined dense")
                        self.dpi = ui.number(
                            "Page image DPI",
                            value=self.workbench.config.extraction.image_dpi,
                            min=72,
                            max=600,
                            step=1,
                            precision=0,
                        ).props("outlined dense")
                        level = (
                            self.workbench.config.translation.uncertainty_level.value
                            if self.workbench.config.translation.mark_uncertain_terms
                            else "off"
                        )
                        self.uncertainty = ui.select(
                            self.workbench.config.web.uncertainty_level_choices,
                            value=level,
                            label="Mark uncertain terms",
                        ).props("outlined dense")
                    self.uncertainty_instructions = (
                        ui.textarea(
                            "Uncertainty guidance",
                            value=self.workbench.config.translation.uncertainty_instructions or "",
                        )
                        .props(
                            "outlined autogrow "
                            f"maxlength={self.workbench.config.web.max_instruction_characters}"
                        )
                        .classes("w-full")
                    )
                    self.uncertainty_instructions.bind_visibility_from(
                        self.uncertainty, "value", backward=lambda v: v != "off"
                    )
                    self.footnotes = (
                        ui.textarea(
                            "Footnote appearance guidance",
                            value=self.workbench.config.translation.footnote_appearance_instructions
                            or "",
                        )
                        .props(
                            "outlined autogrow "
                            f"maxlength={self.workbench.config.web.max_instruction_characters}"
                        )
                        .classes("w-full")
                    )
                    self.auto_continue = ui.checkbox(
                        "Auto continue", value=self.workbench.config.web.auto_continue_default
                    )
                    ui.label(
                        f"Up to {self.workbench.config.web.auto_continue_attempts} "
                        "extra attempts per failed page."
                    ).classes("workbench-subtle")
                self.translate_error = ui.label().classes("text-negative").props("role=alert")
                self.estimate_label = ui.label().props("role=status aria-live=polite")
                with ui.expansion("Cost details", icon="payments").classes(
                    "w-full"
                ) as self.cost_details:
                    self.estimate_details = ui.label().classes(
                        "workbench-subtle whitespace-pre-line"
                    )
                self.cost_details.set_visibility(False)
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
                self.progress_cost = ui.label().classes("workbench-subtle")
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
            or event.file.size() > self.workbench.config.web.max_upload_bytes
        ):
            ui.notify("Choose a PDF within the upload limit.", type="negative")
            return
        self.file = event.file
        self.pdf_page_count = None
        self.estimate_generation += 1
        self.estimate_label.set_text("Counting pages…")
        self.cost_details.set_visibility(False)
        self.start.disable()
        self.file_label.set_text(f"{event.file.name} · {event.file.size() / 1_000_000:.1f} MB")
        try:
            info = await self.workbench.session.request(
                "POST",
                "/api/pdf-info",
                files={"pdf": (event.file.name, await event.file.read(), "application/pdf")},
            )
            if self.file is not event.file:
                return
            self.pdf_page_count = info["page_count"]
            await self.refresh_estimate()
        except DesktopRequestError as exc:
            if self.file is event.file:
                self.estimate_label.set_text(f"Estimate unavailable: {exc}")
        finally:
            if self.file is event.file and not self.busy:
                self.start.enable()

    def remove_file(self) -> None:
        self.file = None
        self.pdf_page_count = None
        self.estimate_generation += 1
        self.estimate_label.set_text("")
        self.cost_details.set_visibility(False)
        if not self.busy:
            self.start.enable()
        self.file_label.set_text("No PDF selected")

    def model_changed(self, event: events.ValueChangeEventArguments[Any]) -> None:
        self.model = str(event.value)
        if self.pdf_page_count is not None:
            background_tasks.create(self.refresh_estimate())

    async def refresh_estimate(self) -> None:
        self.estimate_generation += 1
        generation = self.estimate_generation
        if self.pdf_page_count is None:
            return
        self.estimate_label.set_text("Estimating cost…")
        self.cost_details.set_visibility(False)
        try:
            cost = await self.workbench.session.request(
                "GET",
                "/api/cost-estimate",
                params={"model": self.model, "page_count": self.pdf_page_count},
            )
            if generation != self.estimate_generation:
                return
            total = cost.get("total")
            if total is None:
                self.estimate_label.set_text(f"Cost estimate unavailable · {cost['basis']}")
                return
            self.estimate_label.set_text(
                f"Estimated cost ≈ {total:.4f} {cost['currency']} · {self.pdf_page_count} pages "
                f"at {cost['per_page']:.4f} {cost['currency']}/page"
            )
            self.estimate_details.set_text(
                f"Based on {cost['sample_pages']} completed pages ({cost['basis']}).\n"
                f"Estimated tokens: {cost['input_tokens']:,.0f} input · "
                f"{cost['output_tokens']:,.0f} output.\n"
                f"Prices checked: {', '.join(cost['pricing_checked_on'])}.\n"
                + "\n".join(cost["notes"])
                + "\n"
                + "\n".join(cost["sources"])
            )
            self.cost_details.set_visibility(True)
        except DesktopRequestError as exc:
            if generation == self.estimate_generation:
                self.estimate_label.set_text(f"Cost estimate unavailable: {exc}")

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
        if self.workbench.glossaries.glossary_busy or not self.glossary_choice.enabled:
            self.translate_error.set_text("Wait for the glossary library to load.")
            return
        selected = next(
            (
                g
                for g in self.workbench.glossaries.glossaries
                if g["glossary_id"] == self.glossary_choice.value
            ),
            None,
        )
        if (
            selected
            and self.workbench.glossaries.editing
            and selected["glossary_id"] == self.workbench.glossaries.editing["glossary_id"]
            and self.workbench.glossaries.dirty
        ):
            self.translate_error.set_text("Save or discard changes to the selected glossary.")
            return
        provider = self.workbench.provider_for(self.model)
        key = self.workbench.credentials.key_for(provider)
        if not key and not self.workbench.public["api_keys"][provider]["api_key_configured"]:
            self.translate_error.set_text("Enter an API key in Settings.")
            self.workbench.tabs.set_value("Settings")
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
            self.job = await self.workbench.session.request(
                "POST",
                "/api/jobs",
                data=data,
                files={"pdf": (self.file.name, await self.file.read(), "application/pdf")},
            )
            self.render_progress()
            if key:
                self.workbench.session.keys[provider] = key
                self.workbench.credentials.key_inputs[provider].set_value("")
                self.workbench.credentials.refresh_key_status(provider)
            self.remove_file()
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
        cost = job.get("cost")
        self.progress_cost.set_text(
            f"Recorded cost ≈ {cost['total']:.4f} {cost['currency']} (approximate)"
            if cost and cost.get("total") is not None
            else "Recorded cost unavailable"
            if cost
            else ""
        )
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
            self.job = await self.workbench.session.request(
                "GET", f"/api/jobs/{self.job['job_id']}"
            )
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
            provider = self.job.get("provider") or self.workbench.provider_for(self.model)
            self.job = await self.workbench.session.request(
                "POST",
                f"/api/jobs/{self.job['job_id']}/continue",
                json={"api_key": self.workbench.credentials.key_for(provider) or None},
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
            self.job = await self.workbench.session.request(
                "POST", f"/api/jobs/{self.job['job_id']}/cancel"
            )
            self.render_progress()
            await self.refresh_recoverable()
        except DesktopRequestError as exc:
            self.progress_error.set_text(str(exc))

    async def refresh_recoverable(self) -> None:
        try:
            payload = await self.workbench.session.request("GET", "/api/jobs/recoverable")
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
        if self.job and self.workbench.editor_ready:
            self.workbench.tabs.set_value("Articles")
            await ui.run_javascript(
                f"window.transcriblEditor.open({json.dumps(self.job['job_id'])});", timeout=20
            )
