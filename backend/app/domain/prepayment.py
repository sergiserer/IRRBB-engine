from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PrepaymentConfig:
    cpr_annual: float


def load_prepayment_config(path: Path) -> PrepaymentConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return PrepaymentConfig(cpr_annual=raw["cpr_annual"])


def smm_for_period(cpr_annual: float, period_months: int) -> float:
    """Single-period mortality: the probability that a period's
    remaining balance prepays, converted from the annual conditional
    prepayment rate (CPR) for a period of length period_months.
    period_months=12 reduces to cpr_annual exactly."""
    return 1 - (1 - cpr_annual) ** (period_months / 12)
