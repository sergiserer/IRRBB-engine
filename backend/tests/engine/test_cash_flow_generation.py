from datetime import date

import pytest

from app.domain.instruments import Bond, IssuedDebt, Mortgage, NonMaturingDeposit, TermDeposit
from app.engine.cash_flow_generation import (
    bond_cash_flows,
    floating_repricing_cash_flow,
    issued_debt_cash_flows,
    mortgage_cash_flows,
    nmd_cash_flows,
    term_deposit_cash_flows,
)


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


def test_floating_repricing_cash_flow_reference_case():
    mortgage = Mortgage(
        instrument_id="MTG002",
        currency="EUR",
        notional=180_000,
        start_date=date(2022, 6, 1),
        maturity_date=date(2052, 6, 1),
        rate_type="floating",
        spread=0.012,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2027, 6, 1),
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = floating_repricing_cash_flow(mortgage, date(2026, 8, 14), side="asset")
    assert len(flows) == 1
    cf = flows[0]
    assert cf.amount == 180_000
    assert cf.date == date(2027, 6, 1)
    assert cf.flow_type == "principal"
    assert cf.side == "asset"


def test_floating_repricing_cash_flow_matured_returns_empty():
    bond = Bond(
        instrument_id="BND999",
        currency="EUR",
        notional=500_000,
        start_date=date(2020, 1, 1),
        maturity_date=date(2026, 1, 1),
        rate_type="floating",
        spread=0.005,
        reference_index="EURIBOR_6M",
        repricing_frequency_months=6,
        next_repricing_date=date(2025, 7, 1),
        coupon_frequency_months=6,
    )
    flows = floating_repricing_cash_flow(bond, date(2026, 8, 14), side="asset")
    assert flows == []


def test_bond_fixed_coupon_schedule_reference_case():
    bond = Bond(
        instrument_id="BND001",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2021, 3, 1),
        maturity_date=date(2031, 3, 1),
        rate_type="fixed",
        fixed_rate=0.021,
        coupon_frequency_months=12,
    )
    flows = bond_cash_flows(bond, date(2026, 8, 14))
    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = [f for f in flows if f.flow_type == "principal"]

    # Coupon dates forward from 2021-03-01 every 12 months: ...,2026-03-01
    # (before as_of, excluded), 2027-03-01 .. 2031-03-01 (5 remaining).
    assert len(interest_flows) == 5
    assert [f.date for f in interest_flows] == [
        date(2027, 3, 1),
        date(2028, 3, 1),
        date(2029, 3, 1),
        date(2030, 3, 1),
        date(2031, 3, 1),
    ]
    # coupon = 1,000,000 * 2.1% * (12/12) = 21,000.00
    assert all(f.amount == pytest.approx(21_000.0) for f in interest_flows)

    assert len(principal_flows) == 1
    assert principal_flows[0].amount == 1_000_000
    assert principal_flows[0].date == date(2031, 3, 1)
    assert all(f.side == "asset" for f in flows)


def test_bond_floating_delegates_to_repricing_flow():
    bond = Bond(
        instrument_id="BND002",
        currency="EUR",
        notional=500_000,
        start_date=date(2020, 9, 15),
        maturity_date=date(2028, 9, 15),
        rate_type="floating",
        spread=0.005,
        reference_index="EURIBOR_6M",
        repricing_frequency_months=6,
        next_repricing_date=date(2027, 3, 15),
        coupon_frequency_months=6,
    )
    flows = bond_cash_flows(bond, date(2026, 8, 14))
    assert len(flows) == 1
    assert flows[0].date == date(2027, 3, 15)
    assert flows[0].amount == 500_000
    assert flows[0].side == "asset"


def test_issued_debt_fixed_coupon_schedule_side_is_liability():
    debt = IssuedDebt(
        instrument_id="ISD001",
        currency="EUR",
        notional=2_000_000,
        start_date=date(2022, 1, 10),
        maturity_date=date(2027, 1, 10),
        rate_type="fixed",
        fixed_rate=0.028,
        coupon_frequency_months=12,
    )
    flows = issued_debt_cash_flows(debt, date(2026, 8, 14))
    principal_flows = [f for f in flows if f.flow_type == "principal"]
    assert all(f.side == "liability" for f in flows)
    assert len(principal_flows) == 1
    assert principal_flows[0].amount == 2_000_000
    assert principal_flows[0].date == date(2027, 1, 10)


def test_mortgage_french_amortization_reference_case():
    # notional 100,000 / 6%/yr / monthly / 2 remaining periods, starting
    # exactly at as_of_date so the schedule is easy to check by hand.
    mortgage = Mortgage(
        instrument_id="MTGREF",
        currency="EUR",
        notional=100_000,
        start_date=date(2024, 1, 1),
        maturity_date=date(2024, 3, 1),
        rate_type="fixed",
        fixed_rate=0.06,
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = mortgage_cash_flows(mortgage, date(2024, 1, 1))
    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = sorted([f for f in flows if f.flow_type == "principal"], key=lambda f: f.date)

    assert len(interest_flows) == 2
    assert len(principal_flows) == 2
    assert interest_flows[0].date == date(2024, 2, 1)
    assert interest_flows[1].date == date(2024, 3, 1)
    # First period interest is exactly balance * period_rate = 100,000 * 0.5% = 500.00
    assert interest_flows[0].amount == pytest.approx(500.0)

    # Annuity invariant: total principal repaid equals the original balance.
    assert sum(f.amount for f in principal_flows) == pytest.approx(100_000.0)
    # Each period's total payment (interest + principal) is constant.
    payment_1 = interest_flows[0].amount + principal_flows[0].amount
    payment_2 = interest_flows[1].amount + principal_flows[1].amount
    assert payment_1 == pytest.approx(payment_2)
    assert all(f.side == "asset" for f in flows)


def test_mortgage_matured_returns_empty():
    mortgage = Mortgage(
        instrument_id="MTGOLD",
        currency="EUR",
        notional=50_000,
        start_date=date(2010, 1, 1),
        maturity_date=date(2020, 1, 1),
        rate_type="fixed",
        fixed_rate=0.03,
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = mortgage_cash_flows(mortgage, date(2026, 8, 14))
    assert flows == []


def test_mortgage_floating_delegates_to_repricing_flow():
    mortgage = Mortgage(
        instrument_id="MTG002",
        currency="EUR",
        notional=180_000,
        start_date=date(2022, 6, 1),
        maturity_date=date(2052, 6, 1),
        rate_type="floating",
        spread=0.012,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2027, 6, 1),
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = mortgage_cash_flows(mortgage, date(2026, 8, 14))
    assert len(flows) == 1
    assert flows[0].date == date(2027, 6, 1)
    assert flows[0].amount == 180_000
