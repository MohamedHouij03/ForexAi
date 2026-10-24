import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.market_data import _check_params
from app.core.config import Settings, get_settings
from app.database.models import CoachTrade, Signal
from app.database.session import get_db, get_session_factory
from app.live.service import get_live_service, signal_to_dict, trade_to_dict
from app.trading.coach import Coach, CoachError
from app.websocket.manager import manager

router = APIRouter(tags=["coach"])


class TakeRequest(BaseModel):
    fill_price: float = Field(gt=0, description="The price your broker filled you at")
    units: int | None = Field(None, gt=0, description="Units you actually traded (default: the signal's size)")


class CloseRequest(BaseModel):
    exit_price: float = Field(gt=0, description="The price your broker closed the trade at")
    reason: str | None = Field(None, max_length=200)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coach(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> Coach:
    return Coach(db, settings)


@router.get("/live/status")
def live_status(settings: Settings = Depends(get_settings)) -> dict:
    svc = get_live_service()
    status = svc.status.to_dict() if svc else {"running": False, "message": "Live engine not started."}
    return {**status, "coach_mode": settings.coach_mode, "instruments": settings.instrument_list}


@router.get("/signals")
def list_signals(
    instrument: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    only_trades: bool = Query(False, description="Only BUY/SELL decisions"),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Signal).order_by(Signal.candle_time.desc(), Signal.id.desc()).limit(limit)
    if instrument:
        stmt = stmt.where(Signal.instrument == _check_params(instrument, None)[0])
    if only_trades:
        stmt = stmt.where(Signal.decision != "WAIT")
    return [signal_to_dict(s) for s in db.execute(stmt).scalars()]


@router.get("/signals/current")
def current_signals(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[dict]:
    """The latest call (BUY / SELL / WAIT) for every instrument in the watchlist - the scanner overview."""
    out = []
    for name in settings.instrument_list:
        sig = db.execute(select(Signal).where(Signal.instrument == name)
                         .order_by(Signal.candle_time.desc()).limit(1)).scalar_one_or_none()
        out.append(signal_to_dict(sig) if sig else {"instrument": name, "decision": None})
    return out


@router.get("/signals/latest")
def latest_signal(instrument: str | None = Query(None), db: Session = Depends(get_db)) -> dict | None:
    name = _check_params(instrument, None)[0]
    sig = db.execute(select(Signal).where(Signal.instrument == name)
                     .order_by(Signal.candle_time.desc()).limit(1)).scalar_one_or_none()
    return signal_to_dict(sig) if sig else None


@router.post("/signals/{signal_id}/take")
async def take_signal(signal_id: int, body: TakeRequest, coach: Coach = Depends(_coach)) -> dict:
    try:
        trade = coach.take(signal_id, body.fill_price, body.units, _now())
    except CoachError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = trade_to_dict(trade)
    await manager.broadcast("trade", data)
    await manager.broadcast("signal", signal_to_dict(coach.s.get(Signal, signal_id)))
    return data


@router.post("/signals/{signal_id}/skip")
async def skip_signal(signal_id: int, coach: Coach = Depends(_coach)) -> dict:
    try:
        sig = coach.skip(signal_id)
    except CoachError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = signal_to_dict(sig)
    await manager.broadcast("signal", data)
    return data


@router.get("/trades")
def list_trades(status: str = Query("open", pattern="^(open|closed|all)$"), limit: int = Query(100, ge=1, le=1000),
                db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(CoachTrade).order_by(CoachTrade.opened_at.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(CoachTrade.status == status)
    return [trade_to_dict(t) for t in db.execute(stmt).scalars()]


@router.post("/trades/{trade_id}/close")
async def close_trade(trade_id: int, body: CloseRequest, coach: Coach = Depends(_coach)) -> dict:
    try:
        trade = coach.close(trade_id, body.exit_price, _now(), body.reason)
    except CoachError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = trade_to_dict(trade)
    await manager.broadcast("trade", data)
    await manager.broadcast("stats", coach.stats())
    return data


@router.delete("/trades/{trade_id}")
async def cancel_trade(trade_id: int, coach: Coach = Depends(_coach)) -> dict:
    """Remove an open trade that was recorded by mistake (you did not place it at your broker)."""
    try:
        trade = coach.cancel(trade_id, _now())
    except CoachError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = {**trade_to_dict(trade), "status": "cancelled"}
    await manager.broadcast("trade", data)
    await manager.broadcast("stats", coach.stats())
    return data


@router.get("/coach/stats")
def coach_stats(coach: Coach = Depends(_coach)) -> dict:
    return coach.stats()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Live events: price, signal, trade, status, stats. A snapshot is sent on connect."""
    await manager.connect(ws)
    try:
        settings = get_settings()
        with get_session_factory()() as db:
            coach = Coach(db, settings)
            open_trades = [trade_to_dict(t) for t in coach.open_trades()]
            stats = coach.stats()
        svc = get_live_service()
        snapshot = {"status": svc.status.to_dict() if svc else None, "open_trades": open_trades,
                    "stats": stats, "coach_mode": settings.coach_mode}
        await ws.send_text(json.dumps({"event": "snapshot", "data": snapshot}, default=str))
        while True:
            await ws.receive_text()  # keep-alive; the client never needs to send anything
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)
