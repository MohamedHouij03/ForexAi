"""Create the configured market-data client (DATA_PROVIDER)."""

from __future__ import annotations

from app.core.config import Settings
from app.data.oanda_client import OandaClient
from app.data.twelvedata_client import TwelveDataClient


def make_source(settings: Settings) -> OandaClient | TwelveDataClient:
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
