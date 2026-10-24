"""Minimal OANDA v20 REST client (read-only market data).

Only endpoints needed for market data and credential checks are implemented.
This client has no order-placement methods - V1 never sends real orders.

Docs: https://developer.oanda.com/rest-live-v20/instrument-ep/
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from app.core.config import OANDA_REST_URLS
from app.core.instruments import granularity_delta
from app.data.sources import CandlePage, DataSourceAuthError, DataSourceError

logger = logging.getLogger(__name__)

MAX_CANDLES_PER_REQUEST = 5000
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?Z$")


class OandaError(DataSourceError):
    pass


class OandaAuthError(OandaError, DataSourceAuthError):
    pass


def parse_oanda_time(value: str) -> datetime:
    """Parse OANDA RFC3339 timestamps, which carry nanoseconds (e.g. ...00.000000000Z)."""
    match = _TIME_RE.match(value)
    if not match:
        raise OandaError(f"Unrecognised timestamp from OANDA: {value!r}")
    base, fraction = match.groups()
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    if fraction:
        dt = dt.replace(microsecond=int(fraction[:6].ljust(6, "0")))
    return dt


def format_oanda_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Naive datetime passed to OANDA; use UTC-aware datetimes")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


_OHLC_KEYS = (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"))


def parse_candle(raw: dict) -> dict:
    """Convert an OANDA candle (price=MBA) into a flat row."""
    try:
        mid = raw["mid"]
        row: dict = {
            "time": parse_oanda_time(raw["time"]),
            "volume": int(raw["volume"]),
            "complete": bool(raw["complete"]),
        }
        for prefix, block in (("", mid), ("bid_", raw.get("bid")), ("ask_", raw.get("ask"))):
            for key, name in _OHLC_KEYS:
                row[f"{prefix}{name}"] = float(block[key]) if block else None
    except (KeyError, TypeError, ValueError) as exc:
        raise OandaError(f"Malformed candle from OANDA: {raw!r}") from exc

    if row["ask_close"] is not None and row["bid_close"] is not None:
        row["spread"] = round(row["ask_close"] - row["bid_close"], 10)
    else:
        row["spread"] = None
    return row


class OandaClient:
    source_name = "oanda"

    def __init__(
        self,
        api_key: str,
        environment: str = "practice",
        *,
        timeout: float = 30.0,
        max_retries: int = 5,
        backoff_seconds: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key:
            raise OandaAuthError("OANDA_API_KEY is empty")
        if environment not in OANDA_REST_URLS:
            raise ValueError(f"OANDA environment must be one of {list(OANDA_REST_URLS)}")
        self.environment = environment
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=OANDA_REST_URLS[environment],
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept-Datetime-Format": "RFC3339",
                "Content-Type": "application/json",
            },
        )

    def __enter__(self) -> "OandaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ----------------------------------------------------------- internals
    def _get(self, path: str, params: dict | None = None) -> dict:
        attempt = 0
        while True:
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise OandaError(f"Network error calling OANDA {path}: {exc}") from exc
                self._backoff(attempt, None, f"network error: {exc}")
                attempt += 1
                continue

            if response.status_code in (401, 403):
                raise OandaAuthError(
                    f"OANDA rejected the credentials ({response.status_code}): {_error_message(response)}. "
                    "Check OANDA_API_KEY and that OANDA_ENVIRONMENT matches the account type (practice vs live)."
                )
            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                self._backoff(attempt, response.headers.get("Retry-After"), f"HTTP {response.status_code}")
                attempt += 1
                continue
            if response.status_code >= 400:
                raise OandaError(f"OANDA {path} failed ({response.status_code}): {_error_message(response)}")
            return response.json()

    def _backoff(self, attempt: int, retry_after: str | None, reason: str) -> None:
        delay = min(self.backoff_seconds * 2**attempt, 30.0)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        logger.warning("OANDA request retry %d/%d in %.1fs (%s)", attempt + 1, self.max_retries, delay, reason)
        self._sleep(delay)

    # ---------------------------------------------------------- endpoints
    def get_candles(
        self,
        instrument: str,
        granularity: str,
        *,
        from_time: datetime,
        count: int = MAX_CANDLES_PER_REQUEST,
        include_first: bool = True,
    ) -> list[dict]:
        """Up to ``count`` candles starting at ``from_time`` (mid, bid and ask prices).

        Weekends/closed periods are skipped by OANDA, so a page always holds
        real candles. The last candle may be incomplete (``complete=False``).
        """
        if not 1 <= count <= MAX_CANDLES_PER_REQUEST:
            raise ValueError(f"count must be between 1 and {MAX_CANDLES_PER_REQUEST}")
        payload = self._get(
            f"/v3/instruments/{instrument}/candles",
            params={
                "granularity": granularity,
                "price": "MBA",
                "from": format_oanda_time(from_time),
                "count": count,
                "includeFirst": str(include_first).lower(),
            },
        )
        return [parse_candle(c) for c in payload.get("candles", [])]

    def fetch_page(self, instrument: str, granularity: str, from_time: datetime) -> CandlePage:
        candles = self.get_candles(instrument, granularity, from_time=from_time)
        if not candles:
            return CandlePage([], None)
        live_edge = len(candles) < MAX_CANDLES_PER_REQUEST or not candles[-1]["complete"]
        next_from = None if live_edge else candles[-1]["time"] + granularity_delta(granularity)
        return CandlePage(candles, next_from)

    def earliest_time(self, instrument: str, granularity: str) -> datetime | None:
        return None  # OANDA simply starts at its earliest candle

    def get_account_summary(self, account_id: str) -> dict:
        return self._get(f"/v3/accounts/{account_id}/summary")["account"]

    def list_accounts(self) -> list[dict]:
        return self._get("/v3/accounts").get("accounts", [])


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("errorMessage") or response.text[:200]
    except ValueError:
        return response.text[:200]
