import numpy as np
import pandas as pd
import pytest

from app.trading.backtest import BacktestConfig, compute_metrics, equity_curve, run_backtest

T0 = pd.Timestamp("2024-03-05 10:00", tz="UTC")  # a Tuesday: far from the weekend
STEP = pd.Timedelta(minutes=15)
ATR = 0.0010  # stop 15 pips, target 30 pips


def candles(path, start=1.1000, t0=T0, atr=ATR):
    """Candle 0 = signal candle (close = start); path = (open, high, low, close) of the following candles."""
    rows = [(start, start, start, start)] + list(path)
    return pd.DataFrame({
        "time": [t0 + STEP * i for i in range(len(rows))],
        "open": [r[0] for r in rows], "high": [r[1] for r in rows], "low": [r[2] for r in rows],
        "close": [r[3] for r in rows], "atr_14": [atr] * len(rows),
    })


def flat(n, p=1.1000):
    return [(p, p + 0.0001, p - 0.0001, p)] * n


def signal(side="BUY", t=T0, inst="EUR_USD", strength=0.8):
    pb, ps = (strength, 0.05) if side == "BUY" else (0.05, strength)
    return {"instrument": inst, "time": t, "p_sell": ps, "p_wait": 1 - pb - ps, "p_buy": pb}


def run(c, sigs, **cfg):
    base = dict(threshold=0.5, spread_pips={"EUR_USD": 0.0}, max_holding=4, leverage_forex=500)
    base.update(cfg)
    data = c if isinstance(c, dict) else {"EUR_USD": c}
    return run_backtest(data, pd.DataFrame(sigs), BacktestConfig(**base))


def test_buy_hits_target_and_balance_grows():
    res = run(candles([(1.1000, 1.1031, 1.0995, 1.1030)] + flat(4, 1.1030)), [signal()])
    t = res["trades"].iloc[0]
    assert t["reason"] == "target" and t["side"] == "BUY"
    assert t["units"] == 666  # $1 risk / 0.0015 stop = 666 units (allocation not binding at 500:1)
    assert t["pnl"] == pytest.approx(666 * 0.0030)
    assert t["balance_after"] == pytest.approx(100 + 666 * 0.0030)
    assert t["pips"] == pytest.approx(30)
    assert t["r_multiple"] == pytest.approx(2.0, rel=1e-3)


def test_sell_stopped_out():
    res = run(candles([(1.1000, 1.1016, 1.0998, 1.1010)] + flat(4)), [signal("SELL")])
    t = res["trades"].iloc[0]
    assert t["reason"] == "stop" and t["pnl"] == pytest.approx(-666 * 0.0015)


def test_same_candle_stop_and_target_is_stop():
    res = run(candles([(1.1000, 1.1040, 1.0980, 1.1000)] + flat(3)), [signal()])
    assert res["trades"].iloc[0]["reason"] == "stop"


def test_gap_through_stop_fills_at_open():
    res = run(candles([(1.0970, 1.0975, 1.0960, 1.0965)] + flat(3)), [signal()])
    t = res["trades"].iloc[0]
    assert t["reason"] == "gap_stop" and t["exit"] == pytest.approx(1.0970)
    assert t["pnl"] < -1.0  # worse than the planned $1: gaps are a real risk


def test_time_exit_and_spread_cost():
    res = run(candles(flat(5, 1.1005)), [signal()], spread_pips={"EUR_USD": 1.0})
    t = res["trades"].iloc[0]
    assert t["reason"] == "time" and t["bars"] == 4
    # entry at ask 1.10005, exit at bid 1.10045 -> +4 pips, minus nothing else
    assert t["entry"] == pytest.approx(1.10005) and t["exit"] == pytest.approx(1.10045)
    assert t["pips"] == pytest.approx(4.0)


def test_risk_uses_current_balance():
    path = [(1.1000, 1.1031, 1.0995, 1.1030)] + flat(6, 1.1030)
    c = candles(path)
    second = T0 + STEP * 2  # after the first trade has closed (candle 1)
    c.loc[2:, "close"] = 1.1030
    res = run(c, [signal(), signal(t=second)])
    first, nxt = res["trades"].iloc[0], res["trades"].iloc[1]
    assert nxt["risk_amount"] == pytest.approx(first["balance_after"] * 0.01, rel=0.01)


def test_one_open_trade_at_a_time():
    c = {"EUR_USD": candles(flat(8)), "GBP_USD": candles(flat(8), start=1.2700)}
    res = run(c, [signal(), signal(inst="GBP_USD", t=T0 + STEP)], spread_pips={"EUR_USD": 0.0, "GBP_USD": 0.0})
    assert len(res["trades"]) == 1 and res["skipped"]["max_open"] == 1


def test_daily_loss_limit_blocks_new_trades():
    # stop-outs cost 1% of the CURRENT balance: $1.00 + $0.99 + $0.98 = 2.97% -> above a 2.5% daily limit,
    # so the 4th signal that day is refused (with a 3% limit a 4th trade would still be allowed)
    loss = [(1.1000, 1.1002, 1.0980, 1.0985)]
    c = candles((loss + flat(1, 1.1000)) * 5)
    sigs = [signal(t=T0 + STEP * (2 * k)) for k in range(4)]
    res = run(c, sigs, max_daily_loss_percent=2.5)
    assert len(res["trades"]) == 3
    assert res["skipped"]["daily_limit"] == 1


def test_no_entry_right_before_weekend():
    friday = pd.Timestamp("2024-03-08 20:00", tz="UTC")  # market closes 22:00 UTC (winter); 4h hold crosses it
    res = run(candles(flat(6), t0=friday), [signal(t=friday)], max_holding=16)
    assert res["trades"].empty and res["skipped"]["weekend"] == 1


def test_allocation_limits_size_on_small_leverage():
    res = run(candles([(1.1000, 1.1031, 1.0995, 1.1030)] + flat(4, 1.1030)), [signal()], leverage_forex=30,
              allocation_percent=10)
    assert res["trades"].iloc[0]["units"] == 272  # $10 margin x 30 / 1.10


def test_metrics_and_equity():
    trades = pd.DataFrame({
        "entry_time": [T0, T0 + STEP * 10, T0 + pd.Timedelta(days=1)],
        "exit_time": [T0 + STEP, T0 + STEP * 11, T0 + pd.Timedelta(days=1, minutes=15)],
        "side": ["BUY", "SELL", "BUY"], "instrument": ["EUR_USD"] * 3,
        "pnl": [2.0, -1.0, 2.04], "pips": [30.0, -15.0, 30.0], "reason": ["target", "stop", "target"],
        "r_multiple": [2.0, -1.0, 2.0], "risk_amount": [1.0, 1.02, 1.01],
        "balance_after": [102.0, 101.0, 103.04],
    })
    m = compute_metrics(trades, 100.0)
    assert m["final_balance"] == 103.04 and m["total_return_pct"] == pytest.approx(3.04)
    assert m["win_rate"] == pytest.approx(2 / 3, abs=1e-4) and m["profit_factor"] == pytest.approx(4.04)
    assert m["max_drawdown_pct"] == pytest.approx((101 / 102 - 1) * 100, abs=0.01)
    assert m["longest_winning_streak"] == 1 and m["longest_losing_streak"] == 1
    assert m["by_side"]["BUY"]["trades"] == 2 and "2024-03" in m["by_month"]
    eq = equity_curve(trades, 100.0)
    assert list(eq["balance"]) == [102.0, 101.0, 103.04]
    assert eq["drawdown_pct"].min() == pytest.approx((101 / 102 - 1) * 100)


def test_no_signals_no_trades():
    res = run(candles(flat(5)), [signal(strength=0.3)])  # below the 0.5 threshold -> WAIT
    assert res["trades"].empty and res["metrics"]["final_balance"] == 100
