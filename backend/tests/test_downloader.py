from datetime import datetime, timedelta, timezone

import pandas as pd

from app.data.downloader import HistoricalDownloader
from app.data.sources import CandlePage
from tests.conftest import make_candles, to_candle_dicts


class FakeSource:
    """Count-based paging like OANDA: candles >= from_time, at most `page_size`, closed periods skipped."""

    source_name = "fake"

    def __init__(self, candles: list[dict], page_size: int = 5000):
        self.candles = candles
        self.page_size = page_size
        self.calls: list[datetime] = []

    def fetch_page(self, instrument, granularity, from_time):
        self.calls.append(from_time)
        page = [c for c in self.candles if c["time"] >= from_time][: self.page_size]
        done = len(page) < self.page_size or (page and not page[-1]["complete"])
        return CandlePage(page, None if done or not page else page[-1]["time"] + timedelta(minutes=15))

    def earliest_time(self, instrument, granularity):
        return None


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_paginates_and_stores_everything(repo):
    df = make_candles("2024-03-04", "2024-03-16")  # spans a weekend
    source = FakeSource(to_candle_dicts(df), page_size=100)
    result = HistoricalDownloader(source, repo, "EUR_USD", "M15").download(
        utc(2024, 3, 1), utc(2024, 4, 1)
    )
    assert result.candles_stored == len(df)
    assert result.pages == -(-len(df) // 100)  # ceil
    assert repo.sources("EUR_USD", "M15") == {"fake"}
    assert repo.count("EUR_USD", "M15") == len(df)
    stored = repo.load_dataframe("EUR_USD", "M15")
    assert stored["time"].is_monotonic_increasing
    assert stored["time"].dt.tz is not None
    pd.testing.assert_series_equal(stored["close"], df["close"], check_names=False)


def test_rerun_is_idempotent_no_duplicates(repo):
    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-06"))
    dl = HistoricalDownloader(FakeSource(candles, page_size=50), repo, "EUR_USD", "M15")
    dl.download(utc(2024, 3, 4), utc(2024, 3, 7))
    dl.download(utc(2024, 3, 4), utc(2024, 3, 7))
    assert repo.count("EUR_USD", "M15") == len(candles)
    assert not repo.load_dataframe("EUR_USD", "M15")["time"].duplicated().any()


def test_incomplete_live_candle_is_not_stored(repo):
    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-05"))
    candles[-1]["complete"] = False
    result = HistoricalDownloader(FakeSource(candles), repo, "EUR_USD", "M15").download(utc(2024, 3, 4), utc(2024, 3, 6))
    assert result.incomplete_skipped == 1
    assert repo.count("EUR_USD", "M15") == len(candles) - 1
    assert repo.latest_time("EUR_USD", "M15") == candles[-2]["time"]


def test_end_is_exclusive(repo):
    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-06"))
    end = utc(2024, 3, 5)
    HistoricalDownloader(FakeSource(candles, page_size=30), repo, "EUR_USD", "M15").download(utc(2024, 3, 4), end)
    assert repo.latest_time("EUR_USD", "M15") == utc(2024, 3, 4, 23, 45)


def test_resume_continues_after_latest(repo):
    all_candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-08"))
    first_half = [c for c in all_candles if c["time"] < utc(2024, 3, 6)]
    HistoricalDownloader(FakeSource(first_half), repo, "EUR_USD", "M15").download(utc(2024, 3, 4), utc(2024, 3, 9))

    source = FakeSource(all_candles)
    latest = repo.latest_time("EUR_USD", "M15")
    HistoricalDownloader(source, repo, "EUR_USD", "M15").download(latest, utc(2024, 3, 9))
    assert source.calls[0] == latest
    assert repo.count("EUR_USD", "M15") == len(all_candles)


def test_upsert_updates_existing_values(repo):
    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-04 01:00"))
    repo.upsert_candles("EUR_USD", "M15", candles, source="fake")
    candles[0]["close"] = 1.23456
    repo.upsert_candles("EUR_USD", "M15", candles[:1], source="fake")
    df = repo.load_dataframe("EUR_USD", "M15")
    assert len(df) == len(candles)
    assert df.iloc[0]["close"] == 1.23456


def test_naive_datetimes_rejected(repo):
    import pytest
    from sqlalchemy.exc import StatementError

    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-04 00:30"))
    candles[0]["time"] = candles[0]["time"].replace(tzinfo=None)
    with pytest.raises(StatementError):
        repo.upsert_candles("EUR_USD", "M15", candles, source="fake")


def test_mid_only_candles_roundtrip(repo):
    """Twelve Data rows carry no bid/ask/volume; they must store and load as NaN."""
    candles = to_candle_dicts(make_candles("2024-03-04", "2024-03-04 02:00"))
    for c in candles:
        for k in [k for k in c if k.startswith(("bid_", "ask_"))] + ["spread", "volume"]:
            c[k] = None
    repo.upsert_candles("EUR_USD", "M15", candles, source="twelvedata")
    df = repo.load_dataframe("EUR_USD", "M15")
    assert len(df) == len(candles)
    assert df["bid_close"].isna().all() and df["volume"].isna().all()
    assert df["bid_close"].dtype == float


def test_delete_all(repo):
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-03-04", "2024-03-04 01:00")), source="x")
    assert repo.delete_all("EUR_USD", "M15") == 5
    assert repo.count("EUR_USD", "M15") == 0
