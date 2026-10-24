"""Validate the candle data (missing candles, duplicates, malformed values).

Usage (from backend/):
    python -m training.validate_data                  # clean + validate every INSTRUMENTS pair in the database
    python -m training.validate_data -i XAU_USD       # one instrument
    python -m training.validate_data --source parquet # validate the existing ML dataset file only
Exit code: 0 = PASS/WARN, 1 = FAIL.
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
from app.data.pipeline import build_dataset, validate_with_settings
from app.data.storage import dataset_path, load_parquet
from app.database.repository import CandleRepository
from app.database.session import get_session_factory, init_db
from training.common import format_dataset_result
from training.download_data import selected_instruments


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR",
                   help="Instrument(s) to validate. Default: every instrument in INSTRUMENTS")
    p.add_argument("--granularity", default=settings.granularity)
    p.add_argument("--source", choices=("db", "parquet"), default="db")
    args = p.parse_args(argv)
    granularity = args.granularity.upper()
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    exit_code = 0
    if args.source == "db":
        init_db()
    for instrument in instruments:
        if args.source == "parquet":
            path = dataset_path(settings.data_dir, instrument, granularity)
            if not path.exists():
                print(f"{instrument}: no dataset at {path}. Run training/download_data.py first.", file=sys.stderr)
                exit_code = 1
                continue
            report = validate_with_settings(load_parquet(path), settings, instrument, granularity)
            print(report.format_text())
        else:
            with get_session_factory()() as session:
                raw = CandleRepository(session).load_dataframe(instrument, granularity)
            if raw.empty:
                print(f"{instrument}: no candles stored. Run training/download_data.py first.", file=sys.stderr)
                exit_code = 1
                continue
            result = build_dataset(raw, settings, instrument, granularity)
            report = result.report
            print(format_dataset_result(result))
        if report.status == "FAIL":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
