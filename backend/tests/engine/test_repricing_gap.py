from datetime import date
from pathlib import Path

import pytest

from app.data.loaders import load_balance_sheet
from app.domain.time_buckets import load_time_buckets
from app.engine.repricing_gap import build_gap_report

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


def test_bucket_row_gap_is_assets_minus_liabilities():
    balance_sheet = load_balance_sheet(DATA_DIR)
    buckets = load_time_buckets(CONFIG_PATH)

    report = build_gap_report(balance_sheet, AS_OF_DATE, buckets)

    for row in report.rows:
        assert row.gap == pytest.approx(row.assets - row.liabilities)
