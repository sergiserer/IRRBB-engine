from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from app.domain.cash_flow import CashFlow


def test_cash_flow_holds_fields():
    cf = CashFlow(
        instrument_id="X1",
        currency="EUR",
        date=date(2027, 1, 1),
        amount=1000.0,
        flow_type="principal",
        side="asset",
    )
    assert cf.instrument_id == "X1"
    assert cf.currency == "EUR"
    assert cf.date == date(2027, 1, 1)
    assert cf.amount == 1000.0
    assert cf.flow_type == "principal"
    assert cf.side == "asset"


def test_cash_flow_is_immutable():
    cf = CashFlow(
        instrument_id="X1",
        currency="EUR",
        date=date(2027, 1, 1),
        amount=1000.0,
        flow_type="principal",
        side="asset",
    )
    with pytest.raises(FrozenInstanceError):
        cf.amount = 2000.0
