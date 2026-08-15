from datetime import date

import pytest

from app.domain.balance_sheet import BalanceSheet
from app.domain.cash_flow import CashFlow
from app.domain.instruments import Bond, Leg, Swap, TermDeposit
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.eve import compute_eve, pv, swap_pv


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
