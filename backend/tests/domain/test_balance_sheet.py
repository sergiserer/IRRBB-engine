from datetime import date

from app.domain.balance_sheet import BalanceSheet
from app.domain.instruments import Mortgage, NonMaturingDeposit, TermDeposit


def _mortgage(instrument_id: str, notional: float, currency: str = "EUR") -> Mortgage:
    return Mortgage(
        instrument_id=instrument_id,
        currency=currency,
        notional=notional,
        start_date=date(2023, 1, 1),
        maturity_date=date(2043, 1, 1),
        rate_type="fixed",
        fixed_rate=0.03,
        amortization_type="french",
        payment_frequency_months=1,
    )


def _term_deposit(instrument_id: str, notional: float, currency: str = "EUR") -> TermDeposit:
    return TermDeposit(
        instrument_id=instrument_id,
        currency=currency,
        notional=notional,
        start_date=date(2025, 1, 1),
        maturity_date=date(2026, 1, 1),
        fixed_rate=0.02,
    )


def _nmd(instrument_id: str, notional: float, currency: str = "EUR") -> NonMaturingDeposit:
    return NonMaturingDeposit(
        instrument_id=instrument_id,
        currency=currency,
        notional=notional,
        as_of_date=date(2026, 8, 13),
        rate=0.001,
    )


def test_total_assets_sums_mortgages_and_bonds():
    bs = BalanceSheet(mortgages=[_mortgage("M1", 100_000), _mortgage("M2", 50_000)])
    assert bs.total_assets() == 150_000


def test_total_liabilities_sums_deposits_nmd_and_issued_debt():
    bs = BalanceSheet(
        term_deposits=[_term_deposit("T1", 20_000)],
        nmd=[_nmd("N1", 5_000)],
    )
    assert bs.total_liabilities() == 25_000


def test_by_currency_filters_all_lists():
    bs = BalanceSheet(
        mortgages=[_mortgage("M1", 100_000, "EUR"), _mortgage("M2", 50_000, "USD")],
        term_deposits=[_term_deposit("T1", 20_000, "EUR")],
    )
    eur_only = bs.by_currency("EUR")
    assert [m.instrument_id for m in eur_only.mortgages] == ["M1"]
    assert [t.instrument_id for t in eur_only.term_deposits] == ["T1"]
