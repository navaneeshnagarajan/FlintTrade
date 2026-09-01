"""OpenAlgo v2.0.2.2 REST method/payload contracts for OpenAlgoClient.

Grounded in the public tagged release
``openalgo-eventlet-stability-security``
(commit ef1f6b9c2165607ae4c01edb9a3e189e26596d4d).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from flinttrade_core.config import Settings
from flinttrade_core.openalgo_client import OpenAlgoClient


def _client() -> OpenAlgoClient:
    return OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test-key")
    )


@pytest.mark.asyncio
async def test_option_chain_posts_underlying_and_ddmmmyy_expiry_without_unknown_fields() -> None:
    """OptionChainSchema accepts underlying + expiry_date (DDMMMYY), not symbol/expiry."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": {
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "expiry_date": "26MAR26",
                "underlying_ltp": 24050.0,
                "chain": [
                    {"strike": 24000.0, "ce": {"ltp": 150}, "pe": {"ltp": 120}},
                ],
            },
        }
    )

    try:
        await client.option_chain("NIFTY", "NSE_INDEX", "2026-03-26")
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "optionchain"
    assert payload["underlying"] == "NIFTY"
    assert payload["exchange"] == "NSE_INDEX"
    assert payload["expiry_date"] == "26MAR26"
    assert "symbol" not in payload
    assert "expiry" not in payload


@pytest.mark.asyncio
async def test_synthetic_future_posts_underlying_not_symbol() -> None:
    """SyntheticFutureSchema requires underlying, not symbol."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "synthetic_future_price": 26015.25}
    )

    try:
        await client.synthetic_future("NIFTY", "NSE_INDEX", "26MAR26")
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "syntheticfuture"
    assert payload["underlying"] == "NIFTY"
    assert payload["exchange"] == "NSE_INDEX"
    assert payload["expiry_date"] == "26MAR26"
    assert "symbol" not in payload


@pytest.mark.asyncio
async def test_modify_order_includes_required_disclosed_quantity_and_trigger_price() -> None:
    """ModifyOrderSchema requires disclosed_quantity and trigger_price."""
    from flinttrade_core.models import ModifyOrder

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "123"}
    )

    try:
        await client.modify_order(ModifyOrder(orderid="123", symbol="RELIANCE", price="2550"))
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "modifyorder"
    assert "disclosed_quantity" in payload
    assert "trigger_price" in payload


@pytest.mark.asyncio
async def test_place_order_omits_undeclared_market_protection() -> None:
    """OrderSchema in v2.0.2.2 does not declare market_protection (unknown raises)."""
    from flinttrade_core.models import Action, Order

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "OID-1"}
    )

    try:
        await client.place_order(
            Order(symbol="RELIANCE", action=Action.BUY, market_protection=True)
        )
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "placeorder"
    assert "market_protection" not in payload


@pytest.mark.asyncio
async def test_intervals_posts_apikey_and_returns_bucketed_data() -> None:
    """Intervals is POST /api/v1/intervals and returns seconds/minutes/... buckets."""
    buckets = {
        "seconds": ["1s"],
        "minutes": ["1m", "5m"],
        "hours": ["1h"],
        "days": ["D"],
        "weeks": ["W"],
        "months": ["M"],
    }
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": buckets}
    )
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": ["1m", "5m"]}
    )

    try:
        result = await client.intervals()
    finally:
        await client.close()

    assert client._post.await_count == 1
    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "intervals"
    assert payload["apikey"] == "test-key"
    assert result == buckets


@pytest.mark.asyncio
async def test_instruments_gets_apikey_and_exchange_as_query() -> None:
    """Instruments is GET /api/v1/instruments with apikey and optional exchange query."""
    client = _client()
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": []}
    )
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "error", "message": "should not POST"}
    )

    try:
        await client.instruments("NFO")
    finally:
        await client.close()

    assert client._get.await_count == 1
    assert client._post.await_count == 0
    assert client._get.await_args.args[0] == "instruments"
    params = client._get.await_args.kwargs["params"]
    assert params["apikey"] == "test-key"
    assert params["exchange"] == "NFO"


@pytest.mark.asyncio
async def test_timings_posts_market_timings_with_date() -> None:
    """Timings is POST /api/v1/market/timings with apikey and date."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": {}}
    )
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "error", "message": "should not GET"}
    )

    try:
        await client.timings("2026-08-29")
    finally:
        await client.close()

    assert client._post.await_count == 1
    assert client._get.await_count == 0
    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "market/timings"
    assert payload["apikey"] == "test-key"
    assert payload["date"] == "2026-08-29"


@pytest.mark.asyncio
async def test_ticker_uses_apikey_query_and_from_to_dates() -> None:
    """Ticker GET authenticates with apikey query and HistorySchema from/to dates."""
    client = _client()
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": []}
    )

    try:
        await client.ticker(
            "NSE",
            "RELIANCE",
            interval="5m",
            from_date="2026-08-01",
            to_date="2026-08-29",
        )
    finally:
        await client.close()

    assert client._get.await_args.args[0] == "ticker/NSE:RELIANCE"
    params = client._get.await_args.kwargs["params"]
    assert params["apikey"] == "test-key"
    assert params["interval"] == "5m"
    assert params["from"] == "2026-08-01"
    assert params["to"] == "2026-08-29"
    headers = client._get.await_args.kwargs.get("headers") or {}
    assert not any(name.lower() in {"x-api-key", "x-api_key"} for name in headers)


@pytest.mark.asyncio
async def test_telegram_posts_notify_with_username_and_message() -> None:
    """Telegram notify is POST /api/v1/telegram/notify with username and message."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success"}
    )

    try:
        await client.telegram("hello", username="trader1")
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "telegram/notify"
    assert payload["username"] == "trader1"
    assert payload["message"] == "hello"
