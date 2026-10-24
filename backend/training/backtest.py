"""Phase 8 - backtest the current model with your account rules, starting at ACCOUNT_BALANCE.

Only OUT-OF-SAMPLE signals are traded: walk-forward predictions (each made by a
model trained on earlier data only) and the untouched test period. Each period
is backtested separately from a fresh $100 balance.

Writes into the model folder: backtest_<period>.json, backtest_<period>_trades.csv
Usage (from backend/):
    python -m training.backtest
    python -m training.backtest --version v20260923-211049
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from app.core.config import Settings, get_settings
from app.features.store import load_features
from app.trading.backtest import BacktestConfig, equity_curve, run_backtest

PERIODS = ("walk_forward", "test")


def backtest_model(settings: Settings, version: str, log=print) -> dict:
    folder = settings.models_dir / version
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    preds_path = folder / "oos_predictions.parquet"
    if not preds_path.exists():
        raise FileNotFoundError(f"{version} has no out-of-sample predictions; retrain with scripts\\train.cmd")
    preds = pd.read_parquet(preds_path)
    preds["time"] = pd.to_datetime(preds["time"], utc=True)
    gran = report.get("granularity", "M15")
    candles = {i: load_features(settings, i, gran)[["time", "open", "high", "low", "close", "atr_14"]]
               for i in report["instruments"]}
    cfg = BacktestConfig(
        starting_balance=settings.account_balance, risk_percent=settings.max_risk_percent,
        allocation_percent=settings.max_trade_allocation_percent, leverage_forex=settings.leverage_forex,
        leverage_metal=settings.leverage_metal, max_open_trades=settings.max_open_trades,
        max_daily_loss_percent=settings.max_daily_loss_percent, sl_atr=report["target"]["sl_atr"],
        tp_atr=report["target"]["tp_atr"], max_holding=report.get("horizon", report["target"]["horizon"]),
        threshold=report["threshold"], granularity=gran,
        spread_pips={i: settings.spread_pips(i) for i in report["instruments"]},
    )
    summary = {}
    for period in PERIODS:
        p = preds[preds["period"] == period]
        if p.empty:
            continue
        start, end = p["time"].min(), p["time"].max()
        window = {i: c[(c["time"] >= start)] for i, c in candles.items()}
        result = run_backtest(window, p, cfg)
        m = result["metrics"]
        out = {"version": version, "model": report["model"], "granularity": gran, "period": period,
               "start": start.isoformat(), "end": end.isoformat(), "signals": result["signals"],
               "skipped": result["skipped"], "config": result["config"], "metrics": m}
        (folder / f"backtest_{period}.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        result["trades"].to_csv(folder / f"backtest_{period}_trades.csv", index=False)
        equity_curve(result["trades"], cfg.starting_balance).to_csv(folder / f"backtest_{period}_equity.csv",
                                                                    index=False)
        summary[period] = out
        log(f"{period:<13} {start:%Y-%m-%d} -> {end:%Y-%m-%d}  ${m['starting_balance']:.0f} -> "
            f"${m['final_balance']:.2f} ({m['total_return_pct']:+.1f}%)  trades {m['trades']}  "
            f"win {m.get('win_rate', 0):.1%}  PF {m.get('profit_factor')}  max DD {m.get('max_drawdown_pct')}%  "
            f"Sharpe {m.get('sharpe_ratio')}")
        ror = m.get("risk_of_ruin") or {}
        if ror:
            log(f"{'':13} Monte Carlo: chance of a 20% drawdown {ror['prob_drawdown_20pct']:.0%}, "
                f"50% drawdown {ror['prob_drawdown_50pct']:.0%}; median final ${ror['median_final_balance']}")
    return summary


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    p = argparse.ArgumentParser(description="Backtest the current model with the account rules.")
    p.add_argument("--version", help="Model version (default: current)")
    args = p.parse_args(argv)
    version = args.version
    if version is None:
        pointer = settings.models_dir / "current.json"
        if not pointer.exists():
            print("No trained model yet. Run scripts\\train.cmd", file=sys.stderr)
            return 1
        version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
    try:
        backtest_model(settings, version)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
