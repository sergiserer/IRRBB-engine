from __future__ import annotations

from datetime import date
from typing import List

import pandas as pd

from app.domain.cash_flow import CashFlow, Side
from app.domain.instruments import Bond, Instrument, IssuedDebt, NonMaturingDeposit, TermDeposit


def nmd_cash_flows(nmd: NonMaturingDeposit, as_of_date: date) -> List[CashFlow]:
    """Places the full balance on as_of_date (the overnight bucket) —
    a placeholder until Fase 5 adds a behavioural decay model."""
    return [
        CashFlow(
            instrument_id=nmd.instrument_id,
            currency=nmd.currency,
            date=as_of_date,
            amount=nmd.notional,
            flow_type="principal",
            side="liability",
        )
    ]


def term_deposit_cash_flows(deposit: TermDeposit, as_of_date: date) -> List[CashFlow]:
    if deposit.maturity_date <= as_of_date:
        return []
    years = (deposit.maturity_date - deposit.start_date).days / 365
    interest = deposit.notional * deposit.fixed_rate * years
    return [
        CashFlow(
            instrument_id=deposit.instrument_id,
            currency=deposit.currency,
            date=deposit.maturity_date,
            amount=deposit.notional,
            flow_type="principal",
            side="liability",
        ),
        CashFlow(
            instrument_id=deposit.instrument_id,
            currency=deposit.currency,
            date=deposit.maturity_date,
            amount=interest,
            flow_type="interest",
            side="liability",
        ),
    ]


def floating_repricing_cash_flow(instrument: Instrument, as_of_date: date, side: Side) -> List[CashFlow]:
    """Basic Fase 2 treatment for floating-rate instruments: only the
    principal is slotted, at the next repricing date. Interim coupons are
    not projected because their size depends on a future reference rate
    that isn't available until the discount curve is wired in (Fase 3+)."""
    if instrument.maturity_date <= as_of_date:
        return []
    return [
        CashFlow(
            instrument_id=instrument.instrument_id,
            currency=instrument.currency,
            date=instrument.next_repricing_date,
            amount=instrument.notional,
            flow_type="principal",
            side=side,
        )
    ]


def _fixed_coupon_schedule(
    instrument_id: str,
    currency: str,
    notional: float,
    start_date: date,
    maturity_date: date,
    fixed_rate: float,
    coupon_frequency_months: int,
    as_of_date: date,
    side: Side,
) -> List[CashFlow]:
    """Assumes an exact integer number of coupon periods between
    start_date and maturity_date (true for the Fase 1 synthetic data); no
    stub-period handling in Fase 2."""
    if maturity_date <= as_of_date:
        return []
    coupon = notional * fixed_rate * (coupon_frequency_months / 12)
    step = pd.DateOffset(months=coupon_frequency_months)
    maturity_ts = pd.Timestamp(maturity_date)
    current = pd.Timestamp(start_date) + step

    flows: List[CashFlow] = []
    while current <= maturity_ts:
        cf_date = current.date()
        if cf_date > as_of_date:
            flows.append(
                CashFlow(
                    instrument_id=instrument_id,
                    currency=currency,
                    date=cf_date,
                    amount=coupon,
                    flow_type="interest",
                    side=side,
                )
            )
        current += step

    flows.append(
        CashFlow(
            instrument_id=instrument_id,
            currency=currency,
            date=maturity_date,
            amount=notional,
            flow_type="principal",
            side=side,
        )
    )
    return flows


def bond_cash_flows(bond: Bond, as_of_date: date) -> List[CashFlow]:
    if bond.rate_type == "floating":
        return floating_repricing_cash_flow(bond, as_of_date, side="asset")
    return _fixed_coupon_schedule(
        bond.instrument_id,
        bond.currency,
        bond.notional,
        bond.start_date,
        bond.maturity_date,
        bond.fixed_rate,
        bond.coupon_frequency_months,
        as_of_date,
        side="asset",
    )


def issued_debt_cash_flows(debt: IssuedDebt, as_of_date: date) -> List[CashFlow]:
    if debt.rate_type == "floating":
        return floating_repricing_cash_flow(debt, as_of_date, side="liability")
    return _fixed_coupon_schedule(
        debt.instrument_id,
        debt.currency,
        debt.notional,
        debt.start_date,
        debt.maturity_date,
        debt.fixed_rate,
        debt.coupon_frequency_months,
        as_of_date,
        side="liability",
    )
