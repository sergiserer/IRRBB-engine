from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SOTConfig:
    threshold_pct: float


def load_sot_config(path: Path) -> SOTConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SOTConfig(threshold_pct=raw["threshold_pct"])
