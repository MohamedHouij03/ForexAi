"""Phase 4 - targets: what would have happened to a real trade opened at each candle.

For every candle t we simulate BOTH a BUY and a SELL opened at t's close, with
exactly the rules the coach will use:

  stop loss   = SL_MULT x ATR(t)   away from entry
  take profit = TP_MULT x ATR(t)   away from entry
  spread      = the instrument's modelled spread (pips), paid on entry and exit
  max holding = H candles; then the trade is closed at the candle's close

Prices are mid prices, so a BUY enters at mid + spread/2 (the ask) and exits at
mid - spread/2 (the bid); a SELL the opposite. The outcome is measured in R
(1 R = the stop-loss distance): stop = -1 R, target = +TP/SL R (2 R by default),
time exit = whatever the position was worth, net of spread.

If the stop and the target are both touched inside the same candle we cannot
know which came first, so we assume the STOP (pessimistic).

label =  1 (BUY)  if the buy hits its target first
        -1 (SELL) if the sell hits its target first
         0 (WAIT) otherwise (both stopped out, or time ran out)

These columns look into the FUTURE by definition. They are targets only and
must never be used as model inputs. A label is only valid when the next H
candles exist without any gap (no missing candles, no weekend inside the
window) and the features at t are ready.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from app.core.instruments import GRANULARITY_SECONDS, get_instrument

BUY, WAIT, SELL = 1, 0, -1
TARGET_COLUMNS = ["long_r", "short_r", "long_outcome", "short_outcome", "long_bars", "short_bars", "label",
                  "label_valid"]


@dataclass(frozen=True)
class TargetConfig:
    horizon: int = 16          # max holding, candles
    sl_atr: float = 1.5
    tp_atr: float = 3.0
    spread_pips: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def _simulate(close, high, low, entry_offset, target_dist, stop_dist, horizon, direction):
    """Vectorised first-touch simulation for one direction. Returns (r, outcome_code, bars)."""
    n = len(close)
    r = np.full(n, np.nan)
    outcome = np.zeros(n, dtype=np.int8)  # 1 = target, -1 = stop, 2 = time exit, 0 = unknown
    bars = np.zeros(n, dtype=np.int16)
    open_ = np.ones(n, dtype=bool)
    rr = target_dist / stop_dist

    if direction == BUY:
        tp_level = close + entry_offset + target_dist   # mid level where the bid reaches the target
        sl_level = close + entry_offset - stop_dist
    else:
        tp_level = close - entry_offset - target_dist
        sl_level = close - entry_offset + stop_dist

    for k in range(1, horizon + 1):
        fh = np.roll(high, -k)
        fl = np.roll(low, -k)
        fh[n - k:] = np.nan
        fl[n - k:] = np.nan
        if direction == BUY:
            hit_sl = fl <= sl_level
            hit_tp = fh >= tp_level
        else:
            hit_sl = fh >= sl_level
            hit_tp = fl <= tp_level
        stop_now = open_ & hit_sl                      # stop first when both happen in one candle
        tp_now = open_ & hit_tp & ~hit_sl
        r[stop_now], outcome[stop_now], bars[stop_now] = -1.0, -1, k
        r[tp_now], outcome[tp_now], bars[tp_now] = rr[tp_now], 1, k
        open_ &= ~(stop_now | tp_now)

    exit_close = np.roll(close, -horizon)
    exit_close[n - horizon:] = np.nan
    pnl = (exit_close - close - 2 * entry_offset) if direction == BUY else (close - exit_close - 2 * entry_offset)
    timed = open_ & ~np.isnan(exit_close)
    r[timed] = pnl[timed] / stop_dist[timed]
    outcome[timed], bars[timed] = 2, horizon
    return r, outcome, bars


def make_targets(features: pd.DataFrame, instrument: str, config: TargetConfig,
                 granularity: str = "M15") -> pd.DataFrame:
    """Add target columns to a feature frame (from app.features.engineering.build_features)."""
    inst = get_instrument(instrument)
    h = config.horizon
    close = features["close"].to_numpy(float)
    high = features["high"].to_numpy(float)
    low = features["low"].to_numpy(float)
    atr = features["atr_14"].to_numpy(float)
    half_spread = inst.pips_to_price(config.spread_pips) / 2
    entry_offset = np.full(len(close), half_spread)
    stop_dist = config.sl_atr * atr
    target_dist = config.tp_atr * atr

    long_r, long_out, long_bars = _simulate(close, high, low, entry_offset, target_dist, stop_dist, h, BUY)
    short_r, short_out, short_bars = _simulate(close, high, low, entry_offset, target_dist, stop_dist, h, SELL)

    # Valid only if the next h candles are exactly h steps later (no gap, no weekend) and features are ready.
    times = features["time"]
    step = pd.Timedelta(seconds=GRANULARITY_SECONDS[granularity])
    contiguous = (times.shift(-h) - times) == h * step
    valid = contiguous.to_numpy() & features["ready"].to_numpy(bool) & (atr > 0)

    label = np.where(long_out == 1, BUY, np.where(short_out == 1, SELL, WAIT)).astype(np.int8)
    out = features.copy()
    out["long_r"] = np.where(valid, long_r, np.nan)
    out["short_r"] = np.where(valid, short_r, np.nan)
    out["long_outcome"] = np.where(valid, long_out, 0).astype(np.int8)
    out["short_outcome"] = np.where(valid, short_out, 0).astype(np.int8)
    out["long_bars"] = long_bars
    out["short_bars"] = short_bars
    out["label"] = label
    out["label_valid"] = valid
    return out


def label_summary(df: pd.DataFrame) -> dict:
    v = df[df["label_valid"]]
    if v.empty:
        return {"valid": 0}
    counts = v["label"].value_counts(normalize=True)
    return {
        "valid": int(len(v)),
        "buy_pct": round(float(counts.get(BUY, 0)) * 100, 2),
        "sell_pct": round(float(counts.get(SELL, 0)) * 100, 2),
        "wait_pct": round(float(counts.get(WAIT, 0)) * 100, 2),
        "mean_long_r": round(float(v["long_r"].mean()), 4),
        "mean_short_r": round(float(v["short_r"].mean()), 4),
    }
