from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_as_of_date,
    get_balance_sheet,
    get_cpr_annual,
    get_currency,
    get_nmd_decay_config,
    get_shock_config,
    get_yield_curve,
)
from app.api.schemas import BalanceSheetSummary, EVEResponse, NIIScenarioResponse, ShockScenarioResponse
from app.domain.balance_sheet import BalanceSheet
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.shocks import ShockConfig
from app.domain.yield_curve import YieldCurve
from app.engine.eve import EVEResult, compute_eve
from app.engine.nii import NIIScenarioResult, run_nii_scenarios
from app.engine.shocks import ShockScenarioResult, run_eba_shock_scenarios


router = APIRouter()


@router.get("/balance-sheet", response_model=BalanceSheetSummary)
def get_balance_sheet_summary(
    balance_sheet: BalanceSheet = Depends(get_balance_sheet),
) -> BalanceSheetSummary:
    return BalanceSheetSummary(
        total_assets=balance_sheet.total_assets(),
        total_liabilities=balance_sheet.total_liabilities(),
        counts={
            "mortgages": len(balance_sheet.mortgages),
            "bonds": len(balance_sheet.bonds),
            "term_deposits": len(balance_sheet.term_deposits),
            "nmd": len(balance_sheet.nmd),
            "issued_debt": len(balance_sheet.issued_debt),
            "swaps": len(balance_sheet.swaps),
        },
    )


def _eve_response(result: EVEResult) -> EVEResponse:
    return EVEResponse(
        as_of_date=result.as_of_date,
        pv_assets=result.pv_assets,
        pv_liabilities=result.pv_liabilities,
        swap_net_pv=result.swap_net_pv,
        eve=result.eve,
    )


@router.get("/eve", response_model=EVEResponse)
def get_eve(
    balance_sheet: BalanceSheet = Depends(get_balance_sheet),
    as_of_date: date = Depends(get_as_of_date),
    yield_curve: YieldCurve = Depends(get_yield_curve),
    cpr_annual: float = Depends(get_cpr_annual),
    nmd_decay_config: NmdDecayConfig = Depends(get_nmd_decay_config),
) -> EVEResponse:
    result = compute_eve(balance_sheet, as_of_date, yield_curve, cpr_annual, nmd_decay_config)
    return _eve_response(result)


def _shock_scenario_response(result: ShockScenarioResult) -> ShockScenarioResponse:
    return ShockScenarioResponse(
        scenario=result.scenario,
        base_eve=result.base_eve,
        delta_eve=result.delta_eve,
        eve_result=_eve_response(result.eve_result),
    )


@router.get("/shocks", response_model=list[ShockScenarioResponse])
def get_shocks(
    balance_sheet: BalanceSheet = Depends(get_balance_sheet),
    as_of_date: date = Depends(get_as_of_date),
    yield_curve: YieldCurve = Depends(get_yield_curve),
    currency: str = Depends(get_currency),
    shock_config: ShockConfig = Depends(get_shock_config),
    cpr_annual: float = Depends(get_cpr_annual),
    nmd_decay_config: NmdDecayConfig = Depends(get_nmd_decay_config),
) -> list[ShockScenarioResponse]:
    results = run_eba_shock_scenarios(
        balance_sheet, as_of_date, yield_curve, currency, shock_config, cpr_annual, nmd_decay_config
    )
    return [_shock_scenario_response(r) for r in results]


def _nii_scenario_response(result: NIIScenarioResult) -> NIIScenarioResponse:
    return NIIScenarioResponse(
        scenario=result.scenario,
        base_nii_12m=result.base_nii_12m,
        base_nii_24m=result.base_nii_24m,
        delta_nii_12m=result.delta_nii_12m,
        delta_nii_24m=result.delta_nii_24m,
        as_of_date=result.nii_result.as_of_date,
        monthly_net_interest=result.nii_result.monthly_net_interest,
        nii_12m=result.nii_result.nii_12m,
        nii_24m=result.nii_result.nii_24m,
    )


@router.get("/nii", response_model=list[NIIScenarioResponse])
def get_nii(
    balance_sheet: BalanceSheet = Depends(get_balance_sheet),
    as_of_date: date = Depends(get_as_of_date),
    yield_curve: YieldCurve = Depends(get_yield_curve),
    currency: str = Depends(get_currency),
    shock_config: ShockConfig = Depends(get_shock_config),
    cpr_annual: float = Depends(get_cpr_annual),
    nmd_decay_config: NmdDecayConfig = Depends(get_nmd_decay_config),
) -> list[NIIScenarioResponse]:
    results = run_nii_scenarios(
        balance_sheet, as_of_date, yield_curve, currency, shock_config, cpr_annual, nmd_decay_config
    )
    return [_nii_scenario_response(r) for r in results]
