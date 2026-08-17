from datetime import date
from pathlib import Path

import pytest

from app.data.loaders import load_balance_sheet
from app.domain.balance_sheet import BalanceSheet
from app.domain.cash_flow import CashFlow
from app.domain.instruments import Bond, Leg, Swap, TermDeposit
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.cash_flow_generation import mortgage_cash_flows
from app.engine.eve import compute_eve, pv, swap_pv
from app.engine.repricing_gap import generate_all_cash_flows


def _reference_curve() -> YieldCurve:
    return YieldCurve([CurvePoint(tenor_years=1.0, rate=0.05), CurvePoint(tenor_years=3.0, rate=0.07)])


def test_pv_discounts_and_sums_cash_flows():
    as_of_date = date(2025, 1, 1)
    flows = [
        CashFlow(instrument_id="A", currency="EUR", date=date(2026, 1, 1), amount=1000, flow_type="principal", side="asset"),
        CashFlow(instrument_id="A", currency="EUR", date=date(2027, 1, 1), amount=2000, flow_type="principal", side="asset"),
    ]
    # 1000 * DF(1) + 2000 * DF(2) = 1000*0.9523809523809523 + 2000*0.8899964400142398
    result = pv(flows, as_of_date, _reference_curve())
    assert result == pytest.approx(2732.373832409432, rel=1e-9)


def test_pv_of_empty_list_is_zero():
    assert pv([], date(2025, 1, 1), _reference_curve()) == 0.0


def test_swap_pv_reference_case():
    swap = Swap(
        instrument_id="SWPFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        payment_frequency_months=12,
        pay_leg=Leg(rate_type="fixed", fixed_rate=0.05),
        receive_leg=Leg(rate_type="floating", spread=0.01, reference_index="EURIBOR_12M"),
    )
    result = swap_pv(swap, date(2025, 1, 1), _reference_curve())
    assert result == pytest.approx(36_308.464289952506, rel=1e-9)


def test_compute_eve_small_balance_sheet_reference_case():
    as_of_date = date(2025, 1, 1)
    bond = Bond(
        instrument_id="BNDFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=as_of_date,
        maturity_date=date(2027, 1, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2026, 1, 1),
        coupon_frequency_months=12,
    )
    deposit = TermDeposit(
        instrument_id="TDPFWD",
        currency="EUR",
        notional=500_000,
        start_date=as_of_date,
        maturity_date=date(2027, 1, 1),
        fixed_rate=0.04,
    )
    swap = Swap(
        instrument_id="SWPFWD",
        currency="EUR",
        notional=1_000_000,
        start_date=as_of_date,
        maturity_date=date(2027, 1, 1),
        payment_frequency_months=12,
        pay_leg=Leg(rate_type="fixed", fixed_rate=0.05),
        receive_leg=Leg(rate_type="floating", spread=0.01, reference_index="EURIBOR_12M"),
    )
    balance_sheet = BalanceSheet(bonds=[bond], term_deposits=[deposit], swaps=[swap])

    result = compute_eve(balance_sheet, as_of_date, _reference_curve())

    assert result.pv_assets == pytest.approx(1_018_423.7739239518, rel=1e-9)
    assert result.pv_liabilities == pytest.approx(480_598.0776076895, rel=1e-9)
    assert result.swap_net_pv == pytest.approx(36_308.464289952506, rel=1e-9)
    assert result.eve == pytest.approx(574_134.1606062148, rel=1e-9)


DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
AS_OF_DATE = date(2026, 8, 14)  # same as test_repricing_gap.py: after every start_date, before any maturity


def _flat_zero_curve() -> YieldCurve:
    # A single point makes rate_at (and therefore discount_factor) flat
    # everywhere -- DF(t) == 1.0 for all t > 0 -- so PV reduces to the
    # undiscounted cash flow sum, which this test computes independently
    # via the same generators compute_eve uses internally. This is the
    # "hand-computed" reference case for the full synthetic balance
    # sheet: trivial arithmetic (a sum), but genuine end-to-end wiring
    # coverage across every instrument type and the swap netting path.
    return YieldCurve([CurvePoint(tenor_years=1.0, rate=0.0)])


def test_compute_eve_reconciles_with_independently_summed_cash_flows():
    balance_sheet = load_balance_sheet(DATA_DIR)
    curve = _flat_zero_curve()

    result = compute_eve(balance_sheet, AS_OF_DATE, curve)

    flows = generate_all_cash_flows(balance_sheet, AS_OF_DATE, curve)
    expected_assets = sum(f.amount for f in flows if f.side == "asset")
    expected_liabilities = sum(f.amount for f in flows if f.side == "liability")
    expected_swap_net_pv = sum(swap_pv(s, AS_OF_DATE, curve) for s in balance_sheet.swaps)

    assert result.pv_assets == pytest.approx(expected_assets)
    assert result.pv_liabilities == pytest.approx(expected_liabilities)
    assert result.swap_net_pv == pytest.approx(expected_swap_net_pv)
    assert result.eve == pytest.approx(expected_assets - expected_liabilities + expected_swap_net_pv)


def test_compute_eve_floating_mortgage_fully_amortizes_under_curve():
    # MTG002 (floating, notional 180,000): under a curve, its cash flows
    # must fully amortize the notional regardless of the projected rate
    # path -- a structural invariant of the recast-every-period annuity,
    # independent of any specific curve.
    balance_sheet = load_balance_sheet(DATA_DIR)
    mtg002 = next(m for m in balance_sheet.mortgages if m.instrument_id == "MTG002")

    flows = mortgage_cash_flows(mtg002, AS_OF_DATE, yield_curve=_flat_zero_curve())
    principal_total = sum(f.amount for f in flows if f.flow_type == "principal")

    assert principal_total == pytest.approx(180_000.0)


def test_compute_eve_floating_mortgage_pv_stays_within_notional_band_under_flat_curve():
    # Magnitude sanity invariant, independent of the amortization
    # invariant above: a floating instrument's PV under a flat curve at a
    # realistic rate must stay within a reasonable band of its notional
    # -- it should not be a multiple of the notional. This is the
    # invariant that would have caught the Fase 3 de-annualization bug
    # instantly (the buggy PV came out at ~7.8x notional), unlike the
    # amortization-only test above, which is blind to the rate level.
    balance_sheet = load_balance_sheet(DATA_DIR)
    mtg002 = next(m for m in balance_sheet.mortgages if m.instrument_id == "MTG002")
    flat_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])

    flows = mortgage_cash_flows(mtg002, AS_OF_DATE, yield_curve=flat_curve)
    mortgage_pv = pv(flows, AS_OF_DATE, flat_curve)

    assert 0.8 * mtg002.notional < mortgage_pv < 1.3 * mtg002.notional


def test_compute_eve_with_cpr_annual_differs_from_without():
    # MTG001 (fixed) is the only instrument affected by cpr_annual;
    # prepayment shifts principal earlier in time, which must change
    # both pv_assets and the overall eve versus the cpr_annual=0.0
    # baseline under any curve with a nonzero rate.
    balance_sheet = load_balance_sheet(DATA_DIR)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])

    eve_without_cpr = compute_eve(balance_sheet, AS_OF_DATE, curve)
    eve_with_cpr = compute_eve(balance_sheet, AS_OF_DATE, curve, cpr_annual=0.05)

    assert eve_with_cpr.pv_assets != pytest.approx(eve_without_cpr.pv_assets)
    assert eve_with_cpr.eve != pytest.approx(eve_without_cpr.eve)
    # Liabilities and swap PV are unaffected -- cpr_annual only touches
    # mortgages, which are always assets.
    assert eve_with_cpr.pv_liabilities == pytest.approx(eve_without_cpr.pv_liabilities)
    assert eve_with_cpr.swap_net_pv == pytest.approx(eve_without_cpr.swap_net_pv)


def test_compute_eve_with_nmd_decay_config_differs_from_without():
    # NMD is always a liability; splitting it into non-core (still
    # overnight) + core (spread out over years, so DF(t) < 1 under any
    # curve with a positive rate) must reduce pv_liabilities and
    # therefore change eve, versus the nmd_decay_config=None baseline.
    balance_sheet = load_balance_sheet(DATA_DIR)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    decay_config = NmdDecayConfig(core_fraction=0.5, core_max_life_years=5.0, decay_frequency_months=1)

    eve_without_decay = compute_eve(balance_sheet, AS_OF_DATE, curve)
    eve_with_decay = compute_eve(balance_sheet, AS_OF_DATE, curve, nmd_decay_config=decay_config)

    assert eve_with_decay.pv_liabilities != pytest.approx(eve_without_decay.pv_liabilities)
    assert eve_with_decay.eve != pytest.approx(eve_without_decay.eve)
    # Assets and swap PV are unaffected -- nmd_decay_config only touches
    # NMD, which is always a liability.
    assert eve_with_decay.pv_assets == pytest.approx(eve_without_decay.pv_assets)
    assert eve_with_decay.swap_net_pv == pytest.approx(eve_without_decay.swap_net_pv)
