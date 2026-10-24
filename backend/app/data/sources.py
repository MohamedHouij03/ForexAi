"""Common interface for market-data providers (Twelve Data, OANDA, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class DataSourceError(RuntimeError):
    """A provider request failed (network, rate limit exhausted, bad response)."""


class DataSourceAuthError(DataSourceError):
    """The provider rejected the credentials. Retrying will not help."""


@dataclass
class CandlePage:
    """Chronological candles starting at the requested time.

    ``next_from`` is where the next page starts, or None when the provider has
    no more data (live edge reached).
    """

    candles: list[dict]
    next_from: datetime | None


class CandleSource(Protocol):
    source_name: str

    def fetch_page(self, instrument: str, granularity: str, from_time: datetime) -> CandlePage: ...

    def earliest_time(self, instrument: str, granularity: str) -> datetime | None: ...
