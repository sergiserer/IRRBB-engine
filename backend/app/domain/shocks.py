from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict

import yaml

SCENARIOS = [
    "parallel_up",
    "parallel_down",
    "steepener",
    "flattener",
    "short_up",
    "short_down",
]


@dataclass(frozen=True)
class ShockConfig:
    decay_years: float
    scenario_weights: Dict[str, Dict[str, float]]
    currency_params: Dict[str, Dict[str, float]]


def load_shock_config(path: Path) -> ShockConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ShockConfig(
        decay_years=raw["decay_years"],
        scenario_weights=raw["scenario_weights"],
        currency_params=raw["currencies"],
    )


def shock_function(scenario: str, currency: str, config: ShockConfig) -> Callable[[float], float]:
    """Returns Delta(t) for the given EBA/BCBS d368 Annex 2 scenario:

        Dshort(t) = R_short * exp(-t / decay_years)
        Dlong(t)  = R_long * (1 - exp(-t / decay_years))

        parallel_up/down : +/- R_parallel (constant)
        short_up/down    : +/- Dshort(t)
        steepener        : scenario_weights['steepener'] applied to (Dshort, Dlong)
        flattener        : scenario_weights['flattener'] applied to (Dshort, Dlong)

    Raises ValueError for an unrecognised scenario name or a currency
    missing from config.currency_params.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    if currency not in config.currency_params:
        raise ValueError(f"no shock parameters configured for currency: {currency}")

    params = config.currency_params[currency]
    decay = config.decay_years

    def d_short(t: float) -> float:
        return params["short"] * math.exp(-t / decay)

    def d_long(t: float) -> float:
        return params["long"] * (1 - math.exp(-t / decay))

    if scenario == "parallel_up":
        return lambda t: params["parallel"]
    if scenario == "parallel_down":
        return lambda t: -params["parallel"]
    if scenario == "short_up":
        return d_short
    if scenario == "short_down":
        return lambda t: -d_short(t)

    weights = config.scenario_weights[scenario]
    return lambda t: weights["short"] * d_short(t) + weights["long"] * d_long(t)
