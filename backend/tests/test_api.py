import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import make_candles, to_candle_dicts


@pytest.fixture
def client(db_session):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded(repo):
    df = make_candles("2024-03-04", "2024-03-09")
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(df), source="fake")
    return df


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["trading_mode"] == "paper"
    assert body["data_provider"] == {"name": "twelvedata", "configured": False}


def test_config_distinguishes_allocation_from_risk(client):
    body = client.get("/api/config").json()
    assert body["trading_mode"] == "paper"
    risk = body["risk"]
    assert risk["account_balance"] == 100
    assert risk["max_trade_allocation_percent"] == 50 and risk["max_trade_allocation"] == 50
    assert risk["max_risk_percent"] == 1
    assert risk["max_risk_amount"] == 1.0
    assert risk["max_open_trades"] == 1 and risk["max_daily_loss_percent"] == 3
    assert risk["leverage_forex"] == 30 and risk["leverage_metal"] == 20
    assert risk["target_risk_reward"] == 2.0
    assert "oanda_api_key" not in str(body).lower()


def test_candles_endpoint(client, seeded):
    body = client.get("/api/candles", params={"limit": 10}).json()
    assert body["count"] == 10
    times = [c["time"] for c in body["candles"]]
    assert times == sorted(times)
    last = body["candles"][-1]
    assert last["time"].startswith(seeded["time"].iloc[-1].strftime("%Y-%m-%dT%H:%M:%S"))
    assert last["spread_pips"] == pytest.approx(0.8)


def test_candles_rejects_bad_params(client):
    btc = client.get("/api/candles", params={"instrument": "BTC_USD"})
    assert btc.status_code == 400 and "crypto" in btc.json()["detail"]
    assert client.get("/api/candles", params={"instrument": "AAPL"}).status_code == 400
    assert client.get("/api/candles", params={"granularity": "W"}).status_code == 400
    assert client.get("/api/candles", params={"limit": 0}).status_code == 422


def test_data_summary(client, seeded):
    body = client.get("/api/data/summary").json()
    assert body["candles"] == len(seeded)
    assert body["sources"] == ["fake"]
    assert body["first_time"].startswith("2024-03-04T00:00:00")


def test_validation_run_and_fetch(client, seeded):
    ran = client.post("/api/data/validation").json()
    assert ran["status"] == "PASS"
    saved = client.get("/api/data/validation").json()
    assert saved["rows"] == len(seeded)
    assert client.get("/api/data/summary").json()["last_validation_status"] == "PASS"


def test_instruments_endpoint(client, seeded, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("INSTRUMENTS", "EUR_USD,xau/usd,USDJPY")
    get_settings.cache_clear()
    try:
        body = client.get("/api/instruments").json()
    finally:
        get_settings.cache_clear()
    assert [i["name"] for i in body] == ["EUR_USD", "XAU_USD", "USD_JPY"]
    eur, gold, jpy = body
    assert eur["candles"] == len(seeded) and eur["display_precision"] == 5
    assert gold["asset_class"] == "metal" and gold["pip_size"] == 0.01 and gold["unit_label"] == "oz"
    assert gold["candles"] == 0 and gold["description"] == "Gold / US Dollar"
    assert jpy["pip_size"] == 0.01 and jpy["display_precision"] == 3


def test_candles_accept_any_supported_instrument(client, repo):
    df = make_candles("2024-03-04", "2024-03-05", instrument="XAU_USD")
    repo.upsert_candles("XAU_USD", "M15", to_candle_dicts(df), source="fake")
    body = client.get("/api/candles", params={"instrument": "xau/usd", "limit": 3}).json()
    assert body["instrument"] == "XAU_USD" and body["count"] == 3
    assert body["candles"][-1]["spread_pips"] == 30.0  # $0.30 spread = 30 gold pips


def test_risk_preview(client, repo):
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-03-04", "2024-03-09")), source="fake")
    body = client.get("/api/risk/preview", params={"instrument": "EUR_USD"}).json()
    assert body["direction"] == "BUY" and body["units"] > 0
    assert body["risk_amount"] <= 1.0 and body["margin_required"] <= 50
    assert body["limited_by"] == "risk"  # beginner defaults: the 1% loss limit sets the size
    assert body["risk_reward"] == pytest.approx(2.0)
    assert body["take_profit"] > body["entry"] > body["stop_loss"]
    assert client.get("/api/risk/preview", params={"instrument": "GBP_USD"}).status_code == 404


def test_indicators_endpoint(client, repo):
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-01-08", "2024-02-24")), source="fake")
    body = client.get("/api/indicators", params={"instrument": "EUR_USD"}).json()
    assert 0 <= body["rsi_14"] <= 100
    assert body["trend"] in ("Uptrend", "Downtrend", "Sideways / mixed")
    assert body["volatility"] in ("Low", "Normal", "High")
    assert body["atr_pips"] > 0 and body["ema200"] is not None
    assert body["macd_hist"] == pytest.approx(body["macd"] - body["macd_signal"])
    assert client.get("/api/indicators", params={"instrument": "NZD_USD"}).status_code == 404


def test_model_endpoint(client, tmp_path, monkeypatch):
    import json as _json

    from app.core.config import get_settings

    settings = get_settings()
    assert client.get("/api/model").status_code in (200, 404)
    version_dir = settings.models_dir / "v-test"
    version_dir.mkdir(parents=True, exist_ok=True)
    stats = {"trades": 300, "expectancy_r": -0.1, "lower_bound_r": -0.2, "win_rate": 0.3, "profit_factor": 0.8,
             "total_r": -30.0}
    report = {
        "version": "v-test", "created_at": "2026-09-23T00:00:00+00:00", "model": "xgboost", "deployable": False,
        "not_deployable_reasons": ["untouched test period mean -0.1 R is not positive"], "threshold": 0.35,
        "instruments": ["EUR_USD"], "periods": {}, "target": {"horizon": 16},
        "test": {**stats, "by_instrument": {"EUR_USD": stats},
                 "classification": {"log_loss": 0.9, "log_loss_baseline": 0.95}},
        "comparison": {"xgboost": {"threshold": 0.35, "validation": {"chosen": stats, "classification": {
            "log_loss": 0.85, "log_loss_baseline": 0.9}}, "walk_forward": {**stats, "positive_fold_share": 0.4}}},
        "feature_importance": {"hour_sin": 0.2, "rsi_14": 0.1},
    }
    (version_dir / "report.json").write_text(_json.dumps(report))
    (settings.models_dir / "current.json").write_text(_json.dumps({"version": "v-test"}))
    body = client.get("/api/model").json()
    assert body["deployable"] is False and body["model"] == "xgboost"
    assert body["test"]["expectancy_r"] == -0.1
    assert body["comparison"]["xgboost"]["walk_forward"]["positive_fold_share"] == 0.4


def test_backtest_endpoint(client):
    import json as _json

    from app.core.config import get_settings

    settings = get_settings()
    folder = settings.models_dir / "v-bt"
    folder.mkdir(parents=True, exist_ok=True)
    (settings.models_dir / "current.json").write_text(_json.dumps({"version": "v-bt"}))
    (folder / "backtest_test.json").write_text(_json.dumps({
        "version": "v-bt", "period": "test", "metrics": {"trades": 2, "final_balance": 101.0}}))
    pd.DataFrame({"time": ["2025-07-01T10:00:00Z", "2025-07-02T10:00:00Z"], "balance": [99.0, 101.0],
                  "drawdown_pct": [-1.0, 0.0]}).to_csv(folder / "backtest_test_equity.csv", index=False)
    pd.DataFrame({"entry_time": ["a", "b"], "pnl": [-1.0, 2.0], "pips": [float("nan"), 30.0]}).to_csv(
        folder / "backtest_test_trades.csv", index=False)
    body = client.get("/api/backtest").json()
    assert body["metrics"]["final_balance"] == 101.0 and body["available_periods"] == ["test"]
    assert [p["balance"] for p in body["equity"]] == [99.0, 101.0]
    assert body["trades"][0]["pnl"] == 2.0 and body["trades"][1]["pips"] is None  # newest first, NaN -> null
    assert client.get("/api/backtest", params={"period": "walk_forward"}).status_code == 404
    assert client.get("/api/backtest", params={"period": "bogus"}).status_code == 422


def _actionable_signal(db, **kw):
    from datetime import datetime, timedelta, timezone

    from app.database.models import Signal

    now = datetime.now(timezone.utc)
    fields = dict(instrument="EUR_USD", granularity="M15", candle_time=now.replace(microsecond=0) - timedelta(minutes=15),
                  mode="practice", model_decision="BUY", decision="BUY", entry=1.10000, stop_loss=1.09850,
                  take_profit=1.10300, atr=0.001, units=666, risk_amount=1.0, status="actionable",
                  expires_at=now + timedelta(minutes=10))
    fields.update(kw)
    sig = Signal(**fields)
    db.add(sig)
    db.commit()
    return sig


def test_coach_flow_endpoints(client, db_session):
    sig = _actionable_signal(db_session)
    assert client.get("/api/signals/latest", params={"instrument": "EUR_USD"}).json()["id"] == sig.id
    assert client.get("/api/signals", params={"only_trades": True}).json()[0]["decision"] == "BUY"

    bad = client.post(f"/api/signals/{sig.id}/take", json={"fill_price": 1.2})
    assert bad.status_code == 400 and "pips away" in bad.json()["detail"]
    trade = client.post(f"/api/signals/{sig.id}/take", json={"fill_price": 1.10010}).json()
    assert trade["status"] == "open" and trade["stop_loss"] == pytest.approx(1.09850)  # the signal's own stop
    assert [t["id"] for t in client.get("/api/trades").json()] == [trade["id"]]

    closed = client.post(f"/api/trades/{trade['id']}/close", json={"exit_price": 1.10310}).json()
    assert closed["status"] == "closed" and closed["pnl"] > 1.9
    stats = client.get("/api/coach/stats").json()
    assert stats["your_trades"]["closed"] == 1 and stats["balance"] > 101.9
    assert client.post(f"/api/trades/{trade['id']}/close", json={"exit_price": 1.1}).status_code == 400


def test_skip_signal_endpoint(client, db_session):
    sig = _actionable_signal(db_session)
    assert client.post(f"/api/signals/{sig.id}/skip").json()["status"] == "skipped"
    assert client.post(f"/api/signals/{sig.id}/take", json={"fill_price": 1.1}).status_code == 400


def test_websocket_snapshot(client, db_session):
    with client.websocket_connect("/api/ws") as ws:
        msg = ws.receive_json()
    assert msg["event"] == "snapshot"
    assert msg["data"]["coach_mode"] in ("practice", "proven")
    assert msg["data"]["open_trades"] == [] and msg["data"]["stats"]["balance"] == 100


def test_live_status_when_disabled(client):
    body = client.get("/api/live/status").json()
    assert body["running"] is False and "disabled" in body["message"]


def test_chart_endpoint(client, repo, db_session):
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-01-08", "2024-02-24")), source="fake")
    last = make_candles("2024-01-08", "2024-02-24")["time"].iloc[-1].to_pydatetime()
    _actionable_signal(db_session, candle_time=last)
    body = client.get("/api/chart", params={"instrument": "EUR_USD", "limit": 300}).json()
    assert len(body["candles"]) == 300 and body["display_precision"] == 5
    times = [c["time"] for c in body["candles"]]
    assert times == sorted(times) and isinstance(times[0], int)  # unix seconds, ascending
    assert len(body["ema200"]) == 300 and body["ema20"][-1]["value"] > 0
    assert body["signals"][0]["decision"] == "BUY" and body["signals"][0]["time"] == times[-1]
    assert client.get("/api/chart", params={"instrument": "NZD_USD"}).status_code == 404


def test_current_signals_covers_whole_watchlist(client, db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("INSTRUMENTS", "EUR_USD,GBP_USD")
    get_settings.cache_clear()
    try:
        _actionable_signal(db_session)  # EUR_USD BUY
        body = client.get("/api/signals/current").json()
    finally:
        get_settings.cache_clear()
    assert [s["instrument"] for s in body] == ["EUR_USD", "GBP_USD"]
    assert body[0]["decision"] == "BUY" and body[1]["decision"] is None  # no signal yet for GBP/USD
