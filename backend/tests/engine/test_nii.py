from datetime import date

import pytest

from app.domain.balance_sheet import BalanceSheet
from app.domain.instruments import Bond, Mortgage, TermDeposit
from app.domain.yield_curve import CurvePoint, YieldCurve
from app.engine.nii import compute_nii, month_boundaries, month_index


def test_month_boundaries_returns_25_calendar_month_starts():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert len(boundaries) == 25
    assert boundaries[0] == date(2025, 1, 1)
    assert boundaries[1] == date(2025, 2, 1)
    assert boundaries[12] == date(2026, 1, 1)
    assert boundaries[24] == date(2027, 1, 1)


def test_month_index_buckets_dates_into_the_correct_month():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert month_index(date(2025, 1, 1), boundaries) == 0
    assert month_index(date(2025, 1, 31), boundaries) == 0
    assert month_index(date(2025, 2, 1), boundaries) == 1
    assert month_index(date(2026, 1, 1), boundaries) == 12
    assert month_index(date(2026, 12, 31), boundaries) == 23


def test_month_index_returns_none_outside_the_24_month_window():
    boundaries = month_boundaries(date(2025, 1, 1))
    assert month_index(date(2024, 12, 31), boundaries) is None  # antes de as_of_date
    assert month_index(date(2027, 1, 1), boundaries) is None  # exactamente en el borde de 24m, excluido
    assert month_index(date(2030, 1, 1), boundaries) is None  # muy más allá


def test_compute_nii_reference_case_buckets_and_accumulates_by_month():
    # as_of_date = 2025-01-01. Tres instrumentos, todos verificados de
    # forma independiente en Python (ver la spec, sección "Testing plan"):
    #
    # Bond (activo, fijo 3%, semestral, notional 200,000): start=2024-10-01,
    #   maturity=2026-10-01 -> cupones en 2025-04-01, 2025-10-01,
    #   2026-04-01, 2026-10-01 (maturity, +principal excluido del NII).
    #   cupon = 200,000 * 0.03 * (6/12) = 3,000.0 cada uno. Meses
    #   transcurridos desde as_of: 3, 9, 15, 21 -- todos estrictamente
    #   dentro de un bucket, ninguno en un borde.
    #
    # Mortgage (activo, variable, notional 100,000, spread 1%, pagos
    #   anuales, curva rate_at(1)=0.05/rate_at(3)=0.07 interpolada): mismo
    #   caso de referencia que
    #   test_mortgage_floating_with_curve_recasts_payment_each_period --
    #   interest_1 = 6,000.0 en 2026-01-01 (12 meses transcurridos,
    #   exactamente boundary[12] -- cae en el bucket 12, el mes 13, así
    #   que queda FUERA de nii_12m pero DENTRO de nii_24m); interest_2 =
    #   4,121.405455386045 en 2027-01-01 (24 meses transcurridos,
    #   exactamente boundary[24] -- fuera de la ventana por completo).
    #
    # TermDeposit (pasivo, fijo 2.5%, notional 80,000): start=2025-01-01
    #   (=as_of), maturity=2025-07-01 (181 días = 6 meses transcurridos,
    #   exactamente boundary[6]). interes = 80,000 * 0.025 * (181/365) =
    #   991.7808219178082.
    #
    # monthly_net_interest es 0 en todas partes salvo:
    #   bucket 3:  +3,000.0                (bond)
    #   bucket 6:  -991.7808219178082      (term deposit)
    #   bucket 9:  +3,000.0                (bond)
    #   bucket 12: +6,000.0                (mortgage interest_1)
    #   bucket 15: +3,000.0                (bond)
    #   bucket 21: +3,000.0                (bond)
    #
    # nii_12m = suma(buckets 0..11) = 3,000 - 991.7808219178082 + 3,000
    #         = 5,008.219178082192
    # nii_24m = nii_12m + 6,000 + 3,000 + 3,000 = 17,008.219178082192
    #   (mortgage interest_2 en el bucket 24 queda excluido por completo)
    bond = Bond(
        instrument_id="BONDNII",
        currency="EUR",
        notional=200_000,
        start_date=date(2024, 10, 1),
        maturity_date=date(2026, 10, 1),
        rate_type="fixed",
        fixed_rate=0.03,
        coupon_frequency_months=6,
    )
    mortgage = Mortgage(
        instrument_id="MTGNII",
        currency="EUR",
        notional=100_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        rate_type="floating",
        spread=0.01,
        reference_index="EURIBOR_12M",
        repricing_frequency_months=12,
        next_repricing_date=date(2026, 1, 1),
        amortization_type="french",
        payment_frequency_months=12,
    )
    term_deposit = TermDeposit(
        instrument_id="TDNII",
        currency="EUR",
        notional=80_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2025, 7, 1),
        rate_type="fixed",
        fixed_rate=0.025,
    )
    balance_sheet = BalanceSheet(mortgages=[mortgage], bonds=[bond], term_deposits=[term_deposit])
    as_of_date = date(2025, 1, 1)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.05), CurvePoint(tenor_years=3.0, rate=0.07)])

    result = compute_nii(balance_sheet, as_of_date, curve)

    assert len(result.monthly_net_interest) == 24
    assert result.monthly_net_interest[3] == pytest.approx(3_000.0)
    assert result.monthly_net_interest[6] == pytest.approx(-991.7808219178082, rel=1e-9)
    assert result.monthly_net_interest[9] == pytest.approx(3_000.0)
    assert result.monthly_net_interest[12] == pytest.approx(6_000.0)
    assert result.monthly_net_interest[15] == pytest.approx(3_000.0)
    assert result.monthly_net_interest[21] == pytest.approx(3_000.0)
    other_indices = set(range(24)) - {3, 6, 9, 12, 15, 21}
    assert all(result.monthly_net_interest[i] == 0.0 for i in other_indices)

    assert result.nii_12m == pytest.approx(5_008.219178082192, rel=1e-9)
    assert result.nii_24m == pytest.approx(17_008.219178082192, rel=1e-9)


def test_compute_nii_contributes_nothing_after_instrument_matures():
    # El bono vence por completo en el mes 6 transcurrido (2025-07-01): el
    # cupón que caería exactamente en as_of_date+6m (2025-01-01) queda
    # excluido (cf_date debe ser > as_of_date), así que el ÚNICO flujo de
    # interés es el cupón final al vencimiento: 50,000 * 0.04 * (6/12) =
    # 1,000.0, bucket 6. Balance estático (run-off): nada se reinvierte,
    # así que todos los buckets tras el vencimiento deben ser exactamente 0.
    bond = Bond(
        instrument_id="BONDMATURES",
        currency="EUR",
        notional=50_000,
        start_date=date(2024, 7, 1),
        maturity_date=date(2025, 7, 1),
        rate_type="fixed",
        fixed_rate=0.04,
        coupon_frequency_months=6,
    )
    balance_sheet = BalanceSheet(bonds=[bond])
    as_of_date = date(2025, 1, 1)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.05)])

    result = compute_nii(balance_sheet, as_of_date, curve)

    assert result.monthly_net_interest[6] == pytest.approx(1_000.0)
    assert result.monthly_net_interest[7:] == [0.0] * 17
