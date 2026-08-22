from __future__ import annotations

from datetime import date

from fastapi import Request

from app.domain.balance_sheet import BalanceSheet
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.shocks import ShockConfig
from app.domain.sot import SOTConfig
from app.domain.yield_curve import YieldCurve


def get_balance_sheet(request: Request) -> BalanceSheet:
    return request.app.state.balance_sheet


def get_yield_curve(request: Request) -> YieldCurve:
    return request.app.state.yield_curve


def get_as_of_date(request: Request) -> date:
    return request.app.state.as_of_date


def get_currency() -> str:
    return "EUR"


def get_shock_config(request: Request) -> ShockConfig:
    return request.app.state.shock_config


def get_sot_config(request: Request) -> SOTConfig:
    return request.app.state.sot_config


def get_cpr_annual(request: Request) -> float:
    return request.app.state.cpr_annual


def get_nmd_decay_config(request: Request) -> NmdDecayConfig:
    return request.app.state.nmd_decay_config
