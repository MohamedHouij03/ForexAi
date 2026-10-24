"""Paginated, resumable historical candle download (provider-agnostic)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from app.data.sources import CandleSource
from app.database.repository import CandleRepository

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    instrument: str
    granularity: str
    source: str
    requested_start: datetime
    requested_end: datetime
    pages: int = 0
    candles_received: int = 0
    candles_stored: int = 0
    incomplete_skipped: int = 0
    first_time: datetime | None = None
    last_time: datetime | None = None

    def to_dict(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(self).items()}


class HistoricalDownloader:
    def __init__(self, source: CandleSource, repository: CandleRepository, instrument: str, granularity: str):
        self.source = source
        self.repository = repository
        self.instrument = instrument
        self.granularity = granularity

    def download(self, start: datetime, end: datetime | None = None) -> DownloadResult:
        """Download completed candles with ``start <= time < end`` and upsert them.

        Pages are fetched oldest-first and committed one by one, so an
        interrupted run can resume from the latest stored candle.
        Incomplete (still-forming) candles are never stored.
        """
        end = end or datetime.now(timezone.utc)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware UTC datetimes")
        result = DownloadResult(self.instrument, self.granularity, self.source.source_name, start, end)

        cursor = start
        while cursor < end:
            page = self.source.fetch_page(self.instrument, self.granularity, cursor)
            result.pages += 1
            result.candles_received += len(page.candles)

            in_range = [c for c in page.candles if start <= c["time"] < end]
            complete = [c for c in in_range if c["complete"]]
            result.incomplete_skipped += len(in_range) - len(complete)

            if complete:
                self.repository.upsert_candles(
                    self.instrument, self.granularity, complete, source=self.source.source_name
                )
                result.candles_stored += len(complete)
                if result.first_time is None:
                    result.first_time = complete[0]["time"]
                result.last_time = complete[-1]["time"]
            logger.info(
                "Page %d from %s: %d candles stored (total %d)",
                result.pages, cursor.strftime("%Y-%m-%d %H:%M"), len(complete), result.candles_stored,
            )

            if page.next_from is None or page.next_from <= cursor:
                break
            cursor = page.next_from

        return result
