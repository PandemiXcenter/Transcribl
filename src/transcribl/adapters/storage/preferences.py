"""Atomic TOML persistence for a small, strictly validated non-secret settings file."""

import json
import os
import tomllib
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from transcribl.domain.preferences import (
    PreferencesConflictError,
    PreferencesStorageError,
    SavedPreferences,
    WorkbenchPreferences,
)

_LOCK = RLock()


class FilesystemPreferencesRepository:
    def __init__(self, root: Path) -> None:
        self.path = root / ".settings.toml"

    def load(self, defaults: WorkbenchPreferences) -> SavedPreferences:
        with _LOCK:
            try:
                if not self.path.exists():
                    return SavedPreferences(revision=0, values=defaults)
                return SavedPreferences.model_validate(tomllib.loads(self.path.read_text("utf-8")))
            except (OSError, ValueError):
                raise PreferencesStorageError("Local settings are unavailable or invalid") from None

    def save(self, values: WorkbenchPreferences, *, expected_revision: int) -> SavedPreferences:
        with _LOCK:
            current = self.load(values)
            if current.revision != expected_revision:
                raise PreferencesConflictError("Settings changed; reload before saving")
            saved = SavedPreferences(revision=current.revision + 1, values=values)
            # The strict model contains only strings, integers, booleans and string
            # dictionaries. JSON string escaping is also valid for TOML basic strings.
            lines = [f"revision = {saved.revision}", "", "[values]"]
            scalars = values.model_dump(exclude={"style_prompts", "thinking_levels"})
            lines.extend(
                f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in scalars.items()
            )
            for field in ("style_prompts", "thinking_levels"):
                lines.extend(["", f"[values.{field}]"])
                lines.extend(
                    f"{json.dumps(key, ensure_ascii=False)} = "
                    f"{json.dumps(value, ensure_ascii=False)}"
                    for key, value in getattr(values, field).items()
                )
            temporary: Path | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False
                ) as handle:
                    temporary = Path(handle.name)
                    handle.write("\n".join(lines) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(self.path)
                return saved
            except OSError:
                raise PreferencesStorageError("Local settings could not be saved") from None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
