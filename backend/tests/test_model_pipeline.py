import json

import numpy as np
import pandas as pd
import pytest

from app.models import evaluation as ev
from app.models.dataset import chronological_boundaries, split_masks, walk_forward_folds

T0 = pd.Timestamp("2024-01-01", tz="UTC")


def times(n, freq="15min"):
    return pd.Series(pd.date_range(T0, periods=n, freq=freq))


# ----------------------------------------------------------------- splits
def test_chronological_split_with_embargo():
    t = times(10_000)
    b = chronological_boundaries(t, horizon=16)
    m = split_masks(t, b)
    tr, va, te = t[m["train"]], t[m["validation"]], t[m["test"]]
    assert tr.max() < va.min() < va.max() < te.min()  # strictly chronological, never shuffled
    assert va.min() - tr.max() >= b.embargo            # labels of train rows cannot reach validation
    assert te.min() - va.max() >= b.embargo
    assert not (m["train"] & m["validation"]).any() and not (m["validation"] & m["test"]).any()
    assert 0.55 < m["train"].mean() < 0.62 and 0.17 < m["test"].mean() < 0.23


def test_walk_forward_folds_stay_before_test():
    t = times(10_000)
    b = chronological_boundaries(t, horizon=16)
    folds = walk_forward_folds(t, b.test_start, n_folds=4, embargo=b.embargo)
    assert len(folds) == 4
    prev_end = None
    for f in folds:
        train_t, test_t = t[f["train"]], t[f["test"]]
        assert train_t.max() < test_t.min() - b.embargo + pd.Timedelta(minutes=15)  # expanding window, embargo
        assert test_t.max() < b.test_start                                         # test period untouched
        if prev_end is not None:
            assert test_t.min() >= prev_end
        prev_end = test_t.max()
    assert t[folds[-1]["train"]].size > t[folds[0]["train"]].size


# ------------------------------------------------------------- decisions
def proba(buy, sell):
    buy, sell = np.asarray(buy, float), np.asarray(sell, float)
    return pd.DataFrame({"p_sell": sell, "p_wait": 1 - buy - sell, "p_buy": buy})


def test_decide_thresholds_and_wait():
    d = ev.decide(proba([0.6, 0.2, 0.5, 0.3], [0.1, 0.65, 0.5, 0.3]), 0.5)
    assert list(d) == [ev.BUY, ev.SELL, ev.WAIT, ev.WAIT]  # tie -> WAIT; below threshold -> WAIT
    assert (ev.decide(proba([0.34] * 3, [0.33] * 3), 0.5) == ev.WAIT).all()  # the model can always say WAIT


def signal_frame(n=8, bars=3):
    return pd.DataFrame({
        "instrument": ["EUR_USD"] * n, "time": times(n),
        "long_r": [2.0, -1.0, 2.0, -1.0, 2.0, -1.0, 2.0, -1.0], "short_r": [-1.0] * n,
        "long_bars": [bars] * n, "short_bars": [bars] * n, "label": [1] * n,
    })


def test_trades_do_not_overlap_per_instrument():
    df = signal_frame(bars=3)
    trades = ev.take_trades(df, np.full(8, ev.BUY))
    assert list(trades["time"]) == list(df["time"].iloc[[0, 3, 6]])  # busy for 3 candles after each entry
    assert list(trades["r"]) == [2.0, -1.0, 2.0]


def test_trade_stats():
    s = ev.trade_stats(pd.DataFrame({"r": [2.0, -1.0, -1.0, 2.0], "side": ["BUY", "BUY", "SELL", "SELL"]}))
    assert s["trades"] == 4 and s["expectancy_r"] == 0.5 and s["win_rate"] == 0.5
    assert s["profit_factor"] == 2.0 and s["total_r"] == 2.0
    assert s["buy_expectancy_r"] == 0.5
    assert ev.trade_stats(pd.DataFrame({"r": []}))["trades"] == 0


def test_choose_threshold_requires_minimum_trades():
    sweep = [{"threshold": 0.4, "trades": 500, "expectancy_r": 0.02},
             {"threshold": 0.6, "trades": 50, "expectancy_r": 0.9}]  # great but too few trades
    assert ev.choose_threshold(sweep, min_trades=200)["threshold"] == 0.4
    assert ev.choose_threshold(sweep, min_trades=1000) is None


def test_deployability_gate():
    good_val = {"trades": 800, "expectancy_r": 0.12, "lower_bound_r": 0.03}
    good_wf = {"expectancy_r": 0.08, "positive_fold_share": 0.8}
    assert ev.deployable(good_val, good_wf, {"expectancy_r": 0.05}) == (True, [])
    ok, reasons = ev.deployable({"trades": 800, "expectancy_r": 0.03, "lower_bound_r": -0.02}, good_wf,
                                {"expectancy_r": 0.05})
    assert not ok and "not significant" in reasons[0]
    assert not ev.deployable(good_val, {"expectancy_r": 0.08, "positive_fold_share": 0.4}, {"expectancy_r": 0.05})[0]
    assert not ev.deployable(good_val, good_wf, {"expectancy_r": -0.01})[0]  # must survive the untouched test
    assert not ev.deployable(None, good_wf, {"expectancy_r": 0.05})[0]


# ------------------------------------------------------- end-to-end (small)
def test_run_training_end_to_end_on_random_walk(monkeypatch, tmp_path):
    """On a random walk there is no edge: the pipeline must run, save, and refuse to deploy."""
    from app.core.config import Settings
    from app.data.pipeline import build_dataset
    from app.models.pipeline import current_report, load_current, run_training
    from tests.conftest import make_candles

    settings = Settings(_env_file=None, data_dir=tmp_path / "data", models_dir=tmp_path / "models",
                        instruments="EUR_USD,GBP_USD")
    for i, name in enumerate(("EUR_USD", "GBP_USD")):
        build_dataset(make_candles("2024-01-08", "2024-06-29", seed=20 + i), settings, name, "M15")

    logs = []
    report = run_training(settings, ["EUR_USD", "GBP_USD"], models=("logistic_regression", "xgboost"),
                          n_folds=2, log=logs.append)
    assert report["deployable"] is False and report["not_deployable_reasons"]
    assert report["model"] in ("logistic_regression", "xgboost")
    assert set(report["comparison"]) == {"logistic_regression", "xgboost"}
    p = report["periods"]
    assert p["train"]["end"] < p["validation"]["start"] < p["validation"]["end"] < p["test"]["start"]
    assert len(report["comparison"]["xgboost"]["walk_forward"]["folds"]) == 2
    assert abs(sum(report["feature_importance"].values()) - 1) < 1e-3  # each value is rounded to 5 decimals

    model, saved = load_current(settings)
    assert saved["version"] == report["version"] == current_report(settings)["version"]
    assert hasattr(model, "predict_proba")
    assert json.loads((settings.models_dir / "current.json").read_text())["version"] == report["version"]
    assert any("DEPLOYABLE: no" in line for line in logs)
