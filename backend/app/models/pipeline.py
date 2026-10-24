"""Phases 5-7 end to end: train, compare, walk-forward, select, final test, save.

Order matters for honesty:
  1. Every model is fitted on TRAIN only; decisions (threshold, model choice)
     use VALIDATION and walk-forward folds, all older than the TEST period.
  2. The chosen model is refitted on TRAIN+VALIDATION and evaluated on TEST
     exactly once. Nothing is tuned afterwards.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from app.core.config import Settings
from app.models import evaluation as ev
from app.models.dataset import (
    FEATURES,
    build_training_frame,
    chronological_boundaries,
    split_masks,
    target_config,
    walk_forward_folds,
)
from app.models.targets import label_summary
from app.models.training import CLASSES, MODEL_NAMES, feature_importance, fit_model, make_model, predict_proba

logger = logging.getLogger(__name__)
DEFAULT_THRESHOLD = 0.5


def _predictions(model, rows: pd.DataFrame, period: str) -> pd.DataFrame:
    """Out-of-sample probabilities for every ready candle in `rows` (inputs of the backtester)."""
    if rows.empty:
        return pd.DataFrame(columns=["instrument", "time", "p_sell", "p_wait", "p_buy", "period"])
    proba = predict_proba(model, rows[FEATURES]).astype(np.float32)
    return pd.DataFrame({"instrument": rows["instrument"].to_numpy(), "time": rows["time"].reset_index(drop=True),
                         **{c: proba[c].to_numpy() for c in proba}, "period": period})


def _period(times: pd.Series) -> dict:
    return {"start": pd.Timestamp(times.min()).isoformat(), "end": pd.Timestamp(times.max()).isoformat(),
            "rows": int(len(times))}


def _fit(name, X, y, X_val=None, y_val=None, n_estimators=None):
    """Fit a candidate. XGBoost refits (walk-forward, final) reuse the tree count found on validation."""
    if name == "xgboost" and n_estimators is not None:
        model = make_model(name)
        model.set_params(n_estimators=n_estimators, early_stopping_rounds=None)
        model.fit(X, np.searchsorted(CLASSES, y), verbose=False)
        return model
    return fit_model(name, X, y, X_val, y_val)


def run_training(
    settings: Settings,
    instruments: list[str],
    models: tuple[str, ...] = MODEL_NAMES,
    n_folds: int = 5,
    granularity: str = "M15",
    log: Callable[[str], None] = print,
    horizon: int | None = None,
) -> dict:
    started = time.time()
    horizon = horizon or settings.max_holding_candles
    # every ready candle (for out-of-sample predictions used by the backtester) ...
    full = build_training_frame(settings, instruments, granularity, horizon, labelled_only=False)
    # ... and the rows with a valid label (for training and trade statistics)
    df = full[full["label_valid"]].reset_index(drop=True)
    bounds = chronological_boundaries(df["time"], horizon, granularity)
    masks = split_masks(df["time"], bounds)
    tr, va, te = (df[masks[k]] for k in ("train", "validation", "test"))
    log(f"Data: {len(df):,} labelled candles from {len(instruments)} instrument(s)")
    for name, part in (("train", tr), ("validation", va), ("test", te)):
        log(f"  {name:<10} {part['time'].min():%Y-%m-%d} -> {part['time'].max():%Y-%m-%d}  {len(part):>9,} rows")

    X_tr, y_tr = tr[FEATURES], tr["label"].to_numpy()
    X_va, y_va = va[FEATURES], va["label"].to_numpy()

    candidates: dict[str, dict] = {}
    for name in models:
        t0 = time.time()
        model = _fit(name, X_tr, y_tr, X_va, y_va)
        best_iter = int(getattr(model, "best_iteration", 0) or 0) + 1 if name == "xgboost" else None
        proba = predict_proba(model, X_va)
        sweep = ev.threshold_sweep(va, proba)
        chosen = ev.choose_threshold(sweep)
        thr = chosen["threshold"] if chosen else DEFAULT_THRESHOLD
        decisions = ev.decide(proba, thr)
        candidates[name] = {
            "model": model,
            "n_estimators": best_iter,
            "threshold": thr,
            "validation": {
                "chosen": chosen,
                "classification": ev.classification_metrics(y_va, proba, decisions),
                "top_5pct": ev.top_confidence_stats(va, proba, 0.05),
                "sweep": sweep,
            },
            "feature_importance": feature_importance(name, model, FEATURES),
            "fit_seconds": round(time.time() - t0, 1),
        }
        c = chosen or {}
        log(f"  {name:<20} validation: threshold {thr:.3f}  trades {c.get('trades', 0):>5}  "
            f"mean {c.get('expectancy_r')} R  (95% low {c.get('lower_bound_r')})  "
            f"log-loss {candidates[name]['validation']['classification']['log_loss']} "
            f"vs baseline {candidates[name]['validation']['classification']['log_loss_baseline']}  "
            f"[{candidates[name]['fit_seconds']}s]")

    # ---------------------------------------------------------- walk-forward
    log(f"Walk-forward: {n_folds} expanding folds, all before the test period")
    folds = walk_forward_folds(df["time"], bounds.test_start, n_folds, bounds.embargo)
    full_t = full["time"]
    for name, cand in candidates.items():
        fold_rows, all_trades, oos = [], [], []
        for f in folds:
            ftr, fte = df[f["train"]], df[f["test"]]
            model = _fit(name, ftr[FEATURES], ftr["label"].to_numpy(), n_estimators=cand["n_estimators"])
            window = full[(full_t >= pd.Timestamp(f["start"])) & (full_t < pd.Timestamp(f["end"]))]
            oos.append(_predictions(model, window, "walk_forward"))
            proba = predict_proba(model, fte[FEATURES])
            trades = ev.take_trades(fte, ev.decide(proba, cand["threshold"]))
            all_trades.append(trades)
            stats = ev.trade_stats(trades)
            fold_rows.append({"fold": f["fold"], "start": f["start"], "end": f["end"], "train_rows": int(len(ftr)),
                              "test_rows": int(len(fte)), **stats,
                              "top_5pct_expectancy_r": ev.top_confidence_stats(fte, proba, 0.05)["expectancy_r"]})
        pooled = ev.trade_stats(pd.concat(all_trades, ignore_index=True))
        exps = [r["expectancy_r"] for r in fold_rows if r["expectancy_r"] is not None]
        cand["oos_predictions"] = oos
        cand["walk_forward"] = {**pooled, "folds": fold_rows,
                                "positive_fold_share": round(float(np.mean([e > 0 for e in exps])), 3) if exps else 0.0}
        log(f"  {name:<20} walk-forward: trades {pooled['trades']:>5}  mean {pooled['expectancy_r']} R  "
            f"profitable folds {cand['walk_forward']['positive_fold_share']:.0%}")

    # --------------------------------------------------------------- select
    def score(item):
        c = item[1]
        chosen = c["validation"]["chosen"]
        return (chosen is not None, (chosen or {}).get("expectancy_r") or -9,
                c["walk_forward"].get("expectancy_r") or -9)

    best_name, best = max(candidates.items(), key=score)
    log(f"Selected: {best_name} (best validation result after costs; walk-forward shown for stability)")

    # ------------------------------------------------ final fit + one-time test
    trva = df[masks["train"] | masks["validation"]]
    final = _fit(best_name, trva[FEATURES], trva["label"].to_numpy(), n_estimators=best["n_estimators"])
    proba_te = predict_proba(final, te[FEATURES])
    dec_te = ev.decide(proba_te, best["threshold"])
    trades_te = ev.take_trades(te, dec_te)
    test = {**ev.trade_stats(trades_te),
            "classification": ev.classification_metrics(te["label"].to_numpy(), proba_te, dec_te),
            "top_5pct": ev.top_confidence_stats(te, proba_te, 0.05),
            "by_instrument": {inst: ev.trade_stats(g) for inst, g in trades_te.groupby("instrument")}
            if len(trades_te) else {}}
    ok, reasons = ev.deployable(best["validation"]["chosen"], best["walk_forward"], test)
    oos_test = _predictions(final, full[full_t >= bounds.test_start], "test")
    log(f"TEST (untouched until now): trades {test['trades']}  mean {test['expectancy_r']} R  "
        f"win rate {test['win_rate']}  profit factor {test['profit_factor']}")
    log("DEPLOYABLE: yes - live signals allowed" if ok else "DEPLOYABLE: no - the assistant will keep answering WAIT")
    for r in reasons:
        log(f"  - {r}")

    # ----------------------------------------------------------------- save
    version = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    out_dir = settings.models_dir / version
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, out_dir / "model.joblib")
    trades_te.to_csv(out_dir / "test_trades.csv", index=False)
    pd.concat(best["oos_predictions"] + [oos_test], ignore_index=True).to_parquet(
        out_dir / "oos_predictions.parquet", index=False, compression="zstd")
    report = {
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": best_name,
        "deployable": ok,
        "not_deployable_reasons": reasons,
        "threshold": best["threshold"],
        "instruments": instruments,
        "granularity": granularity,
        "horizon": horizon,
        "features": FEATURES,
        "target": {**target_config(settings, instruments[0], horizon).to_dict(),
                   "spread_pips": {i: settings.spread_pips(i) for i in instruments}},
        "periods": {"train": _period(tr["time"]), "validation": _period(va["time"]), "test": _period(te["time"]),
                    "final_fit": _period(trva["time"]), **bounds.to_dict()},
        "labels": {"train": label_summary(tr), "validation": label_summary(va), "test": label_summary(te)},
        "test": test,
        "feature_importance": best["feature_importance"],
        "comparison": {
            name: {"threshold": c["threshold"], "validation": {k: v for k, v in c["validation"].items()},
                   "walk_forward": c["walk_forward"], "n_estimators": c["n_estimators"],
                   "fit_seconds": c["fit_seconds"], "top_features": dict(list(c["feature_importance"].items())[:15])}
            for name, c in candidates.items()
        },
        "training_seconds": round(time.time() - started, 1),
        # Every run that evaluates on the same test period weakens it as an "unseen" check. Count them.
        "prior_runs_seen_test": sum(1 for d in settings.models_dir.glob("v*/report.json")
                                    if json.loads(d.read_text(encoding="utf-8"))["periods"]["test"]["start"]
                                    == _period(te["time"])["start"]) ,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (settings.models_dir / "current.json").write_text(
        json.dumps({"version": version, "path": str(out_dir)}, indent=2), encoding="utf-8")
    log(f"Saved model {version} -> {out_dir}  ({report['training_seconds']}s total)")
    return report


def load_current(settings: Settings) -> tuple[object, dict] | None:
    pointer = settings.models_dir / "current.json"
    if not pointer.exists():
        return None
    info = json.loads(pointer.read_text(encoding="utf-8"))
    folder = settings.models_dir / info["version"]
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    return joblib.load(folder / "model.joblib"), report


def current_report(settings: Settings) -> dict | None:
    pointer = settings.models_dir / "current.json"
    if not pointer.exists():
        return None
    version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
    path: Path = settings.models_dir / version / "report.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
