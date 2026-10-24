from datetime import datetime, timezone

import httpx
import pytest

from app.data.oanda_client import (
    OandaAuthError,
    OandaClient,
    OandaError,
    format_oanda_time,
    parse_candle,
    parse_oanda_time,
)

RAW_CANDLE = {
    "complete": True,
    "volume": 812,
    "time": "2024-03-04T10:15:00.000000000Z",
    "bid": {"o": "1.08501", "h": "1.08560", "l": "1.08470", "c": "1.08530"},
    "mid": {"o": "1.08508", "h": "1.08567", "l": "1.08477", "c": "1.08537"},
    "ask": {"o": "1.08515", "h": "1.08574", "l": "1.08484", "c": "1.08544"},
}


def make_client(handler, **kwargs) -> OandaClient:
    return OandaClient("test-token", "practice", transport=httpx.MockTransport(handler),
                       sleep=lambda s: None, **kwargs)


def test_parse_time_with_nanoseconds():
    assert parse_oanda_time("2024-03-04T10:15:00.000000000Z") == datetime(2024, 3, 4, 10, 15, tzinfo=timezone.utc)
    assert parse_oanda_time("2024-03-04T10:15:00.123456789Z").microsecond == 123456
    assert parse_oanda_time("2024-03-04T10:15:00Z").tzinfo == timezone.utc
    with pytest.raises(OandaError):
        parse_oanda_time("2024-03-04 10:15")


def test_format_time_requires_timezone():
    assert format_oanda_time(datetime(2024, 1, 1, tzinfo=timezone.utc)) == "2024-01-01T00:00:00.000000Z"
    with pytest.raises(ValueError):
        format_oanda_time(datetime(2024, 1, 1))


def test_parse_candle_keeps_mid_bid_ask_and_spread():
    row = parse_candle(RAW_CANDLE)
    assert row["time"] == datetime(2024, 3, 4, 10, 15, tzinfo=timezone.utc)
    assert (row["open"], row["high"], row["low"], row["close"]) == (1.08508, 1.08567, 1.08477, 1.08537)
    assert row["bid_close"] == 1.08530 and row["ask_close"] == 1.08544
    assert row["spread"] == pytest.approx(0.00014)
    assert row["volume"] == 812 and row["complete"] is True


def test_parse_candle_rejects_malformed():
    with pytest.raises(OandaError):
        parse_candle({"time": "2024-03-04T10:15:00.000000000Z", "volume": 1, "complete": True})


def test_get_candles_request_shape():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = request.url
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"instrument": "EUR_USD", "granularity": "M15", "candles": [RAW_CANDLE]})

    with make_client(handler) as client:
        candles = client.get_candles("EUR_USD", "M15", from_time=datetime(2024, 3, 4, tzinfo=timezone.utc), count=10)

    assert len(candles) == 1
    url = seen["url"]
    assert url.host == "api-fxpractice.oanda.com"
    assert url.path == "/v3/instruments/EUR_USD/candles"
    assert url.params["granularity"] == "M15"
    assert url.params["price"] == "MBA"
    assert url.params["count"] == "10"
    assert url.params["from"].startswith("2024-03-04T00:00:00")
    assert seen["auth"] == "Bearer test-token"


def test_count_limit_enforced():
    with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError):
            client.get_candles("EUR_USD", "M15", from_time=datetime(2024, 1, 1, tzinfo=timezone.utc), count=5001)


def test_auth_error_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"errorMessage": "Insufficient authorization to perform request."})

    with make_client(handler) as client:
        with pytest.raises(OandaAuthError, match="Insufficient authorization"):
            client.list_accounts()
    assert len(calls) == 1


def test_rate_limit_is_retried_then_succeeds():
    responses = iter([httpx.Response(429), httpx.Response(503), httpx.Response(200, json={"accounts": [{"id": "101-1"}]})])
    with make_client(lambda r: next(responses)) as client:
        assert client.list_accounts() == [{"id": "101-1"}]


def test_retries_exhausted_raises():
    with make_client(lambda r: httpx.Response(500, text="boom"), max_retries=2) as client:
        with pytest.raises(OandaError, match="500"):
            client.list_accounts()


def test_network_errors_are_retried():
    attempts = iter([httpx.ConnectError("down"), None])

    def handler(request):
        exc = next(attempts)
        if exc:
            raise exc
        return httpx.Response(200, json={"accounts": []})

    with make_client(handler) as client:
        assert client.list_accounts() == []


def test_empty_api_key_rejected():
    with pytest.raises(OandaAuthError):
        OandaClient("", "practice")
