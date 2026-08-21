from datetime import date
from pathlib import Path

import pytest

from app.data.loaders import load_balance_sheet
from app.domain.shocks import load_shock_config
from app.domain.sot import SOTConfig
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.eve import EVEResult
from app.engine.shocks import ShockScenarioResult, run_eba_shock_scenarios
from app.engine.sot import compute_sot

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
SHOCK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "eba_shocks.yaml"
AS_OF_DATE = date(2026, 8, 14)  # same as test_shock_scenarios.py


def _result(scenario: str, delta_eve: float) -> ShockScenarioResult:
    # eve_result/base_eve values are irrelevant to compute_sot -- it only
    # reads .scenario and .delta_eve from each ShockScenarioResult, and
    # stores the list as-is for traceability. Placeholder EVEResult keeps
    # these fixtures focused on what compute_sot actually consumes.
    eve_result = EVEResult(as_of_date=date(2026, 1, 1), pv_assets=0.0, pv_liabilities=0.0, swap_net_pv=0.0)
    return ShockScenarioResult(scenario=scenario, base_eve=0.0, eve_result=eve_result, delta_eve=delta_eve)


def test_compute_sot_reference_case_no_breach():
    # 6 escenarios sinteticos, el peor es parallel_up con delta_eve=500_000.
    # tier1_capital=10_000_000, threshold_pct=0.15 -> threshold_amount=1_500_000.
    # 500_000 < 1_500_000 -> no rompe el umbral. ratio = 500_000/10_000_000 = 0.05.
    scenario_results = [
        _result("parallel_up", 500_000.0),
        _result("parallel_down", -200_000.0),
        _result("steepener", 100_000.0),
        _result("flattener", 50_000.0),
        _result("short_up", 300_000.0),
        _result("short_down", -150_000.0),
    ]
    config = SOTConfig(threshold_pct=0.15)

    result = compute_sot(scenario_results, tier1_capital=10_000_000.0, config=config)

    assert result.tier1_capital == pytest.approx(10_000_000.0)
    assert result.threshold_pct == pytest.approx(0.15)
    assert result.threshold_amount == pytest.approx(1_500_000.0)
    assert result.worst_scenario == "parallel_up"
    assert result.worst_delta_eve == pytest.approx(500_000.0)
    assert result.ratio == pytest.approx(0.05)
    assert result.breaches is False
    assert result.scenario_results == scenario_results


def test_compute_sot_reference_case_breaches():
    # Mismos 6 escenarios, tier1_capital mas bajo: threshold_amount =
    # 2_000_000 * 0.15 = 300_000 < 500_000 (peor delta_eve) -> rompe.
    # ratio = 500_000 / 2_000_000 = 0.25.
    scenario_results = [
        _result("parallel_up", 500_000.0),
        _result("parallel_down", -200_000.0),
        _result("steepener", 100_000.0),
        _result("flattener", 50_000.0),
        _result("short_up", 300_000.0),
        _result("short_down", -150_000.0),
    ]
    config = SOTConfig(threshold_pct=0.15)

    result = compute_sot(scenario_results, tier1_capital=2_000_000.0, config=config)

    assert result.threshold_amount == pytest.approx(300_000.0)
    assert result.worst_delta_eve == pytest.approx(500_000.0)
    assert result.ratio == pytest.approx(0.25)
    assert result.breaches is True


def test_compute_sot_worst_scenario_ignores_large_gains():
    # parallel_up tiene el mayor VALOR ABSOLUTO (-900_000) pero es una
    # GANANCIA grande (delta_eve muy negativo bajo la convencion EBA), no
    # una perdida. El peor escenario real es parallel_down (+200_000, la
    # mayor perdida). tier1_capital=1_000_000 -> threshold_amount=150_000
    # < 200_000 -> rompe. Confirma que "peor" = max(delta_eve), no max(abs()).
    scenario_results = [
        _result("parallel_up", -900_000.0),
        _result("parallel_down", 200_000.0),
        _result("steepener", -50_000.0),
        _result("flattener", 10_000.0),
        _result("short_up", -30_000.0),
        _result("short_down", 5_000.0),
    ]
    config = SOTConfig(threshold_pct=0.15)

    result = compute_sot(scenario_results, tier1_capital=1_000_000.0, config=config)

    assert result.worst_scenario == "parallel_down"
    assert result.worst_delta_eve == pytest.approx(200_000.0)
    assert result.ratio == pytest.approx(0.2)
    assert result.breaches is True


def test_compute_sot_integrates_with_real_run_eba_shock_scenarios():
    # No es un caso de referencia a mano (los valores de EVE ya estan
    # verificados por test_shock_scenarios.py) -- confirma que compute_sot
    # conecta correctamente con la salida real de run_eba_shock_scenarios:
    # el peor delta_eve/escenario que compute_sot reporta debe coincidir
    # con el maximo calculado independientemente aqui mismo.
    balance_sheet = load_balance_sheet(DATA_DIR)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    shock_config = load_shock_config(SHOCK_CONFIG_PATH)
    scenario_results = run_eba_shock_scenarios(balance_sheet, AS_OF_DATE, base_curve, "EUR", shock_config)
    sot_config = SOTConfig(threshold_pct=0.15)

    result = compute_sot(scenario_results, tier1_capital=50_000_000.0, config=sot_config)

    expected_worst = max(scenario_results, key=lambda r: r.delta_eve)
    assert result.worst_scenario == expected_worst.scenario
    assert result.worst_delta_eve == pytest.approx(expected_worst.delta_eve)
    assert result.threshold_amount == pytest.approx(50_000_000.0 * 0.15)
    assert result.ratio == pytest.approx(expected_worst.delta_eve / 50_000_000.0)
    assert result.breaches == (expected_worst.delta_eve > 50_000_000.0 * 0.15)
    assert result.scenario_results == scenario_results
    assert len(result.scenario_results) == 6
