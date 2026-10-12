from pathlib import Path

import pytest
from pydantic import ValidationError

from transcribl.application.currency import display_cost
from transcribl.config import load_project_config
from transcribl.domain.costs import CostSettings, CostSummary
from transcribl.domain.currency import Currency, ExchangeRates


@pytest.mark.parametrize("currency", ["DKK", "EUR", "USD", "GBP"])
def test_currency_projection_preserves_usage_and_missing_prices(currency: Currency) -> None:
    rates = load_project_config(Path("config/default.toml")).costs.exchange_rates
    cost = CostSummary(
        kind="recorded",
        page_count=2,
        total_usd=2,
        per_page_usd=1,
        input_tokens=1000,
        output_tokens=500,
        basis="test",
    )
    original = cost.model_dump_json()
    displayed = display_cost(cost, currency, rates)
    factor = rates.units_per_eur[currency] / rates.units_per_eur["USD"]
    assert displayed.total == pytest.approx(2 * factor)
    assert displayed.per_page == pytest.approx(factor)
    assert displayed.total_usd == 2
    assert displayed.input_tokens == 1000 and displayed.output_tokens == 500
    assert displayed.exchange_rate_checked_on == rates.checked_on
    assert CostSummary.model_validate_json(displayed.model_dump_json()) == displayed
    assert cost.model_dump_json() == original
    unknown = CostSummary(kind="estimate", page_count=2, basis="No history")
    assert display_cost(unknown, currency, rates).total is None
    assert display_cost(unknown, currency, rates).per_page is None


@pytest.mark.parametrize(
    "rates",
    [
        {"EUR": 1, "USD": 1.1, "DKK": 7.4},
        {"EUR": 2, "USD": 1.1, "DKK": 7.4, "GBP": 0.85},
        {"EUR": 1, "USD": 0, "DKK": 7.4, "GBP": 0.85},
        {"EUR": 1, "USD": 1.1, "DKK": float("nan"), "GBP": 0.85},
    ],
)
def test_invalid_exchange_rates_rejected(rates: dict[str, float]) -> None:
    defaults = load_project_config(Path("config/default.toml")).costs.exchange_rates
    with pytest.raises(ValidationError):
        ExchangeRates.model_validate({**defaults.model_dump(), "units_per_eur": rates})


@pytest.mark.parametrize("choices", [["USD"], ["DKK", "DKK"], []])
def test_currency_choices_must_be_unique_and_include_default(choices: list[str]) -> None:
    defaults = load_project_config(Path("config/default.toml")).costs
    with pytest.raises(ValidationError):
        CostSettings.model_validate({**defaults.model_dump(), "currency_choices": choices})
