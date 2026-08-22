from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_as_of_date,
    get_balance_sheet,
    get_cpr_annual,
    get_currency,
    get_nmd_decay_config,
    get_shock_config,
    get_sot_config,
    get_yield_curve,
)
from app.api.main import app
from app.data.ecb_client import parse_ecb_csv
from app.data.loaders import load_balance_sheet
from app.domain.nmd_decay import load_nmd_decay_config
from app.domain.prepayment import load_prepayment_config
from app.domain.shocks import load_shock_config
from app.domain.sot import load_sot_config
from app.engine.eve import compute_eve
from app.engine.nii import run_nii_scenarios
from app.engine.shocks import run_eba_shock_scenarios
from app.engine.sot import compute_sot

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "ecb_curve_sample.csv"
AS_OF_DATE = date(2026, 8, 14)  # misma fecha que test_shock_scenarios.py / test_sot.py

_balance_sheet = load_balance_sheet(DATA_DIR)
_yield_curve = parse_ecb_csv(FIXTURE_PATH.read_text())
_shock_config = load_shock_config(CONFIG_DIR / "eba_shocks.yaml")
_sot_config = load_sot_config(CONFIG_DIR / "sot.yaml")
_cpr_annual = load_prepayment_config(CONFIG_DIR / "prepayment.yaml").cpr_annual
_nmd_decay_config = load_nmd_decay_config(CONFIG_DIR / "nmd_decay.yaml")


@pytest.fixture
def client():
    app.dependency_overrides[get_balance_sheet] = lambda: _balance_sheet
    app.dependency_overrides[get_yield_curve] = lambda: _yield_curve
    app.dependency_overrides[get_as_of_date] = lambda: AS_OF_DATE
    app.dependency_overrides[get_currency] = lambda: "EUR"
    app.dependency_overrides[get_shock_config] = lambda: _shock_config
    app.dependency_overrides[get_sot_config] = lambda: _sot_config
    app.dependency_overrides[get_cpr_annual] = lambda: _cpr_annual
    app.dependency_overrides[get_nmd_decay_config] = lambda: _nmd_decay_config
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_balance_sheet_summary(client):
    response = client.get("/balance-sheet")
    assert response.status_code == 200
    body = response.json()
    assert body["total_assets"] == pytest.approx(_balance_sheet.total_assets())
    assert body["total_liabilities"] == pytest.approx(_balance_sheet.total_liabilities())
    assert body["counts"] == {
        "mortgages": len(_balance_sheet.mortgages),
        "bonds": len(_balance_sheet.bonds),
        "term_deposits": len(_balance_sheet.term_deposits),
        "nmd": len(_balance_sheet.nmd),
        "issued_debt": len(_balance_sheet.issued_debt),
        "swaps": len(_balance_sheet.swaps),
    }


def test_cors_allows_configured_localhost_origin(client):
    response = client.get("/eve", headers={"Origin": "http://localhost:5173"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_get_eve_matches_direct_engine_call(client):
    response = client.get("/eve")
    assert response.status_code == 200
    expected = compute_eve(_balance_sheet, AS_OF_DATE, _yield_curve, _cpr_annual, _nmd_decay_config)
    body = response.json()
    assert body["as_of_date"] == AS_OF_DATE.isoformat()
    assert body["pv_assets"] == pytest.approx(expected.pv_assets)
    assert body["pv_liabilities"] == pytest.approx(expected.pv_liabilities)
    assert body["swap_net_pv"] == pytest.approx(expected.swap_net_pv)
    assert body["eve"] == pytest.approx(expected.eve)


def test_get_shocks_matches_direct_engine_call(client):
    response = client.get("/shocks")
    assert response.status_code == 200
    expected = run_eba_shock_scenarios(
        _balance_sheet, AS_OF_DATE, _yield_curve, "EUR", _shock_config, _cpr_annual, _nmd_decay_config
    )
    body = response.json()
    assert len(body) == 6
    assert [r["scenario"] for r in body] == [e.scenario for e in expected]
    for r, e in zip(body, expected):
        assert r["base_eve"] == pytest.approx(e.base_eve)
        assert r["delta_eve"] == pytest.approx(e.delta_eve)
        assert r["eve_result"]["eve"] == pytest.approx(e.eve_result.eve)


def test_get_nii_matches_direct_engine_call(client):
    response = client.get("/nii")
    assert response.status_code == 200
    expected = run_nii_scenarios(
        _balance_sheet, AS_OF_DATE, _yield_curve, "EUR", _shock_config, _cpr_annual, _nmd_decay_config
    )
    body = response.json()
    assert len(body) == 2
    assert [r["scenario"] for r in body] == [e.scenario for e in expected]
    for r, e in zip(body, expected):
        assert r["base_nii_12m"] == pytest.approx(e.base_nii_12m)
        assert r["base_nii_24m"] == pytest.approx(e.base_nii_24m)
        assert r["delta_nii_12m"] == pytest.approx(e.delta_nii_12m)
        assert r["delta_nii_24m"] == pytest.approx(e.delta_nii_24m)
        assert r["nii_12m"] == pytest.approx(e.nii_result.nii_12m)
        assert r["nii_24m"] == pytest.approx(e.nii_result.nii_24m)
        assert r["monthly_net_interest"] == pytest.approx(e.nii_result.monthly_net_interest)


def test_get_sot_matches_direct_engine_call(client):
    tier1_capital = 100_000_000.0
    response = client.get("/sot", params={"tier1_capital": tier1_capital})
    assert response.status_code == 200
    scenario_results = run_eba_shock_scenarios(
        _balance_sheet, AS_OF_DATE, _yield_curve, "EUR", _shock_config, _cpr_annual, _nmd_decay_config
    )
    expected = compute_sot(scenario_results, tier1_capital, _sot_config)
    body = response.json()
    assert body["tier1_capital"] == pytest.approx(expected.tier1_capital)
    assert body["threshold_pct"] == pytest.approx(expected.threshold_pct)
    assert body["threshold_amount"] == pytest.approx(expected.threshold_amount)
    assert body["worst_scenario"] == expected.worst_scenario
    assert body["worst_delta_eve"] == pytest.approx(expected.worst_delta_eve)
    assert body["ratio"] == pytest.approx(expected.ratio)
    assert body["breaches"] == expected.breaches
    assert len(body["scenario_results"]) == 6


def test_get_sot_missing_tier1_capital_returns_422(client):
    response = client.get("/sot")
    assert response.status_code == 422


def test_get_sot_non_positive_tier1_capital_returns_422(client):
    response = client.get("/sot", params={"tier1_capital": 0})
    assert response.status_code == 422


def test_get_sot_infinite_tier1_capital_returns_422(client):
    response = client.get("/sot", params={"tier1_capital": "inf"})
    assert response.status_code == 422


@pytest.mark.integration
def test_real_app_startup_and_balance_sheet_endpoint():
    with TestClient(app) as real_client:
        response = real_client.get("/balance-sheet")
        sot_response = real_client.get("/sot", params={"tier1_capital": 100_000_000.0})
    assert response.status_code == 200
    assert response.json()["total_assets"] > 0
    assert sot_response.status_code == 200
