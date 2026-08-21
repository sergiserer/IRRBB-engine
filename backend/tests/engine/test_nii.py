from datetime import date

import pytest

from app.domain.balance_sheet import BalanceSheet
from app.domain.instruments import Bond, Mortgage, NonMaturingDeposit, TermDeposit
from app.domain.nmd_decay import NmdDecayConfig
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


def test_compute_nii_nets_swap_receive_and_pay_legs_by_month():
    from app.domain.instruments import Leg, Swap

    # Mismas fechas/curva que la hipoteca del caso de referencia principal,
    # reutilizadas aquí porque sus forward rates ya están verificadas de
    # forma independiente: forward_rate(0,1) = 0.05 exacto,
    # forward_rate(1,2) = 0.07009523809523821 (verificado contra
    # YieldCurve.forward_rate directamente, no contra nii.py).
    # payment_frequency_months=12, así que period_rate = tasa anual, sin
    # escalar por freq/12.
    #
    # receive_leg (variable, spread 1%): cupon_1 = 1,000,000 *
    #   (0.05 + 0.01) = 60,000.0, fecha 2026-01-01 (bucket 12).
    #   cupon_2 = 1,000,000 * (0.07009523809523821 + 0.01) =
    #   80,095.23809523821, fecha 2027-01-01 (bucket 24, excluido).
    # pay_leg (fijo 3%): cupon_1 = 1,000,000 * 0.03 = 30,000.0 (bucket 12),
    #   cupon_2 = 30,000.0 (bucket 24, excluido).
    # net_1 = 60,000.0 - 30,000.0 = 30,000.0, bucket 12.
    # net_2 queda enteramente fuera de la ventana (ambas patas en bucket 24).
    swap = Swap(
        instrument_id="SWAPNII",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2027, 1, 1),
        payment_frequency_months=12,
        pay_leg=Leg(rate_type="fixed", fixed_rate=0.03),
        receive_leg=Leg(rate_type="floating", spread=0.01, reference_index="EURIBOR_12M"),
    )
    balance_sheet = BalanceSheet(swaps=[swap])
    as_of_date = date(2025, 1, 1)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.05), CurvePoint(tenor_years=3.0, rate=0.07)])

    result = compute_nii(balance_sheet, as_of_date, curve)

    assert result.monthly_net_interest[12] == pytest.approx(30_000.0, rel=1e-6)
    assert result.nii_12m == pytest.approx(0.0)
    assert result.nii_24m == pytest.approx(30_000.0, rel=1e-6)


def test_run_nii_scenarios_parallel_up_and_down_move_nii_in_opposite_directions():
    from pathlib import Path

    from app.domain.shocks import load_shock_config
    from app.engine.nii import NII_SCENARIOS, run_nii_scenarios

    CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "eba_shocks.yaml"

    # Libro sensible a activo por construcción: un único bono variable
    # (sin pasivo variable que lo compense). Bajo una curva base plana,
    # un shock paralelo cambia cada forward rate en la misma constante,
    # así que cada cupón trimestral sube estrictamente bajo parallel_up y
    # baja estrictamente bajo parallel_down frente a la curva base -- el
    # signo de delta_nii (base - escenario) debe diferir entre los dos
    # escenarios sea cual sea la magnitud exacta del shock EUR en
    # eba_shocks.yaml.
    bond = Bond(
        instrument_id="BONDFLOAT",
        currency="EUR",
        notional=1_000_000,
        start_date=date(2025, 1, 1),
        maturity_date=date(2030, 1, 1),
        rate_type="floating",
        spread=0.0,
        reference_index="EURIBOR_3M",
        repricing_frequency_months=3,
        next_repricing_date=date(2025, 4, 1),
        coupon_frequency_months=3,
    )
    balance_sheet = BalanceSheet(bonds=[bond])
    as_of_date = date(2025, 1, 1)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    config = load_shock_config(CONFIG_PATH)

    results = run_nii_scenarios(balance_sheet, as_of_date, base_curve, "EUR", config)

    assert [r.scenario for r in results] == NII_SCENARIOS
    up = next(r for r in results if r.scenario == "parallel_up")
    down = next(r for r in results if r.scenario == "parallel_down")
    assert up.delta_nii_12m * down.delta_nii_12m < 0
    assert up.delta_nii_24m * down.delta_nii_24m < 0


def test_compute_nii_with_nmd_decay_config_differs_from_without():
    # With nmd_decay_config=None (the Fase 2 placeholder), nmd_cash_flows
    # emits only a single flow_type='principal' flow at as_of_date --
    # compute_nii only accumulates flow_type='interest', so an NMD-only
    # balance sheet's NII is exactly 0.0 under the default. Supplying a
    # decay_config splits the NMD into non-core (still principal-only)
    # and a core tranche that pays flow_type='interest' monthly on its
    # declining balance (see nmd_cash_flows's docstring) -- with
    # decay_frequency_months=1, several of those interest flows land
    # inside both the 12m and 24m windows, so nii_12m/nii_24m must move
    # away from 0.0, same "differs from without" pattern as
    # test_compute_eve_with_nmd_decay_config_differs_from_without.
    nmd = NonMaturingDeposit(
        instrument_id="NMDNII",
        currency="EUR",
        notional=500_000,
        as_of_date=date(2025, 1, 1),
        rate=0.01,
    )
    balance_sheet = BalanceSheet(nmd=[nmd])
    as_of_date = date(2025, 1, 1)
    curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])
    decay_config = NmdDecayConfig(core_fraction=0.5, core_max_life_years=5.0, decay_frequency_months=1)

    result_without_decay = compute_nii(balance_sheet, as_of_date, curve)
    result_with_decay = compute_nii(balance_sheet, as_of_date, curve, nmd_decay_config=decay_config)

    assert result_without_decay.nii_12m == pytest.approx(0.0)
    assert result_without_decay.nii_24m == pytest.approx(0.0)
    assert result_with_decay.nii_12m != pytest.approx(result_without_decay.nii_12m)
    assert result_with_decay.nii_24m != pytest.approx(result_without_decay.nii_24m)
    # NMD is always a liability: the core tranche's interest expense
    # makes NII strictly more negative than the 0.0 baseline.
    assert result_with_decay.nii_12m < 0.0
    assert result_with_decay.nii_24m < 0.0


def test_run_nii_scenarios_threads_cpr_annual_and_nmd_decay_config():
    from pathlib import Path

    from app.domain.shocks import load_shock_config
    from app.engine.nii import run_nii_scenarios

    CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "eba_shocks.yaml"
    config = load_shock_config(CONFIG_PATH)
    as_of_date = date(2025, 1, 1)
    base_curve = YieldCurve([CurvePoint(tenor_years=1.0, rate=0.03)])

    # cpr_annual: same mechanism as
    # test_run_eba_shock_scenarios_threads_cpr_annual -- a fixed-rate
    # mortgage is the only instrument type affected (BCBS d368 scopes
    # prepayment risk to fixed-rate loans). _fixed_mortgage_schedule
    # computes each period's interest on the balance BEFORE that
    # period's own prepayment, so the first quarterly coupon (month 3)
    # is identical with/without cpr_annual -- payment_frequency_months=3
    # (rather than 12) puts a second and third coupon (months 6 and 9)
    # inside the 12m window too, where the prior period's prepayment has
    # already shrunk the balance, so nii_12m (and nii_24m) must differ.
    mortgage = Mortgage(
        instrument_id="MTGNIISCEN",
        currency="EUR",
        notional=500_000,
        start_date=as_of_date,
        maturity_date=date(2035, 1, 1),
        rate_type="fixed",
        fixed_rate=0.04,
        amortization_type="french",
        payment_frequency_months=3,
    )
    mortgage_balance_sheet = BalanceSheet(mortgages=[mortgage])

    results_without_cpr = run_nii_scenarios(mortgage_balance_sheet, as_of_date, base_curve, "EUR", config)
    results_with_cpr = run_nii_scenarios(
        mortgage_balance_sheet, as_of_date, base_curve, "EUR", config, cpr_annual=0.1
    )

    assert results_with_cpr[0].base_nii_12m != pytest.approx(results_without_cpr[0].base_nii_12m)
    assert results_with_cpr[0].base_nii_24m != pytest.approx(results_without_cpr[0].base_nii_24m)

    # nmd_decay_config: same mechanism as
    # test_run_eba_shock_scenarios_threads_nmd_decay_config -- an NMD is
    # the only instrument type affected.
    nmd = NonMaturingDeposit(
        instrument_id="NMDNIISCEN",
        currency="EUR",
        notional=500_000,
        as_of_date=as_of_date,
        rate=0.01,
    )
    nmd_balance_sheet = BalanceSheet(nmd=[nmd])
    decay_config = NmdDecayConfig(core_fraction=0.5, core_max_life_years=5.0, decay_frequency_months=1)

    results_without_decay = run_nii_scenarios(nmd_balance_sheet, as_of_date, base_curve, "EUR", config)
    results_with_decay = run_nii_scenarios(
        nmd_balance_sheet, as_of_date, base_curve, "EUR", config, nmd_decay_config=decay_config
    )

    assert results_with_decay[0].base_nii_12m != pytest.approx(results_without_decay[0].base_nii_12m)
    assert results_with_decay[0].base_nii_24m != pytest.approx(results_without_decay[0].base_nii_24m)
    # Every scenario (base + both shocked curves) uses the same
    # nmd_decay_config -- confirm at least one shocked scenario's
    # nii_result also differs, not just the base, proving the parameter
    # reaches all the way through run_nii_scenarios -> compute_nii ->
    # generate_all_cash_flows.
    parallel_up_without = next(r for r in results_without_decay if r.scenario == "parallel_up")
    parallel_up_with = next(r for r in results_with_decay if r.scenario == "parallel_up")
    assert parallel_up_with.nii_result.nii_12m != pytest.approx(parallel_up_without.nii_result.nii_12m)
