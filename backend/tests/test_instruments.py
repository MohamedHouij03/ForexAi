from datetime import timedelta

import pytest

from app.core.instruments import (
    UnsupportedInstrumentError,
    get_instrument,
    granularity_delta,
    granularity_label,
    normalize_instrument_name,
)

EURUSD = get_instrument("EUR_USD")


@pytest.mark.parametrize("raw", ["EUR_USD", "eur_usd", "EUR/USD", "EURUSD", "eur-usd", " EUR_USD "])
def test_name_normalisation(raw):
    assert normalize_instrument_name(raw) == "EUR_USD"


@pytest.mark.parametrize(
    "name, asset_class, pip, precision",
    [
        ("EUR_USD", "forex", 0.0001, 5),
        ("AUD_USD", "forex", 0.0001, 5),
        ("GBP_JPY", "forex", 0.01, 3),
        ("USD_JPY", "forex", 0.01, 3),
        ("EUR_HUF", "forex", 0.01, 3),
        ("USD_TRY", "forex", 0.0001, 5),
        ("EUR_GBP", "forex", 0.0001, 5),
        ("XAU_USD", "metal", 0.01, 3),
        ("XAG_USD", "metal", 0.0001, 5),
        ("XPT_USD", "metal", 0.01, 3),
        ("XAU_EUR", "metal", 0.01, 3),
    ],
)
def test_pip_conventions(name, asset_class, pip, precision):
    inst = get_instrument(name)
    assert inst.asset_class == asset_class
    assert inst.pip_size == pytest.approx(pip)
    assert inst.display_precision == precision


@pytest.mark.parametrize("name", ["BTC_USD", "ETH/USD", "BTCUSDT", "DOGEUSD", "USD_BTC"])
def test_crypto_rejected(name):
    with pytest.raises(UnsupportedInstrumentError, match="crypto"):
        get_instrument(name)


@pytest.mark.parametrize("name", ["AAPL", "AAPL_USD", "SPX500_USD", "US30", "EUR_XAU", "USD_USD", "ABC_USD", "EUR"])
def test_stocks_indices_and_nonsense_rejected(name):
    with pytest.raises(UnsupportedInstrumentError):
        get_instrument(name)


def test_descriptions():
    assert get_instrument("XAU_USD").description == "Gold / US Dollar"
    assert get_instrument("AUD_USD").description == "Australian Dollar / US Dollar"
    assert get_instrument("XAU_USD").unit_label == "oz"


@pytest.mark.parametrize("diff, pips", [(0.0001, 1), (0.0012, 12), (-0.00155, -15.5), (0.00001, 0.1)])
def test_price_to_pips(diff, pips):
    assert EURUSD.price_to_pips(diff) == pytest.approx(pips)


def test_pips_to_price_roundtrip():
    assert EURUSD.pips_to_price(12) == pytest.approx(0.0012)
    assert get_instrument("USD_JPY").price_to_pips(0.25) == pytest.approx(25)
    assert get_instrument("XAU_USD").price_to_pips(1.50) == pytest.approx(150)  # $1.50 gold move = 150 pips


@pytest.mark.parametrize("units, pip_value", [(1, 0.0001), (1_000, 0.10), (10_000, 1.0), (100_000, 10.0)])
def test_eurusd_pip_value_usd_account(units, pip_value):
    assert units * EURUSD.pip_value_per_unit() == pytest.approx(pip_value)


def test_gold_pip_value():
    # 1 oz of gold: a $0.01 move (1 pip) is worth $0.01
    assert get_instrument("XAU_USD").pip_value_per_unit() == pytest.approx(0.01)


def test_usd_base_pip_value_uses_price():
    # USD/JPY at 150: 1 pip (0.01 JPY) on 100,000 units = 1,000 JPY = $6.67
    assert 100_000 * get_instrument("USD_JPY").pip_value_per_unit(price=150.0) == pytest.approx(6.6667, rel=1e-4)


def test_cross_pip_value_needs_conversion_rate():
    eurgbp = get_instrument("EUR_GBP")
    with pytest.raises(ValueError, match="GBP_USD"):
        eurgbp.pip_value_per_unit(price=0.85)
    # 100k EUR/GBP: 1 pip = 10 GBP = $12.70 at GBP/USD 1.27
    assert 100_000 * eurgbp.pip_value_per_unit(price=0.85, rates={"GBP_USD": 1.27}) == pytest.approx(12.70)
    # an inverse quote also works: USD/CHF 0.90 -> 1 CHF = $1.111
    assert get_instrument("EUR_CHF").quote_to_account_rate(0.95, rates={"USD_CHF": 0.90}) == pytest.approx(
        1.1111, rel=1e-4
    )


def test_granularity_helpers():
    assert granularity_delta("M15") == timedelta(minutes=15)
    assert granularity_label("M15") == "15m"
    assert granularity_label("H1") == "1h"
    with pytest.raises(ValueError):
        granularity_delta("W")
