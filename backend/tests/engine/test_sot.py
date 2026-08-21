from datetime import date

import pytest

from app.domain.sot import SOTConfig
from app.engine.eve import EVEResult
from app.engine.shocks import ShockScenarioResult
from app.engine.sot import compute_sot


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
