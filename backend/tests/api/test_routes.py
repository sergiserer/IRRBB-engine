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
