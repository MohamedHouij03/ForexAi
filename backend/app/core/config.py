"""Application configuration.

All settings are read from environment variables (or the repository-level
``.env`` file). Every risk parameter is configurable; the defaults reflect a
small $100 paper-trading account.

IMPORTANT distinction (both are % of the CURRENT balance, so they scale with it):
  * MAX_RISK_PERCENT             - the maximum LOSS if the Stop Loss is hit
                                   (1% of $100 = $1). This normally sets the size.
  * MAX_TRADE_ALLOCATION_PERCENT - the MARGIN one trade may lock up
                                   (50% of $100 = $50), a safety cap. With
                                   leverage L, position value <= margin x L.
Plus account-level limits: MAX_OPEN_TRADES and MAX_DAILY_LOSS_PERCENT.
They are two independent limits; position size is the largest size that
respects both.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'data' / 'forex_ai.db').as_posix()}"

OANDA_REST_URLS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
OANDA_STREAM_URLS = {
    "practice": "https://stream-fxpractice.oanda.com",
    "live": "https://stream-fxtrade.oanda.com",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Forex AI Trading Assistant"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # ------------------------------------------------------------ database
    # Default: a local SQLite file (no server to install). PostgreSQL also works, e.g.
    # postgresql+psycopg://forex:forex@localhost:5432/forex_ai
    database_url: str = DEFAULT_DATABASE_URL

    # ------------------------------------------------------- data provider
    # twelvedata: free API key by email, mid prices only (no bid/ask/volume), 15m history from 2020.
    # oanda:      requires an OANDA practice account, provides bid/ask/volume.
    data_provider: Literal["twelvedata", "oanda"] = "twelvedata"

    # ---------------------------------------------------------- Twelve Data
    twelvedata_api_key: SecretStr | None = None
    twelvedata_requests_per_minute: int = Field(8, ge=1)  # free Basic plan limit

    # --------------------------------------------------------------- OANDA
    oanda_api_key: SecretStr | None = None
    oanda_account_id: str | None = None
    oanda_environment: Literal["practice", "live"] = "practice"

    # ------------------------------------------------------------- network
    request_timeout_seconds: float = Field(30.0, gt=0)
    max_retries: int = Field(5, ge=0)

    # ---------------------------------------------------------------- data
    # Watchlist: any forex pairs and spot metals, comma-separated (first = default on screen).
    instruments: str = "EUR_USD,GBP_USD,USD_JPY,AUD_USD,XAU_USD"
    granularity: str = "M15"
    history_years: int = Field(10, ge=1, le=25)
    data_dir: Path = BACKEND_DIR / "data"
    models_dir: Path = BACKEND_DIR / "models"

    # Dataset validation thresholds
    validation_min_coverage: float = Field(0.98, gt=0, le=1)
    # Spread flagged as unusually wide above this many basis points of price (0.10%), any instrument.
    validation_max_normal_spread_bps: float = Field(10.0, gt=0)
    # Candle-to-candle move flagged as extreme; empty = per asset class (forex 1.5%, metals 3%).
    validation_max_abs_return: float | None = Field(None, gt=0)

    # ---------------------------------------------------------------- risk
    # V1 is paper trading only. Any other value is rejected at startup.
    trading_mode: Literal["paper"] = "paper"
    account_currency: Literal["USD"] = "USD"
    account_balance: float = Field(100.0, gt=0)
    # Beginner-safe defaults: the 1% loss limit decides position size; the margin cap is a safety net.
    max_trade_allocation_percent: float = Field(50.0, gt=0, le=100)
    max_risk_percent: float = Field(1.0, gt=0, le=5)
    # Account-level protection (enforced by the backtester and paper trader, Phases 8 and 11).
    max_open_trades: int = Field(1, ge=1, le=20)
    max_daily_loss_percent: float = Field(3.0, gt=0, le=50)
    # Broker leverage (position value / margin). Typical retail limits: 30:1 forex majors, 20:1 gold.
    leverage_forex: float = Field(30.0, ge=1, le=1000)
    leverage_metal: float = Field(20.0, ge=1, le=1000)
    stop_loss_atr_multiplier: float = Field(1.5, gt=0)
    take_profit_atr_multiplier: float = Field(3.0, gt=0)

    # -------------------------------------------------------------- signal
    signal_probability_threshold: float = Field(0.65, gt=0.34, lt=1)
    prediction_horizon_candles: int = Field(4, ge=1)
    # Maximum time a trade is held before the coach says "close" (candles). Labels use the same limit.
    max_holding_candles: int = Field(16, ge=1, le=500)
    # ---------------------------------------------------------------- live coach
    # practice: show the model's signals even if it has not proven an edge (clearly labelled, demo only)
    # proven:   only signals from a model that passed every out-of-sample check (otherwise WAIT)
    coach_mode: Literal["practice", "proven"] = "practice"
    # Practice mode only: minimum P(BUY)/P(SELL) for a signal (lower = more, weaker signals).
    # Empty = use the threshold chosen during training.
    practice_signal_threshold: float | None = Field(None, gt=0.05, lt=1)
    live_engine_enabled: bool = True
    live_poll_seconds: int = Field(20, ge=5, le=300)
    live_settle_seconds: int = Field(20, ge=0, le=300)   # wait after a candle closes before fetching it
    live_max_fetch_attempts: int = Field(4, ge=1, le=20)  # per candle per instrument (each costs 1 credit)
    live_price_stream: bool = True                        # Twelve Data WebSocket (free plan: EUR/USD, XAU/USD)
    signal_expiry_minutes: int = Field(15, ge=1, le=240)  # how long a BUY/SELL can still be taken
    # Pairs WITHOUT the free live stream: check the price this often while you have a trade open on them
    # (1 API credit per check; ~20 credits per 30-minute trade at 90 s). 0 = only at candle closes.
    live_trade_price_seconds: int = Field(90, ge=0, le=900)
    # Never spend more than this many API credits per UTC day (free plan: 800); price checks stop first.
    daily_request_budget: int = Field(760, ge=50)
    # Phone notifications via a Telegram bot (blank = off). Setup: python -m app.notify.telegram
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    # Modelled spread per instrument in pips, e.g. "EUR_USD:0.8,XAU_USD:25" (default: instrument table)
    spread_pips_overrides: str = ""

    @field_validator("oanda_api_key", "twelvedata_api_key", "telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def _blank_key_is_none(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("oanda_account_id", mode="before")
    @classmethod
    def _blank_account_is_none(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value.strip()

    @field_validator("database_url", mode="before")
    @classmethod
    def _blank_database_url_uses_sqlite(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return DEFAULT_DATABASE_URL
        return value

    @field_validator("instruments")
    @classmethod
    def _check_instruments(cls, value: str) -> str:
        from app.core.instruments import get_instrument

        names = [get_instrument(n).name for n in value.split(",") if n.strip()]
        if not names:
            raise ValueError("INSTRUMENTS must list at least one instrument, e.g. EUR_USD")
        return ",".join(dict.fromkeys(names))  # normalised, de-duplicated, order kept

    @field_validator("validation_max_abs_return", "practice_signal_threshold", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    # ------------------------------------------------------------ derived
    @property
    def instrument_list(self) -> list[str]:
        return self.instruments.split(",")

    @property
    def default_instrument(self) -> str:
        return self.instrument_list[0]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def oanda_configured(self) -> bool:
        return self.oanda_api_key is not None and bool(self.oanda_api_key.get_secret_value())

    @property
    def twelvedata_configured(self) -> bool:
        return self.twelvedata_api_key is not None and bool(self.twelvedata_api_key.get_secret_value())

    @property
    def data_provider_configured(self) -> bool:
        return self.twelvedata_configured if self.data_provider == "twelvedata" else self.oanda_configured

    @property
    def oanda_rest_url(self) -> str:
        return OANDA_REST_URLS[self.oanda_environment]

    @property
    def oanda_stream_url(self) -> str:
        return OANDA_STREAM_URLS[self.oanda_environment]

    @property
    def max_risk_amount(self) -> float:
        """Maximum loss at the Stop Loss for the configured starting balance."""
        return round(self.account_balance * self.max_risk_percent / 100.0, 2)

    @property
    def max_trade_allocation(self) -> float:
        """Maximum margin per trade for the configured starting balance."""
        return round(self.account_balance * self.max_trade_allocation_percent / 100.0, 2)

    def spread_pips(self, instrument: str) -> float:
        from app.core.instruments import get_instrument

        inst = get_instrument(instrument)
        for item in self.spread_pips_overrides.split(","):
            if ":" in item:
                name, value = item.split(":", 1)
                if get_instrument(name).name == inst.name:
                    return float(value)
        return inst.typical_spread_pips

    def leverage_for(self, asset_class: str) -> float:
        return self.leverage_metal if asset_class == "metal" else self.leverage_forex

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
