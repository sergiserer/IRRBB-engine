from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.domain.sot import SOTConfig
from app.engine.shocks import ShockScenarioResult


@dataclass
class SOTResult:
    tier1_capital: float
    threshold_pct: float
    threshold_amount: float
    worst_scenario: str
    worst_delta_eve: float
    ratio: float
    breaches: bool
    scenario_results: List[ShockScenarioResult]


def compute_sot(
    scenario_results: List[ShockScenarioResult],
    tier1_capital: float,
    config: SOTConfig,
) -> SOTResult:
    """Standardised Outlier Test de EVE (BCBS d368 Anexo 2 / EBA
    GL/2022/14): compara el peor delta_eve de los 6 escenarios (el de
    mayor perdida bajo la convencion EBA base_eve - eve_result.eve,
    donde positivo = perdida) contra threshold_pct * tier1_capital.

    'Peor' es siempre max(delta_eve), nunca max(abs(delta_eve)) -- un
    escenario de gran GANANCIA (delta_eve muy negativo) no debe poder
    disparar el SOT.

    No recalcula EVE ni escenarios -- toma la salida ya calculada de
    run_eba_shock_scenarios (Fase 4). tier1_capital es un parametro de
    entrada simple, responsabilidad del caller: este proyecto sintetico
    no tiene una cifra de capital real (ver design spec, seccion
    Non-goals)."""
    worst = max(scenario_results, key=lambda r: r.delta_eve)
    threshold_amount = tier1_capital * config.threshold_pct
    return SOTResult(
        tier1_capital=tier1_capital,
        threshold_pct=config.threshold_pct,
        threshold_amount=threshold_amount,
        worst_scenario=worst.scenario,
        worst_delta_eve=worst.delta_eve,
        ratio=worst.delta_eve / tier1_capital,
        breaches=worst.delta_eve > threshold_amount,
        scenario_results=scenario_results,
    )
