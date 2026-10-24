from datetime import datetime

from pydantic import BaseModel


class DatabaseStatus(BaseModel):
    ok: bool
    error: str | None = None


class DataProviderStatus(BaseModel):
    name: str
    configured: bool


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    trading_mode: str
    server_time: datetime
    database: DatabaseStatus
    data_provider: DataProviderStatus


class RiskConfig(BaseModel):
    account_currency: str
    account_balance: float
    max_trade_allocation_percent: float
    max_trade_allocation: float
    max_risk_percent: float
    max_risk_amount: float
    leverage_forex: float
    leverage_metal: float
    max_open_trades: int
    max_daily_loss_percent: float
    stop_loss_atr_multiplier: float
    take_profit_atr_multiplier: float
    target_risk_reward: float


class SignalConfig(BaseModel):
    probability_threshold: float
    prediction_horizon_candles: int


class ConfigResponse(BaseModel):
    trading_mode: str
    instruments: list[str]
    granularity: str
    data_provider: str
    risk: RiskConfig
    signal: SignalConfig


class CandleOut(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    bid_close: float | None
    ask_close: float | None
    spread: float | None
    spread_pips: float | None
    volume: int | None


class CandlesResponse(BaseModel):
    instrument: str
    granularity: str
    count: int
    candles: list[CandleOut]


class DataSummary(BaseModel):
    instrument: str
    granularity: str
    candles: int
    first_time: datetime | None
    last_time: datetime | None
    sources: list[str]
    parquet_file: str | None
    parquet_size_mb: float | None
    last_validation_status: str | None
    last_validation_at: str | None


class InstrumentInfo(BaseModel):
    name: str
    display_name: str
    description: str
    asset_class: str
    pip_size: float
    display_precision: int
    unit_label: str
    candles: int
    last_time: datetime | None
    validation_status: str | None
