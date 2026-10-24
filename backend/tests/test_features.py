import numpy as np
import pandas as pd
import pytest

from app.features.engineering import (
    DISPLAY_COLUMNS,
    LONG_GAP_BARS,
    MODEL_FEATURES,
    WARMUP_BARS,
    build_features,
    market_trend,
    volatility_regime,
)
from app.features.indicators import bollinger, ema, macd, rate_of_change, rsi
from app.features.sessions import current_session_name, session_flags
from tests.conftest import make_candles

ALL_COLUMNS = MODEL_FEATURES + DISPLAY_COLUMNS


@pytest.fixture(scope="module")
def long_candles() -> pd.DataFrame:
    return make_candles("2024-01-08", "2024-03-02", seed=11)  # ~3,800 candles


@pytest.fixture(scope="module")
def features(long_candles) -> pd.DataFrame:
    return build_features(long_candles, "EUR_USD")


# ------------------------------------------------------------------ indicators
def test_ema_matches_definition():
    s = pd.Series(np.arange(1.0, 31.0))
    e = ema(s, 10)
    assert e.iloc[:9].isna().all()
    alpha = 2 / 11
    manual = [s.iloc[0]]
    for x in s.iloc[1:]:
        manual.append(alpha * x + (1 - alpha) * manual[-1])
    assert e.iloc[-1] == pytest.approx(manual[-1])


def test_rsi_extremes_and_known_value():
    up = pd.Series(np.arange(1.0, 40.0))
    assert rsi(up, 14).iloc[-1] == pytest.approx(100)
    assert rsi(up[::-1].reset_index(drop=True), 14).iloc[-1] == pytest.approx(0)
    assert rsi(pd.Series([1.0] * 30), 14).iloc[-1] == pytest.approx(50)
    # period 2, deltas +1, -1, +2: Wilder averages -> gain 1.25, loss 0.25 after the 3rd delta
    r = rsi(pd.Series([10.0, 11.0, 10.0, 12.0]), 2)
    assert pd.isna(r.iloc[0]) and pd.isna(r.iloc[1])
    assert r.iloc[3] == pytest.approx(100 - 100 / (1 + 1.25 / 0.25))
    assert ((rsi(pd.Series(np.random.default_rng(1).normal(0, 1, 500).cumsum() + 100)).dropna()).between(0, 100)).all()


def test_macd_is_ema_difference():
    s = pd.Series(np.random.default_rng(2).normal(0, 1, 200).cumsum() + 100)
    m = macd(s)
    pd.testing.assert_series_equal(m["macd"], ema(s, 12) - ema(s, 26), check_names=False)
    pd.testing.assert_series_equal(m["macd_hist"], m["macd"] - m["macd_signal"], check_names=False)


def test_bollinger_and_roc():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    bb = bollinger(s, period=5, num_std=2)
    std = np.std([1, 2, 3, 4, 5])
    assert bb["bb_middle"].iloc[-1] == 3
    assert bb["bb_upper"].iloc[-1] == pytest.approx(3 + 2 * std)
    assert bb["bb_middle"].iloc[:4].isna().all()
    assert rate_of_change(s, 2).iloc[-1] == pytest.approx((5 / 3 - 1) * 100)


# -------------------------------------------------------------------- sessions
@pytest.mark.parametrize(
    "ts, asia, london, newyork, overlap",
    [
        ("2024-07-10 03:00", 1, 0, 0, 0),   # Tokyo morning
        ("2024-07-10 07:30", 1, 1, 0, 0),   # London opens 07:00 UTC in summer (BST); Tokyo still open
        ("2024-01-10 07:30", 1, 0, 0, 0),   # ...but 08:00 UTC in winter
        ("2024-07-10 09:30", 0, 1, 0, 0),   # Tokyo closed (18:30 local), London open
        ("2024-07-10 12:30", 0, 1, 1, 1),   # London/New York overlap
        ("2024-07-10 18:00", 0, 0, 1, 0),   # New York afternoon
        ("2024-07-10 22:30", 0, 0, 0, 0),   # between sessions
        ("2024-07-13 12:30", 0, 0, 0, 0),   # Saturday
    ],
)
def test_session_flags_follow_local_clocks(ts, asia, london, newyork, overlap):
    row = session_flags(pd.Series([pd.Timestamp(ts, tz="UTC")])).iloc[0]
    assert (row.session_asia, row.session_london, row.session_newyork, row.session_overlap) == (
        asia, london, newyork, overlap)


def test_session_name():
    assert current_session_name(pd.Timestamp("2024-07-10 12:30", tz="UTC")) == "London / New York overlap"
    assert current_session_name(pd.Timestamp("2024-07-10 03:00", tz="UTC")) == "Asian"


# ------------------------------------------------------------ build_features
def test_columns_and_ready_rows(features, long_candles):
    assert len(features) == len(long_candles)
    assert set(ALL_COLUMNS) <= set(features.columns)
    assert len(MODEL_FEATURES) == len(set(MODEL_FEATURES))
    ready = features[features["ready"]]
    assert not features["ready"].iloc[:WARMUP_BARS].any()  # warm-up is never ready
    assert len(ready) == len(features) - WARMUP_BARS
    assert np.isfinite(ready[MODEL_FEATURES].to_numpy(dtype=float)).all()


def test_candle_structure_features(features, long_candles):
    i = WARMUP_BARS + 5
    c, f = long_candles.iloc[i], features.iloc[i]
    a = f["atr_14"]
    assert f["body_atr"] == pytest.approx((c.close - c.open) / a)
    assert f["upper_wick_atr"] == pytest.approx((c.high - max(c.open, c.close)) / a)
    assert f["lower_wick_atr"] == pytest.approx((min(c.open, c.close) - c.low) / a)
    assert f["range_atr"] == pytest.approx((c.high - c.low) / a)
    assert 0 <= f["body_to_range"] <= 1
    assert f["bullish"] == int(c.close > c.open)
    assert f["ret_4"] == pytest.approx(np.log(c.close / long_candles.iloc[i - 4].close))


def test_no_lookahead_truncation(long_candles, features):
    """The decisive leakage test: features at time t must not change when later candles are removed."""
    for cut in (650, 1200, 2500, len(long_candles) - 1):
        partial = build_features(long_candles.iloc[:cut], "EUR_USD")
        pd.testing.assert_frame_equal(
            partial[ALL_COLUMNS].reset_index(drop=True),
            features[ALL_COLUMNS].iloc[:cut].reset_index(drop=True),
            check_exact=False, rtol=1e-9, atol=1e-12,
        )


def test_no_lookahead_future_shock(long_candles, features):
    shocked = long_candles.copy()
    shocked.loc[2000:, ["open", "high", "low", "close"]] *= 1.25  # rewrite the future
    after = build_features(shocked, "EUR_USD")
    pd.testing.assert_frame_equal(after[ALL_COLUMNS].iloc[:2000], features[ALL_COLUMNS].iloc[:2000])
    assert not np.allclose(after["ema200"].iloc[2100], features["ema200"].iloc[2100])


def test_gap_features():
    df = make_candles("2024-01-08", "2024-02-10", seed=3)
    holed = df.drop(index=[1500, 1501, 1502]).reset_index(drop=True)
    f = build_features(holed, "EUR_USD")
    assert f.loc[1500, "bars_missing_before"] == 3
    assert (f.loc[1500:1523, "bars_missing_24"] == 3).all()
    assert f.loc[1524, "bars_missing_24"] == 0
    assert f["segment"].nunique() == 1  # a short hole does not restart indicators


def test_long_gap_restarts_indicators():
    df = make_candles("2024-01-08", "2024-03-02", seed=4)
    hole = (df["time"] >= "2024-02-05") & (df["time"] < "2024-02-08")  # 3 trading days missing
    f = build_features(df[~hole].reset_index(drop=True), "EUR_USD")
    first_after = int(np.argmax(f["time"] >= pd.Timestamp("2024-02-08", tz="UTC")))
    assert f.loc[first_after, "bars_missing_before"] > LONG_GAP_BARS
    assert f["segment"].nunique() == 2
    assert pd.isna(f.loc[first_after, "ema10"])  # indicators start again after the hole
    assert not f.loc[first_after:first_after + WARMUP_BARS - 1, "ready"].any()


def test_features_are_scale_free():
    """Model features must not depend on the price level (EUR/USD ~1.08 vs USD/JPY ~150)."""
    df = make_candles("2024-01-08", "2024-02-24", seed=5)
    scaled = df.copy()
    scaled[["open", "high", "low", "close"]] *= 140.0
    a = build_features(df, "EUR_USD")
    b = build_features(scaled, "USD_JPY")
    ready = a["ready"]
    # tolerance covers floating-point noise of rolling sums at different magnitudes
    pd.testing.assert_frame_equal(a.loc[ready, MODEL_FEATURES], b.loc[ready, MODEL_FEATURES],
                                  check_exact=False, rtol=1e-4, atol=1e-8)


def test_gold_features_build():
    df = make_candles("2024-07-01", "2024-08-31", instrument="XAU_USD")
    f = build_features(df, "XAU_USD")
    assert f["ready"].sum() > 0
    assert np.isfinite(f.loc[f["ready"], MODEL_FEATURES].to_numpy(dtype=float)).all()


def test_rejects_duplicates(long_candles):
    with pytest.raises(ValueError, match="duplicate"):
        build_features(pd.concat([long_candles, long_candles.iloc[[5]]]), "EUR_USD")


def test_trend_and_volatility_labels():
    assert market_trend(pd.Series({"ema20": 3, "ema50": 2, "ema200": 1})) == "Uptrend"
    assert market_trend(pd.Series({"ema20": 1, "ema50": 2, "ema200": 3})) == "Downtrend"
    assert market_trend(pd.Series({"ema20": 2, "ema50": 1, "ema200": 3})) == "Sideways / mixed"
    assert market_trend(pd.Series({"ema20": np.nan, "ema50": 1, "ema200": 3})) == "Unknown"
    assert (volatility_regime(0.5), volatility_regime(1.0), volatility_regime(1.6)) == ("Low", "Normal", "High")
