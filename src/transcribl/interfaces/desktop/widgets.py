from nicegui import ui


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

    def set_value(self, value: str) -> None:
        custom = value not in self.select.options or value == "Custom"
        self.custom.set_value(value if custom else "")
        self.select.set_value("Custom" if custom else value)
        self.custom.set_visibility(custom)

    @property
    def value(self) -> str:
        return str(
            self.custom.value if self.select.value == "Custom" else self.select.value
        ).strip()
