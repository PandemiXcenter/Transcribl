from pathlib import Path
from tomllib import TOMLDecodeError, load

from pydantic import ValidationError

from transcribl.config.preferences import resolve_workbench_preferences, workbench_defaults
from transcribl.config.project import ProjectConfig
from transcribl.domain.errors import ConfigurationError


def load_project_config(path: Path) -> ProjectConfig:
    if not path.is_file():
        raise ConfigurationError(f"Configuration file does not exist: {path}")
    try:
        with path.open("rb") as handle:
            data = load(handle)
        config = ProjectConfig.model_validate(data)
        artifacts_dir = config.paths.artifacts_dir
        if not artifacts_dir.is_absolute():
            artifacts_dir = (path.resolve().parent / artifacts_dir).resolve()
            config = config.model_copy(
                update={"paths": config.paths.model_copy(update={"artifacts_dir": artifacts_dir})}
            )
        return resolve_workbench_preferences(config, workbench_defaults(config))
    except TOMLDecodeError as exc:
        raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration in {path}: {exc}") from exc
