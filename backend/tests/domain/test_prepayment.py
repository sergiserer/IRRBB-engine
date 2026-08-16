from pathlib import Path

import pytest

from app.domain.prepayment import PrepaymentConfig, load_prepayment_config, smm_for_period

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "prepayment.yaml"


def test_load_prepayment_config_reads_cpr_annual():
    config = load_prepayment_config(CONFIG_PATH)
    assert config == PrepaymentConfig(cpr_annual=0.05)


def test_smm_for_period_monthly_reference_case():
    # cpr_annual=0.06, monthly period: smm = 1 - (1 - 0.06) ** (1/12).
    # Computed independently in Python (not by calling smm_for_period):
    # 1 - 0.94**(1/12) = 0.005143012831822946
    assert smm_for_period(0.06, 1) == pytest.approx(0.005143012831822946, rel=1e-9)


def test_smm_for_period_annual_period_equals_cpr():
    # period_months=12 must reduce to the annual CPR exactly (a 12-month
    # "period" IS the annual period the CPR is quoted for).
    assert smm_for_period(0.06, 12) == pytest.approx(0.06)


def test_smm_for_period_zero_cpr_is_zero():
    assert smm_for_period(0.0, 1) == 0.0
