from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.data.ecb_client import fetch_eur_curve
from app.data.loaders import load_balance_sheet
from app.domain.nmd_decay import load_nmd_decay_config
from app.domain.prepayment import load_prepayment_config
from app.domain.shocks import load_shock_config
from app.domain.sot import load_sot_config

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "synthetic"
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.balance_sheet = load_balance_sheet(DATA_DIR)
    app.state.yield_curve = fetch_eur_curve()
    app.state.as_of_date = date.today()
    app.state.shock_config = load_shock_config(CONFIG_DIR / "eba_shocks.yaml")
    app.state.sot_config = load_sot_config(CONFIG_DIR / "sot.yaml")
    app.state.cpr_annual = load_prepayment_config(CONFIG_DIR / "prepayment.yaml").cpr_annual
    app.state.nmd_decay_config = load_nmd_decay_config(CONFIG_DIR / "nmd_decay.yaml")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.include_router(router)
