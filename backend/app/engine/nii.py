from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

import pandas as pd

from app.domain.balance_sheet import BalanceSheet
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.yield_curve import YieldCurve
from app.engine.repricing_gap import generate_all_cash_flows

HORIZON_MONTHS = 24


def month_boundaries(as_of_date: date) -> List[date]:
    """HORIZON_MONTHS + 1 fechas frontera de calendario exactas:
    as_of_date + k meses para k=0..HORIZON_MONTHS (boundaries[0] es
    as_of_date). Usa pd.DateOffset, mismo mecanismo que las rejillas de
    fechas de mortgage_cash_flows/swap_leg_cash_flows -- exacto, sin
    aproximación de día fijo (a diferencia de TimeBucket, pensado para
    buckets de gap/EVE no uniformes, no para meses de calendario)."""
    return [(pd.Timestamp(as_of_date) + pd.DateOffset(months=k)).date() for k in range(HORIZON_MONTHS + 1)]


def month_index(cf_date: date, boundaries: List[date]) -> Optional[int]:
    """Índice k tal que boundaries[k] <= cf_date < boundaries[k+1]. None
    si cf_date cae fuera de [boundaries[0], boundaries[-1]) -- antes de
    as_of_date, o en/después del borde de HORIZON_MONTHS meses. No es un
    error: un balance run-off puede no generar flujos más allá del
    horizonte."""
    for k in range(len(boundaries) - 1):
        if boundaries[k] <= cf_date < boundaries[k + 1]:
            return k
    return None


@dataclass
class NIIResult:
    as_of_date: date
    monthly_net_interest: List[float]

    @property
    def nii_12m(self) -> float:
        return sum(self.monthly_net_interest[:12])

    @property
    def nii_24m(self) -> float:
        return sum(self.monthly_net_interest)


def compute_nii(
    balance_sheet: BalanceSheet,
    as_of_date: date,
    yield_curve: YieldCurve,
    cpr_annual: float = 0.0,
    nmd_decay_config: NmdDecayConfig | None = None,
) -> NIIResult:
    """Net interest income por mes de calendario sobre HORIZON_MONTHS
    meses, balance estático (run-off): el principal que vence/amortiza
    no se reinviste -- sale gratis de que generate_all_cash_flows ya deja
    de emitir flujos para un instrumento tras su vencimiento/amortización.
    Suma flow_type='interest': activo suma, pasivo resta. Flujos fuera de
    la ventana de HORIZON_MONTHS meses se descartan (ver month_index)."""
    boundaries = month_boundaries(as_of_date)
    monthly = [0.0] * HORIZON_MONTHS

    flows = generate_all_cash_flows(balance_sheet, as_of_date, yield_curve, cpr_annual, nmd_decay_config)
    for cf in flows:
        if cf.flow_type != "interest":
            continue
        idx = month_index(cf.date, boundaries)
        if idx is None:
            continue
        if cf.side == "asset":
            monthly[idx] += cf.amount
        else:
            monthly[idx] -= cf.amount

    return NIIResult(as_of_date=as_of_date, monthly_net_interest=monthly)
