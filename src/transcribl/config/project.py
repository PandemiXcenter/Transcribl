from typing import Literal, Self

from pydantic import model_validator

from transcribl.config.base import ConfigModel, ExtractionConfig, PathsConfig
from transcribl.config.interface import DesktopConfig, WebConfig, WorkbenchConfig
from transcribl.config.preferences import workbench_defaults
from transcribl.config.providers import ProviderConfig
from transcribl.config.translation import (
    ConfiguredMarkdownExportSettings,
    ConfiguredTranslationSettings,
    PdfExportConfig,
)
from transcribl.domain.costs import CostSettings


class ProjectConfig(ConfigModel):
    """Fully resolved, non-secret application configuration."""

    config_version: Literal[1]
    paths: PathsConfig
    extraction: ExtractionConfig
    provider: ProviderConfig
    translation: ConfiguredTranslationSettings
    export: ConfiguredMarkdownExportSettings
    pdf_export: PdfExportConfig
    desktop: DesktopConfig
    web: WebConfig
    workbench: WorkbenchConfig
    costs: CostSettings

    @model_validator(mode="after")
    def default_uncertainty_level_must_be_selectable(self) -> Self:
        default_choice = (
            self.translation.uncertainty_level.value
            if self.translation.mark_uncertain_terms
            else "off"
        )
        if default_choice not in self.web.uncertainty_level_choices:
            raise ValueError(
                "the configured uncertainty default must appear in uncertainty_level_choices"
            )
        workbench_defaults(self)
        return self
