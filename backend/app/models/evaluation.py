"""Phase 7 - evaluation on unseen data.

Accuracy is NOT the goal: a model that always says WAIT is ~60% "accurate" and
earns nothing. What matters is the result of the trades it would have taken:

  * decisions: BUY if P(BUY) >= threshold and P(BUY) > P(SELL); SELL likewise; else WAIT
  * trades do not overlap per instrument: after a signal, further signals on that
    instrument are ignored until the trade has closed (as when following the coach)
  * each trade's result in R comes from the target simulation (spread included)

Deployability gate - the model may give live signals only if ALL hold:
  1. validation: >= MIN_TRADES trades and the 95% one-sided lower bound of the
     mean R is above 0 (edge not explained by luck),
  2. walk-forward: positive mean R overall and in at least 60% of folds,
  3. final untouched test period: positive mean R.
Otherwise the assistant keeps answering WAIT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

BUY, WAIT, SELL = 1, 0, -1
THRESHOLDS = np.round(np.arange(0.20, 0.701, 0.025), 3)  # BUY/SELL base rates are ~0.18-0.20
MIN_TRADES = 200
Z_95_ONE_SIDED = 1.645


def decide(proba: pd.DataFrame, threshold: float) -> np.ndarray:
    pb, ps = proba["p_buy"].to_numpy(), proba["p_sell"].to_numpy()
    return np.where((pb >= threshold) & (pb > ps), BUY, np.where((ps >= threshold) & (ps > pb), SELL, WAIT))


def take_trades(df: pd.DataFrame, decisions: np.ndarray) -> pd.DataFrame:
    """Non-overlapping trades per instrument. df needs instrument, time, long_r/short_r, long_bars/short_bars."""
    sig = df.assign(decision=decisions)
    sig = sig[sig["decision"] != WAIT]
    if sig.empty:
        return sig.assign(r=pd.Series(dtype=float), side=pd.Series(dtype=str))
    is_buy_all = (sig["decision"] == BUY).to_numpy()
    r_all = np.where(is_buy_all, sig["long_r"].to_numpy(float), sig["short_r"].to_numpy(float))
    bars_all = np.where(is_buy_all, sig["long_bars"].to_numpy(), sig["short_bars"].to_numpy()).astype(np.int64)
    t_all = pd.DatetimeIndex(sig["time"]).tz_convert("UTC").as_unit("ns").asi8  # ns since epoch
    step_ns = 15 * 60 * 10**9
    keep = np.zeros(len(sig), dtype=bool)
    for inst in sig["instrument"].unique():
        idx = np.flatnonzero((sig["instrument"] == inst).to_numpy())
        busy_until = np.iinfo(np.int64).min
        for i in idx:  # time-ordered within each instrument
            if t_all[i] >= busy_until:
                keep[i] = True
                busy_until = t_all[i] + step_ns * max(int(bars_all[i]), 1)
    taken = sig[keep]
    return pd.DataFrame({
        "instrument": taken["instrument"].to_numpy(),
        "time": taken["time"].to_numpy(),
        "side": np.where(is_buy_all[keep], "BUY", "SELL"),
        "r": r_all[keep],
        "label": taken["label"].to_numpy(),
        "bars": bars_all[keep],
    })


def trade_stats(trades: pd.DataFrame) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "expectancy_r": None, "lower_bound_r": None, "win_rate": None,
                "profit_factor": None, "total_r": 0.0}
    r = trades["r"].to_numpy()
    mean, sd = float(r.mean()), float(r.std(ddof=1)) if n > 1 else 0.0
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    out = {
        "trades": n,
        "expectancy_r": round(mean, 4),
        "lower_bound_r": round(mean - Z_95_ONE_SIDED * sd / np.sqrt(n), 4) if n > 1 else None,
        "win_rate": round(float((r > 0).mean()), 4),
        "profit_factor": round(float(gains / losses), 3) if losses > 0 else None,
        "total_r": round(float(r.sum()), 2),
    }
    for side in ("BUY", "SELL"):
        s = trades.loc[trades["side"] == side, "r"]
        out[f"{side.lower()}_trades"] = int(len(s))
        out[f"{side.lower()}_expectancy_r"] = round(float(s.mean()), 4) if len(s) else None
    return out


def threshold_sweep(df: pd.DataFrame, proba: pd.DataFrame, thresholds=THRESHOLDS) -> list[dict]:
    rows = []
    for thr in thresholds:
        stats = trade_stats(take_trades(df, decide(proba, float(thr))))
        rows.append({"threshold": float(thr), **stats})
    return rows


def choose_threshold(sweep: list[dict], min_trades: int = MIN_TRADES) -> dict | None:
    eligible = [s for s in sweep if s["trades"] >= min_trades and s["expectancy_r"] is not None]
    return max(eligible, key=lambda s: s["expectancy_r"]) if eligible else None


def classification_metrics(y: np.ndarray, proba: pd.DataFrame, decisions: np.ndarray) -> dict:
    classes = [SELL, WAIT, BUY]
    p = proba[["p_sell", "p_wait", "p_buy"]].to_numpy()
    prior = np.array([(y == c).mean() for c in classes])
    matrix = pd.crosstab(pd.Series(y, name="actual"), pd.Series(decisions, name="decision")).reindex(
        index=classes, columns=classes, fill_value=0)
    return {
        "log_loss": round(float(log_loss(y, p, labels=classes)), 5),
        "log_loss_baseline": round(float(log_loss(y, np.tile(prior, (len(y), 1)), labels=classes)), 5),
        "accuracy_argmax": round(float((np.array(classes)[p.argmax(axis=1)] == y).mean()), 4),
        "class_share": {"sell": round(float(prior[0]), 4), "wait": round(float(prior[1]), 4),
                        "buy": round(float(prior[2]), 4)},
        # rows = what actually happened, columns = what the model decided (at the chosen threshold)
        "confusion_matrix": {"labels": ["SELL", "WAIT", "BUY"], "matrix": matrix.to_numpy().tolist()},
    }


def top_confidence_stats(df: pd.DataFrame, proba: pd.DataFrame, top_frac: float = 0.05) -> dict:
    """Threshold-free check: trade only the most confident top_frac of candles."""
    conf = proba[["p_buy", "p_sell"]].max(axis=1)
    cut = conf.quantile(1 - top_frac)
    pb, ps = proba["p_buy"].to_numpy(), proba["p_sell"].to_numpy()
    decisions = np.where(conf.to_numpy() >= cut, np.where(pb > ps, BUY, SELL), WAIT)
    return trade_stats(take_trades(df, decisions))


def deployable(validation: dict | None, walk_forward: dict, test: dict) -> tuple[bool, list[str]]:
    reasons = []
    if validation is None or validation["trades"] < MIN_TRADES:
        reasons.append(f"fewer than {MIN_TRADES} validation trades at any threshold")
    elif (validation["lower_bound_r"] or 0) <= 0:
        reasons.append(f"validation edge not significant (mean {validation['expectancy_r']:+.3f} R, "
                       f"95% lower bound {validation['lower_bound_r']:+.3f} R)")
    if (walk_forward.get("expectancy_r") or 0) <= 0:
        reasons.append(f"walk-forward mean {walk_forward.get('expectancy_r')} R is not positive")
    if walk_forward.get("positive_fold_share", 0) < 0.6:
        reasons.append(f"only {walk_forward.get('positive_fold_share', 0):.0%} of walk-forward folds profitable")
    if (test.get("expectancy_r") or 0) <= 0:
        reasons.append(f"untouched test period mean {test.get('expectancy_r')} R is not positive")
    return (not reasons), reasons
