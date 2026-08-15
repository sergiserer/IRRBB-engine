from pathlib import Path

import pytest

from app.domain.shocks import SCENARIOS, load_shock_config, shock_function

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
