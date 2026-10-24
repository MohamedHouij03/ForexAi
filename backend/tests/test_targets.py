import numpy as np
import pandas as pd
import pytest

from app.models.dataset import FEATURES
from app.models.targets import BUY, SELL, TARGET_COLUMNS, WAIT, TargetConfig, make_targets

T0 = pd.Timestamp("2024-03-05 10:00", tz="UTC")
ATR = 0.0010  # 10 pips -> SL 15 pips, TP 30 pips with the defaults


def frame(path: list[tuple[float, float, float]], start_close=1.1000, atr=ATR) -> pd.DataFrame:
    """Candle 0 is the signal candle (close = start_close); `path` gives (high, low, close) of later candles."""
    rows = [(start_close, start_close, start_close)] + path
    n = len(rows)
    return pd.DataFrame({
        "time": [T0 + pd.Timedelta(minutes=15 * i) for i in range(n)],
        "open": [r[2] for r in rows], "high": [r[0] for r in rows], "low": [r[1] for r in rows],
        "close": [r[2] for r in rows], "atr_14": [atr] * n, "ready": [True] * n,
    })


def run(path, horizon=4, spread=0.0, **kw):
    return make_targets(frame(path, **kw), "EUR_USD", TargetConfig(horizon=horizon, sl_atr=1.5, tp_atr=3.0,
                                                                     spread_pips=spread)).iloc[0]


def flat(n, price=1.1000):
    return [(price + 0.0001, price - 0.0001, price)] * n


def test_buy_target_hit_first():
    r = run([(1.1010, 1.0995, 1.1008), (1.1031, 1.1005, 1.1025)] + flat(2, 1.1025))
    assert r["label"] == BUY
    assert r["long_r"] == pytest.approx(2.0) and r["long_outcome"] == 1 and r["long_bars"] == 2
    assert r["short_r"] == pytest.approx(-1.0)  # the sell was stopped out on the way up


def test_sell_target_hit_first():
    r = run([(1.1002, 1.0985, 1.0990), (1.0995, 1.0969, 1.0975)] + flat(2, 1.0975))
    assert r["label"] == SELL and r["short_r"] == pytest.approx(2.0) and r["long_r"] == pytest.approx(-1.0)


def test_stop_and_target_in_same_candle_counts_as_stop():
    r = run([(1.1035, 1.0980, 1.1000)] + flat(3))  # huge candle touches both
    assert r["long_outcome"] == -1 and r["long_r"] == pytest.approx(-1.0)
    assert r["label"] == WAIT


def test_time_exit_uses_last_close():
    r = run([(1.1006, 1.0998, 1.1004)] * 4)
    assert r["long_outcome"] == 2 and r["label"] == WAIT
    assert r["long_r"] == pytest.approx(0.0004 / 0.0015)
    assert r["short_r"] == pytest.approx(-0.0004 / 0.0015)


def test_spread_makes_targets_harder_and_costs_on_time_exit():
    path = [(1.1030, 1.0995, 1.1025)] + flat(3, 1.1025)  # exactly +30 pips high
    assert run(path)["label"] == BUY
    with_spread = run(path, spread=1.0)  # the bid must reach entry_ask + 30 pips -> not reached
    assert with_spread["label"] == WAIT
    timed = run([(1.1006, 1.0998, 1.1004)] * 4, spread=1.0)
    assert timed["long_r"] == pytest.approx((0.0004 - 0.0001) / 0.0015)


def test_invalid_when_future_missing_or_gap():
    df = frame(flat(3))  # only 3 future candles for horizon 4
    assert not make_targets(df, "EUR_USD", TargetConfig(horizon=4))["label_valid"].iloc[0]
    gapped = frame(flat(6))
    gapped.loc[3:, "time"] += pd.Timedelta(hours=1)  # a hole inside the window
    t = make_targets(gapped, "EUR_USD", TargetConfig(horizon=4))
    assert not t["label_valid"].iloc[:3].any()  # every window that contains the hole is invalid
    contiguous = frame(flat(8))
    assert make_targets(contiguous, "EUR_USD", TargetConfig(horizon=4))["label_valid"].iloc[:4].all()


def test_not_ready_features_are_not_labelled():
    df = frame(flat(6))
    df.loc[0, "ready"] = False
    assert not make_targets(df, "EUR_USD", TargetConfig(horizon=4))["label_valid"].iloc[0]


def test_targets_are_never_features():
    assert not set(TARGET_COLUMNS) & set(FEATURES)
    assert not any(f.startswith(("long_", "short_", "label")) for f in FEATURES)
