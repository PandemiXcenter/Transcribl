"""Non-secret price configuration and approximate usage-cost projections."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from transcribl.domain.currency import Currency, ExchangeRates
from transcribl.domain.models import ContractModel


class TokenPrice(ContractModel):
    provider: Literal["gemini", "openai", "anthropic"]
    input_usd_per_million: float = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: float = Field(ge=0, allow_inf_nan=False)
    checked_on: date
    source: HttpUrl
    valid_until: date | None = None
    long_context_threshold: int | None = Field(default=None, ge=1)
    long_input_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    long_output_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    note: str = ""

    @model_validator(mode="after")
    def complete_tier(self) -> Self:
        values = (
            self.long_context_threshold,
            self.long_input_usd_per_million,
            self.long_output_usd_per_million,
        )
        if any(v is not None for v in values) and not all(v is not None for v in values):
            raise ValueError("A long-context tier requires its threshold and both rates")
        if self.valid_until is not None and self.valid_until < self.checked_on:
            raise ValueError("Price expiry must not precede its verification date")
        return self


class CostSettings(ContractModel):
    default_currency: Currency
    currency_choices: list[Currency] = Field(min_length=1)
    exchange_rates: ExchangeRates
    minimum_matching_pages: int = Field(ge=1, le=1000)
    max_history_pages: int = Field(ge=1, le=100_000)
    prices: dict[str, TokenPrice]

    @model_validator(mode="after")
    def enough_history(self) -> Self:
        if (
            len(set(self.currency_choices)) != len(self.currency_choices)
            or self.default_currency not in self.currency_choices
        ):
            raise ValueError("Currency choices must be unique and include the default")
        if self.minimum_matching_pages > self.max_history_pages:
            raise ValueError("History limit must accommodate minimum matching pages")
        return self


class CostSummary(ContractModel):
    kind: Literal["estimate", "recorded"]
    currency: Currency = "USD"
    total: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    per_page: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    exchange_rate: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    exchange_rate_checked_on: date | None = None
    total_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    per_page_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    page_count: int = Field(ge=1)
    sample_pages: int = Field(default=0, ge=0)
    input_tokens: float = Field(default=0, ge=0)
    output_tokens: float = Field(default=0, ge=0)
    basis: str
    pricing_checked_on: list[date] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
