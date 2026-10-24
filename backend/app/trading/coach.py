"""Phase 11 - the coach: your demo-account trades, followed live.

Flow: a BUY/SELL signal arrives -> you place it on your demo account -> "I took this
trade" (your real fill price) -> the coach watches it and advises when to close ->
"I closed it" (your real exit price) -> result, balance and track record update.

Your fill will differ slightly from the signal's price, so stop and target keep the
signal's DISTANCES from your actual entry. Set the same SL/TP in your broker too:
it protects you even when this app is not running.

Paper balance = ACCOUNT_BALANCE + P/L of your closed coach trades; the next
signal's size is computed from it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.instruments import GRANULARITY_SECONDS, get_instrument
from app.database.models import CoachTrade, Signal
from app.signals.engine import AccountState
from app.trading.backtest import trading_day

BUY, SELL = "BUY", "SELL"


WARN_STOP_FRACTION = 0.7  # warn when the price has gone 70% of the way to the stop loss

class CoachError(ValueError):
    """A request the coach refuses (explained in the message)."""


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Coach:
    def __init__(self, session: Session, settings: Settings):
        self.s = session
        self.settings = settings

    # ---------------------------------------------------------------- account
    def closed_pnl(self) -> float:
        return float(self.s.execute(select(func.coalesce(func.sum(CoachTrade.pnl), 0.0))
                                    .where(CoachTrade.status == "closed")).scalar_one())

    def balance(self) -> float:
        return round(self.settings.account_balance + self.closed_pnl(), 2)

    def open_trades(self) -> list[CoachTrade]:
        return list(self.s.execute(select(CoachTrade).where(CoachTrade.status == "open")
                                   .order_by(CoachTrade.opened_at)).scalars())

    def account_state(self, now: datetime) -> AccountState:
        day = trading_day(pd.Timestamp(now))
        closed = self.s.execute(select(CoachTrade).where(CoachTrade.status == "closed")).scalars().all()
        today = [t for t in closed if trading_day(pd.Timestamp(_utc(t.closed_at))) == day]
        realised = float(sum(t.pnl or 0.0 for t in today))
        balance = self.balance()
        return AccountState(balance=balance, open_instruments=[t.instrument for t in self.open_trades()],
                            day_realised=realised, day_start_balance=balance - realised)

    # ---------------------------------------------------------------- signals
    def expire_signals(self, now: datetime) -> list[Signal]:
        stale = self.s.execute(select(Signal).where(Signal.status == "actionable",
                                                    Signal.expires_at <= now)).scalars().all()
        for sig in stale:
            sig.status = "expired"
        self.s.commit()
        return list(stale)

    @staticmethod
    def too_late_price(sig: Signal) -> float | None:
        """Past this price the move already happened: a quarter of the stop distance beyond the entry."""
        if sig.entry is None or sig.stop_loss is None:
            return None
        q = abs(sig.entry - sig.stop_loss) * 0.25
        return sig.entry + q if sig.decision == BUY else sig.entry - q

    def expire_late(self, instrument: str, mid: float, now: datetime) -> list[Signal]:
        """Remove BUY/SELL signals whose price has already run away - too late to enter."""
        late = []
        for sig in self.s.execute(select(Signal).where(Signal.status == "actionable",
                                                       Signal.instrument == instrument)).scalars():
            limit = self.too_late_price(sig)
            if limit is None or sig.decision not in (BUY, SELL):
                continue
            if (sig.decision == BUY and mid > limit) or (sig.decision == SELL and mid < limit):
                sig.status = "expired"
                sig.reason = (f"Too late - price already moved {'above' if sig.decision == BUY else 'below'} "
                              f"{limit:.{get_instrument(instrument).display_precision}f}. Signal removed.")
                late.append(sig)
        self.s.commit()
        return late

    def skip(self, signal_id: int) -> Signal:
        sig = self._actionable(signal_id, datetime.now(timezone.utc), allow_expired=True)
        sig.status = "skipped"
        self.s.commit()
        return sig

    def _actionable(self, signal_id: int, now: datetime, allow_expired: bool = False) -> Signal:
        sig = self.s.get(Signal, signal_id)
        if sig is None:
            raise CoachError("Signal not found.")
        if sig.decision not in (BUY, SELL):
            raise CoachError("This signal is WAIT - there is nothing to take.")
        if sig.status in ("taken", "skipped"):
            raise CoachError(f"This signal was already {sig.status}.")
        if not allow_expired and (sig.status == "expired" or (sig.expires_at and _utc(sig.expires_at) <= now)):
            raise CoachError("This signal has expired - the price has moved on. Wait for the next one.")
        return sig

    # ---------------------------------------------------------------- trades
    def take(self, signal_id: int, fill_price: float, units: int | None, now: datetime) -> CoachTrade:
        sig = self._actionable(signal_id, now)
        inst = get_instrument(sig.instrument)
        state = self.account_state(now)
        if sig.instrument in state.open_instruments:
            raise CoachError(f"You already have an open {inst.display_name} trade.")
        if len(state.open_instruments) >= self.settings.max_open_trades:
            raise CoachError(f"Maximum {self.settings.max_open_trades} open trade(s) - close one first.")
        if fill_price <= 0:
            raise CoachError("Enter the price your broker filled you at.")
        drift = inst.price_to_pips(abs(fill_price - sig.entry))
        if drift > max(20.0, inst.price_to_pips(sig.atr or 0) * 2):
            raise CoachError(f"Your price is {drift:.1f} pips away from the signal - please check it.")
        units = int(units or sig.units or 0)
        if units <= 0:
            raise CoachError("Units must be positive.")

        # the stop and target stay exactly as shown on the signal - the same values you type at your broker
        buy = sig.decision == BUY
        sl, tp = sig.stop_loss, sig.take_profit
        if (buy and fill_price >= tp) or (not buy and fill_price <= tp):
            raise CoachError("Your price is already past the target - this trade was too late. "
                             "Close it at your broker now.")
        if (buy and fill_price <= sl) or (not buy and fill_price >= sl):
            raise CoachError("Your price is already past the stop loss - close it at your broker now.")
        sl_dist = abs(fill_price - sl)
        risk = units * sl_dist * inst.quote_to_account_rate(fill_price)
        step = timedelta(seconds=GRANULARITY_SECONDS[sig.granularity])
        horizon = self.settings.max_holding_candles
        trade = CoachTrade(
            signal_id=sig.id, instrument=sig.instrument, side=sig.decision, units=units,
            entry_price=fill_price, stop_loss=inst.round_price(sl), take_profit=inst.round_price(tp),
            risk_amount=round(risk, 2), opened_at=now, close_by=_utc(sig.candle_time) + step * (horizon + 1),
            status="open", last_price=fill_price, last_price_at=now,
        )
        sig.status = "taken"
        self.s.add(trade)
        self.s.flush()
        if len(self.open_trades()) >= self.settings.max_open_trades:
            # other signals from the same moment can no longer be taken
            for other in self.s.execute(select(Signal).where(Signal.status == "actionable",
                                                             Signal.id != sig.id)).scalars():
                other.status = "expired"
        self.s.commit()
        return trade

    def cancel(self, trade_id: int, now: datetime) -> CoachTrade:
        """Undo "I took this trade" when it was recorded by mistake (not placed at the broker)."""
        trade = self.s.get(CoachTrade, trade_id)
        if trade is None or trade.status != "open":
            raise CoachError("Open trade not found.")
        sig = self.s.get(Signal, trade.signal_id) if trade.signal_id else None
        if sig is not None and sig.status == "taken":
            still_valid = sig.expires_at is not None and _utc(sig.expires_at) > now
            sig.status = "actionable" if still_valid else "expired"
        trade.status = "cancelled"
        self.s.flush()
        data = trade
        self.s.delete(trade)
        self.s.commit()
        return data

    def close(self, trade_id: int, exit_price: float, now: datetime, reason: str | None = None) -> CoachTrade:
        trade = self.s.get(CoachTrade, trade_id)
        if trade is None or trade.status != "open":
            raise CoachError("Open trade not found.")
        if exit_price <= 0:
            raise CoachError("Enter the price your broker closed the trade at.")
        inst = get_instrument(trade.instrument)
        diff = exit_price - trade.entry_price if trade.side == BUY else trade.entry_price - exit_price
        pnl = trade.units * diff * inst.quote_to_account_rate(exit_price)
        trade.exit_price, trade.closed_at, trade.status = exit_price, now, "closed"
        trade.close_reason = reason or trade.advice_reason or "closed manually"
        trade.pips = round(inst.price_to_pips(diff), 2)
        trade.pnl = round(pnl, 2)
        trade.r_multiple = round(pnl / trade.risk_amount, 3) if trade.risk_amount else None
        self.s.flush()
        trade.balance_after = self.balance()
        self.s.commit()
        return trade

    # ---------------------------------------------------------------- live following
    def _half_spread(self, instrument: str) -> float:
        return get_instrument(instrument).pips_to_price(self.settings.spread_pips(instrument)) / 2

    def _advise(self, trade: CoachTrade, reason: str, now: datetime) -> bool:
        if trade.advice == "close":
            return False
        trade.advice, trade.advice_reason, trade.advice_at = "close", reason, now
        return True

    def _warn_near_stop(self, trade: CoachTrade, px: float, now: datetime) -> bool:
        """Heads-up once the price has used WARN_STOP_FRACTION of the way to the stop loss."""
        if trade.advice is not None:
            return False
        dist = abs(trade.entry_price - trade.stop_loss)
        against = (trade.entry_price - px) if trade.side == BUY else (px - trade.entry_price)
        if dist <= 0 or against < WARN_STOP_FRACTION * dist:
            return False
        inst = get_instrument(trade.instrument)
        trade.advice, trade.advice_at = "warn", now
        trade.advice_reason = (
            f"Going against you: {inst.price_to_pips(against):.1f} pips down, the stop loss is "
            f"{inst.price_to_pips(abs(trade.stop_loss - px)):.1f} pips away. Your broker's stop closes it "
            f"automatically (about ${trade.risk_amount:.2f} max). You may also close now to lose a little less.")
        return True

    def on_price(self, instrument: str, mid: float, now: datetime) -> list[CoachTrade]:
        """Real-time tick: update P/L and advise closing when the stop or target is reached."""
        changed = []
        hs = self._half_spread(instrument)
        for t in self.open_trades():
            if t.instrument != instrument:
                continue
            t.last_price, t.last_price_at = mid, now
            px = mid - hs if t.side == BUY else mid + hs  # the price you would close at
            hit_tp = px >= t.take_profit if t.side == BUY else px <= t.take_profit
            hit_sl = px <= t.stop_loss if t.side == BUY else px >= t.stop_loss
            if hit_sl and self._advise(t, "Stop loss reached - close the trade (your broker's stop should have done it).", now):
                changed.append(t)
            elif hit_tp and self._advise(t, "Target reached - take the profit and close the trade.", now):
                changed.append(t)
            elif not hit_sl and not hit_tp and self._warn_near_stop(t, px, now):
                changed.append(t)
        self.s.commit()
        return changed

    def on_candle(self, instrument: str, candle: pd.Series, model_decision: str | None,
                  now: datetime) -> list[CoachTrade]:
        """Candle close: stop/target inside the candle, time limit, or the AI turning against the trade."""
        changed = []
        hs = self._half_spread(instrument)
        step = timedelta(seconds=GRANULARITY_SECONDS[self.settings.granularity])
        candle_start = pd.Timestamp(candle["time"]).to_pydatetime() if "time" in candle else None
        for t in self.open_trades():
            if t.instrument != instrument:
                continue
            opened = _utc(t.opened_at)
            if candle_start is not None and candle_start + step <= opened:
                continue  # candle ended before the trade existed (e.g. re-checked after a restart)
            t.last_price, t.last_price_at = float(candle["close"]), now
            if candle_start is not None and candle_start < opened:
                # the candle's high/low may come from before the entry: judge only its closing price
                lo = hi = float(candle["close"])
            else:
                lo, hi = float(candle["low"]), float(candle["high"])
            if t.side == BUY:
                hit_sl, hit_tp = lo - hs <= t.stop_loss, hi - hs >= t.take_profit
            else:
                hit_sl, hit_tp = hi + hs >= t.stop_loss, lo + hs <= t.take_profit
            reason = None
            if hit_sl:
                reason = "Stop loss was reached during the last candle - close the trade if your broker has not."
            elif hit_tp:
                reason = "Target was reached during the last candle - take the profit and close."
            elif now >= _utc(t.close_by):
                hours = self.settings.max_holding_candles * GRANULARITY_SECONDS[self.settings.granularity] / 3600
                reason = f"Time limit reached ({hours:g} h) - close the trade now."
            elif model_decision and model_decision not in ("WAIT", t.side):
                reason = f"The AI now favours {model_decision} - consider closing the trade."
            if reason and self._advise(t, reason, now):
                changed.append(t)
        self.s.commit()
        return changed

    # ---------------------------------------------------------------- track record
    def evaluate_outcomes(self, instrument: str, candles: pd.DataFrame, horizon: int) -> int:
        """Score every past model call on `instrument` as if it had been followed exactly."""
        pending = self.s.execute(select(Signal).where(
            Signal.instrument == instrument, Signal.outcome_r.is_(None), Signal.model_decision != "WAIT",
            Signal.entry.is_not(None))).scalars().all()
        if not pending or candles.empty:
            return 0
        times = pd.DatetimeIndex(candles["time"])
        hs = self._half_spread(instrument)
        done = 0
        for sig in pending:
            after = candles[times > pd.Timestamp(_utc(sig.candle_time))].head(horizon)
            buy = sig.model_decision == BUY
            risk = abs(sig.entry - sig.stop_loss)
            result = None
            for _, c in after.iterrows():
                lo, hi = (c["low"] - hs, c["high"] - hs) if buy else (c["low"] + hs, c["high"] + hs)
                if (lo <= sig.stop_loss) if buy else (hi >= sig.stop_loss):
                    result = (-1.0, "stop", c["time"])
                elif (hi >= sig.take_profit) if buy else (lo <= sig.take_profit):
                    result = (abs(sig.take_profit - sig.entry) / risk, "target", c["time"])
                if result:
                    break
            if result is None and len(after) == horizon:
                last = after.iloc[-1]
                exit_px = last["close"] - hs if buy else last["close"] + hs
                result = (((exit_px - sig.entry) if buy else (sig.entry - exit_px)) / risk, "time", last["time"])
            if result:
                sig.outcome_r, sig.outcome_reason = round(float(result[0]), 3), result[1]
                sig.outcome_at = pd.Timestamp(result[2]).to_pydatetime()
                done += 1
        self.s.commit()
        return done

    def stats(self) -> dict:
        closed = self.s.execute(select(CoachTrade).where(CoachTrade.status == "closed")).scalars().all()
        pnl = np.array([t.pnl or 0.0 for t in closed])
        r = np.array([t.r_multiple for t in closed if t.r_multiple is not None])
        calls = self.s.execute(select(Signal).where(Signal.model_decision != "WAIT")).scalars().all()
        scored = np.array([c.outcome_r for c in calls if c.outcome_r is not None])
        statuses = [c.status for c in calls if c.decision != "WAIT"]
        return {
            "balance": self.balance(),
            "starting_balance": self.settings.account_balance,
            "your_trades": {
                "closed": len(closed), "open": len(self.open_trades()),
                "total_pnl": round(float(pnl.sum()), 2),
                "win_rate": round(float((pnl > 0).mean()), 4) if len(pnl) else None,
                "average_r": round(float(r.mean()), 3) if len(r) else None,
            },
            "ai_track_record": {
                "calls": len(calls), "scored": int(len(scored)),
                "average_r": round(float(scored.mean()), 3) if len(scored) else None,
                "win_rate": round(float((scored > 0).mean()), 4) if len(scored) else None,
                "total_r": round(float(scored.sum()), 2) if len(scored) else 0.0,
            },
            "signals_followed": statuses.count("taken"),
            "signals_skipped": statuses.count("skipped"),
            "signals_expired": statuses.count("expired"),
        }
