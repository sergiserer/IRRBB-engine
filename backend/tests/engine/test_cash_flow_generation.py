from datetime import date
from pathlib import Path

import pytest

from app.domain.instruments import Bond, IssuedDebt, Leg, Mortgage, NonMaturingDeposit, Swap, TermDeposit
from app.domain.nmd_decay import NmdDecayConfig, load_nmd_decay_config
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.cash_flow_generation import (
    bond_cash_flows,
    floating_repricing_cash_flow,
    issued_debt_cash_flows,
    mortgage_cash_flows,
    nmd_cash_flows,
    swap_leg_cash_flows,
    term_deposit_cash_flows,
)

NMD_DECAY_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "nmd_decay.yaml"


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


def test_nmd_cash_flows_with_decay_config_splits_core_and_non_core():
    # notional 100,000, core_fraction=0.5, core_max_life_years=1,
    # decay_frequency_months=1. All figures below computed independently
    # in Python from the formula (not by calling nmd_cash_flows):
    #   non_core = 100,000 * (1 - 0.5) = 50,000.0, dated as_of_date
    #   core = 100,000 * 0.5 = 50,000.0
    #   horizon T = 2 * core_max_life_years = 2 years = 24 months
    #   n_periods = round(24 / 1) - 1 = 23
    #     (the -1 is what makes the discrete average maturity of flows
    #      placed at k = 1..n exactly T/2: mean(1..23) = 12 months = 1
    #      year = core_max_life_years, saturating the cap rather than
    #      overshooting it as n = 24 would -> mean(1..24) = 12.5 months)
    #   per_period_amount = 50,000 / 23 = 2173.913043478261
    #   first core date = 2026-01-01 + 1 month  = 2026-02-01
    #   last core date  = 2026-01-01 + 23 months = 2027-12-01
    #   total flows = 1 non-core + 23 core = 24
    #   sum = 50,000.0 + 23 * 2173.913043478261 = 100,000.0
    nmd = NonMaturingDeposit(
        instrument_id="NMDCORE",
        currency="EUR",
        notional=100_000,
        as_of_date=date(2026, 1, 1),
        rate=0.001,
    )
    as_of = date(2026, 1, 1)
    decay_config = NmdDecayConfig(core_fraction=0.5, core_max_life_years=1, decay_frequency_months=1)

    flows = nmd_cash_flows(nmd, as_of, decay_config=decay_config)

    assert len(flows) == 24  # 1 non-core + 23 core periods
    assert all(f.flow_type == "principal" for f in flows)
    assert all(f.side == "liability" for f in flows)

    non_core_flow = next(f for f in flows if f.date == as_of)
    assert non_core_flow.amount == pytest.approx(50_000.0)

    core_flows = sorted([f for f in flows if f.date != as_of], key=lambda f: f.date)
    assert len(core_flows) == 23
    assert core_flows[0].date == date(2026, 2, 1)
    assert core_flows[0].amount == pytest.approx(2173.913043478261, rel=1e-9)
    assert core_flows[-1].date == date(2027, 12, 1)
    assert core_flows[-1].amount == pytest.approx(2173.913043478261, rel=1e-9)

    # Fully reconciles: non-core + all core periods sum to the notional.
    assert sum(f.amount for f in flows) == pytest.approx(100_000.0)


def test_nmd_core_runoff_weighted_average_maturity_saturates_eba_cap():
    # Magnitude-sanity invariant under the REAL shipped config (same
    # pattern prescribed after the Fase 3 bug, where an amortization-
    # sums-to-par test was blind to the level of the rate): flow counts,
    # dates and the sum-to-notional invariant are all insensitive to the
    # runoff horizon being wrong, so assert the regulatory quantity
    # itself -- the weighted-average maturity of the CORE component (the
    # thing EBA/GL/2022/14 caps; the non-core piece is overnight by
    # construction and is excluded).
    #
    # With core_max_life_years = T/2 and equal core amounts at k = 1..n
    # periods, WAM = (n + 1)/2 periods = core_max_life_years exactly.
    # The band below is two-sided on purpose: too long breaches the cap,
    # too short silently under-utilizes it.
    decay_config = load_nmd_decay_config(NMD_DECAY_CONFIG_PATH)
    nmd = NonMaturingDeposit(
        instrument_id="NMDWAM",
        currency="EUR",
        notional=1_000_000,
        as_of_date=date(2026, 1, 1),
        rate=0.001,
    )
    as_of = date(2026, 1, 1)

    flows = nmd_cash_flows(nmd, as_of, decay_config=decay_config)
    core_flows = [f for f in flows if f.date != as_of]
    assert core_flows  # guard: an empty core would make the WAM vacuous

    # ACT/365, the year fraction convention used throughout the engine.
    wam_years = sum(f.amount * (f.date - as_of).days / 365 for f in core_flows) / sum(
        f.amount for f in core_flows
    )

    # Tolerance ~0.01y (~3.7 days) absorbs the ACT/365-vs-calendar-month
    # drift (a 1..119 monthly grid measured in 365-day years lands at
    # 5.0010y, not 5.0000y) without being loose enough to hide an
    # off-by-one period (which would move the WAM by ~0.042y).
    assert wam_years <= decay_config.core_max_life_years + 0.01
    assert wam_years >= decay_config.core_max_life_years - 0.01


def test_nmd_cash_flows_without_decay_config_is_unchanged():
    # Regression guard: decay_config defaults to None, reproducing the
    # Fase 2 placeholder exactly.
    nmd = NonMaturingDeposit(
        instrument_id="NMDCORE",
        currency="EUR",
        notional=100_000,
        as_of_date=date(2026, 1, 1),
        rate=0.001,
    )
    as_of = date(2026, 1, 1)
    flows = nmd_cash_flows(nmd, as_of)
    assert len(flows) == 1
    assert flows[0].amount == pytest.approx(100_000.0)
    assert flows[0].date == as_of
    assert flows[0].flow_type == "principal"
    assert flows[0].side == "liability"


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
    # cpr_annual defaults to 0.0 -- no prepayment flows are ever emitted
    # unless a caller explicitly opts in.
    assert all(f.flow_type != "prepayment" for f in flows)


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


def test_mortgage_fixed_with_cpr_pays_off_before_maturity_date():
    # notional 100,000, 6% fixed, monthly, 24-month contractual term,
    # cpr_annual=0.20 (illustrative, deliberately higher than the
    # project's 5% default so the early-payoff effect is unambiguous in
    # a short 24-period window). All figures below computed
    # independently in Python from the formulas in the design spec
    # (docs/superpowers/specs/2026-08-16-phase5-prepayment-design.md),
    # not by calling mortgage_cash_flows:
    #   period_rate = 0.06 * (1/12) = 0.005
    #   payment_fixed = 100,000 * 0.005 / (1 - 1.005**-24) = 4,432.061025275781
    #   smm = 1 - (1 - 0.20)**(1/12) = 0.018423470126248342
    #   Period 1: interest = 100,000 * 0.005 = 500.0
    #             scheduled_principal = 4,432.061025275781 - 500.0 = 3,932.0610252757806
    #             prepayment = 0.018423470126248342 * (100,000 - 3,932.0610252757806)
    #                        = 1,769.9048037910807
    #   Simulating all periods this way, the balance reaches 0 after 20
    #   of the 24 contractual monthly periods (last flow 2025-09-01,
    #   contractual maturity_date is 2026-01-01).
    mortgage = Mortgage(
        instrument_id="MTGCPR",
        currency="EUR",
        notional=100_000,
        start_date=date(2024, 1, 1),
        maturity_date=date(2026, 1, 1),
        rate_type="fixed",
        fixed_rate=0.06,
        amortization_type="french",
        payment_frequency_months=1,
    )
    flows = mortgage_cash_flows(mortgage, date(2024, 1, 1), cpr_annual=0.20)

    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = sorted([f for f in flows if f.flow_type == "principal"], key=lambda f: f.date)
    prepayment_flows = sorted([f for f in flows if f.flow_type == "prepayment"], key=lambda f: f.date)

    assert len(interest_flows) == 20
    assert len(principal_flows) == 20
    assert len(prepayment_flows) == 20
    dates = sorted({f.date for f in flows})
    assert dates[-1] == date(2025, 9, 1)
    assert dates[-1] < mortgage.maturity_date

    assert interest_flows[0].date == date(2024, 2, 1)
    assert interest_flows[0].amount == pytest.approx(500.0)
    assert principal_flows[0].amount == pytest.approx(3_932.0610252757806, rel=1e-9)
    assert prepayment_flows[0].amount == pytest.approx(1_769.9048037910807, rel=1e-9)

    # Fully amortizes: scheduled + unscheduled principal sums to the notional.
    total_principal = sum(f.amount for f in principal_flows) + sum(f.amount for f in prepayment_flows)
    assert total_principal == pytest.approx(100_000.0)
    assert all(f.side == "asset" for f in flows)


def test_mortgage_floating_ignores_cpr_annual():
    # BCBS d368 scopes prepayment risk to fixed-rate loans; cpr_annual is
    # accepted for floating mortgages (so callers don't need to branch
    # by rate_type) but must have zero effect on the output.
    mortgage = Mortgage(
        instrument_id="MTGFWDCPR",
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
    curve = _reference_curve()
    flows_without_cpr = mortgage_cash_flows(mortgage, as_of_date, yield_curve=curve, cpr_annual=0.0)
    flows_with_cpr = mortgage_cash_flows(mortgage, as_of_date, yield_curve=curve, cpr_annual=0.20)
    assert flows_without_cpr == flows_with_cpr


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


def test_mortgage_floating_with_curve_monthly_payment_deannualizes_rate():
    # Regression test for the Fase 3 de-annualization bug: with monthly
    # payments (freq=1), period_rate must be forward_rate(t1,t2) + spread
    # scaled by (freq/12), same as the fixed-rate branch does. Both
    # payment periods here (2024-01-01 -> 2024-02-01 -> 2024-03-01) fall
    # entirely within [0, 1] years from as_of_date, where this curve's
    # rate_at is flat at 5% (t <= first tenor of 1.0) -- so forward_rate
    # is exactly 0.05 for both periods regardless of the exact t1/t2,
    # making the annual rate = 0.05 + spread(0.01) = 0.06 for both
    # periods, identical to test_mortgage_french_amortization_reference_case's
    # fixed 6% case. Correctly de-annualized: period_rate = 0.06 * (1/12)
    # = 0.005 -> first interest = 100,000 * 0.005 = 500.00. The bug (no
    # de-annualization) would instead use period_rate = 0.06, an interest
    # of 6,000.00 -- 12x too large.
    mortgage = Mortgage(
        instrument_id="MTGCURVEMONTHLY",
        currency="EUR",
        notional=100_000,
        start_date=date(2024, 1, 1),
        maturity_date=date(2024, 3, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2025, 1, 1),
        amortization_type="french",
        payment_frequency_months=1,
    )
    as_of_date = date(2024, 1, 1)
    flows = mortgage_cash_flows(mortgage, as_of_date, yield_curve=_reference_curve())

    interest_flows = sorted([f for f in flows if f.flow_type == "interest"], key=lambda f: f.date)
    principal_flows = sorted([f for f in flows if f.flow_type == "principal"], key=lambda f: f.date)

    assert [f.date for f in interest_flows] == [date(2024, 2, 1), date(2024, 3, 1)]
    # First period interest is exactly balance * period_rate = 100,000 * 0.5% = 500.00
    assert interest_flows[0].amount == pytest.approx(500.0)
    # Annuity invariant: total principal repaid equals the original balance.
    assert sum(f.amount for f in principal_flows) == pytest.approx(100_000.0)
    # Each period's total payment (interest + principal) is constant --
    # only true if both periods used the same (correctly de-annualized)
    # period_rate, since both forward rates are 0.05 here.
    payment_1 = interest_flows[0].amount + principal_flows[0].amount
    payment_2 = interest_flows[1].amount + principal_flows[1].amount
    assert payment_1 == pytest.approx(payment_2)
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


def test_mortgage_fixed_empty_payment_grid_returns_empty():
    # Regression test: start_date=2024-01-01, maturity_date=2024-07-15,
    # payment_frequency_months=12 -- the annual payment grid's first date
    # (2025-01-01) falls AFTER maturity_date, so remaining_dates is empty
    # even though the mortgage hasn't matured yet (as_of_date < maturity_date).
    # Before this fix, _fixed_mortgage_schedule divided by n_total=0 here.
    mortgage = Mortgage(
        instrument_id="MTGEMPTY",
        currency="EUR",
        notional=100_000,
        start_date=date(2024, 1, 1),
        maturity_date=date(2024, 7, 15),
        rate_type="fixed",
        fixed_rate=0.05,
        amortization_type="french",
        payment_frequency_months=12,
    )
    flows = mortgage_cash_flows(mortgage, date(2024, 1, 1))
    assert flows == []


def _reference_swap() -> Swap:
    # notional 1,000,000, 2 annual periods, as_of_date == start_date
    # (same dates/curve as the bond/mortgage Fase 3 fixtures above).
    return Swap(
        instrument_id="SWPFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        payment_frequency_months=12,
        pay_leg=Leg(rate_type="fixed", fixed_rate=0.05),
        receive_leg=Leg(rate_type="floating", spread=0.01, reference_index="EURIBOR_12M"),
    )


def test_swap_leg_cash_flows_fixed_leg_reference_case():
    swap = _reference_swap()
    flows = swap_leg_cash_flows(swap, swap.pay_leg, date(2025, 1, 1), _reference_curve())
    assert [f.date for f in flows] == [date(2026, 1, 1), date(2027, 1, 1)]
    # 1,000,000 * 5% * (12/12) = 50,000 each period, no principal exchange.
    assert all(f.amount == pytest.approx(50_000.0) for f in flows)
    assert all(f.flow_type == "interest" for f in flows)


def test_swap_leg_cash_flows_floating_leg_reference_case():
    swap = _reference_swap()
    flows = swap_leg_cash_flows(swap, swap.receive_leg, date(2025, 1, 1), _reference_curve())
    flows = sorted(flows, key=lambda f: f.date)
    assert [f.date for f in flows] == [date(2026, 1, 1), date(2027, 1, 1)]
    # Same forward rates as the floating bond fixture: 0.06 and 0.0800952380952382
    assert flows[0].amount == pytest.approx(60_000.0)
    assert flows[1].amount == pytest.approx(80_095.23809523821, rel=1e-9)
