from datetime import date

import pytest

from app.domain.instruments import Bond, IssuedDebt, Mortgage, NonMaturingDeposit, TermDeposit
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.cash_flow_generation import (
    bond_cash_flows,
    floating_repricing_cash_flow,
    issued_debt_cash_flows,
    mortgage_cash_flows,
    nmd_cash_flows,
    term_deposit_cash_flows,
)


def _reference_curve() -> YieldCurve:
    # Same curve used across Phase 3 reference cases: rate_at(1)=0.05,
    # rate_at(2)=0.06 (interpolated), forward_rate(1,2)=0.070095238095238095
    return YieldCurve([CurvePoint(tenor_years=1.0, rate=0.05), CurvePoint(tenor_years=3.0, rate=0.07)])


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


def test_floating_repricing_cash_flow_rolls_forward_past_next_repricing_date():
    # Regression test for the crash bug: next_repricing_date is BEFORE
    # as_of_date, which is the normal state of a static snapshot field as
    # the report date advances past it. The function must roll the reset
    # date forward on the instrument's own repricing grid instead of
    # returning a stale, past-dated cash flow (which previously made
    # bucket_for raise ValueError downstream).
    bond = Bond(
        instrument_id="BND003",
        currency="EUR",
        notional=750_000,
        start_date=date(2020, 3, 15),
        maturity_date=date(2035, 3, 15),
        rate_type="floating",
        spread=0.006,
        reference_index="EURIBOR_6M",
        repricing_frequency_months=6,
        next_repricing_date=date(2026, 3, 15),
        coupon_frequency_months=6,
    )
    as_of_date = date(2026, 8, 14)
    flows = floating_repricing_cash_flow(bond, as_of_date, side="asset")

    assert len(flows) == 1
    cf = flows[0]
    # 2026-03-15 is before as_of_date; rolling forward by one 6-month step
    # (the instrument's repricing_frequency_months) lands on 2026-09-15,
    # which is strictly after as_of_date.
    assert cf.date == date(2026, 9, 15)
    assert cf.date > as_of_date
    # The rolled-forward date must remain on the original repricing grid:
    # next_repricing_date + k * repricing_frequency_months for integer k >= 1.
    months_elapsed = (cf.date.year - date(2026, 3, 15).year) * 12 + (
        cf.date.month - date(2026, 3, 15).month
    )
    assert cf.date.day == date(2026, 3, 15).day
    assert months_elapsed % bond.repricing_frequency_months == 0
    assert months_elapsed >= bond.repricing_frequency_months
    assert cf.amount == 750_000
    assert cf.flow_type == "principal"
    assert cf.side == "asset"


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


def test_mortgage_payment_grid_anchored_to_start_date_not_as_of_date():
    # Regression test: as_of_date (2026-08-14) is NOT on the payment grid,
    # which is anchored at start_date (the 15th of each month). The grid
    # must be built from start_date and then filtered to dates strictly
    # after as_of_date, not stepped forward from as_of_date itself — the
    # latter would round the period count up and produce a final payment
    # date past the contractual maturity_date.
    mortgage = Mortgage(
        instrument_id="MTGGRID",
        currency="EUR",
        notional=120_000,
        start_date=date(2020, 1, 15),
        maturity_date=date(2026, 9, 15),
        rate_type="fixed",
        fixed_rate=0.04,
        amortization_type="french",
        payment_frequency_months=1,
    )
    as_of_date = date(2026, 8, 14)
    flows = mortgage_cash_flows(mortgage, as_of_date)

    assert len(flows) > 0
    for f in flows:
        assert f.date <= mortgage.maturity_date
        assert f.date.day == 15
    # Two remaining monthly periods after 2026-08-14: 2026-08-15, 2026-09-15.
    dates = sorted({f.date for f in flows})
    assert dates == [date(2026, 8, 15), date(2026, 9, 15)]


def test_mortgage_zero_percent_uses_straight_line_amortization():
    # 0% fixed-rate mortgage with notional 100,000 / 2 periods
    # Should use straight-line amortization: each period principal = 100,000 / 2 = 50,000
    # Interest should be 0 for all periods
    mortgage = Mortgage(
        instrument_id="MTG_ZERO",
        currency="EUR",
        notional=100_000,
        start_date=date(2024, 1, 1),
        maturity_date=date(2024, 3, 1),
        rate_type="fixed",
        fixed_rate=0.0,
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = mortgage_cash_flows(mortgage, date(2024, 1, 1))
    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = sorted([f for f in flows if f.flow_type == "principal"], key=lambda f: f.date)

    assert len(interest_flows) == 2
    assert len(principal_flows) == 2
    # All interest flows should be 0
    assert all(f.amount == pytest.approx(0.0) for f in interest_flows)
    # Each principal flow should be 50,000 (100,000 / 2 periods)
    assert all(f.amount == pytest.approx(50_000.0) for f in principal_flows)
    # Total principal should equal notional
    assert sum(f.amount for f in principal_flows) == pytest.approx(100_000.0)
    # No NaN values
    assert all(not f.amount != f.amount for f in flows)  # NaN != NaN is True


def test_bond_floating_with_curve_projects_full_coupon_schedule():
    # as_of_date == start_date so both coupon periods are clean 1-year,
    # 2-year points on the reference curve (no leap days: 2025 and 2026
    # are not leap years).
    bond = Bond(
        instrument_id="BNDFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2026, 1, 1),
        coupon_frequency_months=12,
    )
    as_of_date = date(2025, 1, 1)
    flows = bond_cash_flows(bond, as_of_date, yield_curve=_reference_curve())

    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = [f for f in flows if f.flow_type == "principal"]

    assert [f.date for f in interest_flows] == [date(2026, 1, 1), date(2027, 1, 1)]
    # Period 1: forward_rate(0,1) + spread = 0.05 + 0.01 = 0.06 -> coupon = 1,000,000 * 0.06
    assert interest_flows[0].amount == pytest.approx(60_000.0)
    # Period 2: forward_rate(1,2) + spread = 0.070095238095238095 + 0.01
    assert interest_flows[1].amount == pytest.approx(80_095.23809523821, rel=1e-9)

    assert len(principal_flows) == 1
    assert principal_flows[0].amount == 1_000_000
    assert principal_flows[0].date == date(2027, 1, 1)
    assert all(f.side == "asset" for f in flows)


def test_bond_floating_without_curve_keeps_phase2_behaviour():
    # Regression: yield_curve=None (the default) must reproduce Phase 2's
    # bullet-principal-only behaviour exactly.
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


def test_issued_debt_floating_with_curve_side_is_liability():
    debt = IssuedDebt(
        instrument_id="ISDFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2026, 1, 1),
        coupon_frequency_months=12,
    )
    flows = issued_debt_cash_flows(debt, date(2025, 1, 1), yield_curve=_reference_curve())
    assert all(f.side == "liability" for f in flows)
    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    assert interest_flows[0].amount == pytest.approx(60_000.0)
    assert interest_flows[1].amount == pytest.approx(80_095.23809523821, rel=1e-9)


def test_mortgage_floating_with_curve_recasts_payment_each_period():
    # notional 100,000, 2 annual periods, spread 1%, as_of_date == start_date.
    # Period 1: rate = forward_rate(0,1) + 0.01 = 0.06
    #   payment = 100,000 * 0.06 / (1 - 1.06^-2) = 54,543.68932038834
    #   interest = 100,000 * 0.06 = 6,000.0, principal = 48,543.68932038833
    # Period 2 (n=1, balance=51,456.31067961167):
    #   rate = forward_rate(1,2) + 0.01 = 0.0800952380952382
    #   interest = 51,456.31067961167 * rate = 4,121.405455386045
    #   principal = balance (fully amortizes) = 51,456.310679611684
    mortgage = Mortgage(
        instrument_id="MTGFWD",
        currency="EUR",
        notional=100_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2026, 1, 1),
        amortization_type="french",
        payment_frequency_months=12,
    )
    as_of_date = date(2025, 1, 1)
    flows = mortgage_cash_flows(mortgage, as_of_date, yield_curve=_reference_curve())

    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = sorted([f for f in flows if f.flow_type == "principal"], key=lambda f: f.date)

    assert [f.date for f in interest_flows] == [date(2026, 1, 1), date(2027, 1, 1)]
    assert interest_flows[0].amount == pytest.approx(6_000.0)
    assert interest_flows[1].amount == pytest.approx(4_121.405455386045, rel=1e-9)
    assert principal_flows[0].amount == pytest.approx(48_543.68932038833, rel=1e-9)
    assert principal_flows[1].amount == pytest.approx(51_456.310679611684, rel=1e-9)
    # Fully amortizes: total principal repaid equals the original notional.
    assert sum(f.amount for f in principal_flows) == pytest.approx(100_000.0)
    assert all(f.side == "asset" for f in flows)


def test_mortgage_floating_without_curve_keeps_phase2_behaviour():
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
