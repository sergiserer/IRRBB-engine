from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List

from app.domain.balance_sheet import BalanceSheet
from app.domain.cash_flow import CashFlow
from app.domain.instruments import Swap
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.yield_curve import YieldCurve
from app.engine.cash_flow_generation import swap_leg_cash_flows
from app.engine.repricing_gap import generate_all_cash_flows


def pv(cash_flows: Iterable[CashFlow], as_of_date: date, yield_curve: YieldCurve) -> float:
    """Sum of amount * yield_curve.discount_factor(t), t = (cf.date -
    as_of_date).days / 365 (same 365-day convention used throughout the
    codebase). Discounts principal AND interest flows: unlike
    build_gap_report's repricing gap (principal only), EVE is defined
    over the full contractual cash flow."""
    total = 0.0
    for cf in cash_flows:
        t = (cf.date - as_of_date).days / 365
        total += cf.amount * yield_curve.discount_factor(t)
    return total


def swap_pv(swap: Swap, as_of_date: date, yield_curve: YieldCurve) -> float:
    """Net PV of a swap: PV(receive_leg) - PV(pay_leg). Off-balance-sheet
    — not split into asset/liability sides, added directly into EVE by
    compute_eve."""
    receive_flows = swap_leg_cash_flows(swap, swap.receive_leg, as_of_date, yield_curve)
    pay_flows = swap_leg_cash_flows(swap, swap.pay_leg, as_of_date, yield_curve)
    return pv(receive_flows, as_of_date, yield_curve) - pv(pay_flows, as_of_date, yield_curve)


@dataclass
class EVEResult:
    as_of_date: date
    pv_assets: float
    pv_liabilities: float
    swap_net_pv: float

    @property
    def eve(self) -> float:
        return self.pv_assets - self.pv_liabilities + self.swap_net_pv


def compute_eve(
    balance_sheet: BalanceSheet,
    as_of_date: date,
    yield_curve: YieldCurve,
    cpr_annual: float = 0.0,
    nmd_decay_config: NmdDecayConfig | None = None,
) -> EVEResult:
    """PV(assets) - PV(liabilities) + net swap PV under yield_curve.
    Discounts principal and interest cash flows (generate_all_cash_flows
    with a curve supplied projects floating instruments' full schedule —
    see Fase 3 design spec).

    cpr_annual (Fase 5 parte 1): constant CPR passed through to
    generate_all_cash_flows — see its docstring. Default 0.0 preserves
    Fase 3/4 behaviour exactly (no prepayment).

    nmd_decay_config (Fase 5 parte 2): constant NMD core/non-core decay
    passed through to generate_all_cash_flows — see its docstring.
    Default None preserves the Fase 2 overnight-placeholder behaviour
    exactly."""
    flows = generate_all_cash_flows(balance_sheet, as_of_date, yield_curve, cpr_annual, nmd_decay_config)
    asset_flows = [cf for cf in flows if cf.side == "asset"]
    liability_flows = [cf for cf in flows if cf.side == "liability"]
    swap_net_pv = sum(swap_pv(swap, as_of_date, yield_curve) for swap in balance_sheet.swaps)
    return EVEResult(
        as_of_date=as_of_date,
        pv_assets=pv(asset_flows, as_of_date, yield_curve),
        pv_liabilities=pv(liability_flows, as_of_date, yield_curve),
        swap_net_pv=swap_net_pv,
    )
