from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class BalanceSheetSummary(BaseModel):
    total_assets: float
    total_liabilities: float
    counts: dict[str, int]


class EVEResponse(BaseModel):
    as_of_date: date
    pv_assets: float
    pv_liabilities: float
    swap_net_pv: float
    eve: float


class ShockScenarioResponse(BaseModel):
    scenario: str
    base_eve: float
    delta_eve: float
    eve_result: EVEResponse


class NIIScenarioResponse(BaseModel):
    scenario: str
    base_nii_12m: float
    base_nii_24m: float
    delta_nii_12m: float
    delta_nii_24m: float
    as_of_date: date
    monthly_net_interest: list[float]
    nii_12m: float
    nii_24m: float


class SOTResponse(BaseModel):
    tier1_capital: float
    threshold_pct: float
    threshold_amount: float
    worst_scenario: str
    worst_delta_eve: float
    ratio: float
    breaches: bool
    scenario_results: list[ShockScenarioResponse]
