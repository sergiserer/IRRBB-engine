from datetime import date
from pathlib import Path

import pytest

from app.data.loaders import load_balance_sheet
from app.domain.shocks import SCENARIOS, apply_shock, load_shock_config
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.eve import compute_eve
from app.engine.shocks import run_eba_shock_scenarios

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "eba_shocks.yaml"
AS_OF_DATE = date(2026, 8, 14)  # same as test_eve.py: after every start_date, before any maturity


def _config():
    return load_shock_config(CONFIG_PATH)


def test_run_eba_shock_scenarios_returns_all_six_scenarios_in_order():
    balance_sheet = load_balance_sheet(DATA_DIR)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    results = run_eba_shock_scenarios(balance_sheet, AS_OF_DATE, base_curve, "EUR", _config())
    assert [r.scenario for r in results] == SCENARIOS

    expected_base_eve = compute_eve(balance_sheet, AS_OF_DATE, base_curve).eve
    assert all(r.base_eve == pytest.approx(expected_base_eve) for r in results)
    # base_eve is the same value repeated across all 6 results, not
    # recomputed per-scenario.
    assert len({r.base_eve for r in results}) == 1


def test_parallel_shocks_move_eve_in_opposite_directions_reference_case():
    # Flat 0% base curve: EBA parallel_up/down (Delta(t) constant across
    # all t) is exactly equivalent to a plain flat YieldCurve at +/-2%
    # (EUR parallel = 0.02 in eba_shocks.yaml) -- so these delta_eve
    # values are independently verifiable via compute_eve against a
    # plain flat curve, with no dependency on this task's own code.
    balance_sheet = load_balance_sheet(DATA_DIR)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.0)])
    results = run_eba_shock_scenarios(balance_sheet, AS_OF_DATE, base_curve, "EUR", _config())

    parallel_up = next(r for r in results if r.scenario == "parallel_up")
    parallel_down = next(r for r in results if r.scenario == "parallel_down")

    assert parallel_up.delta_eve == pytest.approx(-763236.9922993672, rel=1e-9)
    assert parallel_down.delta_eve == pytest.approx(674451.7043335, rel=1e-9)
    # Duration-mismatch sign check: a parallel-up and a parallel-down
    # shock must move EVE in opposite directions.
    assert parallel_up.delta_eve * parallel_down.delta_eve < 0


def test_run_eba_shock_scenarios_flattener_reconciles_with_manual_apply_shock():
    # Reconciliation test (same pattern as Phase 3's full-balance-sheet
    # EVE check in test_eve.py): the aggregate engine's flattener result
    # must equal calling apply_shock + compute_eve directly for that one
    # scenario -- exercises the full t-dependent formula end-to-end
    # without pinning a fragile aggregate magic number.
    balance_sheet = load_balance_sheet(DATA_DIR)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    config = _config()

    results = run_eba_shock_scenarios(balance_sheet, AS_OF_DATE, base_curve, "EUR", config)
    flattener = next(r for r in results if r.scenario == "flattener")

    shocked_curve = apply_shock(base_curve, "flattener", "EUR", config)
    expected_eve_result = compute_eve(balance_sheet, AS_OF_DATE, shocked_curve)
    expected_base_eve = compute_eve(balance_sheet, AS_OF_DATE, base_curve).eve

    assert flattener.eve_result.eve == pytest.approx(expected_eve_result.eve)
    assert flattener.delta_eve == pytest.approx(expected_base_eve - expected_eve_result.eve)
