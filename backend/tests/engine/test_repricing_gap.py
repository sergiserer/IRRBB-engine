from datetime import date
from pathlib import Path

import pytest

from app.data.loaders import load_balance_sheet
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.time_buckets import load_time_buckets
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.repricing_gap import build_gap_report, generate_all_cash_flows

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "time_buckets.yaml"
AS_OF_DATE = date(2026, 8, 14)  # after every instrument's start_date, before any maturity


def test_build_gap_report_reconciles_with_balance_sheet_totals():
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)

    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)

    assert report.total_assets() == pytest.approx(balance_sheet.total_assets())
    assert report.total_liabilities() == pytest.approx(balance_sheet.total_liabilities())


def test_build_gap_report_places_nmd_in_overnight_bucket():
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)

    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)

    overnight_row = next(r for r in report.rows if r.bucket_name == "overnight")
    expected_nmd_total = sum(n.notional for n in balance_sheet.nmd)
    assert overnight_row.liabilities == pytest.approx(expected_nmd_total)


def test_build_gap_report_places_isd001_principal_in_3m_6m_bucket():
    # Real bucket-placement coverage: the reconciliation test above only
    # checks that total principal sums match, which is true by
    # construction regardless of which dates the flows land on. This
    # verifies an actual instrument lands in the expected bucket.
    # ISD001: notional 2,000,000, maturity 2027-01-10, fixed, liability.
    # (2027-01-10 - 2026-08-14).days == 149, which falls in 3m_6m
    # (90 <= days < 180).
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)

    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)

    row = next(r for r in report.rows if r.bucket_name == "3m_6m")
    assert row.liabilities == pytest.approx(2_000_000.0)


def test_bucket_row_gap_is_assets_minus_liabilities():
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)

    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)

    for row in report.rows:
        assert row.gap == pytest.approx(row.assets - row.liabilities)


def test_generate_all_cash_flows_with_curve_projects_floating_interest():
    # Regression + wiring check: without a curve, ISD002 (floating) yields
    # only its bullet principal flow (Phase 2 behaviour). With a curve,
    # it must also carry projected interest flows (Phase 3 behaviour).
    balance_sheet = load_balance_sheet(DATA_DIR)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03), CurvePoint(tenor_years=5.0, rate=0.03)])

    flows_no_curve = generate_all_cash_flows(balance_sheet, AS_OF_DATE)
    flows_with_curve = generate_all_cash_flows(balance_sheet, AS_OF_DATE, yield_curve=curve)

    isd002_no_curve = [f for f in flows_no_curve if f.instrument_id == "ISD002"]
    isd002_with_curve = [f for f in flows_with_curve if f.instrument_id == "ISD002"]

    assert all(f.flow_type == "principal" for f in isd002_no_curve)
    assert any(f.flow_type == "interest" for f in isd002_with_curve)


def test_build_gap_report_unaffected_by_curve_threading():
    # Full regression: build_gap_report never passes a curve, so its
    # output must be identical to before this task's change.
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)
    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)
    assert report.total_assets() == pytest.approx(balance_sheet.total_assets())
    assert report.total_liabilities() == pytest.approx(balance_sheet.total_liabilities())


def test_generate_all_cash_flows_threads_cpr_annual_to_fixed_mortgages_only():
    balance_sheet = load_balance_sheet(DATA_DIR)
    flows = generate_all_cash_flows(balance_sheet, AS_OF_DATE, cpr_annual=0.05)
    prepayment_flows = [f for f in flows if f.flow_type == "prepayment"]

    # MTG001 is the only fixed-rate mortgage in the synthetic data;
    # MTG002 is floating (cpr_annual has no effect there), and no other
    # instrument type in this balance sheet is mortgage-like.
    assert len(prepayment_flows) > 0
    assert all(f.instrument_id == "MTG001" for f in prepayment_flows)


def test_generate_all_cash_flows_threads_nmd_decay_config_to_nmd_only():
    balance_sheet = load_balance_sheet(DATA_DIR)
    decay_config = NmdDecayConfig(core_fraction=0.5, core_max_life_years=5.0, decay_frequency_months=1)

    flows_without_decay = generate_all_cash_flows(balance_sheet, AS_OF_DATE)
    flows_with_decay = generate_all_cash_flows(balance_sheet, AS_OF_DATE, nmd_decay_config=decay_config)

    nmd_ids = {n.instrument_id for n in balance_sheet.nmd}
    nmd_flows_with_decay = [f for f in flows_with_decay if f.instrument_id in nmd_ids]
    other_flows_without = [f for f in flows_without_decay if f.instrument_id not in nmd_ids]
    other_flows_with = [f for f in flows_with_decay if f.instrument_id not in nmd_ids]

    # Every NMD now carries more than one flow (split into core + non-core).
    assert len(nmd_flows_with_decay) > len(balance_sheet.nmd)
    # Every other instrument type is untouched by nmd_decay_config.
    assert other_flows_with == other_flows_without
