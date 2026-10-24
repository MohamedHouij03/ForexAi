import json

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas import CandleOut, CandlesResponse, DataSummary, InstrumentInfo
from app.core.config import Settings, get_settings
from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.data.pipeline import build_dataset
from app.data.storage import dataset_path, validation_report_path
from app.database.repository import CandleRepository
from app.database.session import get_db
from app.features.engineering import market_trend, volatility_regime
from app.features.sessions import current_session_name
from app.signals.engine import live_features

router = APIRouter(tags=["market-data"])


def _check_params(instrument: str | None, granularity: str | None) -> tuple[str, str]:
    """Normalise and validate; missing values fall back to the first watchlist instrument / GRANULARITY."""
    settings = get_settings()
    granularity = (granularity or settings.granularity).upper()
    try:
        instrument = get_instrument(instrument or settings.default_instrument).name
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if granularity not in GRANULARITY_SECONDS:
        raise HTTPException(status_code=400, detail=f"Unsupported granularity {granularity!r}")
    return instrument, granularity


def _saved_status(settings: Settings, instrument: str, granularity: str) -> tuple[str | None, str | None]:
    path = validation_report_path(settings.reports_dir, instrument, granularity)
    if not path.exists():
        return None, None
    saved = json.loads(path.read_text(encoding="utf-8"))
    return saved.get("status"), saved.get("generated_at")


@router.get("/instruments", response_model=list[InstrumentInfo])
def list_instruments(
    granularity: str | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[InstrumentInfo]:
    """The configured watchlist (INSTRUMENTS) with metadata and what is stored for each."""
    granularity = _check_params(None, granularity)[1]
    repo = CandleRepository(db)
    out = []
    for name in settings.instrument_list:
        inst = get_instrument(name)
        out.append(InstrumentInfo(
            name=inst.name, display_name=inst.display_name, description=inst.description,
            asset_class=inst.asset_class, pip_size=inst.pip_size, display_precision=inst.display_precision,
            unit_label=inst.unit_label, candles=repo.count(inst.name, granularity),
            last_time=repo.latest_time(inst.name, granularity),
            validation_status=_saved_status(settings, inst.name, granularity)[0],
        ))
    return out


@router.get("/candles", response_model=CandlesResponse)
def get_candles(
    instrument: str | None = Query(None, description="e.g. EUR_USD, XAU_USD (default: first in INSTRUMENTS)"),
    granularity: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> CandlesResponse:
    """Most recent stored candles, oldest first."""
    instrument, granularity = _check_params(instrument, granularity)
    pip = get_instrument(instrument).pip_size
    rows = CandleRepository(db).recent(instrument, granularity, limit)
    candles = [
        CandleOut(
            time=r.time, open=r.open, high=r.high, low=r.low, close=r.close,
            bid_close=r.bid_close, ask_close=r.ask_close, spread=r.spread,
            spread_pips=round(r.spread / pip, 2) if r.spread is not None else None,
            volume=r.volume,
        )
        for r in rows
    ]
    return CandlesResponse(instrument=instrument, granularity=granularity, count=len(candles), candles=candles)


@router.get("/data/summary", response_model=DataSummary)
def data_summary(
    instrument: str | None = Query(None, description="e.g. EUR_USD, XAU_USD (default: first in INSTRUMENTS)"),
    granularity: str | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DataSummary:
    instrument, granularity = _check_params(instrument, granularity)
    repo = CandleRepository(db)
    first, last = repo.time_range(instrument, granularity)

    parquet = dataset_path(settings.data_dir, instrument, granularity)
    status, generated = _saved_status(settings, instrument, granularity)

    return DataSummary(
        instrument=instrument,
        granularity=granularity,
        candles=repo.count(instrument, granularity),
        first_time=first,
        last_time=last,
        sources=sorted(repo.sources(instrument, granularity)),
        parquet_file=parquet.name if parquet.exists() else None,
        parquet_size_mb=round(parquet.stat().st_size / 1e6, 2) if parquet.exists() else None,
        last_validation_status=status,
        last_validation_at=generated,
    )


@router.get("/data/validation")
def latest_validation(
    instrument: str | None = Query(None, description="e.g. EUR_USD, XAU_USD (default: first in INSTRUMENTS)"),
    granularity: str | None = Query(None),
    settings: Settings = Depends(get_settings),
) -> dict:
    """The most recent saved validation report (written by download/validate scripts)."""
    instrument, granularity = _check_params(instrument, granularity)
    path = validation_report_path(settings.reports_dir, instrument, granularity)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No validation report yet. Run the downloader first.")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/data/validation")
def run_validation(
    instrument: str | None = Query(None, description="e.g. EUR_USD, XAU_USD (default: first in INSTRUMENTS)"),
    granularity: str | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Rebuild the cleaned dataset from the stored raw candles, validate it, and save the reports."""
    instrument, granularity = _check_params(instrument, granularity)
    raw = CandleRepository(db).load_dataframe(instrument, granularity)
    return build_dataset(raw, settings, instrument, granularity).report.to_dict()


@router.get("/indicators")
def indicators(
    instrument: str | None = Query(None),
    granularity: str | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Latest indicator values from the newest stored candles - the same computation the live engine uses."""
    instrument, granularity = _check_params(instrument, granularity)
    inst = get_instrument(instrument)
    feats = live_features(db, settings, instrument, granularity)
    if feats.empty:
        raise HTTPException(status_code=404, detail=f"No candles for {instrument} yet. Run the downloader.")
    row = feats.iloc[-1]

    def num(col: str) -> float | None:
        v = row[col]
        return None if pd.isna(v) else float(v)

    return {
        "instrument": instrument,
        "time": row["time"].isoformat(),
        "close": num("close"),
        "rsi_14": num("rsi_14"),
        "macd": num("macd"),
        "macd_signal": num("macd_signal"),
        "macd_hist": num("macd_hist"),
        "atr_14": num("atr_14"),
        "atr_pips": None if pd.isna(row["atr_14"]) else round(inst.price_to_pips(float(row["atr_14"])), 2),
        "ema20": num("ema20"),
        "ema50": num("ema50"),
        "ema200": num("ema200"),
        "bb_upper": num("bb_upper"),
        "bb_lower": num("bb_lower"),
        "atr_ratio_100": num("atr_ratio_100"),
        "volatility": volatility_regime(row["atr_ratio_100"]),
        "trend": market_trend(row),
        "session": current_session_name(row["time"]),
        "display_precision": inst.display_precision,
    }


@router.get("/chart")
def chart(
    instrument: str | None = Query(None),
    limit: int = Query(400, ge=50, le=1000),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Candles + EMA20/50/200 + BUY/SELL signal markers + your trades, for the live chart."""
    from sqlalchemy import select

    from app.database.models import CoachTrade, Signal

    instrument, granularity = _check_params(instrument, None)
    feats = live_features(db, settings, instrument, granularity)
    if feats.empty:
        raise HTTPException(status_code=404, detail=f"No candles for {instrument} yet. Run the downloader.")
    feats = feats.tail(limit)
    start = feats["time"].iloc[0].to_pydatetime()

    def val(v) -> float | None:
        return None if pd.isna(v) else round(float(v), 6)

    candles = [{"time": int(t.timestamp()), "open": o, "high": h, "low": lo, "close": c}
               for t, o, h, lo, c in zip(feats["time"], feats["open"], feats["high"], feats["low"], feats["close"])]
    emas = {f"ema{p}": [{"time": int(t.timestamp()), "value": val(v)} for t, v in zip(feats["time"], feats[f"ema{p}"])
                        if not pd.isna(v)] for p in (20, 50, 200)}
    signals = db.execute(select(Signal).where(Signal.instrument == instrument, Signal.decision != "WAIT",
                                              Signal.candle_time >= start).order_by(Signal.candle_time)).scalars()
    trades = db.execute(select(CoachTrade).where(CoachTrade.instrument == instrument)
                        .order_by(CoachTrade.opened_at.desc()).limit(50)).scalars()
    return {
        "instrument": instrument,
        "granularity": granularity,
        "display_precision": get_instrument(instrument).display_precision,
        "candles": candles,
        **emas,
        "signals": [{"id": s.id, "time": int(s.candle_time.timestamp()), "decision": s.decision, "status": s.status,
                     "mode": s.mode, "entry": s.entry, "stop_loss": s.stop_loss, "take_profit": s.take_profit,
                     "outcome_r": s.outcome_r} for s in signals],
        "trades": [{"id": t.id, "side": t.side, "status": t.status, "entry_price": t.entry_price,
                    "stop_loss": t.stop_loss, "take_profit": t.take_profit, "exit_price": t.exit_price,
                    "opened_at": int(t.opened_at.timestamp()),
                    "closed_at": int(t.closed_at.timestamp()) if t.closed_at else None, "pnl": t.pnl}
                   for t in trades],
    }
