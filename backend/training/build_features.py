"""Phase 3 - build model features from the clean datasets.

Reads   backend/data/datasets/<PAIR>_M15.parquet   (from download_data.py)
Writes  backend/data/features/<PAIR>_M15.meta.json (feature list, version, statistics)
        backend/data/features/<PAIR>_M15.parquet   (full table, only with --save; ~50 MB each)

Features are computed from the clean dataset in under a second, so training and
the app recompute them instead of reading a stored copy.

Usage (from backend/):
    python -m training.build_features               # every instrument in INSTRUMENTS
    python -m training.build_features -i XAU_USD
The downloader runs this automatically after each download.
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
from app.features.engineering import MODEL_FEATURES
from app.features.store import build_and_save
from training.download_data import selected_instruments


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    p = argparse.ArgumentParser(description="Build model features from the clean datasets.")
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR",
                   help="Instrument(s). Default: every instrument in INSTRUMENTS")
    p.add_argument("--granularity", default=settings.granularity)
    p.add_argument("--save", action="store_true", help="Also write the full feature table as Parquet")
    args = p.parse_args(argv)
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Building {len(MODEL_FEATURES)} model features per candle (no look-ahead)\n")
    exit_code = 0
    for instrument in instruments:
        try:
            result = build_and_save(settings, instrument, args.granularity.upper(), save_table=args.save)
            print("  " + result.summary() + (f"  -> {result.path}" if result.path else ""))
        except FileNotFoundError as exc:
            print(f"  {instrument:<9} skipped: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
