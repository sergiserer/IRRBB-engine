from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List

from app.domain.balance_sheet import BalanceSheet
from app.domain.cash_flow import CashFlow
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.time_buckets import TimeBucket, bucket_for
from app.domain.yield_curve import YieldCurve
from app.engine.cash_flow_generation import (
    bond_cash_flows,
    issued_debt_cash_flows,
    mortgage_cash_flows,
    nmd_cash_flows,
    term_deposit_cash_flows,
)


def generate_all_cash_flows(
    balance_sheet: BalanceSheet,
    as_of_date: date,
    yield_curve: YieldCurve | None = None,
    cpr_annual: float = 0.0,
    nmd_decay_config: NmdDecayConfig | None = None,
) -> List[CashFlow]:
    """Dispatches to the per-type generators. Swaps are intentionally
    skipped — see app.engine.eve.compute_eve for how swaps are netted
    into EVE separately (they have no principal cash flows to slot).

    yield_curve is threaded through to the floating-rate branches of
    bond_cash_flows/issued_debt_cash_flows/mortgage_cash_flows: None
    (the default, used by build_gap_report) preserves Fase 2's
    bullet-principal-only behaviour; a supplied curve switches those
    branches to full forward-rate-projected schedules (Fase 3, used by
    app.engine.eve.compute_eve).

    cpr_annual (Fase 5 parte 1) is threaded ONLY to mortgage_cash_flows —
    bonds, issued debt, term deposits and NMDs have no prepayment model.

    nmd_decay_config (Fase 5 parte 2) is threaded ONLY to
    nmd_cash_flows — see its docstring. build_gap_report calls this with
    the default None, so NMD keeps landing entirely in the overnight
    bucket in this phase. Unlike cpr_annual's 'prepayment' flow type,
    nmd_decay_config's flows stay flow_type='principal', so
    build_gap_report's existing bucket filter would already handle them
    correctly if a future caller passed a config through it."""
    flows: List[CashFlow] = []
    for mortgage in balance_sheet.mortgages:
        flows.extend(mortgage_cash_flows(mortgage, as_of_date, yield_curve, cpr_annual))
    for bond in balance_sheet.bonds:
        flows.extend(bond_cash_flows(bond, as_of_date, yield_curve))
    for debt in balance_sheet.issued_debt:
        flows.extend(issued_debt_cash_flows(debt, as_of_date, yield_curve))
    for deposit in balance_sheet.term_deposits:
        flows.extend(term_deposit_cash_flows(deposit, as_of_date))
    for nmd in balance_sheet.nmd:
        flows.extend(nmd_cash_flows(nmd, as_of_date, nmd_decay_config))
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
