import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_match_small_paper_account():
    s = make()
    assert s.trading_mode == "paper"
    assert s.account_balance == 100
    assert s.max_trade_allocation_percent == 50 and s.max_trade_allocation == 50
    assert s.max_risk_percent == 1 and s.max_risk_amount == 1.0
    assert s.max_open_trades == 1 and s.max_daily_loss_percent == 3
    assert s.leverage_for("forex") == 30 and s.leverage_for("metal") == 20
    assert s.stop_loss_atr_multiplier == 1.5
    assert s.take_profit_atr_multiplier == 3.0
    assert s.oanda_environment == "practice"
    assert s.data_provider == "twelvedata"


def test_provider_configured_follows_selected_provider():
    assert make(data_provider="twelvedata", twelvedata_api_key="k").data_provider_configured
    assert not make(data_provider="twelvedata", oanda_api_key="k").data_provider_configured
    assert make(data_provider="oanda", oanda_api_key="k").data_provider_configured


@pytest.mark.parametrize("pct, expected", [(1, 1.0), (1.5, 1.5), (2, 2.0)])
def test_max_risk_amount_is_percent_of_balance(pct, expected):
    assert make(max_risk_percent=pct).max_risk_amount == expected


def test_trade_allocation_is_independent_from_risk_amount():
    s = make(account_balance=100, max_trade_allocation_percent=10, max_risk_percent=1.5)
    assert s.max_trade_allocation == 10
    assert s.max_risk_amount == 1.5
    grown = make(account_balance=250, max_trade_allocation_percent=10, max_risk_percent=1.5)
    assert grown.max_trade_allocation == 25 and grown.max_risk_amount == 3.75  # both scale with the balance


def test_live_trading_mode_is_rejected():
    with pytest.raises(ValidationError):
        make(trading_mode="live")


@pytest.mark.parametrize("pct", [0, -1, 5.5])
def test_risk_percent_bounds(pct):
    with pytest.raises(ValidationError):
        make(max_risk_percent=pct)


@pytest.mark.parametrize("pct", [0, -5, 101])
def test_allocation_percent_bounds(pct):
    with pytest.raises(ValidationError):
        make(max_trade_allocation_percent=pct)


def test_blank_api_key_means_not_configured():
    assert make(oanda_api_key="").oanda_configured is False
    assert make(oanda_api_key="   ").oanda_configured is False
    assert make(oanda_api_key="abc").oanda_configured is True


def test_practice_urls():
    s = make()
    assert s.oanda_rest_url == "https://api-fxpractice.oanda.com"
    assert s.oanda_stream_url == "https://stream-fxpractice.oanda.com"


def test_api_key_not_leaked_in_repr():
    assert "supersecret" not in repr(make(oanda_api_key="supersecret"))


def test_instrument_watchlist_normalised_and_validated():
    s = make(instruments="eur/usd, XAUUSD ,AUD_USD,EUR_USD")
    assert s.instrument_list == ["EUR_USD", "XAU_USD", "AUD_USD"]
    assert s.default_instrument == "EUR_USD"
    with pytest.raises(ValidationError, match="crypto"):
        make(instruments="EUR_USD,BTC_USD")


def test_default_database_is_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL")  # set by conftest for test isolation
    url = make().database_url
    assert url.startswith("sqlite:///") and url.endswith("forex_ai.db")


def test_blank_database_url_falls_back_to_sqlite():
    assert make(database_url="").database_url.endswith("forex_ai.db")
