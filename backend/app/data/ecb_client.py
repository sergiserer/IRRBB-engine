from __future__ import annotations

import io

import httpx
import pandas as pd

from app.domain.yield_curve import CurvePoint, YieldCurve

ECB_BASE_URL = "https://data-api.ecb.europa.eu/service/data/YC"
SERIES_KEY = "B.U2.EUR.4F.G_N_A.SV_C_YM"
TENOR_YEARS = {
    "SR_3M": 0.25,
    "SR_6M": 0.5,
    "SR_1Y": 1.0,
    "SR_2Y": 2.0,
    "SR_3Y": 3.0,
    "SR_5Y": 5.0,
    "SR_7Y": 7.0,
    "SR_10Y": 10.0,
    "SR_15Y": 15.0,
    "SR_20Y": 20.0,
}


class ECBFetchError(Exception):
    """Raised when the ECB yield curve cannot be fetched or parsed."""


def parse_ecb_csv(csv_text: str) -> YieldCurve:
    try:
        df = pd.read_csv(io.StringIO(csv_text))
        points = [
            CurvePoint(
                tenor_years=TENOR_YEARS[row["DATA_TYPE_FM"]],
                rate=float(row["OBS_VALUE"]) / 100.0,
            )
            for _, row in df.iterrows()
        ]
    except (KeyError, ValueError) as exc:
        raise ECBFetchError(f"Unexpected ECB response format: {exc}") from exc

    if not points:
        raise ECBFetchError("ECB response contained no observations")
    return YieldCurve(points)


def fetch_eur_curve() -> YieldCurve:
    tenor_keys = "+".join(TENOR_YEARS.keys())
    url = f"{ECB_BASE_URL}/{SERIES_KEY}.{tenor_keys}"
    try:
        response = httpx.get(url, params={"lastNObservations": 1, "format": "csvdata"}, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ECBFetchError(f"Failed to fetch ECB yield curve: {exc}") from exc
    return parse_ecb_csv(response.text)
