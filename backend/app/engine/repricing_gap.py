from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List

from app.domain.balance_sheet import BalanceSheet
from app.domain.cash_flow import CashFlow
from app.domain.time_buckets import TimeBucket, bucket_for
from app.engine.cash_flow_generation import (
    bond_cash_flows,
    issued_debt_cash_flows,
    mortgage_cash_flows,
    nmd_cash_flows,
    term_deposit_cash_flows,
)


def generate_all_cash_flows(balance_sheet: BalanceSheet, as_of_date: date) -> List[CashFlow]:
    """Dispatches to the per-type generators. Swaps are intentionally
    skipped — see the Fase 2 design spec's non-goals."""
    flows: List[CashFlow] = []
    for mortgage in balance_sheet.mortgages:
        flows.extend(mortgage_cash_flows(mortgage, as_of_date))
    for bond in balance_sheet.bonds:
        flows.extend(bond_cash_flows(bond, as_of_date))
    for debt in balance_sheet.issued_debt:
        flows.extend(issued_debt_cash_flows(debt, as_of_date))
    for deposit in balance_sheet.term_deposits:
        flows.extend(term_deposit_cash_flows(deposit, as_of_date))
    for nmd in balance_sheet.nmd:
        flows.extend(nmd_cash_flows(nmd, as_of_date))
    return flows


@dataclass(frozen=True)
class BucketRow:
    bucket_name: str
    assets: float
    liabilities: float

    @property
    def gap(self) -> float:
        return self.assets - self.liabilities


@dataclass
class GapReport:
    as_of_date: date
    rows: List[BucketRow]

    def total_assets(self) -> float:
        return sum(row.assets for row in self.rows)

    def total_liabilities(self) -> float:
        return sum(row.liabilities for row in self.rows)


def build_gap_report(
    balance_sheet: BalanceSheet, as_of_date: date, buckets: List[TimeBucket]
) -> GapReport:
    """Aggregates principal cash flows only — interest cash flows feed NII
    projection (Fase 6), not the repricing/EVE-style principal gap.

    Sums cf.amount regardless of cf.currency: the caller is responsible
    for pre-filtering balance_sheet to a single currency (e.g. via
    BalanceSheet.by_currency()) before calling this function if the
    balance sheet spans multiple currencies, since IRRBB is computed per
    material currency."""
    flows = generate_all_cash_flows(balance_sheet, as_of_date)
    totals = {bucket.name: {"asset": 0.0, "liability": 0.0} for bucket in buckets}
    for cf in flows:
        if cf.flow_type != "principal":
            continue
        bucket_name = bucket_for(cf.date, as_of_date, buckets)
        totals[bucket_name][cf.side] += cf.amount

    rows = [
        BucketRow(
            bucket_name=bucket.name,
            assets=totals[bucket.name]["asset"],
            liabilities=totals[bucket.name]["liability"],
        )
        for bucket in buckets
    ]
    return GapReport(as_of_date=as_of_date, rows=rows)
