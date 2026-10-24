"""Build larger candles (e.g. 1 hour) from clean smaller ones (15 minutes).

A 1-hour candle at 10:00 covers the 15-minute candles 10:00, 10:15, 10:30, 10:45:
open = first open, high = max, low = min, close = last close (same for bid/ask),
volume = sum. Hours with no 15-minute candles produce no candle. Only candles
that are already known are combined, so no future data is involved.
"""

from __future__ import annotations

import pandas as pd

from app.core.instruments import GRANULARITY_SECONDS

_OHLC = {"open": "first", "high": "max", "low": "min", "close": "last"}


def resample_candles(df: pd.DataFrame, to_granularity: str) -> pd.DataFrame:
    seconds = GRANULARITY_SECONDS[to_granularity.upper()]
    rule = pd.Timedelta(seconds=seconds)
    d = df.copy()
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.sort_values("time").set_index("time")

    agg: dict[str, str] = {}
    for prefix in ("", "bid_", "ask_"):
        for col, how in _OHLC.items():
            if f"{prefix}{col}" in d.columns:
                agg[f"{prefix}{col}"] = how
    if "volume" in d.columns:
        agg["volume"] = "sum"
    grouped = d.groupby(d.index.floor(rule))
    out = grouped.agg(agg)
    out["sub_candles"] = grouped.size()
    if "volume" in out and d["volume"].isna().all():
        out["volume"] = float("nan")  # keep "no volume" as missing, not 0
    if {"bid_close", "ask_close"} <= set(out.columns):
        out["spread"] = out["ask_close"] - out["bid_close"]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out.index.name = "time"
    return out.reset_index()
