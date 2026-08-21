from __future__ import annotations

from datetime import date
from typing import List, Optional

import pandas as pd

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
