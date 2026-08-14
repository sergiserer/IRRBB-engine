from __future__ import annotations

from datetime import date
from typing import List

from app.domain.cash_flow import CashFlow, Side
from app.domain.instruments import Instrument, NonMaturingDeposit, TermDeposit


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
