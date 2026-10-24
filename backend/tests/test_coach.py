import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.core.config import Settings
from app.database.models import CoachTrade, Signal
from app.features.engineering import build_features
from app.models.dataset import add_context_features
from app.signals.engine import AccountState, ModelBundle, decide_signal, market_closes_within
from app.trading.coach import Coach, CoachError
from tests.conftest import make_candles, to_candle_dicts

UTC = timezone.utc


def settings(**kw) -> Settings:
    base = dict(_env_file=None, coach_mode="practice", instruments="EUR_USD,GBP_USD,USD_JPY,XAU_USD")
    base.update(kw)
    return Settings(**base)


def bundle(deployable=False, threshold=0.4) -> ModelBundle:
    return ModelBundle(model=None, version="v-test", model_name="xgboost", threshold=threshold,
                       deployable=deployable, granularity="M15", horizon=16, test_expectancy_r=-0.1)


def feature_row(instrument="EUR_USD", end="2024-03-20 12:00"):
    df = make_candles("2024-02-26", end, instrument=instrument)
    feats = add_context_features(build_features(df, instrument), instrument, 1.0)
    return feats.iloc[-1]


def account(balance=100.0, open_=(), realised=0.0):
    return AccountState(balance=balance, open_instruments=list(open_), day_realised=realised,
                        day_start_balance=balance - realised)


BUY_P = {"p_buy": 0.55, "p_wait": 0.35, "p_sell": 0.10}


# ----------------------------------------------------------------- decisions
def test_wait_when_not_confident():
    row = feature_row()
    out = decide_signal(instrument="EUR_USD", row=row, proba={"p_buy": 0.3, "p_wait": 0.5, "p_sell": 0.2},
                        bundle=bundle(), settings=settings(), account=account())
    assert out["decision"] == "WAIT" and out["model_decision"] == "WAIT"
    assert "No strong opportunity" in out["reason"] and "40%" in out["reason"]


def test_buy_signal_levels_and_size():
    s, row = settings(), feature_row()
    out = decide_signal(instrument="EUR_USD", row=row, proba=BUY_P, bundle=bundle(), settings=s, account=account())
    assert out["decision"] == "BUY" and out["status"] == "actionable"
    atr = float(row["atr_14"])
    assert out["entry"] == pytest.approx(row["close"] + 0.00005, abs=1e-5)       # ask = mid + half spread
    assert out["entry"] - out["stop_loss"] == pytest.approx(1.5 * atr, abs=2e-5)
    assert out["take_profit"] - out["entry"] == pytest.approx(3.0 * atr, abs=2e-5)
    assert out["risk_amount"] <= 1.0 + 1e-9 and out["units"] > 0
    assert out["potential_profit"] == pytest.approx(2 * out["risk_amount"], rel=0.02)
    assert out["risk_reward"] == 2.0
    assert "PRACTICE" in out["reason"]  # an unproven model is always labelled
    close = pd.Timestamp(row["time"]) + pd.Timedelta(minutes=15)
    assert pd.Timestamp(out["expires_at"]) == close + pd.Timedelta(minutes=s.signal_expiry_minutes)


def test_practice_threshold_gives_more_signals():
    weak = {"p_buy": 0.27, "p_wait": 0.55, "p_sell": 0.18}
    strict = decide_signal(instrument="EUR_USD", row=feature_row(), proba=weak, bundle=bundle(threshold=0.35),
                           settings=settings(), account=account())
    assert strict["decision"] == "WAIT"
    loose = decide_signal(instrument="EUR_USD", row=feature_row(), proba=weak, bundle=bundle(threshold=0.35),
                          settings=settings(practice_signal_threshold=0.25), account=account())
    assert loose["decision"] == "BUY" and "PRACTICE" in loose["reason"]
    proven = decide_signal(instrument="EUR_USD", row=feature_row(), proba=weak, bundle=bundle(threshold=0.35, deployable=True),
                           settings=settings(coach_mode="proven", practice_signal_threshold=0.25), account=account())
    assert proven["decision"] == "WAIT"  # proven mode never uses the practice threshold


def test_sell_signal():
    out = decide_signal(instrument="EUR_USD", row=feature_row(), proba={"p_buy": 0.1, "p_wait": 0.3, "p_sell": 0.6},
                        bundle=bundle(), settings=settings(), account=account())
    assert out["decision"] == "SELL" and out["stop_loss"] > out["entry"] > out["take_profit"]


def test_proven_mode_blocks_unproven_model():
    out = decide_signal(instrument="EUR_USD", row=feature_row(), proba=BUY_P, bundle=bundle(deployable=False),
                        settings=settings(coach_mode="proven"), account=account())
    assert out["decision"] == "WAIT" and out["model_decision"] == "BUY"
    assert out["entry"] is not None  # levels kept so the model's live record can still be scored
    ok = decide_signal(instrument="EUR_USD", row=feature_row(), proba=BUY_P, bundle=bundle(deployable=True),
                       settings=settings(coach_mode="proven"), account=account())
    assert ok["decision"] == "BUY" and "passed" in ok["reason"]


@pytest.mark.parametrize("acct, expected", [
    (account(open_=["EUR_USD"]), "already have an open"),
    (account(open_=["GBP_USD"]), "Maximum 1 open trade"),
    (account(realised=-3.2), "Daily loss limit"),  # day started at $103.20; 3% = $3.10
])
def test_risk_rules_turn_signals_into_wait(acct, expected):
    out = decide_signal(instrument="EUR_USD", row=feature_row(), proba=BUY_P, bundle=bundle(),
                        settings=settings(), account=acct)
    assert out["decision"] == "WAIT" and expected in out["reason"]


def test_no_new_trade_before_weekend():
    row = feature_row(end="2024-03-15 19:00")  # Friday; market closes 21:00 UTC (summer time in NY)
    out = decide_signal(instrument="EUR_USD", row=row, proba=BUY_P, bundle=bundle(), settings=settings(),
                        account=account())
    assert out["decision"] == "WAIT" and "weekend" in out["reason"]
    assert market_closes_within(datetime(2024, 3, 15, 19, 15, tzinfo=UTC), 240, "forex")
    assert not market_closes_within(datetime(2024, 3, 13, 10, 0, tzinfo=UTC), 240, "forex")


def test_gold_too_small_for_100_dollars():
    row = feature_row("XAU_USD", end="2024-03-20 12:00")
    out = decide_signal(instrument="XAU_USD", row=row, proba=BUY_P, bundle=bundle(), settings=settings(),
                        account=account())
    assert out["decision"] == "WAIT" and "Too small" in out["reason"]


# ----------------------------------------------------------------- coach
NOW = datetime(2024, 3, 20, 12, 20, tzinfo=UTC)


def add_signal(db, decision="BUY", instrument="EUR_USD", entry=1.10000, sl=1.09850, tp=1.10300, units=666,
               status="actionable", expires=NOW + timedelta(minutes=10), candle=datetime(2024, 3, 20, 12, 0, tzinfo=UTC)):
    sig = Signal(instrument=instrument, granularity="M15", candle_time=candle, mode="practice",
                 model_decision=decision, decision=decision, entry=entry, stop_loss=sl, take_profit=tp,
                 atr=0.001, units=units, risk_amount=1.0, status=status, expires_at=expires)
    db.add(sig)
    db.commit()
    return sig


def test_take_keeps_the_signal_levels(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session)
    trade = coach.take(sig.id, fill_price=1.10020, units=None, now=NOW)
    assert trade.entry_price == 1.10020 and trade.units == 666
    assert trade.stop_loss == pytest.approx(1.09850) and trade.take_profit == pytest.approx(1.10300)
    assert trade.risk_amount == pytest.approx(666 * 0.0017, abs=0.01)
    assert db_session.get(Signal, sig.id).status == "taken"
    with pytest.raises(CoachError, match="already taken"):
        coach.take(sig.id, 1.1, None, NOW)


def test_take_refusals(db_session):
    coach = Coach(db_session, settings())
    expired = add_signal(db_session, expires=NOW - timedelta(minutes=1))
    with pytest.raises(CoachError, match="expired"):
        coach.take(expired.id, 1.1, None, NOW)
    far = add_signal(db_session, candle=datetime(2024, 3, 20, 12, 15, tzinfo=UTC))
    with pytest.raises(CoachError, match="pips away"):
        coach.take(far.id, 1.1100, None, NOW)
    wait = add_signal(db_session, decision="WAIT", candle=datetime(2024, 3, 20, 11, 45, tzinfo=UTC))
    with pytest.raises(CoachError, match="WAIT"):
        coach.take(wait.id, 1.1, None, NOW)


def test_one_open_trade_at_a_time(db_session):
    coach = Coach(db_session, settings())
    coach.take(add_signal(db_session).id, 1.1, None, NOW)
    other = add_signal(db_session, instrument="GBP_USD", entry=1.27, sl=1.2685, tp=1.273)
    with pytest.raises(CoachError, match="Maximum 1 open"):
        coach.take(other.id, 1.27, None, NOW)


def test_close_buy_and_balance(db_session):
    coach = Coach(db_session, settings())
    trade = coach.take(add_signal(db_session).id, 1.10000, None, NOW)
    closed = coach.close(trade.id, 1.10300, NOW + timedelta(hours=1))
    assert closed.pnl == pytest.approx(666 * 0.003, abs=0.01) and closed.pips == pytest.approx(30)
    assert closed.r_multiple == pytest.approx(2.0, abs=0.01)
    assert coach.balance() == pytest.approx(100 + 1.998, abs=0.01) == closed.balance_after
    assert coach.stats()["your_trades"]["closed"] == 1


def test_close_sell_usdjpy_converts_to_usd(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, decision="SELL", instrument="USD_JPY", entry=150.00, sl=150.15, tp=149.70, units=1000)
    trade = coach.take(sig.id, 150.00, None, NOW)
    closed = coach.close(trade.id, 149.70, NOW + timedelta(hours=1))
    assert closed.pips == pytest.approx(30)
    assert closed.pnl == pytest.approx(1000 * 0.30 / 149.70, abs=0.01)  # yen profit converted at the exit price


def test_daily_loss_is_tracked(db_session):
    coach = Coach(db_session, settings())
    trade = coach.take(add_signal(db_session).id, 1.10000, None, NOW)
    coach.close(trade.id, 1.09850, NOW + timedelta(minutes=30))
    state = coach.account_state(NOW + timedelta(hours=1))
    assert state.day_realised == pytest.approx(-0.999, abs=0.01)
    assert state.balance == pytest.approx(99.0, abs=0.01)


def test_price_ticks_trigger_close_advice(db_session):
    coach = Coach(db_session, settings())
    trade = coach.take(add_signal(db_session).id, 1.10000, None, NOW)
    assert coach.on_price("EUR_USD", 1.10100, NOW) == []  # still running
    advised = coach.on_price("EUR_USD", 1.10310, NOW)      # bid 1.10305 >= target 1.10300
    assert advised and "Target reached" in advised[0].advice_reason
    assert coach.on_price("EUR_USD", 1.10400, NOW) == []   # advice is given once
    assert db_session.get(CoachTrade, trade.id).last_price == 1.10400


def test_candle_close_advice_time_limit_and_ai_reversal(db_session):
    coach = Coach(db_session, settings())
    trade = coach.take(add_signal(db_session).id, 1.10000, None, NOW)
    calm = pd.Series({"open": 1.1001, "high": 1.1003, "low": 1.0998, "close": 1.1002})
    assert coach.on_candle("EUR_USD", calm, "WAIT", NOW) == []
    flipped = coach.on_candle("EUR_USD", calm, "SELL", NOW)
    assert "now favours SELL" in flipped[0].advice_reason
    t2 = CoachTrade(instrument="GBP_USD", side="BUY", units=100, entry_price=1.27, stop_loss=1.26, take_profit=1.29,
                    risk_amount=1.0, opened_at=NOW, close_by=NOW + timedelta(hours=4), status="open")
    db_session.add(t2)
    db_session.commit()
    late = coach.on_candle("GBP_USD", pd.Series({"open": 1.27, "high": 1.271, "low": 1.269, "close": 1.27}),
                           "WAIT", NOW + timedelta(hours=5))
    assert "Time limit" in late[0].advice_reason


def test_track_record_scores_every_model_call(db_session):
    coach = Coach(db_session, settings(spread_pips_overrides="EUR_USD:0"))
    c0 = datetime(2024, 3, 20, 12, 0, tzinfo=UTC)
    add_signal(db_session, candle=c0)                                         # BUY: target 1.10300
    add_signal(db_session, decision="SELL", entry=1.10000, sl=1.10150, tp=1.09700,
               candle=c0 + timedelta(minutes=15))                             # SELL: stop 1.10150
    candles = pd.DataFrame({
        "time": [c0 + timedelta(minutes=15 * k) for k in range(1, 6)],
        "open": [1.1000, 1.1010, 1.1020, 1.1025, 1.1028],
        "high": [1.1012, 1.1022, 1.1031, 1.1030, 1.1030],
        "low": [1.0998, 1.1008, 1.1018, 1.1020, 1.1025],
        "close": [1.1010, 1.1020, 1.1028, 1.1027, 1.1029],
    })
    assert coach.evaluate_outcomes("EUR_USD", candles, horizon=16) == 2
    buy, sell = db_session.query(Signal).order_by(Signal.candle_time).all()
    assert buy.outcome_reason == "target" and buy.outcome_r == pytest.approx(2.0)
    assert sell.outcome_reason == "stop" and sell.outcome_r == -1.0
    stats = coach.stats()["ai_track_record"]
    assert stats["scored"] == 2 and stats["average_r"] == pytest.approx(0.5)


def test_expire_signals(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, expires=NOW - timedelta(seconds=1))
    assert [s.id for s in coach.expire_signals(NOW)] == [sig.id]
    assert db_session.get(Signal, sig.id).status == "expired"


# ----------------------------------------------------------------- live engine
class FakeSource:
    source_name = "fake"

    def __init__(self, candles):
        self.candles = candles
        self.calls = 0

    def fetch_page(self, instrument, granularity, from_time):
        from app.data.sources import CandlePage

        self.calls += 1
        return CandlePage([c for c in self.candles if c["time"] >= from_time], None)

    def earliest_time(self, instrument, granularity):
        return None

    def close(self):
        pass


def test_live_tick_produces_one_signal_per_candle(db_session, repo, monkeypatch):
    import app.live.service as live

    df = make_candles("2024-03-04", "2024-03-20 12:00")
    history, newest = df.iloc[:-1], df.iloc[[-1]]
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(history), source="fake")
    source = FakeSource(to_candle_dicts(newest))

    b = bundle()
    monkeypatch.setattr(live, "load_model_bundle", lambda s: b)
    monkeypatch.setattr(live, "predict", lambda bundle, row: BUY_P)

    class Recorder:
        def __init__(self):
            self.events = []

        async def broadcast(self, event, data):
            self.events.append((event, data))

    rec = Recorder()
    s = settings(instruments="EUR_USD", live_settle_seconds=10)
    now = datetime(2024, 3, 20, 12, 15, 30, tzinfo=UTC)  # candle 12:00 closed at 12:15
    svc = live.LiveService(s, rec, source_factory=lambda: source, now=lambda: now)

    signals = asyncio.run(svc.tick())
    assert len(signals) == 1 and signals[0]["decision"] == "BUY"
    assert pd.Timestamp(signals[0]["candle_time"]) == pd.Timestamp("2024-03-20 12:00", tz="UTC")
    assert {e for e, _ in rec.events} >= {"signal", "status"}
    assert source.calls == 1

    assert asyncio.run(svc.tick()) == []  # same candle: no duplicate signal, no extra request
    assert source.calls == 1
    assert db_session.query(Signal).count() == 1


def test_live_tick_stops_retrying_a_missing_candle(db_session, repo):
    import app.live.service as live

    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-03-04", "2024-03-20 11:45")),
                        source="fake")
    source = FakeSource([])  # provider never delivers the 12:00 candle

    class Quiet:
        async def broadcast(self, event, data):
            pass

    s = settings(instruments="EUR_USD", live_settle_seconds=10, live_max_fetch_attempts=3)
    svc = live.LiveService(s, Quiet(), source_factory=lambda: source,
                           now=lambda: datetime(2024, 3, 20, 12, 15, 30, tzinfo=UTC))
    for _ in range(5):
        asyncio.run(svc.tick())
    assert source.calls == 3  # capped: every attempt costs an API credit


def test_live_tick_skips_weekend(db_session, repo):
    import app.live.service as live

    source = FakeSource([])

    class Quiet:
        async def broadcast(self, event, data):
            pass

    svc = live.LiveService(settings(instruments="EUR_USD"), Quiet(), source_factory=lambda: source,
                           now=lambda: datetime(2024, 3, 16, 12, 0, tzinfo=UTC))  # Saturday
    asyncio.run(svc.tick())
    assert source.calls == 0


def test_taking_one_signal_expires_the_others(db_session):
    coach = Coach(db_session, settings())
    eur = add_signal(db_session)
    jpy = add_signal(db_session, decision="SELL", instrument="USD_JPY", entry=158.776, sl=158.878, tp=158.675, units=1500)
    coach.take(jpy.id, 158.776, None, NOW)
    assert db_session.get(Signal, eur.id).status == "expired"  # only one trade at a time


def test_cancel_a_mistaken_trade(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session)
    trade = coach.take(sig.id, 1.1, None, NOW)
    coach.cancel(trade.id, NOW + timedelta(minutes=2))
    assert coach.open_trades() == [] and coach.balance() == 100
    assert db_session.get(Signal, sig.id).status == "actionable"  # can still be taken while valid
    with pytest.raises(CoachError):
        coach.cancel(trade.id, NOW)


def test_open_trades_get_frequent_price_checks(db_session):
    import app.live.service as live

    coach = Coach(db_session, settings())
    sig = add_signal(db_session, decision="SELL", instrument="USD_JPY", entry=158.776, sl=158.878, tp=158.675, units=1500)
    coach.take(sig.id, 158.776, None, NOW)

    class PriceSource(FakeSource):
        def __init__(self):
            super().__init__([])
            self.asked = []

        def latest_price(self, instrument):
            self.asked.append(instrument)
            return 158.660  # below the target: the SELL reached its target

    class Rec:
        def __init__(self):
            self.events = []

        async def broadcast(self, event, data):
            self.events.append((event, data))

    src, rec = PriceSource(), Rec()
    svc = live.LiveService(settings(instruments="EUR_USD,USD_JPY"), rec, source_factory=lambda: src,
                           now=lambda: NOW + timedelta(minutes=5))
    assert asyncio.run(svc.poll_trade_prices()) == ["USD_JPY"]
    assert src.asked == ["USD_JPY"]  # only pairs with an open trade are checked
    trades = [d for e, d in rec.events if e == "trade"]
    assert trades and "Target reached" in trades[0]["advice_reason"]
    assert svc.status.requests_today == 1


def test_price_checks_respect_the_daily_budget(db_session):
    import app.live.service as live

    coach = Coach(db_session, settings())
    coach.take(add_signal(db_session, instrument="GBP_USD", entry=1.27, sl=1.2685, tp=1.273).id, 1.27, None, NOW)

    class PriceSource(FakeSource):
        def latest_price(self, instrument):
            raise AssertionError("must not be called when the budget is used up")

    class Quiet:
        async def broadcast(self, event, data):
            pass

    svc = live.LiveService(settings(daily_request_budget=100), Quiet(), source_factory=lambda: PriceSource([]),
                           now=lambda: NOW)
    svc.status.requests_day, svc.status.requests_today = NOW.strftime("%Y-%m-%d"), 60
    assert asyncio.run(svc.poll_trade_prices()) == []


def test_candles_from_before_the_entry_never_trigger_advice(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, decision="SELL", instrument="USD_JPY", entry=158.776, sl=158.878, tp=158.675, units=1500)
    opened = datetime(2024, 3, 20, 12, 17, tzinfo=UTC)
    coach.take(sig.id, 158.776, None, opened)
    spike = {"open": 158.8, "high": 158.8, "low": 158.60, "close": 158.79}  # touched the target at some point
    before = pd.Series({"time": pd.Timestamp("2024-03-20 12:00", tz="UTC"), **spike})  # ended 12:15, before entry
    assert coach.on_candle("USD_JPY", before, "WAIT", opened + timedelta(minutes=10)) == []
    during = pd.Series({"time": pd.Timestamp("2024-03-20 12:15", tz="UTC"), **spike})  # started before entry
    assert coach.on_candle("USD_JPY", during, "WAIT", opened + timedelta(minutes=14)) == []  # only its close counts
    after = pd.Series({"time": pd.Timestamp("2024-03-20 12:30", tz="UTC"), **spike})
    advised = coach.on_candle("USD_JPY", after, "WAIT", opened + timedelta(minutes=29))
    assert advised and "Target" in advised[0].advice_reason


def test_take_refuses_a_fill_already_past_the_target(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, instrument="AUD_USD", entry=0.70114, sl=0.70065, tp=0.70163, units=1047)
    with pytest.raises(CoachError, match="past the target"):
        coach.take(sig.id, 0.70190, None, NOW)  # bought 7.6 pips above the signal: target already behind you


def test_signal_disappears_when_too_late(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, decision="SELL", entry=1.13899, sl=1.13945, tp=1.13853)  # too late below 1.13887
    assert coach.expire_late("EUR_USD", 1.13895, NOW) == []  # still fine
    assert [s.id for s in coach.expire_late("EUR_USD", 1.13866, NOW)] == [sig.id]
    assert db_session.get(Signal, sig.id).status == "expired" and "Too late" in db_session.get(Signal, sig.id).reason


def test_price_checks_also_watch_waiting_signals(db_session):
    import app.live.service as live

    sig = add_signal(db_session, instrument="GBP_USD", entry=1.32214, sl=1.32167, tp=1.32261)

    class PriceSource(FakeSource):
        def latest_price(self, instrument):
            return 1.32240  # above the too-late line 1.32226

    class Rec:
        def __init__(self):
            self.events = []

        async def broadcast(self, event, data):
            self.events.append((event, data))

    rec = Rec()
    svc = live.LiveService(settings(), rec, source_factory=lambda: PriceSource([]), now=lambda: NOW)
    assert asyncio.run(svc.poll_trade_prices()) == ["GBP_USD"]
    assert [d["status"] for e, d in rec.events if e == "signal"] == ["expired"]
    db_session.expire_all()
    assert db_session.get(Signal, sig.id).status == "expired"


def test_warns_when_close_to_the_stop(db_session):
    coach = Coach(db_session, settings())
    sig = add_signal(db_session, decision="SELL", instrument="USD_JPY", entry=157.898, sl=158.035, tp=157.760, units=736)
    trade = coach.take(sig.id, 157.898, None, NOW)
    assert coach.on_price("USD_JPY", 157.95, NOW) == []  # 5 pips against: fine
    warned = coach.on_price("USD_JPY", 157.99, NOW)       # 70%+ of the way to the stop
    assert warned and warned[0].advice == "warn" and "Going against you" in warned[0].advice_reason
    assert coach.on_price("USD_JPY", 157.995, NOW) == []  # only once
    closed = coach.on_price("USD_JPY", 158.04, NOW)       # then the stop: a real close alert
    assert closed and closed[0].advice == "close" and closed[0].id == trade.id
