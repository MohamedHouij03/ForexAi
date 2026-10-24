import pandas as pd

from app.data.cleaning import clean_candles
from app.data.validation import validate_candles
from tests.conftest import make_candles


def mid_only(df):
    return df.drop(columns=[c for c in df.columns if c.startswith(("bid_", "ask_"))] + ["spread", "volume"])


def test_clean_data_is_unchanged(candles_df):
    result = clean_candles(candles_df, "EUR_USD")
    assert len(result.clean) == len(candles_df)
    assert result.summary == {"rows_raw": len(candles_df), "rows_removed": 0, "removed_by_reason": {}}


def test_bad_ohlc_rows_removed_not_repaired(candles_df):
    df = candles_df.copy()
    df.loc[10, "high"] = df.loc[10, "low"] - 0.0005
    result = clean_candles(df, "EUR_USD")
    assert len(result.clean) == len(df) - 1
    assert df.loc[10, "time"] not in set(result.clean["time"])
    assert result.rejected.loc[0, "reason"] == "mid_ohlc_inconsistent"
    assert result.rejected.loc[0, "high"] == df.loc[10, "high"]  # original values kept for inspection


def test_weekend_quotes_removed(candles_df):
    saturday = pd.DataFrame([{**candles_df.iloc[0].to_dict(), "time": pd.Timestamp("2024-03-09 12:00", tz="UTC")}])
    df = pd.concat([candles_df, saturday]).sort_values("time").reset_index(drop=True)
    result = clean_candles(df, "EUR_USD")
    assert result.summary["removed_by_reason"] == {"market_closed": 1}
    assert validate_candles(result.clean, "EUR_USD", "M15").status == "PASS"


def test_duplicates_keep_first(candles_df):
    dup = candles_df.iloc[[5]].assign(close=9.99999, high=9.99999)
    df = pd.concat([candles_df, dup]).reset_index(drop=True)
    result = clean_candles(df, "EUR_USD")
    assert result.summary["removed_by_reason"] == {"duplicate": 1}
    assert not result.clean["time"].duplicated().any()
    assert result.clean.loc[5, "close"] == candles_df.loc[5, "close"]


def test_mid_only_cleaning(candles_df):
    df = mid_only(candles_df)
    df.loc[3, "low"] = df.loc[3, "high"] + 0.001
    result = clean_candles(df, "EUR_USD")
    assert result.summary["removed_by_reason"] == {"mid_ohlc_inconsistent": 1}
    report = validate_candles(result.clean, "EUR_USD", "M15")
    assert report.status == "PASS"
    assert report.coverage["missing_excluding_holidays"] == 1  # the removed candle is now a reported gap


def test_gap_straddling_weekend_is_short_not_long():
    # Missing Friday's last 2 candles and Sunday's first 2: 4 candles, even though ~2 calendar days pass.
    # Summer time: market closes Fri 21:00 UTC, reopens Sun 21:00 UTC.
    df = make_candles("2024-03-11", "2024-03-22")
    fri_end = (df["time"] >= "2024-03-15 20:30") & (df["time"] < "2024-03-15 21:00")
    sun_start = (df["time"] >= "2024-03-17 21:00") & (df["time"] < "2024-03-17 21:30")
    assert (fri_end | sun_start).sum() == 4
    report = validate_candles(df[~(fri_end | sun_start)].reset_index(drop=True), "EUR_USD", "M15")
    assert report.gaps["summary"]["long"]["gaps"] == 0
    assert report.gaps["summary"]["short"] == {"gaps": 1, "missing_candles": 4}
