from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.api.schemas import (
    ConfigResponse,
    DataProviderStatus,
    DatabaseStatus,
    HealthResponse,
    RiskConfig,
    SignalConfig,
)
from app.core.config import Settings, get_settings
from app.database.session import check_connection

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    try:
        check_connection()
        db = DatabaseStatus(ok=True)
    except Exception as exc:  # report, don't crash the health check
        db = DatabaseStatus(ok=False, error=type(exc).__name__ + ": " + str(exc).splitlines()[0][:200])

    return HealthResponse(
        status="ok" if db.ok else "degraded",
        app=settings.app_name,
        environment=settings.environment,
        trading_mode=settings.trading_mode,
        server_time=datetime.now(timezone.utc),
        database=db,
        data_provider=DataProviderStatus(
            name=settings.data_provider, configured=settings.data_provider_configured
        ),
    )


@router.get("/config", response_model=ConfigResponse)
def config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Non-secret runtime configuration. Credentials are never returned."""
    return ConfigResponse(
        trading_mode=settings.trading_mode,
        instruments=settings.instrument_list,
        granularity=settings.granularity,
        data_provider=settings.data_provider,
        risk=RiskConfig(
            account_currency=settings.account_currency,
            account_balance=settings.account_balance,
            max_trade_allocation_percent=settings.max_trade_allocation_percent,
            max_trade_allocation=settings.max_trade_allocation,
            max_risk_percent=settings.max_risk_percent,
            max_risk_amount=settings.max_risk_amount,
            leverage_forex=settings.leverage_forex,
            leverage_metal=settings.leverage_metal,
            max_open_trades=settings.max_open_trades,
            max_daily_loss_percent=settings.max_daily_loss_percent,
            stop_loss_atr_multiplier=settings.stop_loss_atr_multiplier,
            take_profit_atr_multiplier=settings.take_profit_atr_multiplier,
            target_risk_reward=round(settings.take_profit_atr_multiplier / settings.stop_loss_atr_multiplier, 2),
        ),
        signal=SignalConfig(
            probability_threshold=settings.signal_probability_threshold,
            prediction_horizon_candles=settings.prediction_horizon_candles,
        ),
    )
