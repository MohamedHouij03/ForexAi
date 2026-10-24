from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UTCDateTime, utcnow

# SQLite only auto-increments INTEGER primary keys.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

PRICE_COLUMNS = (
    "open", "high", "low", "close",
    "bid_open", "bid_high", "bid_low", "bid_close",
    "ask_open", "ask_high", "ask_low", "ask_close",
)
CANDLE_DATA_COLUMNS = ("time", *PRICE_COLUMNS, "spread", "volume")


class Candle(Base):
    """One completed OHLC candle.

    ``open/high/low/close`` are *mid* prices. Bid/ask OHLC, ``spread``
    (``ask_close - bid_close``) and ``volume`` (tick count - spot FX has no
    centralised traded volume) are stored when the provider supplies them
    (OANDA does; Twelve Data does not, so they are NULL). ``source`` records
    the provider so datasets from different feeds are never mixed silently.
    """

    __tablename__ = "candles"
    __table_args__ = (UniqueConstraint("instrument", "granularity", "time", name="uq_candle_instrument_granularity_time"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(16), index=True)
    granularity: Mapped[str] = mapped_column(String(8), index=True)
    time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)

    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)

    bid_open: Mapped[float | None] = mapped_column(Float)
    bid_high: Mapped[float | None] = mapped_column(Float)
    bid_low: Mapped[float | None] = mapped_column(Float)
    bid_close: Mapped[float | None] = mapped_column(Float)

    ask_open: Mapped[float | None] = mapped_column(Float)
    ask_high: Mapped[float | None] = mapped_column(Float)
    ask_low: Mapped[float | None] = mapped_column(Float)
    ask_close: Mapped[float | None] = mapped_column(Float)

    spread: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    complete: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(16))

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Signal(Base):
    """Every decision the live engine makes at a candle close (BUY, SELL or WAIT), with the reason."""

    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("instrument", "granularity", "candle_time", name="uq_signal_candle"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    instrument: Mapped[str] = mapped_column(String(16), index=True)
    granularity: Mapped[str] = mapped_column(String(8))
    candle_time: Mapped[datetime] = mapped_column(UTCDateTime, index=True)  # stamp of the signal candle
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    model_version: Mapped[str | None] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))                 # practice | proven
    p_buy: Mapped[float | None] = mapped_column(Float)
    p_wait: Mapped[float | None] = mapped_column(Float)
    p_sell: Mapped[float | None] = mapped_column(Float)
    model_decision: Mapped[str] = mapped_column(String(8))        # what the model said
    decision: Mapped[str] = mapped_column(String(8), index=True)  # after risk rules: BUY | SELL | WAIT
    reason: Mapped[str | None] = mapped_column(String(300))
    entry: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    atr: Mapped[float | None] = mapped_column(Float)
    units: Mapped[int | None] = mapped_column(Integer)
    risk_amount: Mapped[float | None] = mapped_column(Float)
    potential_profit: Mapped[float | None] = mapped_column(Float)
    risk_reward: Mapped[float | None] = mapped_column(Float)
    margin_required: Mapped[float | None] = mapped_column(Float)
    balance: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="info", index=True)  # actionable|taken|skipped|expired|info
    # What happened afterwards if the signal had been followed exactly (the AI's live track record)
    outcome_r: Mapped[float | None] = mapped_column(Float)
    outcome_reason: Mapped[str | None] = mapped_column(String(16))
    outcome_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class CoachTrade(Base):
    """A trade you placed on your demo account after a signal, followed live by the coach."""

    __tablename__ = "coach_trades"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    signal_id: Mapped[int | None] = mapped_column(BigIntPK, index=True)
    instrument: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(4))
    units: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    risk_amount: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime)
    close_by: Mapped[datetime] = mapped_column(UTCDateTime)  # maximum holding time
    status: Mapped[str] = mapped_column(String(8), default="open", index=True)  # open | closed
    advice: Mapped[str | None] = mapped_column(String(8))           # None | close
    advice_reason: Mapped[str | None] = mapped_column(String(200))
    advice_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_price: Mapped[float | None] = mapped_column(Float)
    last_price_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    exit_price: Mapped[float | None] = mapped_column(Float)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    close_reason: Mapped[str | None] = mapped_column(String(200))
    pips: Mapped[float | None] = mapped_column(Float)
    pnl: Mapped[float | None] = mapped_column(Float)
    r_multiple: Mapped[float | None] = mapped_column(Float)
    balance_after: Mapped[float | None] = mapped_column(Float)
