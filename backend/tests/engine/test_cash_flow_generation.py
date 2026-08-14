from datetime import date

import pytest

from app.domain.instruments import NonMaturingDeposit, TermDeposit
from app.engine.cash_flow_generation import nmd_cash_flows, term_deposit_cash_flows


def test_nmd_cash_flow_lands_on_as_of_date():
    nmd = NonMaturingDeposit(
        instrument_id="NMD001",
        currency="EUR",
        notional=3_000_000,
        as_of_date=date(2026, 8, 13),
        rate=0.001,
    )
    as_of = date(2026, 8, 14)
    flows = nmd_cash_flows(nmd, as_of)
    assert len(flows) == 1
    cf = flows[0]
    assert cf.date == as_of
    assert cf.amount == 3_000_000
    assert cf.flow_type == "principal"
    assert cf.side == "liability"


def test_term_deposit_bullet_cash_flow_reference_case():
    deposit = TermDeposit(
        instrument_id="TDP001",
        currency="EUR",
        notional=100_000,
        start_date=date(2025, 11, 1),
        maturity_date=date(2026, 11, 1),
        fixed_rate=0.025,
    )
    flows = term_deposit_cash_flows(deposit, date(2026, 8, 14))
    assert len(flows) == 2
    principal = next(f for f in flows if f.flow_type == "principal")
    interest = next(f for f in flows if f.flow_type == "interest")
    assert principal.amount == 100_000
    assert principal.date == date(2026, 11, 1)
    # years = (2026-11-01 - 2025-11-01).days / 365 == 1.0 exactly (no leap day in range)
    # interest = 100,000 * 2.5% * 1.0 = 2,500.00
    assert interest.amount == pytest.approx(2500.0)
    assert interest.date == date(2026, 11, 1)
    assert principal.side == "liability"
    assert interest.side == "liability"


def test_term_deposit_matured_returns_empty():
    deposit = TermDeposit(
        instrument_id="TDP002",
        currency="EUR",
        notional=60_000,
        start_date=date(2026, 2, 1),
        maturity_date=date(2027, 8, 1),
        fixed_rate=0.028,
    )
    flows = term_deposit_cash_flows(deposit, date(2027, 8, 1))
    assert flows == []
