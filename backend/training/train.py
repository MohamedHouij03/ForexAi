"""Phases 5-7 - train Logistic Regression, Random Forest and XGBoost, compare them
on unseen data, walk-forward test them, select one, test it once on the untouched
final period, and save it (backend/models/<version>/).

Usage (from backend/):
    python -m training.train                      # all INSTRUMENTS, all three models
    python -m training.train -i EUR_USD -i GBP_USD
    python -m training.train --models xgboost --folds 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.instruments import UnsupportedInstrumentError
from app.core.logging import configure_logging
from app.models.pipeline import run_training
from app.models.training import MODEL_NAMES
from training.download_data import selected_instruments


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging("WARNING")
    p = argparse.ArgumentParser(description="Train and evaluate the BUY/SELL/WAIT models.")
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR",
                   help="Instrument(s) to train on. Default: every instrument in INSTRUMENTS")
    p.add_argument("--models", nargs="+", choices=MODEL_NAMES, default=list(MODEL_NAMES))
    p.add_argument("--folds", type=int, default=5, help="Walk-forward folds (default 5)")
    p.add_argument("--granularity", default=settings.granularity, help="Candle size, e.g. M15 or H1")
    p.add_argument("--horizon", type=int, help="Max holding in candles (default MAX_HOLDING_CANDLES)")
    args = p.parse_args(argv)
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        run_training(settings, instruments, tuple(args.models), args.folds, args.granularity.upper(),
                     log=lambda m: print(m, flush=True), horizon=args.horizon)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
