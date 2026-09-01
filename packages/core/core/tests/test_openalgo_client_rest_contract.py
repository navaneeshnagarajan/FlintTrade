"""OpenAlgo v2.0.2.2 REST method/payload contracts for OpenAlgoClient.

Grounded in the public tagged release
``openalgo-eventlet-stability-security``
(commit ef1f6b9c2165607ae4c01edb9a3e189e26596d4d).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
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
async def test_option_chain_refuses_empty_expiry_without_posting() -> None:
    """OptionChainSchema requires nonempty expiry_date; do not emit a partial body."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": {}}
    )

    try:
        with pytest.raises(ValueError, match="expiry_date is required"):
            await client.option_chain("NIFTY", "NSE_INDEX", "")
    finally:
        await client.close()

    client._post.assert_not_awaited()


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
async def test_synthetic_future_refuses_empty_expiry_without_posting() -> None:
    """SyntheticFutureSchema requires expiry_date; do not emit a partial body."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "synthetic_future_price": 26015.25}
    )

    try:
        with pytest.raises(ValueError, match="expiry_date is required"):
            await client.synthetic_future("NIFTY", "NSE_INDEX", "")
    finally:
        await client.close()

    client._post.assert_not_awaited()


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
async def test_modify_order_refuses_stop_loss_without_positive_trigger() -> None:
    """SL/SL-M modify must not POST a manufactured zero trigger."""
    from flinttrade_core.models import ModifyOrder, PriceType

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "123"}
    )

    try:
        with pytest.raises(ValueError, match="trigger_price"):
            await client.modify_order(
                ModifyOrder(
                    orderid="123",
                    symbol="RELIANCE",
                    pricetype=PriceType.SL,
                    trigger_price="0",
                )
            )
    finally:
        await client.close()

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_orderbook_preserves_trigger_and_disclosed_aliases() -> None:
    """Orderbook rows keep broker trigger/disclosure through camelCase aliases."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "orderid": "OA-SL",
                    "status": "open",
                    "symbol": "RELIANCE",
                    "pricetype": "SL",
                    "triggerPrice": "1490.5",
                    "disclosedQuantity": "25",
                }
            ],
        }
    )

    try:
        rows = await client.orderbook()
    finally:
        await client.close()

    assert len(rows) == 1
    assert rows[0].trigger_price == "1490.5"
    assert rows[0].disclosed_quantity == "25"


@pytest.mark.asyncio
async def test_orderbook_leaves_omitted_trigger_and_disclosed_blank() -> None:
    """Omitted broker trigger/disclosure must stay blank, not a synthesised zero."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "orderid": "OA-LIMIT",
                    "status": "open",
                    "symbol": "RELIANCE",
                    "pricetype": "LIMIT",
                }
            ],
        }
    )

    try:
        rows = await client.orderbook()
    finally:
        await client.close()

    assert len(rows) == 1
    assert rows[0].trigger_price == ""
    assert rows[0].disclosed_quantity == ""


@pytest.mark.asyncio
async def test_orderbook_rejects_malformed_row_instead_of_dropping_it() -> None:
    """A non-object row must fail the whole book so safety admission cannot undercount."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "orderid": "OA-LIMIT",
                    "status": "open",
                    "symbol": "RELIANCE",
                    "pricetype": "LIMIT",
                },
                "not-an-order",
            ],
        }
    )

    try:
        with pytest.raises(ValueError, match="orderbook row is not an object"):
            await client.orderbook()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_place_options_multi_order_puts_pricetype_product_on_legs() -> None:
    """OptionsMultiOrderSchema rejects unknown top-level pricetype/product."""
    from flinttrade_core.models import Action, OptionType, OptionsLeg, OptionsMultiOrder, PriceType, Product

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "OID-1"}
    )
    order = OptionsMultiOrder(
        underlying="NIFTY",
        expiry_date="26MAR26",
        pricetype=PriceType.MARKET,
        product=Product.NRML,
        legs=[
            OptionsLeg(offset="ATM", option_type=OptionType.CE, action=Action.BUY, quantity="65"),
            OptionsLeg(offset="ATM", option_type=OptionType.PE, action=Action.SELL, quantity="65"),
        ],
    )

    try:
        await client.place_options_multi_order(order)
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "optionsmultiorder"
    assert "pricetype" not in payload
    assert "product" not in payload
    assert payload["legs"][0]["pricetype"] == "MARKET"
    assert payload["legs"][0]["product"] == "NRML"
    assert payload["legs"][1]["pricetype"] == "MARKET"
    assert payload["legs"][1]["product"] == "NRML"


@pytest.mark.asyncio
async def test_place_order_refuses_unsupported_market_protection_without_posting() -> None:
    """v2.0.2.2 removed market_protection; fail closed instead of downgrading."""
    from flinttrade_core.models import Action, Order

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "OID-1"}
    )

    try:
        with pytest.raises(ValueError, match="market_protection is not supported"):
            await client.place_order(
                Order(symbol="RELIANCE", action=Action.BUY, market_protection=True)
            )
    finally:
        await client.close()

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_place_smart_order_refuses_unsupported_market_protection_without_posting() -> None:
    """Smart orders must not silently discard requested market protection either."""
    from flinttrade_core.models import Action, SmartOrder

    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "orderid": "OID-1"}
    )

    try:
        with pytest.raises(ValueError, match="market_protection is not supported"):
            await client.place_smart_order(
                SmartOrder(symbol="RELIANCE", action=Action.BUY, market_protection=True)
            )
    finally:
        await client.close()

    client._post.assert_not_awaited()


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
async def test_timings_refuses_empty_date_without_posting() -> None:
    """MarketTimingsSchema requires date; do not emit a partial body."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": {}}
    )

    try:
        with pytest.raises(ValueError, match="date is required"):
            await client.timings()
    finally:
        await client.close()

    client._post.assert_not_awaited()


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
async def test_ticker_refuses_missing_from_to_dates_without_getting() -> None:
    """HistorySchema requires from/to; do not emit a partial ticker query."""
    client = _client()
    client._get = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": []}
    )

    try:
        with pytest.raises(ValueError, match="from and to dates are required"):
            await client.ticker("NSE", "RELIANCE", interval="5m")
    finally:
        await client.close()

    client._get.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_telegram_refuses_empty_username_without_posting() -> None:
    """Official /telegram/notify rejects empty username; do not emit a partial body."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success"}
    )

    try:
        with pytest.raises(ValueError, match="username is required"):
            await client.telegram("hello")
    finally:
        await client.close()

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_uses_configured_username_for_existing_one_argument_callers() -> None:
    """Existing notification callers remain usable when the linked username is configured."""
    settings = Settings(
        openalgo_host="http://127.0.0.1",
        openalgo_api_key="test-key",
        openalgo_telegram_username="linked-trader",
    )
    client = OpenAlgoClient(settings)
    captured: dict[str, object] = {}

    class RecordingHttp:
        async def post(self, url: str, **kwargs: object) -> httpx.Response:
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return httpx.Response(200, json={"status": "success"})

        async def aclose(self) -> None:
            return None

    client._http = RecordingHttp()  # type: ignore[method-assign]

    try:
        await client.telegram("hello")
    finally:
        await client.close()

    assert captured["url"] == "http://127.0.0.1:5000/api/v1/telegram/notify"
    assert captured["json"] == {
        "apikey": "test-key",
        "username": "linked-trader",
        "message": "hello",
    }


@pytest.mark.asyncio
async def test_option_symbol_posts_underlying_not_symbol() -> None:
    """OptionSymbolSchema requires underlying, not symbol."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "symbol": "NIFTY26MAR2624000CE"}
    )

    try:
        await client.option_symbol(
            "NIFTY",
            exchange="NSE_INDEX",
            expiry_date="26MAR26",
            offset="ATM",
            option_type="CE",
        )
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "optionsymbol"
    assert payload["underlying"] == "NIFTY"
    assert payload["exchange"] == "NSE_INDEX"
    assert payload["expiry_date"] == "26MAR26"
    assert payload["offset"] == "ATM"
    assert payload["option_type"] == "CE"
    assert "symbol" not in payload


@pytest.mark.asyncio
async def test_option_symbol_refuses_empty_expiry_without_posting() -> None:
    """OptionSymbolSchema cannot derive expiry_date from a bare underlying."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success"}
    )

    try:
        with pytest.raises(ValueError, match="expiry_date is required"):
            await client.option_symbol("NIFTY", exchange="NSE_INDEX", offset="ATM")
    finally:
        await client.close()

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_option_symbol_refuses_numeric_offset_without_posting() -> None:
    """Official offset is ATM/ITMn/OTMn, not a numeric strike offset."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success"}
    )

    try:
        with pytest.raises(ValueError, match="offset"):
            await client.option_symbol(
                "NIFTY",
                exchange="NSE_INDEX",
                expiry_date="26MAR26",
            )
    finally:
        await client.close()

    client._post.assert_not_awaited()


@pytest.mark.asyncio
async def test_expiry_posts_required_instrumenttype() -> None:
    """ExpirySchema requires instrumenttype futures|options."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": ["26-MAR-26"]}
    )

    try:
        await client.expiry("NIFTY", "NFO", instrumenttype="options")
    finally:
        await client.close()

    endpoint, payload = client._post.await_args.args[:2]
    assert endpoint == "expiry"
    assert payload["symbol"] == "NIFTY"
    assert payload["exchange"] == "NFO"
    assert payload["instrumenttype"] == "options"


@pytest.mark.asyncio
async def test_expiry_refuses_missing_instrumenttype_without_posting() -> None:
    """Do not emit ExpirySchema without a derivable instrumenttype."""
    client = _client()
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={"status": "success", "data": []}
    )

    try:
        with pytest.raises(ValueError, match="instrumenttype is required"):
            await client.expiry("NIFTY", "NFO")
    finally:
        await client.close()

    client._post.assert_not_awaited()
