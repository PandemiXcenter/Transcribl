from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsConfig(ConfigModel):
    artifacts_dir: Path


class ExtractionConfig(ConfigModel):
    image_dpi: int = Field(ge=72, le=600)
