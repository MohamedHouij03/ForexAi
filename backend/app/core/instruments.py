"""Instrument metadata and pip arithmetic for forex pairs and spot precious metals.

Supported: any pair of the fiat currencies below (EUR_USD, AUD_JPY, USD_TRY, ...)
and spot metals quoted in fiat (XAU_USD gold, XAG_USD silver, XPT_USD, XPD_USD).
Crypto and stocks are deliberately rejected.

Pip conventions (as used by OANDA and most FX brokers):
  * most pairs:                  1 pip = 0.0001  (5-decimal quotes)
  * JPY, HUF, THB quotes:        1 pip = 0.01    (3-decimal quotes)
  * gold, platinum, palladium:   1 pip = 0.01    (3-decimal quotes), 1 unit = 1 troy ounce
  * silver:                      1 pip = 0.0001  (5-decimal quotes), 1 unit = 1 troy ounce

Pip value of ONE unit, in the account currency:
    pip_size x (quote currency -> account currency rate)
  * XXX/USD (EUR/USD, XAU/USD) in a USD account: rate = 1          -> EUR/USD $0.0001, XAU/USD $0.01
  * USD/XXX (USD/JPY) in a USD account:          rate = 1 / price  -> USD/JPY at 150: 0.01/150 = $0.0000667
  * crosses (EUR/GBP) in a USD account:          rate = GBP/USD price (needs a second quote)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Literal

AssetClass = Literal["forex", "metal"]

FIAT_CURRENCIES: dict[str, str] = {
    "USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound", "JPY": "Japanese Yen",
    "CHF": "Swiss Franc", "AUD": "Australian Dollar", "NZD": "New Zealand Dollar", "CAD": "Canadian Dollar",
    "SEK": "Swedish Krona", "NOK": "Norwegian Krone", "DKK": "Danish Krone", "PLN": "Polish Zloty",
    "CZK": "Czech Koruna", "HUF": "Hungarian Forint", "TRY": "Turkish Lira", "ZAR": "South African Rand",
    "MXN": "Mexican Peso", "SGD": "Singapore Dollar", "HKD": "Hong Kong Dollar", "CNH": "Chinese Yuan (offshore)",
    "THB": "Thai Baht", "ILS": "Israeli Shekel", "RON": "Romanian Leu", "INR": "Indian Rupee",
    "BRL": "Brazilian Real", "KRW": "South Korean Won", "TWD": "Taiwan Dollar", "SAR": "Saudi Riyal",
    "AED": "UAE Dirham", "RUB": "Russian Ruble", "CLP": "Chilean Peso", "COP": "Colombian Peso",
    "IDR": "Indonesian Rupiah", "PHP": "Philippine Peso", "MYR": "Malaysian Ringgit", "KWD": "Kuwaiti Dinar",
}
METALS: dict[str, str] = {"XAU": "Gold", "XAG": "Silver", "XPT": "Platinum", "XPD": "Palladium"}
METAL_TRADING_NAMES = {"XAU": "GOLD", "XAG": "SILVER"}  # XAU/USD is shown as GOLD, like in MT4/MT5
CRYPTO_CODES = {"BTC", "ETH", "XRP", "LTC", "SOL", "DOGE", "ADA", "BNB", "USDT", "USDC", "DOT", "BCH", "XBT"}

# Quotes whose pip is the 2nd decimal (large-number currencies).
TWO_DECIMAL_PIP_QUOTES = {"JPY", "HUF", "THB", "INR", "KRW", "IDR", "CLP", "COP", "PHP", "TWD", "RUB"}
METAL_PIP_LOCATION = {"XAU": -2, "XAG": -4, "XPT": -2, "XPD": -2}

# Typical all-in spread on a retail standard account, in pips - deliberately on the cautious side,
# because Twelve Data provides no bid/ask. Used for labels and backtests. Override with SPREAD_PIPS_OVERRIDES.
TYPICAL_SPREAD_PIPS: dict[str, float] = {
    "EUR_USD": 1.0, "GBP_USD": 1.4, "USD_JPY": 1.2, "AUD_USD": 1.2, "USD_CAD": 1.6, "USD_CHF": 1.5,
    "NZD_USD": 1.6, "EUR_GBP": 1.4, "EUR_JPY": 1.8, "GBP_JPY": 2.5, "AUD_JPY": 2.0, "EUR_CHF": 2.0,
    "XAU_USD": 30.0,   # $0.30 per oz
    "XAG_USD": 300.0,  # $0.03 per oz
}
DEFAULT_SPREAD_PIPS = {"forex": 3.0, "metal": 300.0}

_NAME_RE = re.compile(r"^([A-Z]{3,4})[_/\-]?([A-Z]{3,4})$")  # 4 letters only so USDT/DOGE get a clear crypto error


class UnsupportedInstrumentError(ValueError):
    pass


@dataclass(frozen=True)
class Instrument:
    name: str  # OANDA-style: "EUR_USD", "XAU_USD"
    base: str
    quote: str
    asset_class: AssetClass
    pip_location: int

    @property
    def pip_size(self) -> float:
        return 10.0**self.pip_location

    @property
    def display_precision(self) -> int:
        """Quotes carry one digit beyond the pip (the "pipette")."""
        return -self.pip_location + 1

    @property
    def display_name(self) -> str:
        if self.asset_class == "metal" and self.quote == "USD":
            return METAL_TRADING_NAMES.get(self.base, f"{self.base}/{self.quote}")  # what brokers call it
        return f"{self.base}/{self.quote}"

    @property
    def description(self) -> str:
        base = METALS.get(self.base) or FIAT_CURRENCIES[self.base]
        return f"{base} / {FIAT_CURRENCIES[self.quote]}"

    @property
    def unit_label(self) -> str:
        return "oz" if self.asset_class == "metal" else "units"

    @property
    def typical_spread_pips(self) -> float:
        return TYPICAL_SPREAD_PIPS.get(self.name, DEFAULT_SPREAD_PIPS[self.asset_class])

    @property
    def default_max_abs_return(self) -> float:
        """Candle-to-candle move treated as 'extreme' by validation (metals are more volatile)."""
        return 0.03 if self.asset_class == "metal" else 0.015

    def price_to_pips(self, price_difference: float) -> float:
        return price_difference / self.pip_size

    def pips_to_price(self, pips: float) -> float:
        return pips * self.pip_size

    def round_price(self, price: float) -> float:
        return round(price, self.display_precision)

    def quote_to_account_rate(
        self, price: float, account_currency: str = "USD", rates: Mapping[str, float] | None = None
    ) -> float:
        """How many units of the account currency one unit of the quote currency is worth.

        ``price`` is this instrument's current price. For crosses, ``rates`` must
        contain "<QUOTE>_<ACCOUNT>" or "<ACCOUNT>_<QUOTE>" (e.g. {"GBP_USD": 1.27}).
        """
        if self.quote == account_currency:
            return 1.0
        if self.base == account_currency:
            if price <= 0:
                raise ValueError("price must be positive")
            return 1.0 / price
        rates = rates or {}
        direct, inverse = f"{self.quote}_{account_currency}", f"{account_currency}_{self.quote}"
        if direct in rates:
            return rates[direct]
        if inverse in rates:
            return 1.0 / rates[inverse]
        raise ValueError(f"{self.name}: need a {direct} or {inverse} rate to value pips in {account_currency}")

    def pip_value_per_unit(
        self, price: float = 0.0, account_currency: str = "USD", rates: Mapping[str, float] | None = None
    ) -> float:
        """Value of a one-pip move for one unit, in the account currency."""
        return self.pip_size * self.quote_to_account_rate(price, account_currency, rates)


def normalize_instrument_name(name: str) -> str:
    """'eur/usd', 'EURUSD', 'EUR-USD' -> 'EUR_USD'."""
    raw = name.strip().upper()
    match = _NAME_RE.match(raw)
    if not match:
        raise UnsupportedInstrumentError(
            f"{name!r} is not a forex pair or metal. Use BASE_QUOTE, e.g. EUR_USD, AUD_USD or XAU_USD."
        )
    if raw.isalpha():  # no separator: prefer the split where both halves are known codes (BTCUSDT -> BTC + USDT)
        known = FIAT_CURRENCIES.keys() | METALS.keys() | CRYPTO_CODES
        for cut in (3, 4):
            if raw[:cut] in known and raw[cut:] in known:
                return f"{raw[:cut]}_{raw[cut:]}"
    return f"{match.group(1)}_{match.group(2)}"


@lru_cache(maxsize=256)
def get_instrument(name: str) -> Instrument:
    """Validate and describe a forex pair or spot metal. Raises UnsupportedInstrumentError."""
    norm = normalize_instrument_name(name)
    base, quote = norm.split("_")
    if base in CRYPTO_CODES or quote in CRYPTO_CODES:
        raise UnsupportedInstrumentError(f"{norm}: crypto is not supported (forex and precious metals only)")
    if quote not in FIAT_CURRENCIES:
        raise UnsupportedInstrumentError(f"{norm}: quote currency {quote!r} is not a supported fiat currency")
    if base == quote:
        raise UnsupportedInstrumentError(f"{norm}: base and quote are the same")
    if base in METALS:
        return Instrument(norm, base, quote, "metal", METAL_PIP_LOCATION[base])
    if base not in FIAT_CURRENCIES:
        raise UnsupportedInstrumentError(f"{norm}: base {base!r} is not a supported currency or metal")
    pip_location = -2 if quote in TWO_DECIMAL_PIP_QUOTES else -4
    return Instrument(norm, base, quote, "forex", pip_location)


GRANULARITY_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
}


def granularity_delta(granularity: str) -> timedelta:
    try:
        return timedelta(seconds=GRANULARITY_SECONDS[granularity.upper()])
    except KeyError as exc:
        supported = ", ".join(GRANULARITY_SECONDS)
        raise ValueError(f"Unsupported granularity {granularity!r}. Supported: {supported}") from exc


def granularity_label(granularity: str) -> str:
    """'M15' -> '15m', 'H1' -> '1h'."""
    seconds = GRANULARITY_SECONDS[granularity.upper()]
    return f"{seconds // 3600}h" if seconds >= 3600 else f"{seconds // 60}m"
