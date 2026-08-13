# CLAUDE.md

## Proyecto
Motor de riesgo de tipo de interés en el balance bancario (IRRBB), siguiendo
las directrices EBA/Basel. Objetivo: portfolio técnico para optar a roles de
ingeniería en banca/fintech (treasury, riesgo, regtech). Prioriza corrección
financiera y trazabilidad regulatoria sobre velocidad de desarrollo.

## Stack
- Backend: Python 3.11+, FastAPI, pandas/numpy para el motor de cálculo
- Frontend: React + Vite, Recharts o D3 para heatmaps/curvas
- Datos: balance sintético (CSV/JSON), curvas de tipos reales vía API del BCE
- Tests: pytest en backend, Vitest en frontend (si aplica)

## Glosario de dominio (para que no meta la pata con los términos)
- EVE = Economic Value of Equity (valor presente activos - valor presente pasivos)
- NII = Net Interest Income (margen de intereses proyectado a 12-24 meses)
- NMD = Non-Maturing Deposits (depósitos a la vista, requieren supuesto de decay)
- CPR = Constant Prepayment Rate (velocidad de prepago de hipotecas)
- SOT = Standardised Outlier Test (umbral 15% de Tier 1 sobre ΔEVE)
- Los 6 escenarios EBA: parallel up/down, steepener, flattener, short rate up/down

## Convenciones
- Las tablas regulatorias (buckets de tiempo, shocks, umbrales) van en
  `backend/config/*.yaml`, nunca hardcodeadas en el código de negocio
- Todo cálculo financiero (descuento, slotting, shocks) debe tener test
  unitario con un caso de referencia calculado a mano o verificable
- Nombres de variables en inglés (estándar en banca/finanzas: `eve`, `nii`,
  `repricing_gap`, no traducir a español)
- Commits pequeños por fase, mensajes en español o inglés (consistente)

## Fases del proyecto
1. Modelo de balance sintético + carga de curva real
2. Cash flow slotting básico (contractual, sin comportamiento)
3. Motor de descuento + EVE bajo curva base
4. Los 6 shocks + heatmap ΔEVE/ΔNII
5. Supuestos de comportamiento (prepago, NMD decay)
6. NII projection a 12-24 meses
7. Standardised Outlier Test + dashboard final

## Cómo testear
cd backend && pytest
cd frontend && npm test

## Restricciones
- No commitear datos reales de ningún banco — solo datos sintéticos o públicos
- No hacer `git push` sin confirmación explícita
- No añadir dependencias nuevas sin decirlo antes (mantener el stack ligero)
- Si un supuesto financiero no está claro (ej. curva de prepago), preguntar
  antes de inventar un número — mejor una fuente citada (BIS, EBA) que un
  valor arbitrario
- No hacer commit con Claude como autor o coautor
