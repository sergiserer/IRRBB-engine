from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class NmdDecayConfig:
    core_fraction: float
    core_max_life_years: float
    decay_frequency_months: int


def load_nmd_decay_config(path: Path) -> NmdDecayConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return NmdDecayConfig(
        core_fraction=raw["core_fraction"],
        core_max_life_years=raw["core_max_life_years"],
        decay_frequency_months=raw["decay_frequency_months"],
    )
