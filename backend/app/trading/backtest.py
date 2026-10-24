"""Phase 8 - account-level backtest of the coach's rules on out-of-sample signals.

Rules simulated (all from Settings, so the backtest matches what the coach does live):
  * signal at the CLOSE of candle t: BUY if P(BUY) >= threshold and > P(SELL), SELL likewise
  * entry at that close: BUY at the ask (mid + spread/2), SELL at the bid (mid - spread/2)
  * stop / target = SL_MULT / TP_MULT x ATR(t) from the entry price
  * position size from the CURRENT balance: loss at stop <= MAX_RISK_PERCENT,
    margin <= MAX_TRADE_ALLOCATION_PERCENT (app.risk.position_sizing); too small -> skipped
  * at most MAX_OPEN_TRADES open, one per instrument
  * after losing MAX_DAILY_LOSS_PERCENT of the day's starting balance, no new trades
    until the next trading day (days start 17:00 New York)
  * no new trade if the weekend closure starts before the maximum holding time ends
  * exits, checked candle by candle from t+1, BUYs exit at the bid, SELLs at the ask:
      - if a candle OPENS beyond the stop or target (gap, e.g. after a weekend or news)
        the trade is filled at that open price, not at the level (realistic slippage)
      - stop and target inside the same candle -> stop (pessimistic)
      - after MAX_HOLDING candles -> close at that candle's close
  * P/L converted to USD at the exit price (e.g. USD/JPY: yen profit / price)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.core.market_hours import NEW_YORK, ROLLOVER_HOUR_NY, weekly_open_mask
from app.models.evaluation import BUY, SELL, decide
from app.risk.position_sizing import size_position


@dataclass
class BacktestConfig:
    starting_balance: float = 100.0
    risk_percent: float = 1.0
    allocation_percent: float = 50.0
    leverage_forex: float = 30.0
    leverage_metal: float = 20.0
    max_open_trades: int = 1
    max_daily_loss_percent: float = 3.0
    sl_atr: float = 1.5
    tp_atr: float = 3.0
    max_holding: int = 16
    threshold: float = 0.5
    granularity: str = "M15"
    spread_pips: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Series:
    """Per-instrument candle arrays for fast forward scans."""
    time: np.ndarray   # int64 ns
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    atr: np.ndarray
    index: dict        # time ns -> row


def _prepare(candles: dict[str, pd.DataFrame]) -> dict[str, _Series]:
    out = {}
    for name, df in candles.items():
        d = df.sort_values("time")
        t = pd.DatetimeIndex(d["time"]).tz_convert("UTC").as_unit("ns").asi8
        out[name] = _Series(t, *(d[c].to_numpy(float) for c in ("open", "high", "low", "close", "atr_14")),
                            index={int(v): i for i, v in enumerate(t)})
    return out


def trading_day(ts: pd.Timestamp):
    """FX trading day: starts 17:00 New York."""
    return (ts.tz_convert(NEW_YORK) + pd.Timedelta(hours=24 - ROLLOVER_HOUR_NY)).date()


def _simulate_exit(s: _Series, i0: int, side: int, entry: float, sl: float, tp: float, hs: float, max_holding: int):
    """Scan candles after i0. Returns (exit_index, exit_price, reason)."""
    last = min(i0 + max_holding, len(s.time) - 1)
    for k in range(i0 + 1, last + 1):
        if side == BUY:  # exits at the bid = mid - hs
            o, lo, hi = s.open[k] - hs, s.low[k] - hs, s.high[k] - hs
            if o <= sl:
                return k, o, "gap_stop"
            if o >= tp:
                return k, o, "gap_target"
            if lo <= sl:
                return k, sl, "stop"
            if hi >= tp:
                return k, tp, "target"
        else:  # exits at the ask = mid + hs
            o, lo, hi = s.open[k] + hs, s.low[k] + hs, s.high[k] + hs
            if o >= sl:
                return k, o, "gap_stop"
            if o <= tp:
                return k, o, "gap_target"
            if hi >= sl:
                return k, sl, "stop"
            if lo <= tp:
                return k, tp, "target"
    if last <= i0:
        return None
    exit_price = s.close[last] - hs if side == BUY else s.close[last] + hs
    return last, exit_price, "time"


def _weekend_guard(times: pd.Series, instruments: pd.Series, step: pd.Timedelta, horizon: int) -> np.ndarray:
    """True where the market stays open for the whole holding window after entry."""
    ok = np.ones(len(times), dtype=bool)
    for name in instruments.unique():
        m = (instruments == name).to_numpy()
        asset_class = get_instrument(name).asset_class
        t = pd.DatetimeIndex(times[m])
        for k in range(1, horizon + 1):
            ok[np.flatnonzero(m)] &= weekly_open_mask(t + step * k, asset_class)
    return ok


def run_backtest(candles: dict[str, pd.DataFrame], predictions: pd.DataFrame, cfg: BacktestConfig) -> dict:
    """candles: instrument -> DataFrame(time, open, high, low, close, atr_14) covering the period.
    predictions: DataFrame(instrument, time, p_sell, p_wait, p_buy), out-of-sample."""
    series = _prepare(candles)
    step = pd.Timedelta(seconds=GRANULARITY_SECONDS[cfg.granularity])
    sig = predictions[predictions["instrument"].isin(series)].sort_values(["time", "instrument"], kind="stable")
    sig = sig.assign(decision=decide(sig, cfg.threshold))
    sig = sig[sig["decision"] != 0].reset_index(drop=True)
    guard = _weekend_guard(sig["time"], sig["instrument"], step, cfg.max_holding) if len(sig) else np.array([], bool)

    balance = cfg.starting_balance
    open_trades: list[dict] = []
    trades: list[dict] = []
    day_start_balance: dict = {}
    day_realised: dict = {}
    skipped = {"weekend": 0, "max_open": 0, "daily_limit": 0, "not_tradable": 0, "same_instrument": 0}

    def close_until(t_ns: int):
        nonlocal balance
        for tr in sorted([o for o in open_trades if o["exit_ns"] <= t_ns], key=lambda o: o["exit_ns"]):
            open_trades.remove(tr)
            inst = get_instrument(tr["instrument"])
            diff = (tr["exit_price"] - tr["entry"]) if tr["side"] == BUY else (tr["entry"] - tr["exit_price"])
            pnl = tr["units"] * diff * inst.quote_to_account_rate(tr["exit_price"])
            day = trading_day(pd.Timestamp(tr["exit_ns"], tz="UTC"))
            day_start_balance.setdefault(day, balance)
            day_realised[day] = day_realised.get(day, 0.0) + pnl
            balance += pnl
            trades.append({
                "entry_time": pd.Timestamp(tr["entry_ns"], tz="UTC"), "exit_time": pd.Timestamp(tr["exit_ns"], tz="UTC"),
                "instrument": tr["instrument"], "side": "BUY" if tr["side"] == BUY else "SELL",
                "entry": tr["entry"], "stop_loss": tr["sl"], "take_profit": tr["tp"], "units": tr["units"],
                "risk_amount": tr["risk_amount"], "exit": tr["exit_price"], "reason": tr["reason"],
                "result": "win" if pnl > 0 else "loss", "pips": round(inst.price_to_pips(diff), 2),
                "pnl": pnl, "r_multiple": pnl / tr["risk_amount"] if tr["risk_amount"] else 0.0,
                "balance_after": balance, "bars": tr["bars"],
            })

    for j, row in enumerate(sig.itertuples(index=False)):
        t = pd.Timestamp(row.time)
        # the signal candle closes one step after its stamp; exits on earlier candles happen first
        t_ns = int(t.value)
        close_until(t_ns)
        if not guard[j]:
            skipped["weekend"] += 1
            continue
        if any(o["instrument"] == row.instrument for o in open_trades):
            skipped["same_instrument"] += 1
            continue
        if len(open_trades) >= cfg.max_open_trades:
            skipped["max_open"] += 1
            continue
        day = trading_day(t + step)
        start_bal = day_start_balance.setdefault(day, balance)
        if day_realised.get(day, 0.0) <= -start_bal * cfg.max_daily_loss_percent / 100:
            skipped["daily_limit"] += 1
            continue

        s = series[row.instrument]
        i0 = s.index.get(t_ns)
        if i0 is None or not np.isfinite(s.atr[i0]) or s.atr[i0] <= 0:
            continue
        inst = get_instrument(row.instrument)
        hs = inst.pips_to_price(cfg.spread_pips.get(row.instrument, inst.typical_spread_pips)) / 2
        side = int(row.decision)
        entry = s.close[i0] + hs if side == BUY else s.close[i0] - hs
        dist_sl, dist_tp = cfg.sl_atr * s.atr[i0], cfg.tp_atr * s.atr[i0]
        sl = entry - dist_sl if side == BUY else entry + dist_sl
        tp = entry + dist_tp if side == BUY else entry - dist_tp
        pos = size_position(row.instrument, balance=balance, entry=entry, stop_loss=sl,
                            risk_percent=cfg.risk_percent, allocation_percent=cfg.allocation_percent,
                            leverage=cfg.leverage_metal if inst.asset_class == "metal" else cfg.leverage_forex)
        if not pos.tradable:
            skipped["not_tradable"] += 1
            continue
        ex = _simulate_exit(s, i0, side, entry, sl, tp, hs, cfg.max_holding)
        if ex is None:
            continue
        k, exit_price, reason = ex
        open_trades.append({"instrument": row.instrument, "side": side, "entry": entry, "sl": sl, "tp": tp,
                            "units": pos.units, "risk_amount": pos.risk_amount, "entry_ns": t_ns,
                            "exit_ns": int(s.time[k]), "exit_price": exit_price, "reason": reason, "bars": k - i0})
    close_until(np.iinfo(np.int64).max)

    trades_df = pd.DataFrame(trades)
    return {"config": cfg.to_dict(), "trades": trades_df, "signals": int(len(sig)), "skipped": skipped,
            "metrics": compute_metrics(trades_df, cfg.starting_balance)}


# --------------------------------------------------------------------------- metrics
def _streaks(wins: np.ndarray) -> tuple[int, int]:
    best_w = best_l = cur = 0
    last = None
    for w in wins:
        cur = cur + 1 if w == last else 1
        last = w
        if w:
            best_w = max(best_w, cur)
        else:
            best_l = max(best_l, cur)
    return best_w, best_l


def _group_stats(trades: pd.DataFrame, key) -> dict:
    out = {}
    for k, g in trades.groupby(key):
        wins = g["pnl"] > 0
        out[str(k)] = {"trades": int(len(g)), "pnl": round(float(g["pnl"].sum()), 2),
                       "win_rate": round(float(wins.mean()), 4), "avg_r": round(float(g["r_multiple"].mean()), 4)}
    return out


def risk_of_ruin(trades: pd.DataFrame, starting_balance: float, n_sims: int = 2000, seed: int = 7) -> dict:
    """Monte Carlo: reshuffle the trades' R results (with replacement), compound at each trade's risk fraction."""
    if len(trades) < 10:
        return {}
    rng = np.random.default_rng(seed)
    r = trades["r_multiple"].to_numpy()
    frac = (trades["risk_amount"] / (trades["balance_after"] - trades["pnl"])).to_numpy()
    idx = rng.integers(0, len(r), size=(n_sims, len(r)))
    growth = np.cumprod(1 + r[idx] * frac[idx], axis=1)
    worst = growth.min(axis=1)
    return {
        "simulations": n_sims,
        "trades_per_simulation": int(len(r)),
        "prob_drawdown_20pct": round(float((worst <= 0.8).mean()), 4),
        "prob_drawdown_50pct": round(float((worst <= 0.5).mean()), 4),
        "median_final_balance": round(float(np.median(growth[:, -1]) * starting_balance), 2),
        "p5_final_balance": round(float(np.percentile(growth[:, -1], 5) * starting_balance), 2),
        "p95_final_balance": round(float(np.percentile(growth[:, -1], 95) * starting_balance), 2),
    }


def compute_metrics(trades: pd.DataFrame, starting_balance: float) -> dict:
    if trades.empty:
        return {"trades": 0, "starting_balance": starting_balance, "final_balance": starting_balance,
                "total_return_pct": 0.0}
    from app.features.sessions import current_session_name

    pnl = trades["pnl"].to_numpy()
    equity = np.r_[starting_balance, trades["balance_after"].to_numpy()]
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]

    daily = trades.groupby(trades["exit_time"].dt.tz_convert("UTC").dt.normalize())["pnl"].sum()
    days = pd.date_range(daily.index.min(), daily.index.max(), freq="B", tz="UTC")
    daily = daily.reindex(days, fill_value=0.0)
    eq_before = starting_balance + daily.cumsum().shift(1, fill_value=0.0)
    daily_ret = daily / eq_before
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else None

    best_w, best_l = _streaks(pnl > 0)
    final = float(equity[-1])
    return {
        "starting_balance": starting_balance,
        "final_balance": round(final, 2),
        "total_return_pct": round((final / starting_balance - 1) * 100, 2),
        "trades": int(len(trades)),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "loss_rate": round(float((pnl <= 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if losses.sum() < 0 else None,
        "max_drawdown_pct": round(float(dd.min() * 100), 2),
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "average_trade": round(float(pnl.mean()), 4),
        "average_winner": round(float(wins.mean()), 4) if len(wins) else None,
        "average_loser": round(float(losses.mean()), 4) if len(losses) else None,
        "average_r": round(float(trades["r_multiple"].mean()), 4),
        "average_pips_gained": round(float(trades.loc[trades["pips"] > 0, "pips"].mean()), 2)
        if (trades["pips"] > 0).any() else None,
        "average_pips_lost": round(float(trades.loc[trades["pips"] <= 0, "pips"].mean()), 2)
        if (trades["pips"] <= 0).any() else None,
        "longest_winning_streak": best_w,
        "longest_losing_streak": best_l,
        "exit_reasons": {k: int(v) for k, v in trades["reason"].value_counts().items()},
        "by_side": _group_stats(trades, "side"),
        "by_instrument": _group_stats(trades, "instrument"),
        "by_session": _group_stats(trades, trades["entry_time"].map(current_session_name)),
        "by_month": _group_stats(trades, trades["exit_time"].dt.strftime("%Y-%m")),
        "by_year": _group_stats(trades, trades["exit_time"].dt.year),
        "risk_of_ruin": risk_of_ruin(trades, starting_balance),
    }


def equity_curve(trades: pd.DataFrame, starting_balance: float) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=["time", "balance", "drawdown_pct"])
    eq = pd.DataFrame({"time": trades["exit_time"], "balance": trades["balance_after"]})
    peak = np.maximum.accumulate(np.r_[starting_balance, eq["balance"].to_numpy()])[1:]
    eq["drawdown_pct"] = (eq["balance"] / peak - 1) * 100
    return eq.reset_index(drop=True)
