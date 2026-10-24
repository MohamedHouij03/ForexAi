from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.routes.market_data import _check_params
from app.core.config import Settings, get_settings
from app.core.instruments import get_instrument
from app.database.session import get_db
from app.risk.position_sizing import size_position
from app.signals.engine import live_features

router = APIRouter(tags=["risk"])


@router.get("/risk/preview")
def risk_preview(
    instrument: str | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Illustration of position sizing for a hypothetical BUY at the latest clean close.

    Stop and target use the configured ATR multipliers. This is NOT a trading
    signal - it shows what the risk rules would allow right now.
    """
    instrument, granularity = _check_params(instrument, None)
    inst = get_instrument(instrument)
    df = live_features(db, settings, instrument, granularity)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No candles for {instrument} yet. Run the downloader.")
    atr_value = float(df["atr_14"].iloc[-1])
    entry = float(df["close"].iloc[-1])
    stop = entry - settings.stop_loss_atr_multiplier * atr_value
    target = entry + settings.take_profit_atr_multiplier * atr_value

    pos = size_position(
        instrument,
        balance=settings.account_balance,
        entry=entry,
        stop_loss=stop,
        risk_percent=settings.max_risk_percent,
        allocation_percent=settings.max_trade_allocation_percent,
        leverage=settings.leverage_for(inst.asset_class),
    )
    potential_profit = pos.units * (target - entry) * inst.quote_to_account_rate(entry)
    return {
        **pos.to_dict(),
        "as_of": df["time"].iloc[-1].isoformat(),
        "atr": atr_value,
        "atr_pips": round(inst.price_to_pips(atr_value), 2),
        "take_profit": target,
        "potential_profit": round(potential_profit, 4),
        "risk_reward": round((target - entry) / (entry - stop), 2),
        "display_precision": inst.display_precision,
    }
