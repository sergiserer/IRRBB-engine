from pathlib import Path

import pytest

from app.data.ecb_client import ECBFetchError, fetch_eur_curve, parse_ecb_csv
from app.domain.yield_curve import YieldCurve

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "ecb_curve_sample.csv"


def test_parse_ecb_csv_builds_yield_curve_from_fixture():
    csv_text = FIXTURE_PATH.read_text()
    curve = parse_ecb_csv(csv_text)
    assert isinstance(curve, YieldCurve)
    # OBS_VALUE is in percent (UNIT=PCPA); parse_ecb_csv must divide by 100.
    assert curve.rate_at(0.25) == pytest.approx(0.023822184856, rel=1e-9)  # SR_3M
    assert curve.rate_at(10.0) == pytest.approx(0.031654173208, rel=1e-9)  # SR_10Y
    assert curve.rate_at(20.0) == pytest.approx(0.035728146753, rel=1e-9)  # SR_20Y


def test_parse_ecb_csv_malformed_input_raises():
    with pytest.raises(ECBFetchError):
        parse_ecb_csv("not,a,valid,ecb,response\n1,2,3,4,5")


@pytest.mark.integration
def test_fetch_eur_curve_hits_live_ecb_api():
    curve = fetch_eur_curve()
    assert isinstance(curve, YieldCurve)
    ten_year_rate = curve.rate_at(10.0)
    assert -0.05 < ten_year_rate < 0.20
