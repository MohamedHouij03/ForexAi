"""Phase 4 - BUY / WAIT / SELL targets: label statistics per instrument.

Each candle is labelled by simulating a BUY and a SELL with the coach's rules
(SL/TP in ATR, modelled spread, MAX_HOLDING_CANDLES). Labels are recomputed on
demand by training, so nothing is stored; this script shows what they look like.

Usage (from backend/):
    python -m training.create_targets
    python -m training.create_targets -i XAU_USD --horizon 8
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.instruments import UnsupportedInstrumentError
from app.features.store import load_features
from app.models.dataset import target_config
from app.models.targets import label_summary, make_targets
from training.download_data import selected_instruments


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    p = argparse.ArgumentParser(description="Show BUY/WAIT/SELL label statistics.")
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR")
    p.add_argument("--horizon", type=int, help="Max holding in candles (default MAX_HOLDING_CANDLES)")
    args = p.parse_args(argv)
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print("Blindly buying/selling every candle should lose about the spread: that is the bar the AI must beat.\n")
    print(f"{'pair':9} {'labelled':>9} {'BUY%':>6} {'SELL%':>6} {'WAIT%':>6} {'avg R buy':>10} {'avg R sell':>10}  config")
    for name in instruments:
        cfg = target_config(settings, name)
        if args.horizon:
            cfg = replace(cfg, horizon=args.horizon)
        s = label_summary(make_targets(load_features(settings, name, settings.granularity), name, cfg))
        print(f"{name:9} {s['valid']:>9,} {s['buy_pct']:>6} {s['sell_pct']:>6} {s['wait_pct']:>6} "
              f"{s['mean_long_r']:>+10.3f} {s['mean_short_r']:>+10.3f}  "
              f"SL {cfg.sl_atr}xATR TP {cfg.tp_atr}xATR, max {cfg.horizon} candles, spread {cfg.spread_pips} pips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
