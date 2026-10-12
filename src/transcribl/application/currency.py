"""Currency conversion is a display projection; token accounting stays in USD."""

from transcribl.domain.costs import CostSummary
from transcribl.domain.currency import Currency, ExchangeRates


def display_cost(cost: CostSummary, currency: Currency, rates: ExchangeRates) -> CostSummary:
    rate = rates.units_per_eur[currency] / rates.units_per_eur["USD"]
    note = f"Converted from USD using reference rates dated {rates.checked_on.isoformat()}."
    return cost.model_copy(
        update={
            "currency": currency,
            "total": None if cost.total_usd is None else cost.total_usd * rate,
            "per_page": None if cost.per_page_usd is None else cost.per_page_usd * rate,
            "exchange_rate": rate,
            "exchange_rate_checked_on": rates.checked_on,
            "notes": [*cost.notes, note] if currency != "USD" else list(cost.notes),
            "sources": list(dict.fromkeys([*cost.sources, str(rates.source)]))
            if currency != "USD"
            else list(cost.sources),
        }
    )
