from __future__ import annotations

from datetime import date
from typing import List

import pandas as pd

from app.domain.cash_flow import CashFlow, Side
from app.domain.instruments import Bond, Instrument, IssuedDebt, Mortgage, NonMaturingDeposit, TermDeposit
from app.domain.yield_curve import YieldCurve


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
    that isn't available until the discount curve is wired in (Fase 3+).

    instrument.next_repricing_date is a static snapshot field that can be
    in the past relative to as_of_date (the normal state as the report
    date advances past it). When that happens, roll it forward on the
    instrument's own repricing grid until it's strictly after as_of_date
    — an instrument whose reset date has already passed reprices at its
    next scheduled reset — clamped so the roll-forward never overshoots
    the instrument's own maturity_date."""
    if instrument.maturity_date <= as_of_date:
        return []
    next_reset = instrument.next_repricing_date
    step = pd.DateOffset(months=instrument.repricing_frequency_months)
    while next_reset <= as_of_date:
        next_reset = (pd.Timestamp(next_reset) + step).date()
    next_reset = min(next_reset, instrument.maturity_date)
    return [
        CashFlow(
            instrument_id=instrument.instrument_id,
            currency=instrument.currency,
            date=next_reset,
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


def _floating_coupon_schedule(
    instrument_id: str,
    currency: str,
    notional: float,
    start_date: date,
    maturity_date: date,
    spread: float,
    coupon_frequency_months: int,
    as_of_date: date,
    yield_curve: YieldCurve,
    side: Side,
) -> List[CashFlow]:
    """Same coupon-date grid as _fixed_coupon_schedule, but each period's
    rate is yield_curve.forward_rate(t1, t2) + spread instead of a stored
    fixed_rate. t1 is clamped to 0 when the period's true start predates
    as_of_date (no historical fixing data in this synthetic model —
    documented Fase 3 simplification)."""
    if maturity_date <= as_of_date:
        return []
    step = pd.DateOffset(months=coupon_frequency_months)
    maturity_ts = pd.Timestamp(maturity_date)
    period_start = pd.Timestamp(start_date)
    current = period_start + step

    flows: List[CashFlow] = []
    while current <= maturity_ts:
        cf_date = current.date()
        if cf_date > as_of_date:
            t1 = max(0.0, (period_start.date() - as_of_date).days / 365)
            t2 = (cf_date - as_of_date).days / 365
            rate = yield_curve.forward_rate(t1, t2) + spread
            coupon = notional * rate * (coupon_frequency_months / 12)
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
        period_start = current
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


def bond_cash_flows(bond: Bond, as_of_date: date, yield_curve: YieldCurve | None = None) -> List[CashFlow]:
    if bond.rate_type == "floating":
        if yield_curve is None:
            return floating_repricing_cash_flow(bond, as_of_date, side="asset")
        return _floating_coupon_schedule(
            bond.instrument_id,
            bond.currency,
            bond.notional,
            bond.start_date,
            bond.maturity_date,
            bond.spread,
            bond.coupon_frequency_months,
            as_of_date,
            yield_curve,
            side="asset",
        )
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


def issued_debt_cash_flows(
    debt: IssuedDebt, as_of_date: date, yield_curve: YieldCurve | None = None
) -> List[CashFlow]:
    if debt.rate_type == "floating":
        if yield_curve is None:
            return floating_repricing_cash_flow(debt, as_of_date, side="liability")
        return _floating_coupon_schedule(
            debt.instrument_id,
            debt.currency,
            debt.notional,
            debt.start_date,
            debt.maturity_date,
            debt.spread,
            debt.coupon_frequency_months,
            as_of_date,
            yield_curve,
            side="liability",
        )
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


def mortgage_cash_flows(mortgage: Mortgage, as_of_date: date) -> List[CashFlow]:
    """Assumes an exact integer number of payment periods between
    start_date and maturity_date (same assumption as _fixed_coupon_schedule);
    no stub-period handling in Fase 2.

    The payment date grid is anchored to start_date (not as_of_date) since
    that's the instrument's actual contractual payment schedule; as_of_date
    is not generally on that grid. balance starts from mortgage.notional,
    which represents the outstanding principal as of as_of_date (not the
    origination amount) — only dates falling strictly after as_of_date are
    emitted."""
    if mortgage.rate_type == "floating":
        return floating_repricing_cash_flow(mortgage, as_of_date, side="asset")
    if mortgage.maturity_date <= as_of_date:
        return []

    freq = mortgage.payment_frequency_months
    step = pd.DateOffset(months=freq)
    maturity_ts = pd.Timestamp(mortgage.maturity_date)
    current = pd.Timestamp(mortgage.start_date) + step
    grid_dates: List[date] = []
    while current <= maturity_ts:
        grid_dates.append(current.date())
        current += step
    remaining_dates = [d for d in grid_dates if d > as_of_date]
    n = len(remaining_dates)

    period_rate = mortgage.fixed_rate * (freq / 12)
    if period_rate == 0:
        payment = mortgage.notional / n
    else:
        payment = mortgage.notional * period_rate / (1 - (1 + period_rate) ** -n)

    flows: List[CashFlow] = []
    balance = mortgage.notional
    for cf_date in remaining_dates:
        interest = balance * period_rate
        principal = payment - interest
        balance -= principal
        flows.append(
            CashFlow(
                instrument_id=mortgage.instrument_id,
                currency=mortgage.currency,
                date=cf_date,
                amount=interest,
                flow_type="interest",
                side="asset",
            )
        )
        flows.append(
            CashFlow(
                instrument_id=mortgage.instrument_id,
                currency=mortgage.currency,
                date=cf_date,
                amount=principal,
                flow_type="principal",
                side="asset",
            )
        )
    return flows
