from pathlib import Path

import pytest

from app.domain.shocks import SCENARIOS, load_shock_config, shock_function, ShockedYieldCurve, apply_shock
from app.domain.yield_curve import CurvePoint, YieldCurve

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "eba_shocks.yaml"


def _config():
    return load_shock_config(CONFIG_PATH)


def test_load_shock_config_reads_eur_params():
    config = _config()
    assert config.decay_years == 4.0
    assert config.currency_params["EUR"] == {"parallel": 0.02, "short": 0.025, "long": 0.01}
    assert config.scenario_weights["steepener"] == {"short": -0.65, "long": 0.90}
    assert config.scenario_weights["flattener"] == {"short": 0.80, "long": -0.60}


def test_shock_function_unknown_scenario_raises():
    config = _config()
    with pytest.raises(ValueError):
        shock_function("not_a_scenario", "EUR", config)


def test_shock_function_unknown_currency_raises():
    config = _config()
    with pytest.raises(ValueError):
        shock_function("parallel_up", "USD", config)


@pytest.mark.parametrize(
    "scenario,expected_at_t2",
    [
        ("parallel_up", 0.02),
        ("parallel_down", -0.02),
        ("short_up", 0.015163266492815837),
        ("short_down", -0.015163266492815837),
        ("steepener", -0.006314899157743994),
        ("flattener", 0.00976979715252847),
    ],
)
def test_shock_function_reference_values_at_t2(scenario, expected_at_t2):
    # Reference values: dshort(2) = 0.025*exp(-2/4), dlong(2) =
    # 0.01*(1-exp(-2/4)); steepener = -0.65*dshort + 0.90*dlong;
    # flattener = 0.80*dshort - 0.60*dlong. Computed via plain Python
    # math.exp, independent of the implementation under test.
    config = _config()
    fn = shock_function(scenario, "EUR", config)
    assert fn(2.0) == pytest.approx(expected_at_t2, rel=1e-9)


def test_all_scenarios_have_a_shock_function():
    config = _config()
    for scenario in SCENARIOS:
        fn = shock_function(scenario, "EUR", config)
        assert isinstance(fn(1.0), float)


def _flat_base(rate: float) -> YieldCurve:
    return YieldCurve([CurvePoint(tenor_years=1.0, rate=rate)])


def test_shocked_yield_curve_rate_at_adds_shock_to_base():
    # base flat 3% + short_up shock (EUR): rate_at(t) = 0.03 + dshort(t).
    # dshort(1) = 0.025*exp(-1/4) = 0.019470019576785124
    # dshort(2) = 0.025*exp(-2/4) = 0.015163266492815837
    config = _config()
    curve = apply_shock(_flat_base(0.03), "short_up", "EUR", config)
    assert curve.rate_at(1.0) == pytest.approx(0.049470019576785124, rel=1e-9)
    assert curve.rate_at(2.0) == pytest.approx(0.04516326649281584, rel=1e-9)


def test_shocked_yield_curve_discount_factor_uses_shocked_rate():
    # DF(t) = 1/(1+rate_at(t))^t using the shocked rates above.
    config = _config()
    curve = apply_shock(_flat_base(0.03), "short_up", "EUR", config)
    assert curve.discount_factor(1.0) == pytest.approx(0.9528619030043995, rel=1e-9)
    assert curve.discount_factor(2.0) == pytest.approx(0.9154438785349346, rel=1e-9)


def test_shocked_yield_curve_forward_rate_derives_from_shocked_discount_factors():
    # F(1,2) = DF(1)/DF(2) - 1, using the shocked discount factors above.
    config = _config()
    curve = apply_shock(_flat_base(0.03), "short_up", "EUR", config)
    assert curve.forward_rate(1.0, 2.0) == pytest.approx(0.0408741872077929, rel=1e-9)


def test_apply_shock_returns_a_yield_curve_instance():
    config = _config()
    curve = apply_shock(_flat_base(0.0), "parallel_up", "EUR", config)
    assert isinstance(curve, YieldCurve)
    assert isinstance(curve, ShockedYieldCurve)
