from transcribl.config import ProjectConfig, resolve_workbench_preferences, workbench_defaults
from transcribl.domain.preferences import SavedPreferences, WorkbenchPreferences
from transcribl.ports.preferences import PreferencesRepository


class WorkbenchSettingsService:
    def __init__(self, config: ProjectConfig, repository: PreferencesRepository) -> None:
        self.config = config
        self.repository = repository

    def read(self) -> SavedPreferences:
        saved = self.repository.load(workbench_defaults(self.config))
        resolve_workbench_preferences(self.config, saved.values)
        return saved

    def save(self, values: WorkbenchPreferences, *, expected_revision: int) -> SavedPreferences:
        resolve_workbench_preferences(self.config, values)
        return self.repository.save(values, expected_revision=expected_revision)

    def resolved(self) -> ProjectConfig:
        return resolve_workbench_preferences(self.config, self.read().values)
