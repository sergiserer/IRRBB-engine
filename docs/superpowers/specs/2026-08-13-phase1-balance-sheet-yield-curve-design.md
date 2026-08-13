# Fase 1: Modelo de balance sintético + carga de curva de tipos real

## Objetivo

Sentar la capa de dominio y datos del motor IRRBB: modelos de instrumentos
del balance, contenedor de balance sintético, y un módulo de curva de tipos
capaz de cargarse desde una curva real del BCE. Sin cálculo de EVE/NII
todavía (fases 3+), sin cash flow slotting (fase 2), sin API HTTP.

## Alcance

**Incluye:**
- Modelos de dominio (Pydantic) para: hipotecas, depósitos a plazo, NMD,
  bonos, deuda emitida, swaps de tipo simples.
- Contenedor `BalanceSheet` con helpers de agregación.
- Datos sintéticos de balance en CSV (uno por tipo de instrumento).
- `YieldCurve`: interpolación de tasa cero y discount factor.
- Cliente de ingesta de la curva real EUR del BCE (SDMX API).
- Tests unitarios deterministas (fixture de curva fija) + un test de
  integración marcado, excluido del run por defecto, contra el BCE real.

**Explícitamente fuera de alcance (fases posteriores):**
- Cash flow slotting a buckets regulatorios (fase 2).
- Cálculo de EVE, NII, shocks EBA (fases 3-4).
- Comportamiento: prepago (CPR), decay de NMD (fase 5).
- Segunda divisa (USD u otra) y su fuente de curva — se añadirá cuando el
  motor de descuento y agregación ya funcione, para no acoplar dos
  problemas nuevos a la vez.
- Endpoints FastAPI — se conectan cuando haya cálculo real que exponer.
- Tablas regulatorias en `backend/config/*.yaml` (buckets, shocks,
  umbrales) — entran en fases 2 y 4, no se tocan en esta fase.

## Estructura de directorios

```
backend/
  app/
    domain/
      instruments.py      # Instrument base + Mortgage, TermDeposit,
                           # NonMaturingDeposit, Bond, IssuedDebt, Swap
      balance_sheet.py     # BalanceSheet: contenedor + agregaciones
      yield_curve.py        # YieldCurve: interpolación, discount_factor(t)
    data/
      loaders.py            # CSV -> instancias de dominio, con validación
      ecb_client.py          # fetch + parseo de la curva real del BCE
  data/
    synthetic/
      mortgages.csv
      term_deposits.csv
      nmd.csv
      bonds.csv
      issued_debt.csv
      swaps.csv
  tests/
    fixtures/
      ecb_curve_sample.csv   # curva de referencia fija (snapshot), para
                              # tests deterministas de YieldCurve/loaders
    domain/
      test_instruments.py
      test_balance_sheet.py
      test_yield_curve.py
    data/
      test_loaders.py
      test_ecb_client.py     # fixture local + 1 test @pytest.mark.integration
```

## Modelos de dominio

### `Instrument` (base para hipotecas, bonos, deuda emitida)

Campos comunes:

| Campo | Tipo | Notas |
|---|---|---|
| `instrument_id` | `str` | único |
| `currency` | `str` | ISO 4217; solo `"EUR"` poblado en Fase 1, el campo admite cualquier divisa a nivel de esquema |
| `notional` | `float` | > 0 |
| `start_date` | `date` | |
| `maturity_date` | `date` | |
| `rate_type` | `"fixed" \| "floating"` | |
| `fixed_rate` | `float \| None` | requerido si `rate_type == fixed` |
| `spread` | `float \| None` | requerido si `rate_type == floating` |
| `reference_index` | `str \| None` | p.ej. `"EURIBOR_3M"`; requerido si floating |
| `repricing_frequency_months` | `int \| None` | requerido si floating |
| `next_repricing_date` | `date \| None` | requerido si floating |

Un validador de Pydantic exige que estén presentes exactamente los campos
correspondientes al `rate_type` declarado (ni mezcla ni carencia).

### Subclases

- **`Mortgage(Instrument)`** — `+ amortization_type: Literal["french"] = "french"`
  (fijo por ahora; el campo admite `"bullet"`/`"linear"` en el futuro sin
  romper el esquema), `+ payment_frequency_months: int`.
- **`TermDeposit`** — mismo esquema base pero `rate_type` restringido a
  `"fixed"` (sin `spread`/`reference_index`/campos de repricing).
- **`Bond(Instrument)`** e **`IssuedDebt(Instrument)`** — `+ coupon_frequency_months: int`.
  Estructuralmente idénticos; clases separadas porque uno vive en el activo
  (cartera de inversión) y otro en el pasivo (deuda emitida) — el lado lo
  determina la lista de `BalanceSheet` en la que aparecen, no un campo
  redundante.
- **`NonMaturingDeposit`** — esquema propio, sin `maturity_date` ni
  `rate_type`: `instrument_id, currency, notional, as_of_date, rate`. El
  decay de comportamiento llega en fase 5; aquí es solo el saldo.
- **`Swap`** — no hereda de `Instrument` (sin notional principal
  intercambiado). Campos: `instrument_id, currency, notional, start_date,
  maturity_date, payment_frequency_months`, más una pata `pay_leg` y una
  `receive_leg`, cada una un sub-modelo `Leg` con la misma validación
  condicional fixed/floating que `Instrument`.

### `BalanceSheet`

Contenedor con listas tipadas: `mortgages, term_deposits, nmd, bonds,
issued_debt, swaps`. Helpers: `total_assets()`, `total_liabilities()`,
`by_currency(ccy)`.

## Datos sintéticos (CSV)

Un CSV por tipo de instrumento en `backend/data/synthetic/`, columnas
alineadas 1:1 con los campos del modelo Pydantic correspondiente (los
campos de `Swap` se aplanan con prefijo `pay_`/`receive_`, p.ej.
`pay_rate_type, pay_fixed_rate, pay_spread, pay_reference_index,
receive_rate_type, receive_fixed_rate, receive_spread,
receive_reference_index`). Unas pocas filas representativas por fichero,
suficientes para ejercitar fixed/floating y los distintos tipos de
instrumento — no volumen realista de banco, es un portfolio técnico.

## Curva de tipos

### `YieldCurve`

Construida a partir de puntos `(tenor_years: float, rate: float)`
(tasas spot/cero). Métodos:

- `rate_at(t)` — interpolación **lineal sobre la tasa cero** entre los
  tenores publicados. Simplificación explícita de Fase 1 (el BCE ya
  suaviza la curva origen con Svensson, así que interpolar linealmente
  entre sus puntos publicados no añade distorsión relevante) — documentada
  como tal en el docstring, no presentada como requisito regulatorio.
- `discount_factor(t)` = `1 / (1 + rate_at(t)) ** t`. Convención de
  capitalización anual discreta, consistente con el framework
  estandarizado BCBS368 (Anexo 2) / RTS EBA 2022/09 según fuentes
  secundarias (resúmenes técnicos de consultoras, literatura académica
  sobre el framework). **No se pudo verificar contra el texto primario
  del RTS en esta sesión** por limitaciones de herramientas (extracción de
  PDF); pendiente de verificación cuando se implemente el SOT en fase 7,
  donde la exactitud regulatoria estricta importa más.
- Fuera de rango de tenores publicados: extrapolación plana con el rate
  del extremo más cercano (simplificación de Fase 1, documentada como tal).

### `ecb_client.fetch_eur_curve()`

Descarga la curva spot AAA de la zona euro del BCE (SDMX API,
dataset `YC`, serie `YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_<tenor>`) para los
tenores 3M, 6M, 1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 15Y, 20Y vía
`https://data-api.ecb.europa.eu/service/data/YC/...?format=csvdata`,
parsea con pandas y devuelve un `YieldCurve`. Fallos de red/formato
lanzan `ECBFetchError` (excepción de dominio propia) en vez de dejar
escapar el traceback crudo de httpx/pandas.

Fuente: European Central Bank, Statistical Data Warehouse / Data Portal,
dataset YC (Euro area yield curves), https://data.ecb.europa.eu/data/datasets/YC.

## Testing

- Tests de `YieldCurve` (interpolación, discount factor, extrapolación
  plana) y de `loaders`/`ecb_client` (parseo de CSV) usan
  `tests/fixtures/ecb_curve_sample.csv`, un snapshot fijo documentado como
  tal — deterministas, sin red.
- Un test adicional marcado `@pytest.mark.integration` golpea la API real
  del BCE para verificar que el parseo sigue funcionando contra el
  servicio vivo; excluido del run por defecto vía `addopts = -m "not
  integration"` en `pytest.ini`.
- Cada instrumento y cada método de `YieldCurve` tiene al menos un test
  con caso de referencia calculable a mano, conforme a la convención del
  proyecto (`CLAUDE.md`).

## Simplificaciones documentadas (Fase 1)

1. Interpolación lineal sobre tasa cero entre tenores del BCE.
2. Extrapolación plana fuera del rango de tenores publicados.
3. Convención de descuento `1/(1+R)^t` (capitalización anual discreta) —
   pendiente de verificar contra texto primario BCBS368/RTS EBA.
4. Solo EUR poblado; esquema abierto a multi-divisa pero sin segunda
   fuente de curva todavía.
5. NMD sin decay, hipotecas con amortización francesa fija (sin bullet/
   lineal todavía, aunque el campo lo prevé).
