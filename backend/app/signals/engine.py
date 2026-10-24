"""Phase 10 - live signal engine: model + risk rules -> BUY / SELL / WAIT at each candle close.

The engine never forces a trade. A BUY/SELL from the model only survives if every
risk rule passes; otherwise the final decision is WAIT with the reason. Levels
(entry, stop, target) are still recorded for the model's own call so its live
track record can be measured whether or not a trade was allowed or taken.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.core.market_hours import weekly_open_mask
from app.data.cleaning import clean_candles
from app.database.repository import CandleRepository
from app.features.engineering import build_features
from app.models.dataset import FEATURES, add_context_features
from app.risk.position_sizing import size_position

LOOKBACK_CANDLES = 2500  # enough history for EMA200 and the 4-hour EMA to converge (warm-up is 1000)


# ------------------------------------------------------------------ model bundle
@dataclass
class ModelBundle:
    model: object
    version: str
    model_name: str
    threshold: float
    deployable: bool
    granularity: str
    horizon: int
    test_expectancy_r: float | None
    features: list[str] = field(default_factory=lambda: list(FEATURES))  # the columns this model was trained on


_cache: dict[str, ModelBundle] = {}


def load_model_bundle(settings: Settings) -> ModelBundle | None:
    """The model named in models/current.json (cached per version)."""
    pointer = settings.models_dir / "current.json"
    if not pointer.exists():
        return None
    version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
    if version not in _cache:
        folder = settings.models_dir / version
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        _cache[version] = ModelBundle(
            model=joblib.load(folder / "model.joblib"), version=version, model_name=report["model"],
            threshold=float(report["threshold"]), deployable=bool(report["deployable"]),
            granularity=report.get("granularity", "M15"),
            horizon=int(report.get("horizon", report["target"]["horizon"])),
            test_expectancy_r=report.get("test", {}).get("expectancy_r"),
            features=list(report.get("features") or FEATURES),
        )
    return _cache[version]


def predict(bundle: ModelBundle, row: pd.Series) -> dict[str, float]:
    X = pd.DataFrame([row[bundle.features].astype(np.float32).to_numpy()], columns=bundle.features)
    p = bundle.model.predict_proba(X)[0]
    return {"p_sell": float(p[0]), "p_wait": float(p[1]), "p_buy": float(p[2])}


# ------------------------------------------------------------------ features
def live_features(session: Session, settings: Settings, instrument: str, granularity: str) -> pd.DataFrame:
    """Features for the most recent candles, computed exactly like training (clean -> features -> context)."""
    raw = CandleRepository(session).load_recent_dataframe(instrument, granularity, LOOKBACK_CANDLES)
    if raw.empty:
        return raw
    clean = clean_candles(raw, instrument).clean
    feats = build_features(clean, instrument, granularity)
    return add_context_features(feats, instrument, settings.spread_pips(instrument))


# ------------------------------------------------------------------ decision
@dataclass
class AccountState:
    balance: float
    open_instruments: list[str]
    day_realised: float           # P/L of trades closed in the current trading day
    day_start_balance: float


def market_closes_within(candle_close: datetime, minutes: int, asset_class: str) -> bool:
    checks = [pd.Timestamp(candle_close) + pd.Timedelta(minutes=m) for m in range(15, minutes + 1, 15)]
    return bool(checks) and not weekly_open_mask(checks, asset_class).all()


def decide_signal(
    *,
    instrument: str,
    row: pd.Series,
    proba: dict[str, float] | None,
    bundle: ModelBundle | None,
    settings: Settings,
    account: AccountState,
) -> dict:
    """Pure decision logic. Returns the fields of a Signal row."""
    inst = get_instrument(instrument)
    granularity = bundle.granularity if bundle else settings.granularity
    step = timedelta(seconds=GRANULARITY_SECONDS[granularity])
    candle_time = pd.Timestamp(row["time"]).to_pydatetime()
    candle_close = candle_time + step
    out = {
        "instrument": instrument, "granularity": granularity, "candle_time": candle_time,
        "model_version": bundle.version if bundle else None, "mode": settings.coach_mode,
        "p_buy": proba and proba["p_buy"], "p_wait": proba and proba["p_wait"], "p_sell": proba and proba["p_sell"],
        "model_decision": "WAIT", "decision": "WAIT", "reason": None, "atr": float(row.get("atr_14", np.nan)),
        "balance": round(account.balance, 2), "status": "info",
    }

    if bundle is None or proba is None:
        out["reason"] = "No trained model yet."
        return out
    if not bool(row.get("ready", False)):
        out["reason"] = "Indicators are not ready (not enough recent candles)."
        return out

    thr = bundle.threshold
    if settings.coach_mode == "practice" and settings.practice_signal_threshold:
        thr = settings.practice_signal_threshold  # more (weaker) signals for demo practice
    pb, ps = proba["p_buy"], proba["p_sell"]
    model_side = "BUY" if pb >= thr and pb > ps else "SELL" if ps >= thr and ps > pb else "WAIT"
    out["model_decision"] = model_side
    if model_side == "WAIT":
        out["reason"] = (f"No strong opportunity: BUY {pb:.0%}, SELL {ps:.0%} "
                         f"(a signal needs {thr:.0%}).")
        return out

    # Levels for the model's call (also used to score its live track record)
    hs = inst.pips_to_price(settings.spread_pips(instrument)) / 2
    close, atr_v = float(row["close"]), float(row["atr_14"])
    buy = model_side == "BUY"
    entry = close + hs if buy else close - hs
    sl_dist, tp_dist = settings.stop_loss_atr_multiplier * atr_v, settings.take_profit_atr_multiplier * atr_v
    out.update({
        "entry": inst.round_price(entry),
        "stop_loss": inst.round_price(entry - sl_dist if buy else entry + sl_dist),
        "take_profit": inst.round_price(entry + tp_dist if buy else entry - tp_dist),
        "risk_reward": round(tp_dist / sl_dist, 2),
    })

    def wait(reason: str) -> dict:
        out["decision"], out["reason"] = "WAIT", reason
        return out

    if settings.coach_mode == "proven" and not bundle.deployable:
        return wait("The AI has not proven an edge in testing, so no signal is given (proven mode).")
    if instrument in account.open_instruments:
        return wait(f"You already have an open {inst.display_name} trade.")
    if len(account.open_instruments) >= settings.max_open_trades:
        return wait(f"Maximum {settings.max_open_trades} open trade(s) reached - close it first.")
    limit = account.day_start_balance * settings.max_daily_loss_percent / 100
    if account.day_realised <= -limit:
        return wait(f"Daily loss limit reached (-${-account.day_realised:.2f}); no new trades until tomorrow.")
    if market_closes_within(candle_close, settings.max_holding_candles * int(step.total_seconds() // 60), inst.asset_class):
        return wait("The market closes for the weekend before this trade could finish.")

    pos = size_position(instrument, balance=account.balance, entry=entry, stop_loss=out["stop_loss"],
                        risk_percent=settings.max_risk_percent,
                        allocation_percent=settings.max_trade_allocation_percent,
                        leverage=settings.leverage_for(inst.asset_class))
    if not pos.tradable:
        return wait(f"Too small to trade with your limits: {pos.reason}.")

    out.update({
        "decision": model_side,
        "units": pos.units,
        "risk_amount": round(pos.risk_amount, 2),
        "margin_required": round(pos.margin_required, 2),
        "potential_profit": round(pos.units * tp_dist * inst.quote_to_account_rate(entry), 2),
        "status": "actionable",
        "expires_at": candle_close + timedelta(minutes=settings.signal_expiry_minutes),
        "reason": ("PRACTICE signal - this model has NOT proven an edge in testing. Demo account only."
                   if not bundle.deployable else "Model passed all out-of-sample checks."),
    })
    return out
