"""Build 1-hour (or other) datasets from the clean 15-minute datasets - no new download needed.

Writes backend/data/datasets/<PAIR>_H1.parquet (+ validation reports), exactly as
the downloader does for 15-minute data.

Usage (from backend/):
    python -m training.resample                 # all INSTRUMENTS, 15m -> 1h
    python -m training.resample --to H1 -i XAU_USD
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.instruments import GRANULARITY_SECONDS, UnsupportedInstrumentError
from app.core.logging import configure_logging
from app.data.pipeline import build_dataset
from app.data.resample import resample_candles
from app.data.storage import dataset_path, load_parquet
from app.features.store import build_and_save
from training.download_data import selected_instruments


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging("WARNING")
    p = argparse.ArgumentParser(description="Build larger candles from the clean 15-minute datasets.")
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR")
    p.add_argument("--source", default=settings.granularity, choices=sorted(GRANULARITY_SECONDS))
    p.add_argument("--to", default="H1", choices=sorted(GRANULARITY_SECONDS))
    args = p.parse_args(argv)
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    exit_code = 0
    for name in instruments:
        src = dataset_path(settings.data_dir, name, args.source)
        if not src.exists():
            print(f"{name}: no {args.source} dataset. Run the downloader first.", file=sys.stderr)
            exit_code = 1
            continue
        candles = resample_candles(load_parquet(src), args.to)
        result = build_dataset(candles.drop(columns=["sub_candles"]), settings, name, args.to)
        feats = build_and_save(settings, name, args.to)
        cov = result.report.coverage
        print(f"{name:<9} {args.source}->{args.to}: {len(candles):>7,} candles  status {result.report.status}  "
              f"coverage {cov.get('coverage_pct', 0):.2f}%  ready for training {feats.ready_rows:,}")
        if result.report.status == "FAIL":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
