from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

RateType = Literal["fixed", "floating"]


def _validate_rate_fields(
    rate_type: RateType,
    fixed_rate: Optional[float],
    spread: Optional[float],
    reference_index: Optional[str],
) -> None:
    if rate_type == "fixed":
        if fixed_rate is None:
            raise ValueError("fixed_rate is required when rate_type is 'fixed'")
        if spread is not None or reference_index is not None:
            raise ValueError("spread/reference_index must be empty when rate_type is 'fixed'")
    else:
        if spread is None or reference_index is None:
            raise ValueError("spread and reference_index are required when rate_type is 'floating'")
        if fixed_rate is not None:
            raise ValueError("fixed_rate must be empty when rate_type is 'floating'")


class Instrument(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    # notional is the outstanding principal as of the report's as_of_date,
    # not the origination/issuance amount.
    notional: float = Field(gt=0)
    start_date: date
    maturity_date: date
    rate_type: RateType
    fixed_rate: Optional[float] = None
    spread: Optional[float] = None
    reference_index: Optional[str] = None
    repricing_frequency_months: Optional[int] = None
    next_repricing_date: Optional[date] = None

    @model_validator(mode="after")
    def _check_fields(self) -> "Instrument":
        _validate_rate_fields(self.rate_type, self.fixed_rate, self.spread, self.reference_index)
        if self.rate_type == "floating" and (
            self.repricing_frequency_months is None or self.next_repricing_date is None
        ):
            raise ValueError(
                "repricing_frequency_months and next_repricing_date are required "
                "when rate_type is 'floating'"
            )
        if self.maturity_date <= self.start_date:
            raise ValueError("maturity_date must be after start_date")
        return self


class Mortgage(Instrument):
    amortization_type: Literal["french"] = "french"
    payment_frequency_months: int = Field(gt=0)


class Bond(Instrument):
    coupon_frequency_months: int = Field(gt=0)


class IssuedDebt(Instrument):
    coupon_frequency_months: int = Field(gt=0)


class TermDeposit(Instrument):
    rate_type: Literal["fixed"] = "fixed"


class NonMaturingDeposit(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    # notional is the outstanding balance as of the report's as_of_date,
    # not the origination/issuance amount.
    notional: float = Field(gt=0)
    as_of_date: date
    rate: float = Field(ge=0)


class Leg(BaseModel):
    rate_type: RateType
    fixed_rate: Optional[float] = None
    spread: Optional[float] = None
    reference_index: Optional[str] = None

    @model_validator(mode="after")
    def _check_fields(self) -> "Leg":
        _validate_rate_fields(self.rate_type, self.fixed_rate, self.spread, self.reference_index)
        return self


class Swap(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    notional: float = Field(gt=0)
    start_date: date
    maturity_date: date
    payment_frequency_months: int = Field(gt=0)
    pay_leg: Leg
    receive_leg: Leg

    @model_validator(mode="after")
    def _check_dates(self) -> "Swap":
        if self.maturity_date <= self.start_date:
            raise ValueError("maturity_date must be after start_date")
        return self
