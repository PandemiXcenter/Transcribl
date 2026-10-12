from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from nicegui import ui

from transcribl.domain.providers import PROVIDER_LABELS
from transcribl.interfaces.desktop.session import DesktopRequestError

if TYPE_CHECKING:
    from transcribl.interfaces.desktop.workbench import Workbench


class ApiKeysDialog:
    """Credentials controls and state for one desktop window."""

    def __init__(self, workbench: Workbench) -> None:
        self.workbench = workbench

    def api_key_controls(self) -> None:
        self.key_inputs: dict[str, ui.input] = {}
        self.save_keys: dict[str, ui.checkbox] = {}
        self.key_statuses: dict[str, ui.label] = {}
        self.key_messages: dict[str, ui.label] = {}
        self.clear_keys: dict[str, ui.button] = {}
        company_names = PROVIDER_LABELS
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
            for provider in self.workbench.public["api_keys"]:
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
        return entered or self.workbench.session.keys.get(provider, "")

    def refresh_key_status(self, provider: str) -> None:
        status = self.workbench.public["api_keys"][provider]
        message = (
            "Available for this window"
            if self.workbench.session.keys.get(provider)
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
            status = await self.workbench.session.request(
                "POST",
                "/api/settings/api-key",
                json={"provider": provider, "api_key": key, "save_on_computer": save},
            )
            if save:
                self.workbench.session.keys.pop(provider, None)
            else:
                self.workbench.session.keys[provider] = key
            self.workbench.public["api_keys"][provider] = status
            self.key_inputs[provider].set_value("")
            self.key_messages[provider].set_text(
                "Key saved." if save else "Key available for this window."
            )
            self.refresh_key_status(provider)
        except DesktopRequestError as exc:
            self.key_messages[provider].set_text(str(exc))

    async def clear_api_key(self, provider: str) -> None:
        try:
            self.workbench.public["api_keys"][provider] = await self.workbench.session.request(
                "DELETE", "/api/settings/api-key", params={"provider": provider}
            )
            self.workbench.session.keys.pop(provider, None)
            self.key_inputs[provider].set_value("")
            self.refresh_key_status(provider)
            self.key_messages[provider].set_text("Saved key cleared.")
        except DesktopRequestError as exc:
            self.key_messages[provider].set_text(str(exc))
