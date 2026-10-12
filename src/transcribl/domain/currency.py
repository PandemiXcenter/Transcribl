"""Display currencies and dated exchange-rate configuration."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, model_validator

from transcribl.domain.models import ContractModel

Currency = Literal["DKK", "EUR", "USD", "GBP"]


class ExchangeRates(ContractModel):
    checked_on: date
    source: HttpUrl
    units_per_eur: dict[Currency, Annotated[float, Field(gt=0, allow_inf_nan=False)]]

    @model_validator(mode="after")
    def complete_reference(self) -> Self:
        if set(self.units_per_eur) != {"DKK", "EUR", "USD", "GBP"}:
            raise ValueError("Configure exchange rates for DKK, EUR, USD and GBP")
        if self.units_per_eur["EUR"] != 1:
            raise ValueError("EUR is the exchange-rate base and must equal one")
        return self
