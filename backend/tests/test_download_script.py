"""End-to-end: training/download_data.py against a mock OANDA v20 HTTP API."""

import json

import httpx
import pandas as pd
import pytest

from app.core.config import get_settings
from app.data import oanda_client
from app.data.oanda_client import parse_oanda_time
from app.data.storage import dataset_path, load_parquet
from tests.conftest import make_candles, to_candle_dicts
from training import download_data


def to_oanda_json(row, complete=True) -> dict:
    block = lambda p: {k[0]: f"{row[p + k]:.5f}" for k in ("open", "high", "low", "close")}  # noqa: E731
    return {
        "complete": complete,
        "volume": int(row["volume"]),
        "time": row["time"].strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
        "mid": block(""), "bid": block("bid_"), "ask": block("ask_"),
    }


class MockOanda:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.candle_requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer practice-token"
        path = request.url.path
        if path == "/v3/accounts/101-001-1234567-001/summary":
            return httpx.Response(200, json={"account": {"id": "101-001-1234567-001", "currency": "USD"}})
        if path == "/v3/instruments/EUR_USD/candles":
            self.candle_requests += 1
            p = request.url.params
            assert p["price"] == "MBA" and p["granularity"] == "M15"
            start = pd.Timestamp(parse_oanda_time(p["from"]))
            page = self.df[self.df["time"] >= start].head(int(p["count"]))
            last_time = self.df["time"].iloc[-1]
            candles = [to_oanda_json(r, complete=r["time"] != last_time) for r in page.to_dict("records")]
            return httpx.Response(200, json={"instrument": "EUR_USD", "granularity": "M15", "candles": candles})
        return httpx.Response(404, json={"errorMessage": f"unknown path {path}"})


@pytest.fixture
def oanda_env(monkeypatch, db_session):
    monkeypatch.setenv("DATA_PROVIDER", "oanda")
    monkeypatch.setenv("OANDA_API_KEY", "practice-token")
    monkeypatch.setenv("OANDA_ACCOUNT_ID", "101-001-1234567-001")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def install_mock(monkeypatch, mock: MockOanda):
    real = oanda_client.OandaClient
    monkeypatch.setattr(
        download_data, "OandaClient",
        lambda *a, **k: real(*a, transport=httpx.MockTransport(mock), sleep=lambda s: None, **k),
    )


def test_download_script_end_to_end(monkeypatch, oanda_env, repo, capsys):
    df = make_candles("2024-03-04", "2024-03-30")
    mock = MockOanda(df)
    install_mock(monkeypatch, mock)

    code = download_data.main(["--start", "2024-03-01", "--end", "2024-04-01"])
    out = capsys.readouterr().out

    assert code == 0, out
    assert "STATUS: PASS" in out
    # The last candle is still forming ("complete": false) and must not be stored.
    assert repo.count("EUR_USD", "M15") == len(df) - 1

    settings = get_settings()
    parquet = load_parquet(dataset_path(settings.data_dir, "EUR_USD", "M15"))
    assert len(parquet) == len(df) - 1
    assert parquet["time"].is_monotonic_increasing and not parquet["time"].duplicated().any()
    assert {"bid_close", "ask_close", "spread", "volume"} <= set(parquet.columns)

    report = json.loads((settings.reports_dir / "validation_EUR_USD_M15.json").read_text())
    assert report["status"] == "PASS"

    # Second run resumes from the latest stored candle instead of starting over.
    requests_before = mock.candle_requests
    assert download_data.main([]) == 0
    assert mock.candle_requests == requests_before + 1
    assert repo.count("EUR_USD", "M15") == len(df) - 1


def test_download_script_without_credentials(monkeypatch, db_session, capsys):
    get_settings.cache_clear()
    try:
        assert download_data.main(["--check"]) == 2
        assert "Twelve Data API key is not configured" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()


def test_download_script_bad_token(monkeypatch, oanda_env):
    install_mock(monkeypatch, lambda request: httpx.Response(401, json={"errorMessage": "Insufficient authorization"}))
    assert download_data.main(["--check"]) == 2


# ------------------------------------------------------------- Twelve Data
from app.data import twelvedata_client  # noqa: E402


class MockTwelveData:
    """Mimics Twelve Data: inclusive date range, newest `outputsize` bars, then sorted ascending."""

    def __init__(self, df: pd.DataFrame | dict[str, pd.DataFrame]):
        self.frames = df if isinstance(df, dict) else {"EUR/USD": df}
        self.series_requests = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        p = request.url.params
        assert p["apikey"] == "td-key"
        self.df = self.frames.get(p.get("symbol"), next(iter(self.frames.values())))
        if request.url.path == "/api_usage":
            return httpx.Response(200, json={"current_usage": 1, "plan_limit": 8, "plan_category": "basic"})
        if request.url.path == "/earliest_timestamp":
            return httpx.Response(200, json={"datetime": self.df["time"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")})
        if request.url.path == "/time_series":
            self.series_requests += 1
            assert p["timezone"] == "UTC" and p["interval"] == "15min" and p["symbol"] in self.frames
            start, end = (pd.Timestamp(p[k], tz="UTC") for k in ("start_date", "end_date"))
            sel = self.df[(self.df["time"] >= start) & (self.df["time"] <= end)].tail(int(p["outputsize"]))
            if sel.empty:
                return httpx.Response(400, json={"code": 400, "status": "error",
                                                 "message": "No data is available on the specified dates."})
            values = [{"datetime": r["time"].strftime("%Y-%m-%d %H:%M:%S"),
                       **{k: f"{r[k]:.5f}" for k in ("open", "high", "low", "close")}}
                      for r in sel.to_dict("records")]
            return httpx.Response(200, json={"meta": {}, "values": values, "status": "ok"})
        return httpx.Response(404, json={"code": 404, "status": "error", "message": "not found"})


@pytest.fixture
def twelvedata_env(monkeypatch, db_session):
    monkeypatch.setenv("DATA_PROVIDER", "twelvedata")
    monkeypatch.setenv("TWELVEDATA_API_KEY", "td-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def install_twelvedata_mock(monkeypatch, mock):
    real = twelvedata_client.TwelveDataClient
    monkeypatch.setattr(
        download_data, "TwelveDataClient",
        lambda *a, **k: real(*a, transport=httpx.MockTransport(mock), sleep=lambda s: None, **k),
    )


def test_twelvedata_download_end_to_end(monkeypatch, twelvedata_env, repo, capsys):
    # 5 months: needs several 52-day windows, including window boundaries
    df = make_candles("2024-01-08", "2024-06-01")
    mock = MockTwelveData(df)
    install_twelvedata_mock(monkeypatch, mock)

    # Start before the provider's history -> clamped to earliest_timestamp
    code = download_data.main(["--start", "2023-01-01", "--end", "2024-06-02"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "STATUS: PASS" in out
    assert "(no bid/ask)" in out

    assert repo.count("EUR_USD", "M15") == len(df)
    assert repo.sources("EUR_USD", "M15") == {"twelvedata"}
    stored = repo.load_dataframe("EUR_USD", "M15")
    assert not stored["time"].duplicated().any()
    pd.testing.assert_series_equal(stored["close"], df["close"].astype(float), check_names=False)
    assert mock.series_requests == 3  # ~145 days / 52-day windows


def test_refuses_to_mix_providers(monkeypatch, twelvedata_env, repo):
    repo.upsert_candles("EUR_USD", "M15", to_candle_dicts(make_candles("2024-01-08", "2024-01-08 01:00")),
                        source="oanda")
    install_twelvedata_mock(monkeypatch, MockTwelveData(make_candles("2024-01-08", "2024-01-20")))
    assert download_data.main(["--end", "2024-01-20"]) == 2
    assert repo.sources("EUR_USD", "M15") == {"oanda"}

    assert download_data.main(["--replace", "--start", "2024-01-08", "--end", "2024-01-20"]) == 0
    assert repo.sources("EUR_USD", "M15") == {"twelvedata"}


def test_multiple_instruments_in_one_run(monkeypatch, twelvedata_env, repo, capsys):
    frames = {
        "EUR/USD": make_candles("2024-07-08", "2024-07-20"),
        "XAU/USD": make_candles("2024-07-08", "2024-07-20", instrument="XAU_USD"),
    }
    install_twelvedata_mock(monkeypatch, MockTwelveData(frames))
    code = download_data.main(["-i", "eur/usd,XAU_USD", "--start", "2024-07-01", "--end", "2024-07-21"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert repo.count("EUR_USD", "M15") == len(frames["EUR/USD"])
    assert repo.count("XAU_USD", "M15") == len(frames["XAU/USD"])
    assert "SUMMARY" in out and "XAU_USD" in out
    assert out.count("STATUS: PASS") == 2


def test_crypto_instrument_refused(twelvedata_env, capsys):
    assert download_data.main(["-i", "BTC_USD"]) == 2
    assert "crypto" in capsys.readouterr().err
