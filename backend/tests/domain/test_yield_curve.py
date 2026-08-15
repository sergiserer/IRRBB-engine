import pytest

from app.domain.yield_curve import CurvePoint, YieldCurve


def _curve() -> YieldCurve:
    return YieldCurve(
        [
            CurvePoint(tenor_years=1.0, rate=0.05),
            CurvePoint(tenor_years=3.0, rate=0.07),
        ]
    )


def test_rate_at_exact_tenor_returns_published_rate():
    curve = _curve()
    assert curve.rate_at(1.0) == pytest.approx(0.05)
    assert curve.rate_at(3.0) == pytest.approx(0.07)


def test_rate_at_interpolates_linearly_between_tenors():
    curve = _curve()
    # Midpoint between (1, 0.05) and (3, 0.07) -> 0.06
    assert curve.rate_at(2.0) == pytest.approx(0.06)


def test_rate_at_extrapolates_flat_below_min_tenor():
    curve = _curve()
    assert curve.rate_at(0.25) == pytest.approx(0.05)


def test_rate_at_extrapolates_flat_above_max_tenor():
    curve = _curve()
    assert curve.rate_at(10.0) == pytest.approx(0.07)


def test_discount_factor_at_zero_is_one():
    curve = _curve()
    assert curve.discount_factor(0.0) == pytest.approx(1.0)


def test_discount_factor_uses_discrete_annual_compounding():
    curve = _curve()
    # DF(1) = 1 / (1.05)^1 = 0.9523809523809523
    assert curve.discount_factor(1.0) == pytest.approx(0.9523809523809523, rel=1e-12)
    # DF(3) = 1 / (1.07)^3 = 0.8162978768908519
    assert curve.discount_factor(3.0) == pytest.approx(0.8162978768908519, rel=1e-12)
    # DF(2) uses the interpolated rate 0.06: 1 / (1.06)^2 = 0.8899964400142398
    assert curve.discount_factor(2.0) == pytest.approx(0.8899964400142398, rel=1e-12)


def test_discount_factor_negative_time_raises():
    curve = _curve()
    with pytest.raises(ValueError):
        curve.discount_factor(-1.0)


def test_yield_curve_requires_at_least_one_point():
    with pytest.raises(ValueError):
        YieldCurve([])


def test_forward_rate_matches_bootstrapped_relationship():
    curve = _curve()
    # (1+R(2))^2 = (1+R(1))^1 * (1+F(1,2))^1
    # (1.06)^2 / 1.05 - 1 = 1.1236/1.05 - 1 = 0.070095238095238095...
    assert curve.forward_rate(1.0, 2.0) == pytest.approx(0.070095238095238095, rel=1e-12)


def test_forward_rate_from_zero_equals_spot_rate():
    curve = _curve()
    # F(0, t) reduces to rate_at(t) since DF(0) == 1.0
    assert curve.forward_rate(0.0, 1.0) == pytest.approx(0.05)
    assert curve.forward_rate(0.0, 3.0) == pytest.approx(0.07)


def test_forward_rate_zero_length_period_raises():
    curve = _curve()
    with pytest.raises(ValueError):
        curve.forward_rate(2.0, 2.0)


def test_forward_rate_negative_t1_raises():
    curve = _curve()
    with pytest.raises(ValueError):
        curve.forward_rate(-1.0, 1.0)
