from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import events, ui

from transcribl.domain.languages import same_language
from transcribl.interfaces.desktop.session import DesktopRequestError
from transcribl.interfaces.desktop.widgets import LanguageField

if TYPE_CHECKING:
    from transcribl.interfaces.desktop.workbench import Workbench


class GlossariesPanel:
    """Glossaries controls and state for one desktop window."""

    def __init__(self, workbench: Workbench) -> None:
        self.workbench = workbench
        self.glossaries: list[dict[str, Any]] = []
        self.editing: dict[str, Any] | None = None
        self.rows: list[dict[str, str]] = []
        self.dirty = False
        self.glossary_busy = False

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
                        "outlined dense "
                        f"maxlength={self.workbench.config.web.max_glossary_name_characters}"
                    )
                    .classes("w-full")
                )
                self.glossary_language = LanguageField(
                    "Glossary source language",
                    self.workbench.translation.source.value,
                    self.workbench.config.web.language_choices,
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
                        f'maxlength="{self.workbench.config.web.max_term_characters}" '
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
                self.glossary_language.select.on_value_change(self.mark_dirty)
                self.glossary_language.custom.on_value_change(self.mark_dirty)

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

    async def change_glossary(self, event: events.ValueChangeEventArguments[Any]) -> None:
        expected = self.editing["glossary_id"] if self.editing else ""
        if str(event.value) != expected:
            await self.choose_glossary(str(event.value))

    async def choose_glossary(self, glossary_id: str) -> None:
        if self.dirty and not await self.workbench.confirm("Discard unsaved glossary changes?"):
            self.glossary_select.set_value(self.editing["glossary_id"] if self.editing else "")
            return
        self.edit_glossary(glossary_id)

    def edit_glossary(self, glossary_id: str) -> None:
        self.editing = next((g for g in self.glossaries if g["glossary_id"] == glossary_id), None)
        self.rows = [dict(row) for row in self.editing["entries"]] if self.editing else []
        self.glossary_select.set_value(glossary_id if self.editing else "")
        self.glossary_name.set_value(self.editing["name"] if self.editing else "")
        self.glossary_language.set_value(
            (self.editing.get("source_language") or "")
            if self.editing
            else self.workbench.translation.source.value
        )
        self.render_rows()
        self.dirty = False
        ui.run_javascript("window.transcriblGlossaryDirty = false;")
        self.glossary_message.set_text(
            "Assign a source language before using this glossary."
            if self.editing and not self.editing.get("source_language")
            else ""
        )
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
        if len(self.rows) >= self.workbench.config.web.max_glossary_entries:
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
        labels = {
            g["glossary_id"]: f"{g['name']} · {g.get('source_language') or 'Language not assigned'}"
            for g in self.glossaries
        }
        self.glossary_select.set_options({"": "New glossary", **labels})
        source = self.workbench.translation.source.value
        options = {"none": "No glossary"}
        configured = self.workbench.config.translation
        if configured.glossary and same_language(configured.source_language, source):
            options["configured"] = "Configured defaults"
        options.update(
            {
                g["glossary_id"]: labels[g["glossary_id"]]
                for g in self.glossaries
                if same_language(g.get("source_language"), source)
            }
        )
        choice = self.workbench.translation.glossary_choice
        value = choice.value if choice.value in options else "none"
        choice.set_options(options, value=value)
        choice.enable()
        settings_options = {
            "none": "None",
            **{
                g["glossary_id"]: labels[g["glossary_id"]]
                for g in self.glossaries
                if g.get("source_language")
            },
        }
        if configured.glossary:
            settings_options["configured"] = f"Configured defaults · {configured.source_language}"
        default = self.workbench.preferences.default_glossary
        if default not in settings_options:
            settings_options[default] = "Unavailable glossary — choose another"
        self.workbench.settings.settings_glossary.set_options(settings_options)

    async def refresh_glossaries(self) -> None:
        if self.glossary_busy:
            return
        if self.dirty and not await self.workbench.confirm("Discard unsaved glossary changes?"):
            return
        self.set_glossary_busy(True)
        try:
            first_load = not self.workbench.translation.glossary_choice.enabled
            self.glossaries = (await self.workbench.session.request("GET", "/api/glossaries"))[
                "glossaries"
            ]
            self.render_glossary_choices()
            if first_load:
                default = self.workbench.preferences.default_glossary
                self.workbench.settings.settings_glossary.set_value(default)
                if default in self.workbench.translation.glossary_choice.options:
                    self.workbench.translation.glossary_choice.set_value(default)
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
            saved = await self.workbench.session.request(
                "PUT" if glossary_id else "POST",
                f"/api/glossaries/{glossary_id}" if glossary_id else "/api/glossaries",
                json={
                    "name": self.glossary_name.value,
                    "source_language": self.glossary_language.value,
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
            if (
                glossary_id is None
                and saved["glossary_id"] in self.workbench.translation.glossary_choice.options
            ):
                self.workbench.translation.glossary_choice.set_value(saved["glossary_id"])
            self.glossary_message.set_text("Glossary saved.")
        except DesktopRequestError as exc:
            self.glossary_message.set_text(str(exc))
        finally:
            self.set_glossary_busy(False)

    async def delete_glossary(self) -> None:
        if not self.editing or self.glossary_busy:
            return
        selected = dict(self.editing)
        if not await self.workbench.confirm(
            "Delete this glossary? Existing translations keep their original terms."
        ):
            return
        self.set_glossary_busy(True)
        try:
            await self.workbench.session.request(
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
