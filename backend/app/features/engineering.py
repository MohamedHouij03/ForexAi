"""Feature engineering: clean candles -> model features (no look-ahead).

Design rules
  * Every feature at candle t uses candles <= t only.
  * MODEL features are scale-free (normalised by ATR or price, or bounded like
    RSI), so one definition works for EUR/USD, USD/JPY and gold alike.
    Raw price-level indicators (EMA prices, Bollinger bands, ATR in price) are
    kept as DISPLAY columns for the dashboard, not fed to the model.
  * Data gaps: `bars_missing_before` / `bars_missing_24` tell the model how
    many expected candles are absent. After a long provider hole (more than
    one trading day missing) the series is split into segments and indicators
    restart, so nothing is blended across the hole.
  * The first WARMUP_BARS candles of each segment are marked not ready
    (`ready` = False) because long EMAs (incl. the 4-hour EMA) are still converging.
  * Price levels traders watch (v2): recent highs/lows, the last confirmed swing
    high/low (support / resistance), the previous trading day's high/low/close
    and its classic pivot points, and the 1-hour / 4-hour trend built only from
    higher-timeframe candles that have already closed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.core.market_hours import expected_candle_times
from app.features.indicators import atr, bollinger, ema, macd, rate_of_change, rsi
from app.features.sessions import session_flags

FEATURE_VERSION = 2
RETURN_PERIODS = (1, 2, 4, 8, 12, 24)
EMA_PERIODS = (10, 20, 50, 100, 200)
EMA_PAIRS = ((10, 20), (20, 50), (50, 200))
WARMUP_BARS = 1000         # EMA200 converges after ~600 candles, the 4-hour EMA20 after ~1000 (M15)
LONG_GAP_BARS = 96         # more than one trading day (M15) missing -> new segment
RANGE_PERIODS = (24, 96)   # recent high/low: 6 hours and 1 day of M15 candles
SWING_BARS = 3             # a swing high/low needs 3 lower highs / higher lows on each side
TRADING_DAY_ROLL = pd.Timedelta(hours=7)  # the forex day starts at 17:00 New York

MODEL_FEATURES: list[str] = (
    [f"ret_{n}" for n in RETURN_PERIODS]
    + [f"ret_{n}_atr" for n in RETURN_PERIODS]
    + [f"close_ema{p}_atr" for p in EMA_PERIODS]
    + [f"ema{a}_ema{b}_atr" for a, b in EMA_PAIRS]
    + ["ema20_slope_4_atr", "ema50_slope_12_atr"]
    + ["rsi_14", "macd_atr", "macd_signal_atr", "macd_hist_atr", "roc_10"]
    + ["atr_pct", "atr_ratio_100", "volatility_20", "bb_width", "bb_position"]
    + ["body_atr", "upper_wick_atr", "lower_wick_atr", "range_atr", "body_to_range", "bullish"]
    + ["hour", "day_of_week", "hour_sin", "hour_cos",
       "session_asia", "session_london", "session_newyork", "session_overlap"]
    + ["bars_missing_before", "bars_missing_24"]
    # support / resistance and daily levels
    + [f"dist_high_{n}_atr" for n in RANGE_PERIODS] + [f"dist_low_{n}_atr" for n in RANGE_PERIODS]
    + ["dist_swing_high_atr", "dist_swing_low_atr"]
    + ["dist_prev_high_atr", "dist_prev_low_atr", "close_prev_close_atr", "day_range_pos"]
    + ["close_pivot_atr", "dist_r1_atr", "dist_s1_atr"]
    # higher-timeframe trend (closed 1-hour / 4-hour candles only)
    + ["h1_close_ema20_atr", "h1_ema20_ema50_atr", "h1_ema20_slope_atr", "h1_rsi_14"]
    + ["h4_close_ema20_atr", "h4_ema20_slope_atr", "h4_rsi_14"]
)

DISPLAY_COLUMNS: list[str] = (
    [f"ema{p}" for p in EMA_PERIODS]
    + [f"ema{a}_ema{b}" for a, b in EMA_PAIRS]
    + ["atr_14", "macd", "macd_signal", "macd_hist", "bb_upper", "bb_middle", "bb_lower"]
)

BASE_COLUMNS = ["time", "open", "high", "low", "close"]


def _gap_columns(times: pd.Series, freq_seconds: int, asset_class: str) -> pd.DataFrame:
    """Position of each candle on the expected-candle schedule -> how many expected candles are missing."""
    expected = expected_candle_times(times.iloc[0], times.iloc[-1], freq_seconds, asset_class)
    pos = pd.Series(expected.get_indexer(pd.DatetimeIndex(times)), index=times.index)
    # Candles off the schedule (e.g. a metal's daily break) inherit the previous position.
    pos = pos.where(pos >= 0).ffill().fillna(0).astype(np.int64)
    missing_before = (pos.diff() - 1).clip(lower=0).fillna(0).astype(np.int64)
    missing_24 = ((pos - pos.shift(24)) - 24).clip(lower=0)
    return pd.DataFrame({"bars_missing_before": missing_before, "bars_missing_24": missing_24})


def _level_features(seg: pd.DataFrame, safe_atr: pd.Series) -> pd.DataFrame:
    """Support / resistance: distances (in ATR) from the close to levels known at that candle."""
    h, l, c = seg["high"], seg["low"], seg["close"]
    f = pd.DataFrame(index=seg.index)
    for n in RANGE_PERIODS:
        f[f"dist_high_{n}_atr"] = (h.rolling(n, min_periods=n).max() - c) / safe_atr
        f[f"dist_low_{n}_atr"] = (c - l.rolling(n, min_periods=n).min()) / safe_atr

    # Swing high = the highest candle of a 2k+1 window. It is only known k candles later, so the
    # test at candle t looks at candle t-k against the window ending at t (backward-looking only).
    w, k = 2 * SWING_BARS + 1, SWING_BARS
    cand_h, cand_l = h.shift(k), l.shift(k)
    swing_high = cand_h.where(cand_h == h.rolling(w, min_periods=w).max()).ffill()
    swing_low = cand_l.where(cand_l == l.rolling(w, min_periods=w).min()).ffill()
    f["dist_swing_high_atr"] = (swing_high - c) / safe_atr
    f["dist_swing_low_atr"] = (c - swing_low) / safe_atr

    # Previous trading day (17:00 New York roll) and classic floor pivots.
    day = (seg["time"].dt.tz_convert("America/New_York") + TRADING_DAY_ROLL).dt.date
    by_day = seg.groupby(day)
    daily = pd.DataFrame({"h": by_day["high"].max(), "l": by_day["low"].min(), "c": by_day["close"].last()})
    prev = daily.shift(1)
    ph, pl, pc = (day.map(prev[x]).astype(float) for x in ("h", "l", "c"))
    f["dist_prev_high_atr"] = (ph - c) / safe_atr
    f["dist_prev_low_atr"] = (c - pl) / safe_atr
    f["close_prev_close_atr"] = (c - pc) / safe_atr
    day_hi, day_lo = by_day["high"].cummax(), by_day["low"].cummin()
    rng = day_hi - day_lo
    f["day_range_pos"] = ((c - day_lo) / rng.where(rng > 0)).fillna(0.5)
    pivot = (ph + pl + pc) / 3
    f["close_pivot_atr"] = (c - pivot) / safe_atr
    f["dist_r1_atr"] = (2 * pivot - pl - c) / safe_atr
    f["dist_s1_atr"] = (c - (2 * pivot - ph)) / safe_atr
    return f


def _higher_timeframe(seg: pd.DataFrame, freq_seconds: int, rule: str) -> pd.DataFrame:
    """EMA20/EMA50/RSI14 of the higher-timeframe closes, carried forward until the next one closes.

    A candle is the last of its hour (or 4 hours) when the next candle starts a new one; its close
    is that higher-timeframe candle's close, so nothing is used before it exists.
    """
    t = seg["time"]
    closes = seg["close"][(t + pd.Timedelta(seconds=freq_seconds)).dt.floor(rule) != t.dt.floor(rule)]
    e20 = ema(closes, 20)
    out = pd.DataFrame({"ema20": e20, "ema50": ema(closes, 50), "rsi": rsi(closes, 14),
                        "slope": e20 - e20.shift(3)})
    return out.reindex(seg.index).ffill()


def _segment_features(seg: pd.DataFrame, freq_seconds: int) -> pd.DataFrame:
    o, h, l, c = seg["open"], seg["high"], seg["low"], seg["close"]
    f = pd.DataFrame(index=seg.index)

    a = atr(seg, 14)
    f["atr_14"] = a
    safe_atr = a.where(a > 0)

    log_c = np.log(c)
    for n in RETURN_PERIODS:
        f[f"ret_{n}"] = log_c - log_c.shift(n)
        f[f"ret_{n}_atr"] = (c - c.shift(n)) / safe_atr

    emas = {p: ema(c, p) for p in EMA_PERIODS}
    for p, e in emas.items():
        f[f"ema{p}"] = e
        f[f"close_ema{p}_atr"] = (c - e) / safe_atr
    for x, y in EMA_PAIRS:
        diff = emas[x] - emas[y]
        f[f"ema{x}_ema{y}"] = diff
        f[f"ema{x}_ema{y}_atr"] = diff / safe_atr
    f["ema20_slope_4_atr"] = (emas[20] - emas[20].shift(4)) / safe_atr
    f["ema50_slope_12_atr"] = (emas[50] - emas[50].shift(12)) / safe_atr

    f["rsi_14"] = rsi(c, 14)
    m = macd(c)
    for col in ("macd", "macd_signal", "macd_hist"):
        f[col] = m[col]
        f[f"{col}_atr"] = m[col] / safe_atr
    f["roc_10"] = rate_of_change(c, 10)

    f["atr_pct"] = a / c
    f["atr_ratio_100"] = a / a.rolling(100, min_periods=100).mean()
    f["volatility_20"] = f["ret_1"].rolling(20, min_periods=20).std(ddof=0)
    bb = bollinger(c, 20, 2.0)
    for col in bb:
        f[col] = bb[col]
    band = bb["bb_upper"] - bb["bb_lower"]
    f["bb_width"] = band / bb["bb_middle"]
    f["bb_position"] = ((c - bb["bb_lower"]) / band.where(band > 0)).fillna(0.5).where(band.notna())

    body = c - o
    rng = h - l
    f["body_atr"] = body / safe_atr
    f["upper_wick_atr"] = (h - np.maximum(o, c)) / safe_atr
    f["lower_wick_atr"] = (np.minimum(o, c) - l) / safe_atr
    f["range_atr"] = rng / safe_atr
    f["body_to_range"] = (body.abs() / rng.where(rng > 0)).fillna(0.0)
    f["bullish"] = (c > o).astype(np.int8)

    f = f.join(_level_features(seg, safe_atr))
    h1 = _higher_timeframe(seg, freq_seconds, "1h")
    f["h1_close_ema20_atr"] = (c - h1["ema20"]) / safe_atr
    f["h1_ema20_ema50_atr"] = (h1["ema20"] - h1["ema50"]) / safe_atr
    f["h1_ema20_slope_atr"] = h1["slope"] / safe_atr
    f["h1_rsi_14"] = h1["rsi"]
    h4 = _higher_timeframe(seg, freq_seconds, "4h")
    f["h4_close_ema20_atr"] = (c - h4["ema20"]) / safe_atr
    f["h4_ema20_slope_atr"] = h4["slope"] / safe_atr
    f["h4_rsi_14"] = h4["rsi"]
    return f


def build_features(candles: pd.DataFrame, instrument: str, granularity: str = "M15") -> pd.DataFrame:
    """Compute all features for a clean candle DataFrame (sorted, unique UTC times).

    Returns BASE_COLUMNS + MODEL_FEATURES + DISPLAY_COLUMNS + ["segment", "ready"].
    Rows with ready == False (warm-up, or any model feature missing) must not be used for training.
    """
    inst = get_instrument(instrument)
    freq = GRANULARITY_SECONDS[granularity]
    df = candles[BASE_COLUMNS].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time", kind="stable").reset_index(drop=True)
    if df["time"].duplicated().any():
        raise ValueError("duplicate timestamps - clean the data first")
    if df.empty:
        return df.reindex(columns=BASE_COLUMNS + MODEL_FEATURES + DISPLAY_COLUMNS + ["segment", "ready"])

    gaps = _gap_columns(df["time"], freq, inst.asset_class)
    segment = (gaps["bars_missing_before"] > LONG_GAP_BARS).cumsum()

    parts = [_segment_features(seg, freq) for _, seg in df.groupby(segment, sort=True)]
    feats = pd.concat(parts).sort_index()

    t = df["time"]
    feats["hour"] = t.dt.hour
    feats["day_of_week"] = t.dt.dayofweek
    minutes = t.dt.hour * 60 + t.dt.minute
    feats["hour_sin"] = np.sin(2 * np.pi * minutes / 1440)
    feats["hour_cos"] = np.cos(2 * np.pi * minutes / 1440)
    feats = feats.join(session_flags(t))
    feats = feats.join(gaps)

    out = pd.concat([df, feats], axis=1)
    out["segment"] = segment.astype(np.int32)
    bar_in_segment = out.groupby("segment").cumcount()
    model = out[MODEL_FEATURES].replace([np.inf, -np.inf], np.nan)
    out[MODEL_FEATURES] = model
    out["ready"] = (bar_in_segment >= WARMUP_BARS) & model.notna().all(axis=1)
    return out[BASE_COLUMNS + MODEL_FEATURES + DISPLAY_COLUMNS + ["segment", "ready"]]


def market_trend(row: pd.Series) -> str:
    """Human-readable trend from EMA alignment."""
    e20, e50, e200 = row.get("ema20"), row.get("ema50"), row.get("ema200")
    if any(pd.isna(v) for v in (e20, e50, e200)):
        return "Unknown"
    if e20 > e50 > e200:
        return "Uptrend"
    if e20 < e50 < e200:
        return "Downtrend"
    return "Sideways / mixed"


def volatility_regime(atr_ratio: float) -> str:
    """ATR relative to its 100-candle average."""
    if pd.isna(atr_ratio):
        return "Unknown"
    if atr_ratio < 0.8:
        return "Low"
    if atr_ratio > 1.25:
        return "High"
    return "Normal"
