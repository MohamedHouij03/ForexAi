"""Twelve Data REST client (read-only market data).

Free "Basic" plan: 8 API credits per minute, 800 per day. One time_series
request costs one credit. The client throttles itself to stay under the
per-minute limit.

Twelve Data provides mid OHLC prices for forex. It provides no bid/ask and no
volume, so those columns are stored as NULL. Backtests must then apply a
modelled spread.

Paging: ``outputsize`` returns the *newest* N bars of a range, so we page
forward with fixed date windows that can never hold more than 5000 bars
(4999 x granularity of calendar time).

Docs: https://twelvedata.com/docs#time-series
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx

from app.core.instruments import granularity_delta
from app.data.sources import CandlePage, DataSourceAuthError, DataSourceError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"
MAX_OUTPUTSIZE = 5000
INTERVALS = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "1h"}
_TIME_FMT = "%Y-%m-%d %H:%M:%S"
RATE_LIMIT_WAIT_SECONDS = 61.0


class TwelveDataError(DataSourceError):
    pass


class TwelveDataAuthError(TwelveDataError, DataSourceAuthError):
    pass


def to_symbol(instrument: str) -> str:
    """'EUR_USD' -> 'EUR/USD'."""
    return instrument.upper().replace("_", "/")


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FMT).replace(tzinfo=timezone.utc)


def format_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("Naive datetime passed to Twelve Data; use UTC-aware datetimes")
    return dt.astimezone(timezone.utc).strftime(_TIME_FMT)


def parse_bar(raw: dict, *, step, now: datetime) -> dict:
    try:
        t = parse_time(raw["datetime"])
        row = {"time": t, **{k: round(float(raw[k]), 5) for k in ("open", "high", "low", "close")}}
    except (KeyError, TypeError, ValueError) as exc:
        raise TwelveDataError(f"Malformed bar from Twelve Data: {raw!r}") from exc
    for side in ("bid", "ask"):
        for k in ("open", "high", "low", "close"):
            row[f"{side}_{k}"] = None
    row["spread"] = None
    row["volume"] = None
    # Twelve Data returns the still-forming bar too; it is complete once its window has ended.
    row["complete"] = t + step <= now
    return row


class TwelveDataClient:
    source_name = "twelvedata"

    def __init__(
        self,
        api_key: str,
        *,
        requests_per_minute: int = 8,
        timeout: float = 30.0,
        max_retries: int = 5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if not api_key:
            raise TwelveDataAuthError("TWELVEDATA_API_KEY is empty")
        self._api_key = api_key
        # Twelve Data counts credits per clock minute; spacing at 60/(N-1) s guarantees at most N
        # requests land in any one minute even with network jitter (60/N lets N+1 slip in).
        self.min_interval = 60.0 / max(requests_per_minute - 1, 1) if requests_per_minute > 1 else 60.0
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._now = now
        self._last_request: float | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport)

    def __enter__(self) -> "TwelveDataClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ----------------------------------------------------------- internals
    def _throttle(self) -> None:
        if self._last_request is not None and self.min_interval:
            wait = self._last_request + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    def _get(self, path: str, params: dict) -> dict:
        attempt = 0
        while True:
            self._throttle()
            try:
                response = self._http.get(path, params={**params, "apikey": self._api_key})
                payload = response.json()
            except httpx.TransportError as exc:
                if attempt >= self.max_retries:
                    raise TwelveDataError(f"Network error calling Twelve Data {path}: {exc}") from exc
                self._retry_wait(attempt, f"network error: {exc}")
                attempt += 1
                continue
            except ValueError as exc:
                if response.status_code >= 500 and attempt < self.max_retries:
                    self._retry_wait(attempt, f"HTTP {response.status_code}")
                    attempt += 1
                    continue
                raise TwelveDataError(f"Non-JSON response from Twelve Data ({response.status_code})") from exc

            is_error = isinstance(payload, dict) and payload.get("status") == "error"
            code = int(payload.get("code", response.status_code)) if is_error else response.status_code
            message = payload.get("message", "") if is_error else ""

            if code in (401, 403):
                raise TwelveDataAuthError(f"Twelve Data rejected the API key ({code}): {message}")
            if code == 429:
                if "day" in message.lower():
                    raise TwelveDataError(f"Twelve Data daily credit limit reached: {message}")
                if attempt >= self.max_retries:
                    raise TwelveDataError(f"Twelve Data rate limit: {message}")
                logger.warning("Twelve Data per-minute limit hit; waiting %.0fs", RATE_LIMIT_WAIT_SECONDS)
                self._sleep(RATE_LIMIT_WAIT_SECONDS)
                attempt += 1
                continue
            if code >= 500 and attempt < self.max_retries:
                self._retry_wait(attempt, f"HTTP {code}")
                attempt += 1
                continue
            if code == 400 and "no data is available" in message.lower():
                return {"values": []}
            if code >= 400:
                raise TwelveDataError(f"Twelve Data {path} failed ({code}): {message}")
            return payload

    def _retry_wait(self, attempt: int, reason: str) -> None:
        delay = min(2.0**attempt, 30.0)
        logger.warning("Twelve Data retry %d/%d in %.0fs (%s)", attempt + 1, self.max_retries, delay, reason)
        self._sleep(delay)

    # ---------------------------------------------------------- endpoints
    def time_series(self, instrument: str, granularity: str, start: datetime, end: datetime) -> list[dict]:
        """Raw bars with start <= time <= end (Twelve Data's end_date is inclusive), oldest first."""
        payload = self._get("/time_series", {
            "symbol": to_symbol(instrument),
            "interval": _interval(granularity),
            "start_date": format_time(start),
            "end_date": format_time(end),
            "outputsize": MAX_OUTPUTSIZE,
            "order": "asc",
            "timezone": "UTC",
        })
        return payload.get("values") or []

    def fetch_page(self, instrument: str, granularity: str, from_time: datetime) -> CandlePage:
        step = granularity_delta(granularity)
        now = self._now()
        # end_date is inclusive: (MAX_OUTPUTSIZE - 1) steps => at most MAX_OUTPUTSIZE slots, nothing truncated.
        window_end = min(from_time + step * (MAX_OUTPUTSIZE - 1), now + step)
        raw = self.time_series(instrument, granularity, from_time, window_end)
        candles = [parse_bar(b, step=step, now=now) for b in raw]
        candles = [c for c in candles if from_time <= c["time"] < window_end]
        candles.sort(key=lambda c: c["time"])
        return CandlePage(candles, None if window_end > now else window_end)

    def latest_price(self, instrument: str) -> float:
        """Current price (1 API credit)."""
        payload = self._get("/price", {"symbol": to_symbol(instrument)})
        try:
            return float(payload["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TwelveDataError(f"Unexpected /price response: {payload!r}") from exc

    def earliest_time(self, instrument: str, granularity: str) -> datetime | None:
        payload = self._get("/earliest_timestamp", {
            "symbol": to_symbol(instrument), "interval": _interval(granularity), "timezone": "UTC",
        })
        value = payload.get("datetime")
        return parse_time(value) if value else None

    def api_usage(self) -> dict:
        return self._get("/api_usage", {})


def _interval(granularity: str) -> str:
    try:
        return INTERVALS[granularity.upper()]
    except KeyError as exc:
        raise ValueError(f"Granularity {granularity!r} not supported by Twelve Data client") from exc
