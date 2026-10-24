"""Phase 9-10 - the live engine that runs inside the API server.

Candle loop (every LIVE_POLL_SECONDS):
  for each instrument in INSTRUMENTS, when a new candle should have closed
  (and the market is open), fetch it from the provider (1 request; a few retries
  if the provider is late), then for the NEWEST candle only:
    features -> model -> risk rules -> Signal row -> push to dashboards
    open coach trades: stop/target/time/AI-exit advice -> push
    score earlier signals whose outcome is now known
Price stream (Twelve Data WebSocket; free plan: EUR/USD and XAU/USD):
  ticks update open trades' P/L and trigger instant close advice.

Heavy work (HTTP, pandas, model) runs in worker threads so the API stays responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select

from app.core.config import Settings
from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.core.market_hours import weekly_open_mask
from app.data.downloader import HistoricalDownloader
from app.data.providers import make_source
from app.data.sources import DataSourceError
from app.database.models import CoachTrade, Signal
from app.notify.telegram import TelegramNotifier
from app.database.repository import CandleRepository
from app.database.session import get_session_factory
from app.signals.engine import decide_signal, live_features, load_model_bundle, predict
from app.trading.coach import Coach
from app.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)
WS_URL = "wss://ws.twelvedata.com/v1/quotes/price"


def signal_to_dict(s: Signal) -> dict:
    return {c.name: getattr(s, c.name) for c in Signal.__table__.columns}


def trade_to_dict(t: CoachTrade) -> dict:
    return {c.name: getattr(t, c.name) for c in CoachTrade.__table__.columns}


@dataclass
class LiveStatus:
    running: bool = False
    message: str = "starting"
    last_poll: datetime | None = None
    last_candle: dict = field(default_factory=dict)       # instrument -> candle time processed
    prices: dict = field(default_factory=dict)            # instrument -> {price, time}
    stream_symbols: list = field(default_factory=list)    # instruments with real-time ticks
    stream_connected: bool = False
    requests_today: int = 0
    requests_day: str = ""
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"running": self.running, "message": self.message, "last_poll": self.last_poll,
                "last_candle": self.last_candle, "prices": self.prices, "stream_symbols": self.stream_symbols,
                "stream_connected": self.stream_connected, "requests_today": self.requests_today,
                "errors": self.errors[-5:]}


class LiveService:
    def __init__(self, settings: Settings, manager: ConnectionManager, source_factory=None,
                 now=lambda: datetime.now(timezone.utc)):
        self.settings = settings
        self.manager = manager
        self.now = now
        self.status = LiveStatus()
        self._source_factory = source_factory
        self._source = None
        self._attempts: dict[tuple[str, datetime], int] = {}
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.notifier = TelegramNotifier(settings)

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        s = self.settings
        if not s.live_engine_enabled:
            self.status.message = "Live engine disabled (LIVE_ENGINE_ENABLED=false)."
            return
        if not s.data_provider_configured:
            self.status.message = "No data provider API key - add TWELVEDATA_API_KEY to .env."
            return
        self._loop = asyncio.get_running_loop()
        self.status.running = True
        self.status.message = "running"
        self._tasks.append(asyncio.create_task(self._candle_loop(), name="candle-loop"))
        if s.live_trade_price_seconds > 0:
            self._tasks.append(asyncio.create_task(self._trade_price_loop(), name="trade-prices"))
        if s.live_price_stream and s.data_provider == "twelvedata":
            self._tasks.append(asyncio.create_task(self._price_stream(), name="price-stream"))

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.status.running = False
        if self._source is not None:
            self._source.close()

    # ------------------------------------------------------------ candles
    def _get_source(self):
        if self._source is None:
            if self._source_factory:
                self._source = self._source_factory()
            else:
                self._source = make_source(self.settings)
        return self._source

    async def _candle_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # never let the loop die
                logger.exception("Live tick failed")
                self._error(f"tick: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.live_poll_seconds)
            except asyncio.TimeoutError:
                pass

    def expected_last_candle(self, now: datetime) -> datetime:
        step = timedelta(seconds=GRANULARITY_SECONDS[self.settings.granularity])
        settled = pd.Timestamp(now - timedelta(seconds=self.settings.live_settle_seconds))
        return (settled.floor(step) - step).to_pydatetime()

    async def tick(self) -> list[dict]:
        """One pass over the watchlist. Returns the signals produced (for tests)."""
        now = self.now()
        self.status.last_poll = now
        expected = self.expected_last_candle(now)
        produced = []
        for instrument in self.settings.instrument_list:
            inst = get_instrument(instrument)
            if not weekly_open_mask([expected], inst.asset_class)[0]:
                continue  # weekend: nothing to fetch
            new = await asyncio.to_thread(self._fetch_if_due, instrument, expected)
            if new is None:
                continue
            events = await asyncio.to_thread(self._process_candle, instrument, new, now)
            for event, data in events:
                await self.manager.broadcast(event, data)
                if event == "signal":
                    produced.append(data)
                    await asyncio.to_thread(self.notifier.notify_signal, data)  # phone (Telegram), if set up
        await asyncio.to_thread(self._expire)
        return produced

    def _fetch_if_due(self, instrument: str, expected: datetime) -> datetime | None:
        """Fetch new candles if `expected` is not stored yet. Returns the newest candle time if it is new."""
        gran = self.settings.granularity
        with get_session_factory()() as session:
            repo = CandleRepository(session)
            latest = repo.latest_time(instrument, gran)
            if latest is not None and latest >= expected:
                return expected if self.status.last_candle.get(instrument) != expected.isoformat() else None
            key = (instrument, expected)
            if self._attempts.get(key, 0) >= self.settings.live_max_fetch_attempts:
                return None  # provider has no candle for this slot (e.g. a holiday); don't burn credits
            self._attempts[key] = self._attempts.get(key, 0) + 1
            start = latest or (expected - timedelta(days=30))
            try:
                HistoricalDownloader(self._get_source(), repo, instrument, gran).download(start)
                self._count_request()
            except DataSourceError as exc:
                self._error(f"{instrument}: {exc}")
                return None
            latest = repo.latest_time(instrument, gran)
        if latest is not None and latest >= expected and self.status.last_candle.get(instrument) != expected.isoformat():
            return latest
        return None

    def _process_candle(self, instrument: str, candle_time: datetime, now: datetime) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        self.status.last_candle[instrument] = pd.Timestamp(candle_time).isoformat()
        bundle = load_model_bundle(self.settings)
        gran = bundle.granularity if bundle else self.settings.granularity
        if bundle and bundle.granularity != self.settings.granularity:
            self._error(f"Model is {bundle.granularity} but live candles are {self.settings.granularity}.")
            return events
        with get_session_factory()() as session:
            feats = live_features(session, self.settings, instrument, gran)
            if feats.empty:
                return events
            row = feats.iloc[-1]
            if pd.Timestamp(row["time"]) != pd.Timestamp(candle_time):
                return events  # newest candle was removed by cleaning (e.g. weekend quote)
            proba = predict(bundle, row) if bundle and bool(row["ready"]) else None
            coach = Coach(session, self.settings)
            fields = decide_signal(instrument=instrument, row=row, proba=proba, bundle=bundle,
                                   settings=self.settings, account=coach.account_state(now))
            sig = session.query(Signal).filter_by(instrument=instrument, granularity=gran,
                                                  candle_time=fields["candle_time"]).one_or_none()
            if sig is None:
                sig = Signal(**fields)
                session.add(sig)
                session.commit()
                events.append(("signal", signal_to_dict(sig)))
            for trade in coach.on_candle(instrument, row, fields["model_decision"], now):
                events.append(("trade", trade_to_dict(trade)))
            horizon = self.settings.max_holding_candles  # the holding rule, not the training horizon
            coach.evaluate_outcomes(instrument, feats[["time", "open", "high", "low", "close"]], horizon)
            price = {"instrument": instrument, "price": float(row["close"]), "time": row["time"], "source": "candle"}
            if instrument not in self.status.stream_symbols:
                self.status.prices[instrument] = price
                events.append(("price", price))
        events.append(("status", self.status.to_dict()))
        return events

    def _expire(self) -> None:
        with get_session_factory()() as session:
            Coach(session, self.settings).expire_signals(self.now())

    def _error(self, message: str) -> None:
        self.status.errors.append({"time": self.now().isoformat(), "message": message})
        self.status.errors = self.status.errors[-20:]

    # ------------------------------------------------------------ real-time prices
    async def _price_stream(self) -> None:
        import websockets

        from app.data.twelvedata_client import to_symbol

        symbols = {to_symbol(i): i for i in self.settings.instrument_list}
        key = self.settings.twelvedata_api_key.get_secret_value()
        backoff = 5
        while not self._stop.is_set():
            try:
                async with websockets.connect(f"{WS_URL}?apikey={key}", open_timeout=20) as ws:
                    await ws.send(json.dumps({"action": "subscribe", "params": {"symbols": ",".join(symbols)}}))
                    self.status.stream_connected = True
                    backoff = 5
                    last_heartbeat = time.monotonic()
                    last_sent: dict[str, float] = {}
                    while not self._stop.is_set():
                        if time.monotonic() - last_heartbeat > 10:
                            await ws.send(json.dumps({"action": "heartbeat"}))
                            last_heartbeat = time.monotonic()
                        try:
                            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                        except asyncio.TimeoutError:
                            continue
                        if msg.get("event") == "subscribe-status":
                            ok = [symbols[s["symbol"]] for s in msg.get("success") or [] if s["symbol"] in symbols]
                            self.status.stream_symbols = ok
                            await self.manager.broadcast("status", self.status.to_dict())
                        elif msg.get("event") == "price" and msg.get("symbol") in symbols:
                            instrument = symbols[msg["symbol"]]
                            ts = datetime.fromtimestamp(msg.get("timestamp", time.time()), timezone.utc)
                            price = {"instrument": instrument, "price": float(msg["price"]), "time": ts,
                                     "source": "stream"}
                            self.status.prices[instrument] = price
                            if time.monotonic() - last_sent.get(instrument, 0) >= 1.0:  # max 1 push/s per pair
                                last_sent[instrument] = time.monotonic()
                                await self.manager.broadcast("price", price)
                                for event, data in await asyncio.to_thread(self._on_tick, instrument,
                                                                           price["price"], ts):
                                    await self.manager.broadcast(event, data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error(f"price stream: {exc}")
            self.status.stream_connected = False
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 120)

    # ------------------------------------------------------------ open-trade price checks
    def _count_request(self) -> None:
        day = self.now().strftime("%Y-%m-%d")
        if self.status.requests_day != day:
            self.status.requests_day, self.status.requests_today = day, 0
        self.status.requests_today += 1

    def _budget_left(self) -> int:
        day = self.now().strftime("%Y-%m-%d")
        used = self.status.requests_today if self.status.requests_day == day else 0
        return self.settings.daily_request_budget - used

    async def _trade_price_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_trade_prices()
            except Exception as exc:
                logger.exception("Trade price check failed")
                self._error(f"trade prices: {exc}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.live_trade_price_seconds)
            except asyncio.TimeoutError:
                pass

    async def poll_trade_prices(self) -> list[str]:
        """Price check for open trades and waiting BUY/SELL signals on pairs without real-time ticks.
        Returns the instruments checked."""
        with get_session_factory()() as session:
            instruments = {t.instrument for t in Coach(session, self.settings).open_trades()}
            instruments |= set(session.execute(select(Signal.instrument).where(
                Signal.status == "actionable", Signal.decision != "WAIT")).scalars())
        instruments = sorted(instruments)
        checked = []
        for instrument in instruments:
            if instrument in self.status.stream_symbols and self.status.stream_connected:
                continue  # already updated every second
            if not weekly_open_mask([self.now()], get_instrument(instrument).asset_class)[0]:
                continue
            if self._budget_left() <= 50:  # keep credits for the 15-minute candle checks
                self._error("Daily API budget nearly used - open-trade price checks paused until tomorrow.")
                break
            source = self._get_source()
            if not hasattr(source, "latest_price"):
                continue
            try:
                price = await asyncio.to_thread(source.latest_price, instrument)
            except DataSourceError as exc:
                self._error(f"{instrument} price: {exc}")
                continue
            self._count_request()
            ts = self.now()
            data = {"instrument": instrument, "price": price, "time": ts, "source": "poll"}
            self.status.prices[instrument] = data
            await self.manager.broadcast("price", data)
            for event, payload in await asyncio.to_thread(self._on_tick, instrument, price, ts):
                await self.manager.broadcast(event, payload)
            checked.append(instrument)
        return checked

    def _on_tick(self, instrument: str, price: float, ts: datetime) -> list[tuple[str, dict]]:
        """New price: drop signals that are now too late, update open trades. Returns events to broadcast."""
        with get_session_factory()() as session:
            coach = Coach(session, self.settings)
            events = [("signal", signal_to_dict(s)) for s in coach.expire_late(instrument, price, ts)]
            if any(t.instrument == instrument for t in coach.open_trades()):
                events += [("trade", trade_to_dict(t)) for t in coach.on_price(instrument, price, ts)]
            return events


_service: LiveService | None = None


def get_live_service() -> LiveService | None:
    return _service


def set_live_service(service: LiveService | None) -> None:
    global _service
    _service = service
