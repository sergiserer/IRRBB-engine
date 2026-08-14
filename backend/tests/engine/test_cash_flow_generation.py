from datetime import date

from app.domain.instruments import NonMaturingDeposit
from app.engine.cash_flow_generation import nmd_cash_flows


def test_nmd_cash_flow_lands_on_as_of_date():
    nmd = NonMaturingDeposit(
        instrument_id="NMD001",
        currency="EUR",
        notional=3_000_000,
        as_of_date=date(2026, 8, 13),
        rate=0.001,
    )
    as_of = date(2026, 8, 14)
    flows = nmd_cash_flows(nmd, as_of)
    assert len(flows) == 1
    cf = flows[0]
    assert cf.date == as_of
    assert cf.amount == 3_000_000
    assert cf.flow_type == "principal"
    assert cf.side == "liability"
