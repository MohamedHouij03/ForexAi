from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.data.twelvedata_client import (
    MAX_OUTPUTSIZE,
    TwelveDataAuthError,
    TwelveDataClient,
    TwelveDataError,
    parse_bar,
    to_symbol,
)

NOW = datetime(2024, 3, 6, 10, 7, tzinfo=timezone.utc)
STEP = timedelta(minutes=15)


def bar(t: str, o="1.08500", h="1.08560", lo="1.08470", c="1.08530") -> dict:
    return {"datetime": t, "open": o, "high": h, "low": lo, "close": c}


def ok(values) -> httpx.Response:
    return httpx.Response(200, json={"meta": {"symbol": "EUR/USD"}, "values": values, "status": "ok"})


def make_client(handler, **kwargs) -> TwelveDataClient:
    kwargs.setdefault("sleep", lambda s: None)
    return TwelveDataClient("td-key", transport=httpx.MockTransport(handler), now=lambda: NOW, **kwargs)


def test_symbol_mapping():
    assert to_symbol("EUR_USD") == "EUR/USD"


def test_parse_bar_mid_only_and_completeness():
    row = parse_bar(bar("2024-03-06 09:45:00"), step=STEP, now=NOW)
    assert row["time"] == datetime(2024, 3, 6, 9, 45, tzinfo=timezone.utc)
    assert (row["open"], row["high"], row["low"], row["close"]) == (1.085, 1.0856, 1.0847, 1.0853)
    assert row["bid_close"] is None and row["ask_close"] is None and row["spread"] is None
    assert row["volume"] is None
    assert row["complete"] is True  # 09:45 + 15m = 10:00 <= 10:07
    assert parse_bar(bar("2024-03-06 10:00:00"), step=STEP, now=NOW)["complete"] is False


def test_parse_bar_rejects_malformed():
    with pytest.raises(TwelveDataError):
        parse_bar({"datetime": "2024-03-06 09:45:00", "open": "x"}, step=STEP, now=NOW)


def test_fetch_page_request_and_window():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(request.url.params)
        return ok([bar("2024-01-01 00:00:00"), bar("2024-01-01 00:15:00")])

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with make_client(handler) as client:
        page = client.fetch_page("EUR_USD", "M15", start)

    assert seen["symbol"] == "EUR/USD"
    assert seen["interval"] == "15min"
    assert seen["timezone"] == "UTC"
    assert seen["order"] == "asc"
    assert seen["outputsize"] == str(MAX_OUTPUTSIZE)
    assert seen["apikey"] == "td-key"
    assert seen["start_date"] == "2024-01-01 00:00:00"
    # window never exceeds MAX_OUTPUTSIZE slots (end_date is inclusive)
    window_end = start + STEP * (MAX_OUTPUTSIZE - 1)
    assert seen["end_date"] == window_end.strftime("%Y-%m-%d %H:%M:%S")
    assert [c["time"].minute for c in page.candles] == [0, 15]
    assert page.next_from == window_end


def test_fetch_page_excludes_window_end_bar():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_bar = (start + STEP * (MAX_OUTPUTSIZE - 1)).strftime("%Y-%m-%d %H:%M:%S")
    with make_client(lambda r: ok([bar("2024-01-01 00:00:00"), bar(end_bar)])) as client:
        page = client.fetch_page("EUR_USD", "M15", start)
    assert len(page.candles) == 1  # the end bar is fetched again as the first bar of the next page


def test_last_page_reaches_live_edge():
    start = datetime(2024, 3, 5, tzinfo=timezone.utc)
    with make_client(lambda r: ok([bar("2024-03-06 09:45:00"), bar("2024-03-06 10:00:00")])) as client:
        page = client.fetch_page("EUR_USD", "M15", start)
    assert page.next_from is None
    assert [c["complete"] for c in page.candles] == [True, False]


def test_no_data_window_is_empty_page():
    def handler(request):
        return httpx.Response(400, json={"code": 400, "status": "error",
                                         "message": "No data is available on the specified dates."})

    with make_client(handler) as client:
        page = client.fetch_page("EUR_USD", "M15", datetime(2024, 1, 1, tzinfo=timezone.utc))
    assert page.candles == [] and page.next_from is not None


def test_invalid_key_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"code": 401, "status": "error", "message": "**apikey** parameter is incorrect"})

    with make_client(handler) as client:
        with pytest.raises(TwelveDataAuthError, match="apikey"):
            client.api_usage()


def test_minute_rate_limit_waits_and_retries():
    sleeps = []
    responses = iter([
        httpx.Response(200, json={"code": 429, "status": "error",
                                  "message": "You have run out of API credits for the current minute."}),
        httpx.Response(200, json={"current_usage": 1, "plan_limit": 8}),
    ])
    with make_client(lambda r: next(responses), sleep=sleeps.append) as client:
        assert client.api_usage()["plan_limit"] == 8
    assert any(s >= 60 for s in sleeps)


def test_daily_limit_is_not_retried():
    def handler(request):
        return httpx.Response(429, json={"code": 429, "status": "error",
                                         "message": "You have run out of API credits for the day."})

    with make_client(handler) as client:
        with pytest.raises(TwelveDataError, match="daily"):
            client.api_usage()


def test_throttle_spaces_requests():
    clock = {"t": 0.0}
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        clock["t"] += s

    client = make_client(lambda r: httpx.Response(200, json={}), requests_per_minute=8,
                         sleep=fake_sleep, clock=lambda: clock["t"])
    with client:
        client.api_usage()
        client.api_usage()
        client.api_usage()
    assert sleeps == [pytest.approx(60 / 7), pytest.approx(60 / 7)]  # never 9 requests in one clock minute


def test_earliest_time():
    with make_client(lambda r: httpx.Response(200, json={"datetime": "2020-01-30 18:00:00", "unix_time": 1})) as client:
        assert client.earliest_time("EUR_USD", "M15") == datetime(2020, 1, 30, 18, tzinfo=timezone.utc)


def test_empty_key_rejected():
    with pytest.raises(TwelveDataAuthError):
        TwelveDataClient("")


def test_latest_price():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"price": "158.77600"})

    with make_client(handler) as client:
        assert client.latest_price("USD_JPY") == 158.776
    assert seen["symbol"] == "USD/JPY"
