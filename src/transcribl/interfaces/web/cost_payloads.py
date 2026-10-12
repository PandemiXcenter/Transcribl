"""Apply saved display preferences at the HTTP boundary, including historical jobs."""

from dataclasses import asdict

from transcribl.application.currency import display_cost
from transcribl.application.jobs.records import JobSnapshot, ReviewSnapshot
from transcribl.application.workbench_settings import WorkbenchSettingsService
from transcribl.domain.costs import CostSummary


def cost_payload(cost: CostSummary, settings: WorkbenchSettingsService) -> dict[str, object]:
    return display_cost(
        cost, settings.read().values.currency, settings.config.costs.exchange_rates
    ).model_dump(mode="json")


def job_payload(
    snapshot: JobSnapshot | ReviewSnapshot, settings: WorkbenchSettingsService
) -> dict[str, object]:
    payload = asdict(snapshot)
    if snapshot.cost is not None:
        payload["cost"] = cost_payload(CostSummary.model_validate(snapshot.cost), settings)
    return payload
