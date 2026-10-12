from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nicegui import ui

from transcribl.domain.preferences import WorkbenchPreferences
from transcribl.domain.providers import PROVIDER_LABELS
from transcribl.interfaces.desktop.session import DesktopRequestError

if TYPE_CHECKING:
    from transcribl.interfaces.desktop.workbench import Workbench


class SettingsPanel:
    """Settings controls and state for one desktop window."""

    def __init__(self, workbench: Workbench) -> None:
        self.workbench = workbench
        self.settings_revision = workbench.public["preferences"]["revision"]
        self.style_prompts = dict(self.workbench.preferences.style_prompts)

    def settings_controls(self) -> None:
        with ui.column().classes("workbench-section"):
            ui.label("Settings").classes("workbench-title-small")
            with ui.card().classes("workbench-card gap-5"):
                with ui.element("div").classes("workbench-grid"):
                    self.settings_model = ui.select(
                        self.workbench.model_options(),
                        value=self.workbench.preferences.default_model,
                        label="Default model",
                    ).props("outlined dense")
                    self.settings_style = ui.select(
                        list(self.workbench.preferences.style_prompts),
                        value=self.workbench.preferences.default_style,
                        label="Default style",
                    ).props("outlined dense")
                self.settings_glossary = (
                    ui.select({"none": "None"}, value="none", label="Default glossary")
                    .props("outlined dense")
                    .classes("w-full")
                )
                self.currency = (
                    ui.select(
                        self.workbench.public["currency_choices"],
                        value=self.workbench.preferences.currency,
                        label="Price currency",
                    )
                    .props("outlined dense")
                    .classes("w-full")
                )
                ui.label(
                    "Reference exchange rates: "
                    f"{self.workbench.public['exchange_rates']['checked_on']}"
                ).classes("workbench-subtle")
                self.workbench.credentials.api_key_controls()
                ui.button(
                    "API Keys", icon="key", on_click=self.workbench.credentials.api_keys_dialog.open
                )
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
                for provider, choices in self.workbench.public["thinking_choices"].items():
                    self.thinking[provider] = ui.select(
                        {
                            level: "Provider default" if level == "default" else level.title()
                            for level in choices
                        },
                        value=self.workbench.preferences.thinking_levels[provider],
                        label=PROVIDER_LABELS[provider],
                    ).props("outlined dense")
                self.default_context = ui.number(
                    "Default continuity pages",
                    value=self.workbench.preferences.previous_page_context_count,
                    min=0,
                    max=10,
                    precision=0,
                ).props("outlined dense")
                self.default_dpi = ui.number(
                    "Default image DPI",
                    value=self.workbench.preferences.image_dpi,
                    min=72,
                    max=600,
                    precision=0,
                ).props("outlined dense")
                self.default_uncertainty = ui.select(
                    self.workbench.config.web.uncertainty_level_choices,
                    value=self.workbench.preferences.uncertainty_level,
                    label="Default uncertainty marking",
                ).props("outlined dense")
            self.default_auto_continue = ui.checkbox(
                "Auto continue by default", value=self.workbench.preferences.auto_continue
            )
            ui.separator()
            ui.label("Style instructions").classes("text-base font-medium")
            self.style_editor_choice = (
                ui.select(
                    list(self.style_prompts),
                    value=self.workbench.preferences.default_style,
                    label="Edit style",
                    on_change=self.show_style_prompt,
                )
                .props("outlined dense")
                .classes("w-full")
            )
            self.style_prompt = (
                ui.textarea(
                    "Style prompt",
                    value=self.style_prompts[self.workbench.preferences.default_style],
                    on_change=self.edit_style_prompt,
                )
                .props(
                    "outlined rows=5 "
                    f"maxlength={self.workbench.config.workbench.max_style_prompt_characters}"
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
                prompts = self.workbench.public["prompts"]
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
                        value=json.dumps(
                            self.workbench.public["translation"], ensure_ascii=False, indent=2
                        ),
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
        if len(self.style_prompts) >= self.workbench.config.workbench.max_styles:
            self.style_message.set_text("The style library is full.")
            return
        self.style_prompts[name] = self.style_prompt.value
        self.style_editor_choice.set_options(list(self.style_prompts), value=name)
        self.settings_style.set_options(list(self.style_prompts))
        self.new_style_name.set_value("")
        self.style_message.set_text("Style added. Edit its instructions, then save settings.")

    def reset_style(self) -> None:
        name = str(self.style_editor_choice.value)
        original = self.workbench.public["settings_defaults"]["style_prompts"].get(name)
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
                "currency": self.currency.value,
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
            public = await self.workbench.session.request(
                "PUT",
                "/api/settings",
                json={"values": values, "expected_revision": self.settings_revision},
            )
            self.apply_saved_settings(public)
            await self.refresh_prices()
            self.settings_message.set_text(
                "Settings saved. Prices updated; translation defaults apply to new runs."
            )
        except DesktopRequestError as exc:
            self.settings_message.set_text(str(exc))

    async def reload_settings(self) -> None:
        try:
            self.apply_saved_settings(await self.workbench.session.request("GET", "/api/config"))
            await self.refresh_prices()
            self.settings_message.set_text("Saved settings loaded.")
        except DesktopRequestError as exc:
            self.settings_message.set_text(str(exc))

    async def refresh_prices(self) -> None:
        translation = self.workbench.translation
        await translation.refresh_estimate()
        if translation.job and translation.job.get("cost"):
            translation.job = await self.workbench.session.request(
                "GET", f"/api/jobs/{translation.job['job_id']}"
            )
            translation.render_progress()
        if self.workbench.editor_ready:
            await ui.run_javascript("window.transcriblEditor.refreshCosts()")

    def apply_saved_settings(self, public: dict[str, Any]) -> None:
        previous = self.workbench.preferences
        self.workbench.public = public
        self.workbench.preferences = WorkbenchPreferences.model_validate(
            public["preferences"]["values"]
        )
        self.settings_revision = public["preferences"]["revision"]
        saved = self.workbench.preferences
        self.style_prompts = dict(saved.style_prompts)
        self.currency.set_value(saved.currency)
        self.settings_model.set_value(saved.default_model)
        self.settings_style.set_options(list(self.style_prompts), value=saved.default_style)
        self.style_editor_choice.set_options(list(self.style_prompts), value=saved.default_style)
        self.show_style_prompt()
        self.workbench.glossaries.render_glossary_choices()
        self.settings_glossary.set_value(saved.default_glossary)
        self.default_context.set_value(saved.previous_page_context_count)
        self.default_dpi.set_value(saved.image_dpi)
        self.default_uncertainty.set_value(saved.uncertainty_level)
        self.default_auto_continue.set_value(saved.auto_continue)
        for provider, field in self.thinking.items():
            field.set_value(saved.thinking_levels[provider])
        # Preserve deliberate per-job overrides while advancing untouched defaults.
        updates: list[tuple[Any, object, object]] = [
            (self.workbench.translation.job_model, previous.default_model, saved.default_model),
            (
                self.workbench.translation.glossary_choice,
                previous.default_glossary,
                saved.default_glossary,
            ),
            (
                self.workbench.translation.context_count,
                previous.previous_page_context_count,
                saved.previous_page_context_count,
            ),
            (self.workbench.translation.dpi, previous.image_dpi, saved.image_dpi),
            (
                self.workbench.translation.uncertainty,
                previous.uncertainty_level,
                saved.uncertainty_level,
            ),
            (self.workbench.translation.auto_continue, previous.auto_continue, saved.auto_continue),
        ]
        for job_field, old, new in updates:
            if job_field.value == old and (
                job_field is not self.workbench.translation.glossary_choice
                or new in job_field.options
            ):
                job_field.set_value(new)
        style = (
            self.workbench.translation.style
            if self.workbench.translation.style in saved.style_prompts
            and self.workbench.translation.style != previous.default_style
            else saved.default_style
        )
        self.workbench.translation.job_style.set_options(list(saved.style_prompts), value=style)
        self.prompt_settings.set_value(
            json.dumps(public["translation"], ensure_ascii=False, indent=2)
        )
