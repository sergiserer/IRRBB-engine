from datetime import date
from pathlib import Path

from app.data.loaders import load_balance_sheet, load_bonds, load_issued_debt, load_mortgages, load_nmd, load_swaps, load_term_deposits

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"


def test_load_mortgages_parses_fixed_and_floating_rows():
    mortgages = load_mortgages(DATA_DIR / "mortgages.csv")
    assert len(mortgages) == 2
    fixed, floating = mortgages
    assert fixed.instrument_id == "MTG001"
    assert fixed.rate_type == "fixed"
    assert fixed.fixed_rate == 0.035
    assert floating.instrument_id == "MTG002"
    assert floating.rate_type == "floating"
    assert floating.spread == 0.012
    assert floating.reference_index == "EURIBOR_12M"
    assert floating.next_repricing_date == date(2027, 6, 1)


def test_load_bonds_parses_rows():
    bonds = load_bonds(DATA_DIR / "bonds.csv")
    assert len(bonds) == 2
    assert bonds[0].coupon_frequency_months == 12
    assert bonds[1].rate_type == "floating"


def test_load_issued_debt_parses_rows():
    debt = load_issued_debt(DATA_DIR / "issued_debt.csv")
    assert len(debt) == 2
    assert debt[0].instrument_id == "ISD001"
    assert debt[1].reference_index == "EURIBOR_3M"


def test_load_term_deposits_forces_fixed_rate_type():
    deposits = load_term_deposits(DATA_DIR / "term_deposits.csv")
    assert len(deposits) == 2
    assert all(d.rate_type == "fixed" for d in deposits)
    assert deposits[0].fixed_rate == 0.025


def test_load_nmd_parses_rows():
    deposits = load_nmd(DATA_DIR / "nmd.csv")
    assert len(deposits) == 2
    assert deposits[0].instrument_id == "NMD001"
    assert deposits[0].notional == 3_000_000


def test_load_swaps_parses_pay_and_receive_legs():
    swaps = load_swaps(DATA_DIR / "swaps.csv")
    assert len(swaps) == 2
    pay_fixed_swap, pay_floating_swap = swaps
    assert pay_fixed_swap.pay_leg.rate_type == "fixed"
    assert pay_fixed_swap.pay_leg.fixed_rate == 0.025
    assert pay_fixed_swap.receive_leg.rate_type == "floating"
    assert pay_fixed_swap.receive_leg.reference_index == "EURIBOR_6M"
    assert pay_floating_swap.pay_leg.rate_type == "floating"
    assert pay_floating_swap.receive_leg.fixed_rate == 0.027


def test_load_balance_sheet_loads_all_instrument_types():
    bs = load_balance_sheet(DATA_DIR)
    assert len(bs.mortgages) == 2
    assert len(bs.bonds) == 2
    assert len(bs.issued_debt) == 2
    assert len(bs.term_deposits) == 2
    assert len(bs.nmd) == 2
    assert len(bs.swaps) == 2
    assert bs.total_assets() > 0
    assert bs.total_liabilities() > 0
