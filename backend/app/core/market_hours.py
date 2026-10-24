"""Market-hours calendar for forex and spot metals (UTC in, UTC out).

All rules are defined on the New York clock, which keeps them correct across
US daylight-saving changes.

  forex:  open Sunday 17:00 -> Friday 17:00 New York, 24h in between.
  metal:  open Sunday 18:00 -> Friday 17:00 New York, with a daily
          17:00-18:00 break Monday-Thursday (spot gold/silver convention).

Two views are provided:
  * weekly_open_mask - only the weekend closure. Candles outside it are not
    tradable and are removed by cleaning.
  * market_open_mask - weekend closure AND daily breaks. Used to build the
    expected-candle schedule (so a daily break is never "missing data") and the
    live "market open" status. Candles inside a daily break are NOT removed,
    since some feeds legitimately quote through it.

A candle stamped T covers [T, T + granularity). It is expected when the
market is open at T.

Holiday closures (gaps there are classified as "holiday", not missing data):
  forex:  Christmas Day and New Year's Day.
  metal:  the same, plus Good Friday, plus the observed weekday when Dec 25 /
          Jan 1 fall on a weekend (Sat -> Friday before, Sun -> Monday after).
          Verified on Twelve Data XAU/USD 2020-2026; forex keeps trading then.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NEW_YORK = ZoneInfo("America/New_York")
ROLLOVER_HOUR_NY = 17
HOLIDAYS_MMDD = (1225, 101)  # Christmas Day, New Year's Day

# asset class -> (Sunday open hour NY, has daily 17:00-18:00 break)
SCHEDULES = {"forex": (17, False), "metal": (18, True)}


def _ny(times) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(times, utc=True)).tz_convert(NEW_YORK)


def _schedule(asset_class: str) -> tuple[int, bool]:
    try:
        return SCHEDULES[asset_class]
    except KeyError as exc:
        raise ValueError(f"Unknown asset class {asset_class!r}") from exc


def weekly_open_mask(times, asset_class: str = "forex") -> np.ndarray:
    """True unless the timestamp falls in the weekend closure."""
    sunday_open, _ = _schedule(asset_class)
    ny = _ny(times)
    dow, hour = ny.dayofweek, ny.hour  # Monday=0 ... Sunday=6
    closed = (dow == 5) | ((dow == 4) & (hour >= ROLLOVER_HOUR_NY)) | ((dow == 6) & (hour < sunday_open))
    return np.asarray(~closed, dtype=bool)


def market_open_mask(times, asset_class: str = "forex") -> np.ndarray:
    """True where the market is open (weekend closure and daily breaks excluded)."""
    _, daily_break = _schedule(asset_class)
    mask = weekly_open_mask(times, asset_class)
    if daily_break:
        ny = _ny(times)
        in_break = (ny.hour == ROLLOVER_HOUR_NY) & (ny.dayofweek <= 3)  # Mon-Thu 17:00-18:00
        mask &= ~np.asarray(in_break, dtype=bool)
    return mask


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=64)
def metal_holidays(year: int) -> frozenset[date]:
    days = {easter_sunday(year) - timedelta(days=2)}  # Good Friday
    for month, day in ((12, 25), (1, 1)):
        d = date(year, month, day)
        days.add(d)
        if d.weekday() == 5:
            days.add(d - timedelta(days=1))  # Saturday -> observed Friday
        elif d.weekday() == 6:
            days.add(d + timedelta(days=1))  # Sunday -> observed Monday
    return frozenset(days)


def holiday_mask(times, asset_class: str = "forex") -> np.ndarray:
    """True where the timestamp belongs to a holiday trading day.

    The trading day starts at 17:00 New York, so shift by 7 hours to get the
    trading date (e.g. Dec 24 17:00 NY belongs to trading day Dec 25).
    """
    _schedule(asset_class)
    trading = _ny(times) + pd.Timedelta(hours=24 - ROLLOVER_HOUR_NY)
    mask = np.isin(trading.month * 100 + trading.day, HOLIDAYS_MMDD)
    if asset_class == "metal" and len(trading):
        holidays = set().union(*(metal_holidays(int(y)) for y in np.unique(trading.year)))
        mask |= np.asarray([d in holidays for d in trading.date], dtype=bool)
    return mask


def is_market_open(ts: datetime, asset_class: str = "forex") -> bool:
    return bool(market_open_mask([ts], asset_class)[0])


def is_holiday(ts: datetime, asset_class: str = "forex") -> bool:
    return bool(holiday_mask([ts], asset_class)[0])


def expected_candle_times(start: datetime, end: datetime, freq_seconds: int, asset_class: str = "forex") -> pd.DatetimeIndex:
    """All candle timestamps in [start, end] during which the market is open.

    Intended for intraday granularities (<= 1 hour) whose candles align to
    UTC multiples of the granularity.
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    start_ts = start_ts.tz_convert("UTC") if start_ts.tzinfo else start_ts.tz_localize("UTC")
    end_ts = end_ts.tz_convert("UTC") if end_ts.tzinfo else end_ts.tz_localize("UTC")
    freq = pd.Timedelta(seconds=freq_seconds)
    idx = pd.date_range(start_ts.ceil(freq), end_ts.floor(freq), freq=freq, tz="UTC")
    return idx[market_open_mask(idx, asset_class)]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
