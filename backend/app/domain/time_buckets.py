from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass(frozen=True)
class TimeBucket:
    name: str
    lower_days: int
    upper_days: Optional[int]  # None = unbounded (last bucket)


def load_time_buckets(path: Path) -> List[TimeBucket]:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [
        TimeBucket(
            name=b["name"],
            lower_days=b["lower_days"],
            upper_days=b.get("upper_days"),
        )
        for b in raw["buckets"]
    ]


def bucket_for(cf_date: date, as_of_date: date, buckets: List[TimeBucket]) -> str:
    days = (cf_date - as_of_date).days
    if days < 0:
        raise ValueError(f"cash flow date {cf_date} is before as_of_date {as_of_date}")
    for bucket in buckets:
        if bucket.upper_days is None:
            if days >= bucket.lower_days:
                return bucket.name
        elif bucket.lower_days <= days < bucket.upper_days:
            return bucket.name
    raise ValueError(f"no bucket matched {days} days from as_of_date {as_of_date}")
