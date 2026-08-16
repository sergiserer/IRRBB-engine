from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

FlowType = Literal["principal", "interest", "prepayment"]
Side = Literal["asset", "liability"]


@dataclass(frozen=True)
class CashFlow:
    instrument_id: str
    currency: str
    date: date
    amount: float
    flow_type: FlowType
    side: Side
