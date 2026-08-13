from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.instruments import Bond, IssuedDebt, Leg, Mortgage, NonMaturingDeposit, Swap, TermDeposit


def test_mortgage_fixed_rate_valid():
    m = Mortgage(
        instrument_id="MTG001",
        currency="EUR",
        notional=250_000,
        start_date=date(2023, 1, 15),
        maturity_date=date(2043, 1, 15),
        rate_type="fixed",
        fixed_rate=0.035,
        amortization_type="french",
        payment_frequency_months=1,
    )
    assert m.rate_type == "fixed"
    assert m.fixed_rate == 0.035
    assert m.spread is None


def test_mortgage_floating_rate_valid():
    m = Mortgage(
        instrument_id="MTG002",
        currency="EUR",
        notional=180_000,
        start_date=date(2022, 6, 1),
        maturity_date=date(2052, 6, 1),
        rate_type="floating",
        spread=0.012,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2027, 6, 1),
        amortization_type="french",
        payment_frequency_months=1,
    )
    assert m.rate_type == "floating"
    assert m.fixed_rate is None
    assert m.spread == 0.012


def test_mortgage_fixed_without_fixed_rate_raises():
    with pytest.raises(ValidationError):
        Mortgage(
            instrument_id="MTG003",
            currency="EUR",
            notional=100_000,
            start_date=date(2023, 1, 1),
            maturity_date=date(2043, 1, 1),
            rate_type="fixed",
            amortization_type="french",
            payment_frequency_months=1,
        )


def test_mortgage_floating_without_spread_raises():
    with pytest.raises(ValidationError):
        Mortgage(
            instrument_id="MTG004",
            currency="EUR",
            notional=100_000,
            start_date=date(2023, 1, 1),
            maturity_date=date(2043, 1, 1),
            rate_type="floating",
            reference_index="EURIBOR_12M",
            repricing_frequency_months=12,
            next_repricing_date=date(2027, 1, 1),
            amortization_type="french",
            payment_frequency_months=1,
        )


def test_maturity_before_start_raises():
    with pytest.raises(ValidationError):
        Mortgage(
            instrument_id="MTG005",
            currency="EUR",
            notional=100_000,
            start_date=date(2030, 1, 1),
            maturity_date=date(2020, 1, 1),
            rate_type="fixed",
            fixed_rate=0.03,
            amortization_type="french",
            payment_frequency_months=1,
        )


def test_bond_and_issued_debt_share_schema():
    kwargs = dict(
        instrument_id="X",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2021, 3, 1),
        maturity_date=date(2031, 3, 1),
        rate_type="fixed",
        fixed_rate=0.021,
        coupon_frequency_months=12,
    )
    bond = Bond(**{**kwargs, "instrument_id": "BND001"})
    debt = IssuedDebt(**{**kwargs, "instrument_id": "ISD001"})
    assert bond.coupon_frequency_months == debt.coupon_frequency_months == 12


def test_term_deposit_defaults_to_fixed_rate_type():
    td = TermDeposit(
        instrument_id="TDP001",
        currency="EUR",
        notional=100_000,
        start_date=date(2025, 11, 1),
        maturity_date=date(2026, 11, 1),
        fixed_rate=0.025,
    )
    assert td.rate_type == "fixed"
    assert td.spread is None


def test_nmd_valid():
    nmd = NonMaturingDeposit(
        instrument_id="NMD001",
        currency="EUR",
        notional=3_000_000,
        as_of_date=date(2026, 8, 13),
        rate=0.001,
    )
    assert nmd.notional == 3_000_000


def test_nmd_non_positive_notional_raises():
    with pytest.raises(ValidationError):
        NonMaturingDeposit(
            instrument_id="NMD002",
            currency="EUR",
            notional=0,
            as_of_date=date(2026, 8, 13),
            rate=0.001,
        )


def test_swap_valid_fixed_vs_floating_legs():
    swap = Swap(
        instrument_id="SWP001",
        currency="EUR",
        notional=5_000_000,
        start_date=date(2024, 1, 15),
        maturity_date=date(2029, 1, 15),
        payment_frequency_months=6,
        pay_leg=Leg(rate_type="fixed", fixed_rate=0.025),
        receive_leg=Leg(rate_type="floating", spread=0.003, reference_index="EURIBOR_6M"),
    )
    assert swap.pay_leg.fixed_rate == 0.025
    assert swap.receive_leg.reference_index == "EURIBOR_6M"


def test_swap_leg_missing_fields_raises():
    with pytest.raises(ValidationError):
        Swap(
            instrument_id="SWP002",
            currency="EUR",
            notional=2_000_000,
            start_date=date(2023, 7, 1),
            maturity_date=date(2028, 7, 1),
            payment_frequency_months=3,
            pay_leg=Leg(rate_type="floating", spread=0.002, reference_index="EURIBOR_3M"),
            receive_leg=Leg(rate_type="fixed"),  # missing fixed_rate
        )


def test_swap_maturity_before_start_raises():
    with pytest.raises(ValidationError):
        Swap(
            instrument_id="SWP003",
            currency="EUR",
            notional=1_000_000,
            start_date=date(2028, 1, 1),
            maturity_date=date(2020, 1, 1),
            payment_frequency_months=6,
            pay_leg=Leg(rate_type="fixed", fixed_rate=0.02),
            receive_leg=Leg(rate_type="fixed", fixed_rate=0.02),
        )
