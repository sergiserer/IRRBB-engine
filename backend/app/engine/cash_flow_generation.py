from __future__ import annotations

from datetime import date
from typing import List

from app.domain.cash_flow import CashFlow
from app.domain.instruments import NonMaturingDeposit, TermDeposit


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
