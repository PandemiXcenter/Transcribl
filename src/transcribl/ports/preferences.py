from typing import Protocol

from transcribl.domain.preferences import SavedPreferences, WorkbenchPreferences


class PreferencesRepository(Protocol):
    def load(self, defaults: WorkbenchPreferences) -> SavedPreferences: ...

    def save(self, values: WorkbenchPreferences, *, expected_revision: int) -> SavedPreferences: ...
