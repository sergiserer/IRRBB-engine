from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class CurvePoint:
    tenor_years: float
    rate: float


class YieldCurve:
    """Spot (zero) rate curve with linear interpolation between published tenors.

    Interpolates linearly on the zero rate between tenors — the ECB source
    curve is already smoothed via Svensson, so linear interpolation between
    its published points adds negligible distortion for Phase 1 purposes.
    Extrapolates flat beyond the published tenor range.

    Discounting uses discrete annual compounding, DF(t) = 1 / (1 + R(t))^t,
    consistent with the BCBS368 / EBA RTS 2022/09 standardised framework per
    secondary sources; not yet verified against the RTS primary text (see
    the Phase 1 design doc's "Simplificaciones documentadas" section).
    """

    def __init__(self, points: Iterable[CurvePoint]):
        sorted_points = sorted(points, key=lambda p: p.tenor_years)
        if not sorted_points:
            raise ValueError("YieldCurve requires at least one point")
        self._tenors: List[float] = [p.tenor_years for p in sorted_points]
        self._rates: List[float] = [p.rate for p in sorted_points]

    def rate_at(self, t: float) -> float:
        if t <= self._tenors[0]:
            return self._rates[0]
        if t >= self._tenors[-1]:
            return self._rates[-1]
        for i in range(1, len(self._tenors)):
            if t <= self._tenors[i]:
                t0, t1 = self._tenors[i - 1], self._tenors[i]
                r0, r1 = self._rates[i - 1], self._rates[i]
                weight = (t - t0) / (t1 - t0)
                return r0 + weight * (r1 - r0)
        raise AssertionError("unreachable")  # pragma: no cover

    def discount_factor(self, t: float) -> float:
        if t < 0:
            raise ValueError("t must be >= 0")
        if t == 0:
            return 1.0
        r = self.rate_at(t)
        return 1.0 / (1.0 + r) ** t
