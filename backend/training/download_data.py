"""Download historical candles, store them, and validate the dataset.

Provider is chosen by DATA_PROVIDER (default: twelvedata). Data goes to
PostgreSQL (table ``candles``) exactly as downloaded. A cleaned ML dataset
(errors and off-market-hours quotes removed, never repaired) is written to
``backend/data/datasets/<INSTRUMENT>_<GRANULARITY>.parquet``; validation
reports and the list of removed rows go to ``backend/data/reports/``.

The download is resumable: re-running continues from the newest stored
candle, and overlapping candles are upserted (never duplicated).

Usage (run from the backend/ directory):
    python -m training.download_data                    # every INSTRUMENTS pair; first run: all history, later: resume
    python -m training.download_data -i XAU_USD -i AUD_USD   # specific instruments
    python -m training.download_data --start 2022-01-01 # explicit start
    python -m training.download_data --full             # re-download the whole HISTORY_YEARS window
    python -m training.download_data --check            # only verify the API key
    python -m training.download_data --replace          # delete stored data first (e.g. after switching provider)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):  # allow `python training/download_data.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings, get_settings
from app.core.instruments import (
    GRANULARITY_SECONDS,
    UnsupportedInstrumentError,
    get_instrument,
    granularity_delta,
)
from app.core.logging import configure_logging
from app.data.downloader import HistoricalDownloader
from app.data.oanda_client import OandaClient
from app.data.sources import CandleSource, DataSourceAuthError, DataSourceError
from app.data.pipeline import build_dataset
from app.features.store import build_and_save
from app.data.twelvedata_client import TwelveDataClient
from app.database.repository import CandleRepository
from app.database.session import get_session_factory, init_db
from training.common import format_dataset_result, parse_utc

logger = logging.getLogger("download_data")

CREDENTIALS_HELP = {
    "twelvedata": """
Twelve Data API key is not configured.

  1. Sign up for free at https://twelvedata.com (email only, no broker account needed).
  2. Copy your API key from the dashboard (API Keys).
  3. Copy .env.example to .env in the repository root and set:
       DATA_PROVIDER=twelvedata
       TWELVEDATA_API_KEY=<your key>
""",
    "oanda": """
OANDA credentials are not configured.

  Set OANDA_API_KEY, OANDA_ACCOUNT_ID and OANDA_ENVIRONMENT=practice in .env,
  or switch to DATA_PROVIDER=twelvedata (no broker account needed).
""",
}


def build_parser(settings: Settings) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Download historical forex / metal candles.")
    p.add_argument("--instrument", "-i", action="append", metavar="PAIR",
                   help="Instrument(s) to download, e.g. -i EUR_USD -i XAU_USD or -i GBP_USD,USD_JPY. "
                        "Default: every instrument in INSTRUMENTS")
    p.add_argument("--granularity", default=settings.granularity, choices=sorted(GRANULARITY_SECONDS))
    p.add_argument("--start", type=parse_utc, help="UTC start date (YYYY-MM-DD). Default: resume, or all history")
    p.add_argument("--end", type=parse_utc, help="UTC end date (exclusive). Default: now")
    p.add_argument("--years", type=int, default=settings.history_years, help="History length for first/full download")
    p.add_argument("--full", action="store_true", help="Ignore stored data and download the whole window again")
    p.add_argument("--replace", action="store_true", help="Delete stored candles for these instruments first")
    p.add_argument("--check", action="store_true", help="Only verify the provider credentials and exit")
    p.add_argument("--no-validate", action="store_true", help="Skip cleaning, validation and Parquet export")
    return p


def selected_instruments(args, settings: Settings) -> list[str]:
    """Normalised, validated instrument names (raises UnsupportedInstrumentError)."""
    raw = [n for item in (args.instrument or [settings.instruments]) for n in item.split(",") if n.strip()]
    return list(dict.fromkeys(get_instrument(n).name for n in raw))


def make_source(settings: Settings):
    # module-level names so tests can substitute the clients
    if settings.data_provider == "twelvedata":
        return TwelveDataClient(
            settings.twelvedata_api_key.get_secret_value(),
            requests_per_minute=settings.twelvedata_requests_per_minute,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.max_retries,
        )
    return OandaClient(
        settings.oanda_api_key.get_secret_value(),
        settings.oanda_environment,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )


def check_credentials(source, settings: Settings) -> None:
    if source.source_name == "twelvedata":
        usage = source.api_usage()
        logger.info("Twelve Data API key OK (plan %s, %s/%s credits used this minute)",
                    usage.get("plan_category"), usage.get("current_usage"), usage.get("plan_limit"))
    elif settings.oanda_account_id:
        account = source.get_account_summary(settings.oanda_account_id)
        logger.info("OANDA %s account %s reachable (currency %s)",
                    settings.oanda_environment, account.get("id"), account.get("currency"))
    else:
        ids = [a.get("id") for a in source.list_accounts()]
        logger.warning("OANDA_ACCOUNT_ID is not set. Accounts available for this token: %s", ", ".join(ids) or "none")


def resolve_start(args, instrument: str, repo: CandleRepository, source: CandleSource, now: datetime) -> datetime:
    if args.start:
        start = args.start
    else:
        start = (now - timedelta(days=round(365.25 * args.years))).replace(hour=0, minute=0, second=0, microsecond=0)
        latest = None if args.full else repo.latest_time(instrument, args.granularity)
        if latest is not None:
            logger.info("%s: resuming after latest stored candle %s", instrument, latest.isoformat())
            return latest  # re-fetch the last candle; the upsert makes that harmless

    earliest = source.earliest_time(instrument, args.granularity)
    if earliest is not None and start < earliest:
        logger.info("%s: %s history starts at %s", instrument, source.source_name, earliest.isoformat())
        step = granularity_delta(args.granularity)
        start = datetime.fromtimestamp(earliest.timestamp() // step.total_seconds() * step.total_seconds(), timezone.utc)
    return start


def download_instrument(args, instrument: str, source, repo: CandleRepository) -> bool:
    """Download one instrument into the database. False if refused (provider mismatch)."""
    if args.replace:
        logger.info("%s: deleted %d stored candles", instrument, repo.delete_all(instrument, args.granularity))
    other = repo.sources(instrument, args.granularity) - {source.source_name}
    if other:
        logger.error(
            "%s: stored candles came from %s, but DATA_PROVIDER=%s. Mixing feeds would corrupt the dataset. "
            "Re-run with --replace to start over with %s.",
            instrument, ", ".join(sorted(other)), source.source_name, source.source_name,
        )
        return False

    now = datetime.now(timezone.utc)
    start = resolve_start(args, instrument, repo, source, now)
    end = args.end or now
    logger.info("%s: downloading %s from %s to %s via %s", instrument, args.granularity,
                start.isoformat(), end.isoformat(), source.source_name)
    result = HistoricalDownloader(source, repo, instrument, args.granularity).download(start, end)
    logger.info("%s: %d pages, %d candles stored, %d incomplete skipped",
                instrument, result.pages, result.candles_stored, result.incomplete_skipped)
    return True


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    args = build_parser(settings).parse_args(argv)
    try:
        instruments = selected_instruments(args, settings)
    except UnsupportedInstrumentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not settings.data_provider_configured:
        print(CREDENTIALS_HELP[settings.data_provider], file=sys.stderr)
        return 2

    init_db()
    summary: list[tuple[str, int, str]] = []
    exit_code = 0
    try:
        with make_source(settings) as source:
            check_credentials(source, settings)
            if args.check:
                return 0

            for instrument in instruments:
                with get_session_factory()() as session:
                    repo = CandleRepository(session)
                    if not download_instrument(args, instrument, source, repo):
                        summary.append((instrument, repo.count(instrument, args.granularity), "REFUSED"))
                        exit_code = max(exit_code, 2)
                        continue
                    df = repo.load_dataframe(instrument, args.granularity)

                if args.no_validate or df.empty:
                    summary.append((instrument, len(df), "not validated" if len(df) else "no data"))
                    continue
                result = build_dataset(df, settings, instrument, args.granularity)
                print(format_dataset_result(result))
                if result.report.status != "FAIL":
                    print("Features: " + build_and_save(settings, instrument, args.granularity).summary())
                summary.append((instrument, result.report.rows, result.report.status))
                if result.report.status == "FAIL":
                    exit_code = max(exit_code, 1)
    except DataSourceAuthError as exc:
        logger.error("%s", exc)
        return 2
    except DataSourceError as exc:
        logger.error("Data provider error: %s. Progress so far is saved; re-run to resume.", exc)
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted. Progress so far is saved; re-run to resume.")
        return 130

    print("\nSUMMARY (clean ML datasets)")
    for instrument, rows, status in summary:
        print(f"  {instrument:<9} {rows:>9,} candles   {status}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
