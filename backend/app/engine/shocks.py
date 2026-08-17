from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List

from app.domain.balance_sheet import BalanceSheet
from app.domain.nmd_decay import NmdDecayConfig
from app.domain.shocks import SCENARIOS, ShockConfig, apply_shock
from app.domain.yield_curve import YieldCurve
from app.engine.eve import EVEResult, compute_eve


@dataclass
class ShockScenarioResult:
    scenario: str
    base_eve: float
    eve_result: EVEResult
    delta_eve: float
    # EBA convention: base_eve - eve_result.eve, so a positive delta_eve
    # is an economic loss under the scenario.


def run_eba_shock_scenarios(
    balance_sheet: BalanceSheet,
    as_of_date: date,
    base_curve: YieldCurve,
    currency: str,
    config: ShockConfig,
    cpr_annual: float = 0.0,
    nmd_decay_config: NmdDecayConfig | None = None,
) -> List[ShockScenarioResult]:
    """Runs compute_eve under base_curve, then under each of the 6
    apply_shock(...) curves in SCENARIOS order. balance_sheet is assumed
    pre-filtered by currency by the caller, consistent with compute_eve's
    existing convention (Phase 3: 'caller pre-filters by currency').

    cpr_annual (Fase 5 parte 1): constant CPR passed through to every
    compute_eve call (base and all 6 shocked curves) — see its
    docstring. Default 0.0 preserves Fase 4 behaviour exactly.

    nmd_decay_config (Fase 5 parte 2): constant NMD core/non-core decay
    passed through to every compute_eve call (base and all 6 shocked
    curves) — see its docstring. Default None preserves prior behaviour
    exactly."""
    base_eve = compute_eve(balance_sheet, as_of_date, base_curve, cpr_annual, nmd_decay_config).eve
    results: List[ShockScenarioResult] = []
    for scenario in SCENARIOS:
        shocked_curve = apply_shock(base_curve, scenario, currency, config)
        eve_result = compute_eve(balance_sheet, as_of_date, shocked_curve, cpr_annual, nmd_decay_config)
        results.append(
            ShockScenarioResult(
                scenario=scenario,
                base_eve=base_eve,
                eve_result=eve_result,
                delta_eve=base_eve - eve_result.eve,
            )
        )
    return results
