import numpy as np
import pandas as pd
import pytest

from app.data.validation import validate_candles
from tests.conftest import make_candles


def run(df):
    return validate_candles(df, "EUR_USD", "M15")


def check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_clean_dataset_passes(candles_df):
    report = run(candles_df)
    assert report.status == "PASS", report.format_text()
    assert report.coverage["coverage_pct"] == 100
    assert report.rows == len(candles_df)
    assert report.spread_pips["median"] == pytest.approx(0.8)


def test_duplicates_fail(candles_df):
    df = pd.concat([candles_df, candles_df.iloc[[10]]]).sort_values("time", kind="stable")
    report = run(df)
    assert report.status == "FAIL"
    assert check(report, "duplicate_timestamps").count == 2


def test_out_of_order_fails(candles_df):
    df = candles_df.copy()
    df.iloc[[5, 6]] = df.iloc[[6, 5]].to_numpy()
    assert check(run(df), "out_of_order").count >= 1


def test_high_below_low_fails(candles_df):
    df = candles_df.copy()
    df.loc[3, "high"] = df.loc[3, "low"] - 0.001
    report = run(df)
    assert report.status == "FAIL"
    assert check(report, "mid_ohlc_inconsistent").count == 1


def test_ask_below_bid_fails(candles_df):
    df = candles_df.copy()
    df.loc[4, "ask_close"] = df.loc[4, "bid_close"] - 0.0001
    report = run(df)
    assert report.status == "FAIL"
    assert check(report, "ask_below_bid").count == 1


def test_null_and_non_positive_fail(candles_df):
    df = candles_df.copy()
    df.loc[1, "close"] = np.nan
    df.loc[2, "bid_low"] = 0
    report = run(df)
    assert check(report, "null_values").count == 1
    assert check(report, "bid_non_positive_price").count == 1
    assert report.status == "FAIL"


def test_unaligned_timestamp_fails(candles_df):
    df = candles_df.copy()
    df.loc[7, "time"] = df.loc[7, "time"] + pd.Timedelta(minutes=7)
    assert check(run(df), "unaligned_timestamps").count == 1


def test_missing_candles_detected_as_gap(candles_df):
    df = candles_df.drop(index=[100, 101, 102]).reset_index(drop=True)
    report = run(df)
    assert report.coverage["missing_excluding_holidays"] == 3
    assert report.gaps["summary"]["short"] == {"gaps": 1, "missing_candles": 3}
    assert report.gaps["largest"][0]["start"] == candles_df.loc[100, "time"].isoformat()
    # a few missing candles is informational, not a failure
    assert report.status == "PASS"


def test_long_gap_warns():
    df = make_candles("2024-03-04", "2024-03-22")
    gap = (df["time"] >= "2024-03-12") & (df["time"] < "2024-03-14")
    report = run(df[~gap].reset_index(drop=True))
    assert check(report, "long_gaps").count == 1
    assert report.status == "WARN"


def test_low_coverage_warns():
    df = make_candles("2024-03-04", "2024-03-16")
    report = run(df.iloc[::2].reset_index(drop=True))  # drop every other candle
    assert check(report, "coverage_below_threshold").count == 1
    assert report.status == "WARN"


def test_weekend_gap_is_not_missing():
    # make_candles already skips the weekend; coverage must still be 100%
    report = run(make_candles("2024-03-07", "2024-03-12"))
    assert report.coverage["missing_excluding_holidays"] == 0


def test_christmas_closure_is_holiday_not_missing():
    df = make_candles("2024-12-23", "2024-12-27")
    closed = (df["time"] >= "2024-12-24 22:00") & (df["time"] < "2024-12-25 22:00")
    report = run(df[~closed].reset_index(drop=True))
    assert report.coverage["missing_excluding_holidays"] == 0
    assert report.coverage["holiday_missing"] == closed.sum()
    assert report.gaps["summary"]["holiday"]["gaps"] == 1
    assert report.status == "PASS"


def test_wide_spread_and_extreme_return_warn(candles_df):
    df = candles_df.copy()
    df.loc[20, "ask_close"] = df.loc[20, "bid_close"] + 0.0025  # 25 pips
    df.loc[20, "ask_high"] = max(df.loc[20, "ask_high"], df.loc[20, "ask_close"])  # keep ask OHLC consistent
    for k in ("open", "high", "low", "close"):
        df.loc[30, k] = df.loc[30, k] * 1.03
        df.loc[30, f"bid_{k}"] = df.loc[30, k] - 0.00004
        df.loc[30, f"ask_{k}"] = df.loc[30, k] + 0.00004
    report = run(df)
    assert check(report, "wide_spread").count == 1
    assert check(report, "extreme_returns").count >= 1
    assert report.status == "WARN"


def test_candle_during_weekend_warns(candles_df):
    df = candles_df.copy()
    saturday = pd.DataFrame([{**df.iloc[0].to_dict(), "time": pd.Timestamp("2024-03-09 12:00", tz="UTC")}])
    df = pd.concat([df, saturday]).sort_values("time").reset_index(drop=True)
    assert check(run(df), "candles_while_market_closed").count == 1


def test_empty_and_missing_columns_fail(candles_df):
    assert run(candles_df.iloc[0:0]).status == "FAIL"
    assert run(candles_df.drop(columns=["bid_close"])).status == "FAIL"


def test_report_serialises(candles_df, tmp_path):
    report = run(candles_df)
    path = report.save_json(tmp_path / "r.json")
    assert '"status": "PASS"' in path.read_text()
    assert "STATUS: PASS" in report.format_text()


def test_mid_only_dataset_passes_with_info(candles_df):
    df = candles_df.copy()
    for c in [c for c in df.columns if c.startswith(("bid_", "ask_"))] + ["spread", "volume"]:
        df[c] = None
    report = run(df)
    assert report.status == "PASS", report.format_text()
    assert report.fields_available == {"bid_ask": False, "volume": False}
    assert check(report, "bid_ask_not_provided").severity == "info"
    assert report.spread_pips == {}
    assert "(no bid/ask)" in report.format_text()


def test_mid_only_still_catches_bad_ohlc(candles_df):
    df = candles_df.drop(columns=[c for c in candles_df.columns if c.startswith(("bid_", "ask_"))] + ["volume"])
    df.loc[3, "high"] = df.loc[3, "low"] - 0.001
    assert run(df).status == "FAIL"


def test_partially_missing_bid_ask_fails(candles_df):
    df = candles_df.copy()
    df.loc[5, "bid_close"] = None
    assert check(run(df), "null_values").count == 1


def test_gold_dataset_passes_with_metal_schedule():
    df = make_candles("2024-07-08", "2024-07-20", instrument="XAU_USD")
    report = validate_candles(df, "XAU_USD", "M15")
    assert report.status == "PASS", report.format_text()
    assert report.coverage["missing_excluding_holidays"] == 0  # daily breaks are not "missing"
    assert report.spread_pips["median"] == pytest.approx(30)  # $0.30 = 30 gold pips
    assert check(report, "wide_spread").count == 0  # 0.30 / 2300 = 1.3 bp, normal for gold


def test_gold_checked_against_forex_hours_would_show_gaps():
    df = make_candles("2024-07-08", "2024-07-20", instrument="XAU_USD")
    report = validate_candles(df, "EUR_USD", "M15")  # wrong schedule on purpose
    assert report.coverage["missing_excluding_holidays"] > 0


def test_gold_good_friday_gap_is_holiday():
    df = make_candles("2024-03-25", "2024-04-05", instrument="XAU_USD")
    closed = (df["time"] >= "2024-03-28 22:00") & (df["time"] < "2024-03-29 21:00")  # Good Friday session
    report = validate_candles(df[~closed].reset_index(drop=True), "XAU_USD", "M15")
    assert report.coverage["missing_excluding_holidays"] == 0
    assert report.gaps["summary"]["holiday"]["gaps"] == 1
    # the same gap on EUR/USD is real missing data: forex trades on Good Friday
    fx = make_candles("2024-03-25", "2024-04-05")
    fx_closed = (fx["time"] >= "2024-03-28 21:00") & (fx["time"] < "2024-03-29 21:00")
    assert validate_candles(fx[~fx_closed].reset_index(drop=True), "EUR_USD", "M15").coverage[
        "missing_excluding_holidays"] > 0
