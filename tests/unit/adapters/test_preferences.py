import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from transcribl.adapters.storage.preferences import FilesystemPreferencesRepository
from transcribl.config import load_project_config, resolve_workbench_preferences, workbench_defaults
from transcribl.domain.preferences import (
    PreferencesConflictError,
    PreferencesStorageError,
    WorkbenchPreferences,
)


def test_preferences_round_trip_conflicts_and_immutable_config(tmp_path: Path) -> None:
    config = load_project_config(Path("config/default.toml"))
    original = config.model_dump_json()
    values = workbench_defaults(config)
    values.default_model = "gpt-6-luna"
    values.default_style = "Historical Danish"
    values.style_prompts[values.default_style] = (
        'Preserve “æøå” and \\ notation.\nKeep "quoted" words.'
    )
    values.thinking_levels["openai"] = "high"
    repository = FilesystemPreferencesRepository(tmp_path)
    assert repository.load(values).revision == 0
    saved = repository.save(values, expected_revision=0)
    assert saved.revision == 1
    assert FilesystemPreferencesRepository(tmp_path).load(workbench_defaults(config)) == saved
    assert (
        tomllib.loads(repository.path.read_text())["values"]["style_prompts"]
        == values.style_prompts
    )
    assert WorkbenchPreferences.model_validate_json(values.model_dump_json()) == values
    with pytest.raises(PreferencesConflictError):
        repository.save(values, expected_revision=0)
    resolved = resolve_workbench_preferences(config, values)
    assert resolved.provider.openai.thinking_level == "high"
    assert resolved.translation.style.value == "custom"
    assert resolved.translation.style_prompt == values.style_prompts[values.default_style]
    assert config.model_dump_json() == original
    assert list(tmp_path.iterdir()) == [repository.path]


@pytest.mark.parametrize(
    "invalid",
    [
        {"default_style": "Missing"},
        {"thinking_levels": {"openai": "high"}},
        {"api_key": "never-store-secrets"},
        {"previous_page_context_count": 11},
        {"image_dpi": 601},
    ],
)
def test_preferences_reject_invalid_values(invalid: dict[str, object]) -> None:
    config = load_project_config(Path("config/default.toml"))
    data = workbench_defaults(config).model_dump()
    with pytest.raises(ValidationError):
        WorkbenchPreferences.model_validate({**data, **invalid})


def test_preferences_reject_unsupported_models_levels_and_corrupt_files(tmp_path: Path) -> None:
    config = load_project_config(Path("config/default.toml"))
    values = workbench_defaults(config)
    values.default_model = "gemini-3.5-flash"
    with pytest.raises(ValueError, match="allowed"):
        resolve_workbench_preferences(config, values)
    values.default_model = config.provider.selected.model
    values.thinking_levels["gemini"] = "max"
    with pytest.raises(ValueError, match="thinking"):
        resolve_workbench_preferences(config, values)
    repository = FilesystemPreferencesRepository(tmp_path)
    repository.path.write_text("broken = [")
    with pytest.raises(PreferencesStorageError):
        repository.load(values)
    assert repository.path.read_text() == "broken = ["
