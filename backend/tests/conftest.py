import os
import tempfile
from pathlib import Path

# Isolate tests from the developer's .env / database BEFORE importing the app.
# Environment variables take precedence over values in .env files.
_TMP = Path(tempfile.mkdtemp(prefix="forex_ai_tests_"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "DATA_DIR": str(_TMP / "data"),
    "MODELS_DIR": str(_TMP / "models"),  # never touch the real trained models
    "DATA_PROVIDER": "twelvedata",
    "INSTRUMENTS": "EUR_USD",
    "GRANULARITY": "M15",
    "TWELVEDATA_API_KEY": "",
    "OANDA_API_KEY": "",
    "OANDA_ACCOUNT_ID": "",
    "OANDA_ENVIRONMENT": "practice",
    "TRADING_MODE": "paper",
    "ACCOUNT_BALANCE": "100",
    "MAX_TRADE_ALLOCATION_PERCENT": "50",
    "MAX_RISK_PERCENT": "1",
    "MAX_OPEN_TRADES": "1",
    "MAX_DAILY_LOSS_PERCENT": "3",
    # pin every trading setting so the developer's .env can never change test results
    "STOP_LOSS_ATR_MULTIPLIER": "1.5",
    "TAKE_PROFIT_ATR_MULTIPLIER": "3",
    "MAX_HOLDING_CANDLES": "16",
    "COACH_MODE": "practice",
    "PRACTICE_SIGNAL_THRESHOLD": "",
    "SPREAD_PIPS_OVERRIDES": "",
    "HISTORY_YEARS": "10",
    "LEVERAGE_FOREX": "30",
    "LEVERAGE_METAL": "20",
    "LOG_LEVEL": "WARNING",
    "LIVE_ENGINE_ENABLED": "false",
    "TELEGRAM_BOT_TOKEN": "",  # tests never message a real phone
    "TELEGRAM_CHAT_ID": "",  # no network in tests; the engine is tested with a fake source
})

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.core.instruments import get_instrument  # noqa: E402
from app.core.market_hours import expected_candle_times  # noqa: E402
from app.database.models import Candle, CoachTrade, Signal  # noqa: E402
from app.database.repository import CandleRepository  # noqa: E402
from app.database.session import get_session_factory, init_db  # noqa: E402

M15 = 900
HALF_SPREAD = 0.00004  # 0.8 pip total spread


def make_candles(start="2024-03-04", end="2024-03-16", seed=7, instrument="EUR_USD") -> pd.DataFrame:
    """Realistic synthetic M15 candles on every market-open slot in [start, end].

    EUR_USD: ~1.08 with a 0.8-pip spread. XAU_USD: ~2300 with a 30-cent spread.
    """
    inst = get_instrument(instrument)
    level, vol, half_spread = (2300.0, 1.5, 0.15) if inst.asset_class == "metal" else (1.08, 0.0003, HALF_SPREAD)
    dp = inst.display_precision
    times = expected_candle_times(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), M15, inst.asset_class)
    rng = np.random.default_rng(seed)
    n = len(times)
    close = np.round(level + np.cumsum(rng.normal(0, vol, n)), dp)
    open_ = np.r_[close[0], close[:-1]]
    high = np.round(np.maximum(open_, close) + rng.uniform(0, vol, n), dp)
    low = np.round(np.minimum(open_, close) - rng.uniform(0, vol, n), dp)
    df = pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close})
    for side, sign in (("bid", -1), ("ask", 1)):
        for k in ("open", "high", "low", "close"):
            df[f"{side}_{k}"] = np.round(df[k] + sign * half_spread, dp)
    df["spread"] = np.round(df["ask_close"] - df["bid_close"], 10)
    df["volume"] = rng.integers(50, 500, n)
    return df


def to_candle_dicts(df: pd.DataFrame, complete: bool = True) -> list[dict]:
    rows = []
    for rec in df.to_dict("records"):
        rec["time"] = pd.Timestamp(rec["time"]).to_pydatetime()
        rec["volume"] = int(rec["volume"])
        rec["complete"] = complete
        rows.append(rec)
    return rows


@pytest.fixture
def candles_df() -> pd.DataFrame:
    return make_candles()


def _clear(session) -> None:
    for model in (Candle, Signal, CoachTrade):
        session.execute(delete(model))
    session.commit()


@pytest.fixture
def db_session():
    init_db()
    with get_session_factory()() as session:
        _clear(session)
        yield session
        session.rollback()
        _clear(session)


@pytest.fixture
def repo(db_session) -> CandleRepository:
    return CandleRepository(db_session)
