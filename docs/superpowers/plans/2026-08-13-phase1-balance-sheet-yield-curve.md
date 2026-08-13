# Fase 1: Balance sintético + curva de tipos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the domain layer of the IRRBB engine — instrument models, a synthetic balance sheet, and a yield curve module that can load the real EUR curve from the ECB — with no cash flow slotting, EVE/NII calculation, or HTTP API yet.

**Architecture:** Pydantic models represent balance sheet instruments (`app/domain/instruments.py`), a small dataclass container aggregates them (`app/domain/balance_sheet.py`), a standalone `YieldCurve` class handles interpolation/discounting (`app/domain/yield_curve.py`), and a thin data layer (`app/data/loaders.py`, `app/data/ecb_client.py`) turns CSV files and the ECB SDMX API into those domain objects.

**Tech Stack:** Python 3.11+, Pydantic v2 (via FastAPI), pandas, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-phase1-balance-sheet-yield-curve-design.md`

## Global Constraints

- No new pip dependencies — pydantic/pandas/httpx/pytest already installed in `.venv`; ask before adding anything else.
- Variable/function names in English (banking/finance domain standard), even though commit messages and prose may be in Spanish.
- Regulatory tables (buckets, shocks, thresholds) live only in `backend/config/*.yaml` — none are needed in this plan.
- Every financial calculation (discounting) needs a unit test with a hand-verifiable reference value.
- Only synthetic data — never real bank data.
- Git commits: author is the repository's configured git user only. Never add Claude/AI as author or co-author.
- Tests run via `cd backend && pytest` (per `CLAUDE.md`); this plan's Run commands use the venv interpreter explicitly (`../.venv/Scripts/python.exe -m pytest ...`) from the `backend/` directory.

---

### Task 1: Pytest scaffolding and package init

**Files:**
- Create: `backend/pytest.ini`
- Create: `backend/app/domain/__init__.py`
- Create: `backend/app/data/__init__.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: working `app.domain.*` / `app.data.*` imports from any test under `backend/tests/`, an `integration` pytest marker excluded by default.

- [ ] **Step 1: Create the domain and data package directories with empty `__init__.py`**

Run:
```bash
cd backend
mkdir -p app/domain app/data
touch app/domain/__init__.py app/data/__init__.py
```

- [ ] **Step 2: Create `backend/pytest.ini`**

```ini
[pytest]
pythonpath = .
markers =
    integration: hits external network services (excluded by default, run with -m integration)
addopts = -m "not integration"
```

- [ ] **Step 3: Verify the existing smoke test still collects and passes under the new config**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -v`
Expected: `tests/test_smoke.py::test_smoke PASSED`, 1 passed, no errors about markers or paths.

- [ ] **Step 4: Commit**

```bash
git add backend/pytest.ini backend/app/domain/__init__.py backend/app/data/__init__.py
git commit -m "chore: pytest config + domain/data package scaffolding"
```

---

### Task 2: `YieldCurve` domain model

**Files:**
- Create: `backend/app/domain/yield_curve.py`
- Test: `backend/tests/domain/test_yield_curve.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CurvePoint(tenor_years: float, rate: float)`, `YieldCurve(points: Iterable[CurvePoint])` with `.rate_at(t: float) -> float` and `.discount_factor(t: float) -> float`. Used by Task 8 (`ecb_client.py`) and by later phases' discounting engine.

- [ ] **Step 1: Create the test directory and write the failing tests**

Run: `cd backend && mkdir -p tests/domain`

Create `backend/tests/domain/test_yield_curve.py`:

```python
import pytest

from app.domain.yield_curve import CurvePoint, YieldCurve


def _curve() -> YieldCurve:
    return YieldCurve(
        [
            CurvePoint(tenor_years=1.0, rate=0.05),
            CurvePoint(tenor_years=3.0, rate=0.07),
        ]
    )


def test_rate_at_exact_tenor_returns_published_rate():
    curve = _curve()
    assert curve.rate_at(1.0) == pytest.approx(0.05)
    assert curve.rate_at(3.0) == pytest.approx(0.07)


def test_rate_at_interpolates_linearly_between_tenors():
    curve = _curve()
    # Midpoint between (1, 0.05) and (3, 0.07) -> 0.06
    assert curve.rate_at(2.0) == pytest.approx(0.06)


def test_rate_at_extrapolates_flat_below_min_tenor():
    curve = _curve()
    assert curve.rate_at(0.25) == pytest.approx(0.05)


def test_rate_at_extrapolates_flat_above_max_tenor():
    curve = _curve()
    assert curve.rate_at(10.0) == pytest.approx(0.07)


def test_discount_factor_at_zero_is_one():
    curve = _curve()
    assert curve.discount_factor(0.0) == pytest.approx(1.0)


def test_discount_factor_uses_discrete_annual_compounding():
    curve = _curve()
    # DF(1) = 1 / (1.05)^1 = 0.9523809523809523
    assert curve.discount_factor(1.0) == pytest.approx(0.9523809523809523, rel=1e-12)
    # DF(3) = 1 / (1.07)^3 = 0.8162978768908519
    assert curve.discount_factor(3.0) == pytest.approx(0.8162978768908519, rel=1e-12)
    # DF(2) uses the interpolated rate 0.06: 1 / (1.06)^2 = 0.8899964400142398
    assert curve.discount_factor(2.0) == pytest.approx(0.8899964400142398, rel=1e-12)


def test_discount_factor_negative_time_raises():
    curve = _curve()
    with pytest.raises(ValueError):
        curve.discount_factor(-1.0)


def test_yield_curve_requires_at_least_one_point():
    with pytest.raises(ValueError):
        YieldCurve([])
```

- [ ] **Step 2: Run tests to verify they fail on import**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_yield_curve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.yield_curve'`

- [ ] **Step 3: Implement `YieldCurve`**

Create `backend/app/domain/yield_curve.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class CurvePoint:
    tenor_years: float
    rate: float


class YieldCurve:
    """Spot (zero) rate curve with linear interpolation between published tenors.

    Interpolates linearly on the zero rate between tenors — the ECB source
    curve is already smoothed via Svensson, so linear interpolation between
    its published points adds negligible distortion for Phase 1 purposes.
    Extrapolates flat beyond the published tenor range.

    Discounting uses discrete annual compounding, DF(t) = 1 / (1 + R(t))^t,
    consistent with the BCBS368 / EBA RTS 2022/09 standardised framework per
    secondary sources; not yet verified against the RTS primary text (see
    the Phase 1 design doc's "Simplificaciones documentadas" section).
    """

    def __init__(self, points: Iterable[CurvePoint]):
        sorted_points = sorted(points, key=lambda p: p.tenor_years)
        if not sorted_points:
            raise ValueError("YieldCurve requires at least one point")
        self._tenors: List[float] = [p.tenor_years for p in sorted_points]
        self._rates: List[float] = [p.rate for p in sorted_points]

    def rate_at(self, t: float) -> float:
        if t <= self._tenors[0]:
            return self._rates[0]
        if t >= self._tenors[-1]:
            return self._rates[-1]
        for i in range(1, len(self._tenors)):
            if t <= self._tenors[i]:
                t0, t1 = self._tenors[i - 1], self._tenors[i]
                r0, r1 = self._rates[i - 1], self._rates[i]
                weight = (t - t0) / (t1 - t0)
                return r0 + weight * (r1 - r0)
        raise AssertionError("unreachable")  # pragma: no cover

    def discount_factor(self, t: float) -> float:
        if t < 0:
            raise ValueError("t must be >= 0")
        if t == 0:
            return 1.0
        r = self.rate_at(t)
        return 1.0 / (1.0 + r) ** t
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_yield_curve.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/yield_curve.py backend/tests/domain/test_yield_curve.py
git commit -m "feat: YieldCurve with linear interpolation and discount_factor"
```

---

### Task 3: `Instrument` base + `Mortgage`, `Bond`, `IssuedDebt`, `TermDeposit`

**Files:**
- Create: `backend/app/domain/instruments.py`
- Test: `backend/tests/domain/test_instruments.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RateType = Literal["fixed", "floating"]`, `Instrument` (Pydantic `BaseModel` with fields `instrument_id, currency, notional, start_date, maturity_date, rate_type, fixed_rate, spread, reference_index, repricing_frequency_months, next_repricing_date`), `Mortgage(Instrument)` (`+ amortization_type, payment_frequency_months`), `Bond(Instrument)` / `IssuedDebt(Instrument)` (`+ coupon_frequency_months`), `TermDeposit(Instrument)` (`rate_type` fixed to `"fixed"`). Used by Task 4 (shares `_validate_rate_fields`), Task 5 (`BalanceSheet`), Task 6 (loaders).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/domain/test_instruments.py`:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.instruments import Bond, IssuedDebt, Mortgage, TermDeposit


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_instruments.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.instruments'`

- [ ] **Step 3: Implement the base `Instrument` and its subclasses**

Create `backend/app/domain/instruments.py`:

```python
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

RateType = Literal["fixed", "floating"]


def _validate_rate_fields(
    rate_type: RateType,
    fixed_rate: Optional[float],
    spread: Optional[float],
    reference_index: Optional[str],
) -> None:
    if rate_type == "fixed":
        if fixed_rate is None:
            raise ValueError("fixed_rate is required when rate_type is 'fixed'")
        if spread is not None or reference_index is not None:
            raise ValueError("spread/reference_index must be empty when rate_type is 'fixed'")
    else:
        if spread is None or reference_index is None:
            raise ValueError("spread and reference_index are required when rate_type is 'floating'")
        if fixed_rate is not None:
            raise ValueError("fixed_rate must be empty when rate_type is 'floating'")


class Instrument(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    notional: float = Field(gt=0)
    start_date: date
    maturity_date: date
    rate_type: RateType
    fixed_rate: Optional[float] = None
    spread: Optional[float] = None
    reference_index: Optional[str] = None
    repricing_frequency_months: Optional[int] = None
    next_repricing_date: Optional[date] = None

    @model_validator(mode="after")
    def _check_fields(self) -> "Instrument":
        _validate_rate_fields(self.rate_type, self.fixed_rate, self.spread, self.reference_index)
        if self.rate_type == "floating" and (
            self.repricing_frequency_months is None or self.next_repricing_date is None
        ):
            raise ValueError(
                "repricing_frequency_months and next_repricing_date are required "
                "when rate_type is 'floating'"
            )
        if self.maturity_date <= self.start_date:
            raise ValueError("maturity_date must be after start_date")
        return self


class Mortgage(Instrument):
    amortization_type: Literal["french"] = "french"
    payment_frequency_months: int = Field(gt=0)


class Bond(Instrument):
    coupon_frequency_months: int = Field(gt=0)


class IssuedDebt(Instrument):
    coupon_frequency_months: int = Field(gt=0)


class TermDeposit(Instrument):
    rate_type: Literal["fixed"] = "fixed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_instruments.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/instruments.py backend/tests/domain/test_instruments.py
git commit -m "feat: Instrument base + Mortgage, Bond, IssuedDebt, TermDeposit models"
```

---

### Task 4: `NonMaturingDeposit`, `Leg`, `Swap`

**Files:**
- Modify: `backend/app/domain/instruments.py`
- Modify: `backend/tests/domain/test_instruments.py`

**Interfaces:**
- Consumes: `_validate_rate_fields` from Task 3 (same file).
- Produces: `NonMaturingDeposit(instrument_id, currency, notional, as_of_date, rate)`, `Leg(rate_type, fixed_rate, spread, reference_index)`, `Swap(instrument_id, currency, notional, start_date, maturity_date, payment_frequency_months, pay_leg: Leg, receive_leg: Leg)`. Used by Task 5 (`BalanceSheet`), Task 7 (swap loader).

- [ ] **Step 1: Append failing tests to `test_instruments.py`**

Append to `backend/tests/domain/test_instruments.py` (add these imports to the existing `from app.domain.instruments import ...` line: `Leg, NonMaturingDeposit, Swap`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_instruments.py -v`
Expected: FAIL — `ImportError: cannot import name 'NonMaturingDeposit'`

- [ ] **Step 3: Append `NonMaturingDeposit`, `Leg`, `Swap` to `instruments.py`**

Append to `backend/app/domain/instruments.py`:

```python
class NonMaturingDeposit(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    notional: float = Field(gt=0)
    as_of_date: date
    rate: float = Field(ge=0)


class Leg(BaseModel):
    rate_type: RateType
    fixed_rate: Optional[float] = None
    spread: Optional[float] = None
    reference_index: Optional[str] = None

    @model_validator(mode="after")
    def _check_fields(self) -> "Leg":
        _validate_rate_fields(self.rate_type, self.fixed_rate, self.spread, self.reference_index)
        return self


class Swap(BaseModel):
    instrument_id: str
    currency: str = Field(min_length=3, max_length=3)
    notional: float = Field(gt=0)
    start_date: date
    maturity_date: date
    payment_frequency_months: int = Field(gt=0)
    pay_leg: Leg
    receive_leg: Leg

    @model_validator(mode="after")
    def _check_dates(self) -> "Swap":
        if self.maturity_date <= self.start_date:
            raise ValueError("maturity_date must be after start_date")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_instruments.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/instruments.py backend/tests/domain/test_instruments.py
git commit -m "feat: NonMaturingDeposit, Leg, Swap models"
```

---

### Task 5: `BalanceSheet` container

**Files:**
- Create: `backend/app/domain/balance_sheet.py`
- Test: `backend/tests/domain/test_balance_sheet.py`

**Interfaces:**
- Consumes: `Bond, IssuedDebt, Mortgage, NonMaturingDeposit, Swap, TermDeposit` from `app.domain.instruments` (Tasks 3-4).
- Produces: `BalanceSheet(mortgages, term_deposits, nmd, bonds, issued_debt, swaps)` with `.total_assets() -> float`, `.total_liabilities() -> float`, `.by_currency(currency: str) -> BalanceSheet`. Used by Task 7 (`load_balance_sheet`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/domain/test_balance_sheet.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_balance_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.balance_sheet'`

- [ ] **Step 3: Implement `BalanceSheet`**

Create `backend/app/domain/balance_sheet.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.domain.instruments import (
    Bond,
    IssuedDebt,
    Mortgage,
    NonMaturingDeposit,
    Swap,
    TermDeposit,
)


@dataclass
class BalanceSheet:
    mortgages: List[Mortgage] = field(default_factory=list)
    term_deposits: List[TermDeposit] = field(default_factory=list)
    nmd: List[NonMaturingDeposit] = field(default_factory=list)
    bonds: List[Bond] = field(default_factory=list)
    issued_debt: List[IssuedDebt] = field(default_factory=list)
    swaps: List[Swap] = field(default_factory=list)

    def total_assets(self) -> float:
        return sum(m.notional for m in self.mortgages) + sum(b.notional for b in self.bonds)

    def total_liabilities(self) -> float:
        return (
            sum(d.notional for d in self.term_deposits)
            + sum(n.notional for n in self.nmd)
            + sum(i.notional for i in self.issued_debt)
        )

    def by_currency(self, currency: str) -> "BalanceSheet":
        return BalanceSheet(
            mortgages=[i for i in self.mortgages if i.currency == currency],
            term_deposits=[i for i in self.term_deposits if i.currency == currency],
            nmd=[i for i in self.nmd if i.currency == currency],
            bonds=[i for i in self.bonds if i.currency == currency],
            issued_debt=[i for i in self.issued_debt if i.currency == currency],
            swaps=[i for i in self.swaps if i.currency == currency],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/domain/test_balance_sheet.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/balance_sheet.py backend/tests/domain/test_balance_sheet.py
git commit -m "feat: BalanceSheet container with total/by_currency helpers"
```

---

### Task 6: Synthetic data + loaders for `Mortgage`, `Bond`, `IssuedDebt`, `TermDeposit`

**Files:**
- Create: `backend/data/synthetic/mortgages.csv`
- Create: `backend/data/synthetic/bonds.csv`
- Create: `backend/data/synthetic/issued_debt.csv`
- Create: `backend/data/synthetic/term_deposits.csv`
- Create: `backend/app/data/loaders.py`
- Test: `backend/tests/data/test_loaders.py`

**Interfaces:**
- Consumes: `Bond, IssuedDebt, Mortgage, TermDeposit` from `app.domain.instruments` (Task 3).
- Produces: `load_mortgages(path) -> list[Mortgage]`, `load_bonds(path) -> list[Bond]`, `load_issued_debt(path) -> list[IssuedDebt]`, `load_term_deposits(path) -> list[TermDeposit]`, plus private helpers `_clean`, `_clean_int`, `_parse_date`, `_common_kwargs` reused by Task 7.

- [ ] **Step 1: Create the synthetic CSV files**

Create `backend/data/synthetic/mortgages.csv`:

```csv
instrument_id,currency,notional,start_date,maturity_date,rate_type,fixed_rate,spread,reference_index,repricing_frequency_months,next_repricing_date,amortization_type,payment_frequency_months
MTG001,EUR,250000,2023-01-15,2043-01-15,fixed,0.035,,,,,french,1
MTG002,EUR,180000,2022-06-01,2052-06-01,floating,,0.012,EURIBOR_12M,12,2027-06-01,french,1
```

Create `backend/data/synthetic/bonds.csv`:

```csv
instrument_id,currency,notional,start_date,maturity_date,rate_type,fixed_rate,spread,reference_index,repricing_frequency_months,next_repricing_date,coupon_frequency_months
BND001,EUR,1000000,2021-03-01,2031-03-01,fixed,0.021,,,,,12
BND002,EUR,500000,2020-09-15,2028-09-15,floating,,0.005,EURIBOR_6M,6,2027-03-15,6
```

Create `backend/data/synthetic/issued_debt.csv`:

```csv
instrument_id,currency,notional,start_date,maturity_date,rate_type,fixed_rate,spread,reference_index,repricing_frequency_months,next_repricing_date,coupon_frequency_months
ISD001,EUR,2000000,2022-01-10,2027-01-10,fixed,0.028,,,,,12
ISD002,EUR,750000,2023-05-01,2028-05-01,floating,,0.004,EURIBOR_3M,3,2026-11-01,3
```

Create `backend/data/synthetic/term_deposits.csv`:

```csv
instrument_id,currency,notional,start_date,maturity_date,fixed_rate
TDP001,EUR,100000,2025-11-01,2026-11-01,0.025
TDP002,EUR,60000,2026-02-01,2027-08-01,0.028
```

- [ ] **Step 2: Write the failing loader tests**

Run: `cd backend && mkdir -p tests/data`

Create `backend/tests/data/test_loaders.py`:

```python
from datetime import date
from pathlib import Path

from app.data.loaders import load_bonds, load_issued_debt, load_mortgages, load_term_deposits

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_loaders.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.loaders'`

- [ ] **Step 4: Implement the loaders**

Create `backend/app/data/loaders.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_loaders.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/data/synthetic/mortgages.csv backend/data/synthetic/bonds.csv \
        backend/data/synthetic/issued_debt.csv backend/data/synthetic/term_deposits.csv \
        backend/app/data/loaders.py backend/tests/data/test_loaders.py
git commit -m "feat: synthetic data + loaders for mortgages, bonds, issued debt, term deposits"
```

---

### Task 7: Synthetic data + loaders for `NonMaturingDeposit`, `Swap`, and `load_balance_sheet`

**Files:**
- Create: `backend/data/synthetic/nmd.csv`
- Create: `backend/data/synthetic/swaps.csv`
- Modify: `backend/app/data/loaders.py`
- Modify: `backend/tests/data/test_loaders.py`

**Interfaces:**
- Consumes: `NonMaturingDeposit, Swap, Leg` from `app.domain.instruments` (Task 4), `BalanceSheet` from `app.domain.balance_sheet` (Task 5), `load_mortgages/load_bonds/load_issued_debt/load_term_deposits` from Task 6 (same file).
- Produces: `load_nmd(path) -> list[NonMaturingDeposit]`, `load_swaps(path) -> list[Swap]`, `load_balance_sheet(data_dir: Path) -> BalanceSheet`.

- [ ] **Step 1: Create the remaining synthetic CSV files**

Create `backend/data/synthetic/nmd.csv`:

```csv
instrument_id,currency,notional,as_of_date,rate
NMD001,EUR,3000000,2026-08-13,0.001
NMD002,EUR,1200000,2026-08-13,0.0005
```

Create `backend/data/synthetic/swaps.csv`:

```csv
instrument_id,currency,notional,start_date,maturity_date,payment_frequency_months,pay_rate_type,pay_fixed_rate,pay_spread,pay_reference_index,receive_rate_type,receive_fixed_rate,receive_spread,receive_reference_index
SWP001,EUR,5000000,2024-01-15,2029-01-15,6,fixed,0.025,,,floating,,0.003,EURIBOR_6M
SWP002,EUR,2000000,2023-07-01,2028-07-01,3,floating,,0.002,EURIBOR_3M,fixed,0.027,,
```

- [ ] **Step 2: Append failing tests to `test_loaders.py`**

Add `load_balance_sheet, load_nmd, load_swaps` to the existing import from `app.data.loaders`, and append:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_loaders.py -v`
Expected: FAIL — `ImportError: cannot import name 'load_nmd'`

- [ ] **Step 4: Append `load_nmd`, `load_swaps`, `load_balance_sheet` to `loaders.py`**

Update the import line in `backend/app/data/loaders.py` to:

```python
from app.domain.balance_sheet import BalanceSheet
from app.domain.instruments import Bond, IssuedDebt, Leg, Mortgage, NonMaturingDeposit, Swap, TermDeposit
```

Append to `backend/app/data/loaders.py`:

```python
def load_nmd(path: Path) -> list[NonMaturingDeposit]:
    df = pd.read_csv(path)
    return [
        NonMaturingDeposit(
            instrument_id=row["instrument_id"],
            currency=row["currency"],
            notional=row["notional"],
            as_of_date=_parse_date(row["as_of_date"]),
            rate=row["rate"],
        )
        for _, row in df.iterrows()
    ]


def _leg_from_prefix(row: pd.Series, prefix: str) -> Leg:
    return Leg(
        rate_type=row[f"{prefix}_rate_type"],
        fixed_rate=_clean(row.get(f"{prefix}_fixed_rate")),
        spread=_clean(row.get(f"{prefix}_spread")),
        reference_index=_clean(row.get(f"{prefix}_reference_index")),
    )


def load_swaps(path: Path) -> list[Swap]:
    df = pd.read_csv(path)
    return [
        Swap(
            instrument_id=row["instrument_id"],
            currency=row["currency"],
            notional=row["notional"],
            start_date=_parse_date(row["start_date"]),
            maturity_date=_parse_date(row["maturity_date"]),
            payment_frequency_months=_clean_int(row["payment_frequency_months"]),
            pay_leg=_leg_from_prefix(row, "pay"),
            receive_leg=_leg_from_prefix(row, "receive"),
        )
        for _, row in df.iterrows()
    ]


def load_balance_sheet(data_dir: Path) -> BalanceSheet:
    return BalanceSheet(
        mortgages=load_mortgages(data_dir / "mortgages.csv"),
        term_deposits=load_term_deposits(data_dir / "term_deposits.csv"),
        nmd=load_nmd(data_dir / "nmd.csv"),
        bonds=load_bonds(data_dir / "bonds.csv"),
        issued_debt=load_issued_debt(data_dir / "issued_debt.csv"),
        swaps=load_swaps(data_dir / "swaps.csv"),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_loaders.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add backend/data/synthetic/nmd.csv backend/data/synthetic/swaps.csv \
        backend/app/data/loaders.py backend/tests/data/test_loaders.py
git commit -m "feat: synthetic data + loaders for NMD, swaps, and load_balance_sheet"
```

---

### Task 8: ECB yield curve ingestion

**Files:**
- Create: `backend/tests/fixtures/ecb_curve_sample.csv`
- Create: `backend/app/data/ecb_client.py`
- Test: `backend/tests/data/test_ecb_client.py`

**Interfaces:**
- Consumes: `CurvePoint, YieldCurve` from `app.domain.yield_curve` (Task 2).
- Produces: `ECBFetchError(Exception)`, `parse_ecb_csv(csv_text: str) -> YieldCurve`, `fetch_eur_curve() -> YieldCurve`.

- [ ] **Step 1: Create the fixed reference curve fixture**

Run: `cd backend && mkdir -p tests/fixtures`

Create `backend/tests/fixtures/ecb_curve_sample.csv` (real snapshot captured 2026-08-12 from the ECB SDMX API, `YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_<tenor>`, used only to keep tests deterministic and offline):

```csv
KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,BREAKS,COLLECTION,COMPILING_ORG,DISS_ORG,DOM_SER_IDS,FM_CONTRACT_TIME,FM_COUPON_RATE,FM_IDENTIFIER,FM_LOT_SIZE,FM_MATURITY,FM_OUTS_AMOUNT,FM_PUT_CALL,FM_STRIKE_PRICE,PUBL_MU,PUBL_PUBLIC,UNIT_INDEX_BASE,COMPILATION,COVERAGE,DECIMALS,SOURCE_AGENCY,SOURCE_PUB,TITLE,TITLE_COMPL,UNIT,UNIT_MULT
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_10Y,2026-08-12,3.1654173208,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 10-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 10-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_15Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_15Y,2026-08-12,3.4277345605,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 15-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 15-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_1Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_1Y,2026-08-12,2.6067748113,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 1-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 1-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_20Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_20Y,2026-08-12,3.5728146753,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 20-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 20-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,2026-08-12,2.700507465,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 2-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 2-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_3M,2026-08-12,2.3822184856,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 3-month spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 3-month maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_3Y,2026-08-12,2.7369686267,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 3-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 3-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_5Y,2026-08-12,2.8281038942,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 5-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 5-year maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_6M,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_6M,2026-08-12,2.4834093276,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 6-month spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 6-month maturity",PCPA,0
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_7Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_7Y,2026-08-12,2.9596084528,A,F,,,P1D,,E,,,,,,,,,,,,,,,Technical notes are available at the following link: https://www.ecb.europa.eu/stats/financial_markets_and_interest_rates/euro_area_yield_curves/shared/pdf/technical_notes.pdf,,6,,,AAA yield curve - 7-year spot rate,"Euro area (changing composition) - Government bond, nominal, all issuers whose rating is triple A - Svensson model - continuous compounding - yield error minimisation - Yield curve spot rate, 7-year maturity",PCPA,0
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/data/test_ecb_client.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_ecb_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.ecb_client'`

- [ ] **Step 4: Implement `ecb_client.py`**

Create `backend/app/data/ecb_client.py`:

```python
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
                tenor_years=TENOR_YEARS[row["PROVIDER_FM_ID"]],
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
```

- [ ] **Step 5: Run the offline tests to verify they pass**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_ecb_client.py -v`
Expected: 2 passed, 1 deselected (the `integration` test is excluded by `addopts` in `pytest.ini`)

- [ ] **Step 6: Run the integration test explicitly against the live ECB API**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest tests/data/test_ecb_client.py -v -m integration`
Expected: 1 passed (requires network access; if it fails on a connection error rather than an assertion, treat that as an environment issue, not a code defect)

- [ ] **Step 7: Run the full test suite**

Run: `cd backend && ../.venv/Scripts/python.exe -m pytest -v`
Expected: all non-integration tests pass (1 smoke + 8 yield curve + 12 instruments + 3 balance sheet + 7 loaders + 2 ecb_client = 33 passed, 1 deselected)

- [ ] **Step 8: Commit**

```bash
git add backend/tests/fixtures/ecb_curve_sample.csv backend/app/data/ecb_client.py backend/tests/data/test_ecb_client.py
git commit -m "feat: ECB EUR yield curve ingestion (SDMX API client + parser)"
```

---

## After implementation

Phase 1 is complete once Task 8 is committed and the full suite (Step 7) passes. This unblocks Phase 2 (cash flow slotting into regulatory time buckets), which will consume `BalanceSheet`, the `Instrument` subclasses, and `YieldCurve` directly.
