from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from app.domain.instruments import Bond, IssuedDebt, Mortgage, TermDeposit


def _clean(value: Any) -> Optional[Any]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def _clean_int(value: Any) -> Optional[int]:
    value = _clean(value)
    return None if value is None else int(value)


def _parse_date(value: Any) -> Optional[date]:
    value = _clean(value)
    return None if value is None else pd.to_datetime(value).date()


def _common_kwargs(row: pd.Series) -> dict:
    return dict(
        instrument_id=row["instrument_id"],
        currency=row["currency"],
        notional=row["notional"],
        start_date=_parse_date(row["start_date"]),
        maturity_date=_parse_date(row["maturity_date"]),
        rate_type=row["rate_type"],
        fixed_rate=_clean(row.get("fixed_rate")),
        spread=_clean(row.get("spread")),
        reference_index=_clean(row.get("reference_index")),
        repricing_frequency_months=_clean_int(row.get("repricing_frequency_months")),
        next_repricing_date=_parse_date(row.get("next_repricing_date")),
    )


def load_mortgages(path: Path) -> list[Mortgage]:
    df = pd.read_csv(path)
    return [
        Mortgage(
            **_common_kwargs(row),
            amortization_type=row["amortization_type"],
            payment_frequency_months=_clean_int(row["payment_frequency_months"]),
        )
        for _, row in df.iterrows()
    ]


def load_bonds(path: Path) -> list[Bond]:
    df = pd.read_csv(path)
    return [
        Bond(**_common_kwargs(row), coupon_frequency_months=_clean_int(row["coupon_frequency_months"]))
        for _, row in df.iterrows()
    ]


def load_issued_debt(path: Path) -> list[IssuedDebt]:
    df = pd.read_csv(path)
    return [
        IssuedDebt(**_common_kwargs(row), coupon_frequency_months=_clean_int(row["coupon_frequency_months"]))
        for _, row in df.iterrows()
    ]


def load_term_deposits(path: Path) -> list[TermDeposit]:
    df = pd.read_csv(path)
    return [
        TermDeposit(
            instrument_id=row["instrument_id"],
            currency=row["currency"],
            notional=row["notional"],
            start_date=_parse_date(row["start_date"]),
            maturity_date=_parse_date(row["maturity_date"]),
            fixed_rate=row["fixed_rate"],
        )
        for _, row in df.iterrows()
    ]
