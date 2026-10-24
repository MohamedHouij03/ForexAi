import pandas as pd
import pytest

from app.features.indicators import atr, true_range
from app.risk.position_sizing import size_position

DEFAULTS = dict(balance=100.0, risk_percent=1.5, allocation_percent=10.0, leverage=30.0)


def sized(instrument="EUR_USD", entry=1.10000, stop_loss=1.09880, **overrides):
    return size_position(instrument, entry=entry, stop_loss=stop_loss, **{**DEFAULTS, **overrides})


def test_allocation_limits_small_account():
    # 12-pip stop: risk alone would allow $1.50 / $0.0012 = 1250 units ($1,375 = $45.83 margin at 30:1)
    # but margin is capped at $10 -> $300 of EUR -> 272 units
    p = sized()
    assert p.limited_by == "allocation"
    assert p.units == 272
    assert p.margin_required <= 10.0
    assert p.position_value == pytest.approx(299.2)
    assert p.risk_amount == pytest.approx(272 * 0.0012)  # $0.33, below the $1.50 limit
    assert p.tradable and p.direction == "BUY"
    assert p.stop_distance_pips == pytest.approx(12)


def test_risk_limits_with_high_leverage():
    # 500:1 leverage makes margin cheap, so the $1.50 loss limit binds: 1.50 / 0.0012 = 1250 units
    p = sized(leverage=500)
    assert p.limited_by == "risk"
    assert p.units == 1250
    assert p.risk_amount == pytest.approx(1.50)
    assert p.margin_required == pytest.approx(1250 * 1.10 / 500)


def test_never_exceeds_either_limit_and_rounds_down():
    for stop_pips in (3, 7.5, 12, 25, 60, 150):
        for lev in (10, 30, 50, 200, 500):
            p = sized(stop_loss=1.10000 - stop_pips * 0.0001, leverage=lev)
            assert p.risk_amount <= p.max_risk_amount + 1e-9
            assert p.margin_required <= p.max_allocation + 1e-9


def test_limits_scale_with_balance():
    small, grown = sized(leverage=500), sized(balance=200, leverage=500)
    assert grown.max_risk_amount == 3.0 and grown.max_allocation == 20.0
    assert grown.units == 2 * small.units


def test_sell_direction():
    p = sized(entry=1.10000, stop_loss=1.10120, leverage=500)
    assert p.direction == "SELL" and p.units == 1250


def test_usd_jpy_uses_price_conversion():
    # USD/JPY 150, 15-pip stop (0.15 JPY): loss per unit = 0.15/150 = $0.001 -> 1500 units by risk
    p = sized("USD_JPY", entry=150.0, stop_loss=149.85, leverage=500)
    assert p.units == 1500 and p.limited_by == "risk"
    # at 30:1, 1 unit (= $1 of USD) needs $0.0333 margin -> $10 allows 300 units
    assert sized("USD_JPY", entry=150.0, stop_loss=149.85).units == 300


def test_cross_needs_rate():
    with pytest.raises(ValueError, match="GBP_USD"):
        sized("EUR_GBP", entry=0.85, stop_loss=0.8488)
    p = sized("EUR_GBP", entry=0.85, stop_loss=0.8488, leverage=500, rates={"GBP_USD": 1.25})
    assert p.units == 1000  # loss per unit 0.0012 GBP = $0.0015 -> 1.50 / 0.0015


def test_gold_not_tradable_on_small_account():
    # 1 oz at $4,000 with a $10 stop: risks $10 (> $1.50) and needs $200 margin at 20:1 (> $10)
    p = sized("XAU_USD", entry=4000.0, stop_loss=3990.0, leverage=20)
    assert not p.tradable and p.units == 0
    assert "risk" in p.reason
    tight = sized("XAU_USD", entry=4000.0, stop_loss=3999.0, leverage=20)  # $1 stop: risk OK, margin not
    assert not tight.tradable and "margin" in tight.reason


def test_invalid_inputs():
    with pytest.raises(ValueError):
        sized(stop_loss=1.10000)
    with pytest.raises(ValueError):
        sized(balance=0)


def test_atr_matches_manual_calculation():
    df = pd.DataFrame({
        "high": [1.10, 1.12, 1.115, 1.13],
        "low": [1.08, 1.09, 1.112, 1.10],
        "close": [1.09, 1.09, 1.113, 1.12],
    })
    tr = true_range(df)
    # candle 2 gaps up: its own range is 0.003, but from the previous close (1.09) to its high is 0.025
    assert list(tr.round(4)) == [0.02, 0.03, 0.025, 0.03]
    a = atr(df, period=2)
    assert pd.isna(a.iloc[0])
    assert a.iloc[1] == pytest.approx(0.02 * 0.5 + 0.03 * 0.5)  # Wilder smoothing, alpha = 1/period
    assert a.iloc[2] == pytest.approx(a.iloc[1] * 0.5 + 0.025 * 0.5)


def test_atr_has_no_lookahead():
    df = pd.DataFrame({"high": [1.1, 1.2, 1.3, 1.4, 1.5], "low": [1.0, 1.1, 1.2, 1.3, 1.4],
                       "close": [1.05, 1.15, 1.25, 1.35, 1.45]})
    full = atr(df, period=2)
    shocked = df.copy()
    shocked.loc[4, ["high", "low", "close"]] = [9.0, 0.5, 5.0]  # change only the last candle
    assert atr(shocked, period=2).iloc[:4].equals(full.iloc[:4])
