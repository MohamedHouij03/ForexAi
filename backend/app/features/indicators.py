"""Technical indicators.

Every value at time t uses only candles up to and including t (no look-ahead):
only backward-looking operations are used (shift(+n), rolling windows ending at
t, recursive EMAs). Never use shift(-n), centred windows or backfilling here.
"""

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average, alpha = 2 / (period + 1), recursive (no future data)."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range (exponential smoothing with alpha = 1/period)."""
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index, 0-100."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    # Only gains -> 100; only losses -> 0; no movement at all -> neutral 50.
    out = out.where(loss != 0, np.where(gain > 0, 100.0, 50.0))
    return out.where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame({"bb_middle": mid, "bb_upper": mid + num_std * std, "bb_lower": mid - num_std * std})


def rate_of_change(close: pd.Series, period: int) -> pd.Series:
    """Percentage change over `period` candles."""
    return (close / close.shift(period) - 1.0) * 100.0
