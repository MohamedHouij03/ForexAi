from datetime import datetime, timezone

import pandas as pd
import pytest

from app.core.market_hours import expected_candle_times, is_holiday, is_market_open


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "ts, is_open",
    [
        # Summer (EDT, UTC-4): close Fri 21:00 UTC, open Sun 21:00 UTC
        (utc(2024, 7, 5, 20, 45), True),
        (utc(2024, 7, 5, 21, 0), False),
        (utc(2024, 7, 6, 12, 0), False),   # Saturday
        (utc(2024, 7, 7, 20, 45), False),
        (utc(2024, 7, 7, 21, 0), True),
        # Winter (EST, UTC-5): close Fri 22:00 UTC, open Sun 22:00 UTC
        (utc(2024, 1, 12, 21, 45), True),
        (utc(2024, 1, 12, 22, 0), False),
        (utc(2024, 1, 14, 21, 0), False),
        (utc(2024, 1, 14, 22, 0), True),
        (utc(2024, 1, 10, 3, 30), True),   # mid-week
    ],
)
def test_market_open_tracks_new_york_dst(ts, is_open):
    assert is_market_open(ts) is is_open


def test_one_full_week_has_480_m15_candles():
    # Sunday open to Friday close = 5 x 24h = 120h = 480 x 15m
    times = expected_candle_times(utc(2024, 3, 3), utc(2024, 3, 9), 900)
    assert len(times) == 480
    assert times[0] == pd.Timestamp("2024-03-03 22:00", tz="UTC")
    assert times[-1] == pd.Timestamp("2024-03-08 21:45", tz="UTC")


def test_expected_times_are_utc_and_aligned():
    times = expected_candle_times(utc(2024, 3, 4, 0, 7), utc(2024, 3, 4, 2, 0), 900)
    assert str(times.tz) == "UTC"
    assert times[0] == pd.Timestamp("2024-03-04 00:15", tz="UTC")
    assert all(t.minute % 15 == 0 for t in times)


def test_holiday_trading_days():
    assert is_holiday(utc(2024, 12, 25, 12, 0))
    assert is_holiday(utc(2024, 12, 24, 23, 0))   # 18:00 NY on Dec 24 -> trading day Dec 25
    assert not is_holiday(utc(2024, 12, 24, 12, 0))
    assert is_holiday(utc(2025, 1, 1, 10, 0))
    assert not is_holiday(utc(2025, 1, 2, 10, 0))


@pytest.mark.parametrize(
    "ts, is_open",
    [
        # Gold opens Sunday 18:00 New York (22:00 UTC in summer), an hour after forex.
        (utc(2024, 7, 7, 21, 0), False),
        (utc(2024, 7, 7, 22, 0), True),
        # Daily 17:00-18:00 NY break Mon-Thu (21:00-22:00 UTC in summer)
        (utc(2024, 7, 9, 20, 45), True),
        (utc(2024, 7, 9, 21, 0), False),
        (utc(2024, 7, 9, 21, 45), False),
        (utc(2024, 7, 9, 22, 0), True),
        # Friday close like forex
        (utc(2024, 7, 12, 20, 45), True),
        (utc(2024, 7, 12, 21, 0), False),
    ],
)
def test_metal_schedule(ts, is_open):
    assert is_market_open(ts, "metal") is is_open


def test_metal_week_has_fewer_candles_than_forex():
    # forex 120h; metal loses 1h on Sunday + 4 daily breaks = 115h -> 460 candles
    assert len(expected_candle_times(utc(2024, 7, 7), utc(2024, 7, 13), 900, "metal")) == 460


def test_daily_break_is_not_a_weekend_closure():
    from app.core.market_hours import weekly_open_mask

    assert weekly_open_mask([utc(2024, 7, 9, 21, 15)], "metal")[0]
    assert not weekly_open_mask([utc(2024, 7, 13, 12, 0)], "metal")[0]


@pytest.mark.parametrize("year, good_friday", [(2020, "2020-04-10"), (2021, "2021-04-02"), (2022, "2022-04-15"),
                                               (2023, "2023-04-07"), (2024, "2024-03-29"), (2025, "2025-04-18")])
def test_good_friday(year, good_friday):
    from app.core.market_hours import easter_sunday

    assert str(easter_sunday(year) - __import__("datetime").timedelta(days=2)) == good_friday


@pytest.mark.parametrize(
    "ts, metal, forex",
    [
        (utc(2024, 3, 29, 15, 0), True, False),   # Good Friday: gold closed, forex trades
        (utc(2022, 12, 26, 15, 0), True, False),  # Christmas on Sunday -> observed Monday Dec 26
        (utc(2023, 1, 2, 15, 0), True, False),    # New Year on Sunday -> observed Monday Jan 2
        (utc(2021, 12, 24, 15, 0), True, False),  # Christmas on Saturday -> observed Friday Dec 24
        (utc(2024, 12, 25, 15, 0), True, True),   # Christmas Day: both
        (utc(2024, 3, 28, 15, 0), False, False),  # ordinary Thursday
    ],
)
def test_metal_holidays(ts, metal, forex):
    assert is_holiday(ts, "metal") is metal
    assert is_holiday(ts, "forex") is forex
