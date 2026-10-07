"""Delta Exchange native adapter: signing, venue lock, gated writes, and v2 coverage."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from flinttrade_core.exceptions import BrokerError, CredentialsInvalid, UnsupportedCapabilityError
from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.models import Action, Exchange, Order, PriceType
from flinttrade_engine.safety import EmergencyWritePolicy, SafetyBypassError
from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers._base import ROUTER_TOKEN
from flinttrade_gateway.brokers.delta import DELTA_CAPABILITIES, DeltaAdapter
from flinttrade_gateway.brokers.delta_mapping import (
    ENDPOINTS,
    V2_ENDPOINTS,
    sign_request,
    to_place_payload,
)

pytestmark = pytest.mark.unit

_SECRET = "7b6f39dcf660ec1c7c664f612c60410a2bd0c258416b498bf0311f94228f"


def _order(**overrides: object) -> Order:
    payload = {
        "symbol": "CRYPTO:BTCUSD",
        "action": Action.BUY,
        "exchange": Exchange.CRYPTO,
        "pricetype": PriceType.LIMIT,
        "quantity": "2",
        "price": "59000",
    }
    payload.update(overrides)
    return Order(**payload)


class _ScriptedTransport:
    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], str]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: str) -> tuple[int, object]:
        self.calls.append((method, url, headers, body))
        if not self.responses:
            raise AssertionError(f"unexpected Delta call {method} {url}")
        return self.responses.pop(0)


def _adapter(responses: list[tuple[int, object]]) -> tuple[DeltaAdapter, _ScriptedTransport]:
    transport = _ScriptedTransport(responses)
    return DeltaAdapter(transport_factory=lambda: transport, clock=lambda: 1_700_000_000), transport


def _session_ok() -> tuple[int, dict]:
    return 200, {"success": True, "result": [{"asset_symbol": "USD", "available_balance": "10", "user_id": 42}]}


def _page(rows: list[dict], *, after: str | None = None) -> dict:
    return {"success": True, "result": rows, "meta": {"after": after, "before": None}}


@pytest.mark.asyncio
async def test_signature_matches_official_prehash_and_is_sent_verbatim() -> None:
    expected = hmac.new(
        _SECRET.encode(),
        b"GET1700000000/v2/wallet/balances",
        hashlib.sha256,
    ).hexdigest()
    assert sign_request(_SECRET, "GET", "1700000000", "/v2/wallet/balances", "", "") == expected
    adapter, transport = _adapter([_session_ok()])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    method, url, headers, body = transport.calls[0]
    assert method == "GET"
    assert url == "https://cdn-ind.testnet.deltaex.org/v2/wallet/balances"
    assert headers["signature"] == expected
    assert headers["api-key"] == "key"
    assert headers["User-Agent"] == "FlintTrade-delta-native"
    assert body == ""
    assert session.extra["environment"] == "india_testnet"
    assert session.extra["user_id"] == "42"
    assert session.extra["region"] == "india"


@pytest.mark.asyncio
async def test_login_refuses_missing_venue_and_unknown_venue() -> None:
    adapter, _transport = _adapter([])
    with pytest.raises(BrokerError, match="environment"):
        await adapter.login({"api_key": "key", "api_secret": "secret"})
    with pytest.raises(BrokerError, match="india_prod"):
        await adapter.login({"api_key": "key", "api_secret": "secret", "environment": "demo"})


@pytest.mark.asyncio
async def test_rejected_key_does_not_become_a_session() -> None:
    adapter, _transport = _adapter([(401, {"success": False, "error": {"code": "invalid_api_key"}})])
    with pytest.raises(CredentialsInvalid):
        await adapter.login({"api_key": "key", "api_secret": "secret", "environment": "global_prod"})


def test_place_payload_uses_contract_count_and_gtc_for_a_day_order() -> None:
    payload = to_place_payload(_order(validity="DAY"))
    assert payload == {
        "product_symbol": "BTCUSD",
        "size": 2,
        "side": "buy",
        "time_in_force": "gtc",
        "order_type": "limit_order",
        "limit_price": "59000",
    }


@pytest.mark.asyncio
async def test_place_order_is_router_gated_and_signs_the_compact_body() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": {"id": 99, "product_id": 27}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_prod"})
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, _order())
    order_id = await adapter.place_order(session, _order(), _router_token=ROUTER_TOKEN)
    assert order_id == "99"
    method, url, headers, body = transport.calls[1]
    assert method == "POST"
    assert url == "https://api.india.delta.exchange/v2/orders"
    assert body == (
        '{"product_symbol":"BTCUSD","size":2,"side":"buy","time_in_force":"gtc",'
        '"order_type":"limit_order","limit_price":"59000"}'
    )
    prehash = f"POST1700000000/v2/orders{body}"
    assert headers["signature"] == hmac.new(_SECRET.encode(), prehash.encode(), hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_cancel_looks_up_product_id_before_delete() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": {"id": 7, "product_id": 27, "state": "open"}}),
        (200, {"success": True, "result": {"id": 7, "state": "cancelled"}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_prod"})
    await adapter.cancel_order(session, "7", _router_token=ROUTER_TOKEN)
    assert transport.calls[1][0] == "GET"
    assert transport.calls[1][1].endswith("/v2/orders/7")
    assert transport.calls[2][0] == "DELETE"
    assert transport.calls[2][3] == '{"id":7,"product_id":27}'


@pytest.mark.asyncio
async def test_option_chain_uses_delta_expiry_form() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (
            200,
            {
                "success": True,
                "result": [
                    {
                        "symbol": "C-BTC-90000-310126",
                        "contract_type": "call_options",
                        "strike_price": "90000",
                        "spot_price": "89000",
                        "close": "1200",
                        "oi": "3",
                        "greeks": {"delta": "0.4", "gamma": "0", "theta": "0", "vega": "0", "iv": "0.5"},
                    }
                ],
            },
        ),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    chain = await adapter.option_chain(session, {"underlying": "BTC", "expiry_date": "2026-01-31"})
    assert chain.strikes[0].ce_instrument_id == "C-BTC-90000-310126"
    assert chain.strikes[0].ce_greeks_complete is True
    assert "expiry_date=31-01-2026" in transport.calls[1][1]
    assert "underlying_asset_symbols=BTC" in transport.calls[1][1]


@pytest.mark.asyncio
async def test_emergency_plan_uses_native_bulk_cancel_when_nothing_is_protected() -> None:
    adapter, _transport = _adapter([
        _session_ok(),
        (200, _page([{"id": 1, "product_symbol": "BTCUSD", "size": 1, "state": "open"}])),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=EmergencyWritePolicy(name="flatten", verbs=("cancel_all_orders",)),
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    assert plan.writes[0].verb == "cancel_all_orders"
    assert "cancel_all_orders" in plan.pending_verbs


def test_catalog_is_native_but_not_connectable() -> None:
    entry = BROKER_CATALOG["deltaexchange"]
    assert entry.native is True
    assert entry.connectable is False
    assert entry.sdk_pin is None
    assert entry.auth_methods[0].id == "api_key"
    assert "Live order-safety proof" in entry.native_connect_blockers
    assert entry.mcp is not None
    assert entry.mcp.trading_supported is False
    assert entry.mcp.docs_url == "https://mcp.delta.exchange/docs"


def test_v2_swagger_surface_is_addressable() -> None:
    names = [name for name, _method, _path in V2_ENDPOINTS]
    assert len(names) == len(set(names)) == 48
    assert set(ENDPOINTS) == set(names)
    assert ("place_order", "POST", "/v2/orders") in V2_ENDPOINTS
    assert ("close_all_positions", "POST", "/v2/positions/close_all") in V2_ENDPOINTS
    assert ("heartbeat_create", "POST", "/v2/heartbeat/create") in V2_ENDPOINTS
    assert DELTA_CAPABILITIES.bracket_order_native is True
    assert DELTA_CAPABILITIES.streaming_runtime_ready is True
    assert DELTA_CAPABILITIES.market_depth_runtime_ready is True


class _FakeSocket:
    def __init__(self, frames: list[str]) -> None:
        self.frames = frames
        self.sent: list[str] = []

    async def __aenter__(self) -> "_FakeSocket":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def send(self, text: str) -> None:
        self.sent.append(text)

    def __aiter__(self) -> "_FakeSocket":
        return self

    async def __anext__(self) -> str:
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)


@pytest.mark.asyncio
async def test_public_stream_subscribes_and_yields_ticker_ticks() -> None:
    socket = _FakeSocket([
        '{"type":"subscriptions"}',
        '{"type":"ticker","symbol":"BTCUSD","close":"100","volume":"2","quotes":{"best_bid":"99","best_ask":"101"}}',
    ])
    adapter, transport = _adapter([_session_ok()])
    adapter._socket_factory = lambda _url: socket
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    await adapter.subscribe(session, ["CRYPTO:BTCUSD"])
    ticks = [tick async for tick in adapter.stream(session)]
    assert ticks[0].symbol == "BTCUSD"
    assert ticks[0].ltp == 100
    assert ticks[0].bid == 99
    sent = transport.calls  # login only; socket is separate
    assert sent[0][0] == "GET"
    assert '"name": "ticker"' in socket.sent[0]
    assert "BTCUSD" in socket.sent[0]


@pytest.mark.asyncio
async def test_global_stream_refuses_undocumented_socket() -> None:
    adapter, _transport = _adapter([_session_ok()])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "global_prod"})
    await adapter.subscribe(session, ["BTCUSD"])
    with pytest.raises(UnsupportedCapabilityError, match="no documented websocket"):
        async for _tick in adapter.stream(session):
            pass


@pytest.mark.asyncio
async def test_deadman_arm_and_ack_are_router_gated() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": {"heartbeat_id": "flint-1"}}),
        (200, {"success": True, "result": {"ok": True}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(SafetyBypassError):
        await adapter.arm_deadman(session, heartbeat_id="flint-1", ttl_ms=5000)
    await adapter.arm_deadman(session, heartbeat_id="flint-1", ttl_ms=5000, _router_token=ROUTER_TOKEN)
    await adapter.acknowledge_deadman(session, _router_token=ROUTER_TOKEN)
    assert transport.calls[1][0] == "POST"
    assert transport.calls[1][1].endswith("/v2/heartbeat/create")
    assert '"action":"cancel_orders"' in transport.calls[1][3]
    assert transport.calls[2][3] == '{"heartbeat_id":"flint-1","ttl":5000}'


@pytest.mark.asyncio
async def test_deadman_ack_loop_stops_without_another_write() -> None:
    import asyncio

    from flinttrade_gateway.brokers.delta import run_deadman_acks

    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": {"heartbeat_id": "flint-1"}}),
        (200, {"success": True, "result": {"ok": True}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    await adapter.arm_deadman(session, heartbeat_id="flint-1", ttl_ms=5000, _router_token=ROUTER_TOKEN)
    stop = asyncio.Event()
    stop.set()
    before = len(transport.calls)
    await run_deadman_acks(adapter, session, interval_seconds=30, stop=stop, _router_token=ROUTER_TOKEN)
    assert len(transport.calls) == before


@pytest.mark.asyncio
async def test_candle_bounds_accept_iso_dates() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": [{"time": 1, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 3}]}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_prod"})
    candles = await adapter.historical(session, {
        "symbol": "BTCUSD",
        "interval": "1h",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
    })
    assert candles.bars[0].close == 2
    assert "start=1767225600" in transport.calls[1][1]
    assert "end=1767312000" in transport.calls[1][1]


def test_compact_public_ticker_uses_sy_and_d_rows() -> None:
    from flinttrade_gateway.brokers.delta_feed import parse_ticker_frame

    tick = parse_ticker_frame({
        "type": "v2/ticker",
        "sy": "BTCUSD",
        "ts": 1775801092453559,
        "d": [{"s": "BTCUSD", "m": "100.5", "ohlc": [90, 110, 80, 99]}],
    })
    assert tick is not None
    assert tick.symbol == "BTCUSD"
    assert tick.ltp == 99
    assert tick.exchange == "CRYPTO"


@pytest.mark.asyncio
async def test_bulk_cancel_readback_matches_dispatcher_summary() -> None:
    adapter, transport = _adapter([
        _session_ok(),
        (200, _page([{"id": 7, "product_symbol": "BTCUSD", "state": "open"}])),
        (200, {"success": True, "result": {"success": True}}),
        (200, _page([])),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    summary = await adapter.cancel_all_orders(session, _router_token=ROUTER_TOKEN)
    assert {key: summary[key] for key in ("errors", "total", "success", "order_ids")} == {
        "errors": [],
        "total": 1,
        "success": 1,
        "order_ids": ["7"],
    }
    assert isinstance(summary["success"], int)
    assert transport.calls[2][1].endswith("/v2/orders/all")


@pytest.mark.asyncio
async def test_reducing_plan_names_symbol_exchange_product_and_tag() -> None:
    adapter, _transport = _adapter([
        (200, {"success": True, "result": [{"asset_symbol": "USD", "available_balance": "10"}]}),
        (200, {"success": True, "result": [{"product_symbol": "BTCUSD", "size": 2}]}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=EmergencyWritePolicy(name="flatten", verbs=("exit_all_positions",)),
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    payload = plan.writes[0].payload
    assert payload["symbol"] == "BTCUSD"
    assert payload["exchange"] == "CRYPTO"
    assert payload["product"] == "NRML"
    assert str(payload["emergency_tag"]).startswith("fte-delta-")


def test_option_iv_comes_from_quote_fields() -> None:
    from flinttrade_gateway.brokers.delta_mapping import option_chain_from_tickers

    chain = option_chain_from_tickers(
        [{
            "symbol": "C-BTC-90000-310126",
            "strike_price": "90000",
            "greeks": {"delta": "0.4", "gamma": "0", "theta": "0", "vega": "0"},
            "quotes": {"ask_iv": "0.6", "bid_iv": "0.4"},
        }],
        underlying="BTC",
        expiry="2026-01-31",
    )
    strike = chain["strikes"][0]
    assert strike["ce_iv"] == 0.5
    assert strike["ce_greeks_complete"] is True


@pytest.mark.asyncio
async def test_reducing_order_sends_native_boolean_reduce_only() -> None:
    import json

    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": [{"product_symbol": "BTCUSD", "size": 2}]}),
        (200, {"success": True, "result": {"id": 99}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    order_id = await adapter.place_reducing_order(session, {
        "symbol": "BTCUSD", "exchange": "CRYPTO", "product": "NRML",
        "expected_position_size": 2, "size": 2, "emergency_tag": "fixture-exit",
    }, _router_token=ROUTER_TOKEN)
    body = json.loads(transport.calls[-1][3])
    assert body["reduce_only"] is True
    assert body["side"] == "sell"
    assert body["size"] == 2
    assert body["client_order_id"] == "fixture-exit"
    assert order_id == "99"  # Acknowledgement only, not a fill or closed position.


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("reduce_only", "false"), ("post_only", "true"), ("limit_price", "NaN"),
    ("cancel_orders_accepted", "true"), ("mmp", "arbitrary"), ("unknown_mutation", True),
])
async def test_native_create_refuses_invalid_wire_intent_before_transport(field: str, value: object) -> None:
    adapter, transport = _adapter([_session_ok(), (200, {"success": True, "result": {"id": 99}})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    body = {
        "product_symbol": "BTCUSD", "size": 10, "side": "buy", "order_type": "limit_order",
        "time_in_force": "gtc", "limit_price": "59000.50", field: value,
    }
    with pytest.raises(BrokerError):
        await adapter.exchange_call(session, "place_order", body=body, _router_token=ROUTER_TOKEN)
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_native_order_and_position_bracket_bodies_have_distinct_resource_shapes() -> None:
    import json

    adapter, transport = _adapter([
        _session_ok(), (200, {"success": True, "result": {"id": 99}}),
        (200, {"success": True, "result": {"id": 100}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerError):
        await adapter.exchange_call(session, "edit_bracket", body={
            "id": 99, "product_id": 27, "stop_loss_order": {"order_type": "market_order", "stop_price": "56000"},
        }, _router_token=ROUTER_TOKEN)
    await adapter.exchange_call(session, "edit_bracket", body={
        "id": "99", "product_id": "27", "bracket_stop_loss_price": "56000.00",
        "bracket_stop_loss_limit_price": "55000.50", "bracket_stop_trigger_method": "last_traded_price",
    }, _router_token=ROUTER_TOKEN)
    await adapter.exchange_call(session, "place_bracket", body={
        "product_id": "27", "stop_loss_order": {"order_type": "market_order", "trail_amount": "50.00"},
        "take_profit_order": {"order_type": "limit_order", "stop_price": "61000.00", "limit_price": "61000.50"},
    }, _router_token=ROUTER_TOKEN)
    assert len(transport.calls) == 3
    edited = json.loads(transport.calls[1][3])
    created = json.loads(transport.calls[2][3])
    assert transport.calls[1][0] == "PUT"
    assert transport.calls[2][0] == "POST"
    assert all(call[1].endswith("/v2/orders/bracket") for call in transport.calls[1:])
    assert edited["id"] == 99
    assert edited["product_id"] == created["product_id"] == 27
    assert edited["bracket_stop_loss_price"] == "56000.00"
    assert "stop_loss_order" not in edited
    assert created["stop_loss_order"]["trail_amount"] == "50.00"
    assert created["take_profit_order"]["limit_price"] == "61000.50"
    assert "id" not in created


@pytest.mark.asyncio
async def test_close_all_preserves_skipped_products_errors_and_acknowledgement_only_counts() -> None:
    from copy import deepcopy

    native = {"success": True, "result": {
        "skipped_products": [{"product_id": 27, "product_symbol": "BTCUSD",
                              "reason": "market_disrupted_cancel_only_mode"}],
        "orders": [{"id": 99, "product_id": 28, "state": "open"}],
        "errors": [{"product_id": 27, "error": {"code": "market_disrupted", "details": {"retry": False}}}],
    }}
    original = deepcopy(native)
    adapter, transport = _adapter([
        _session_ok(),
        (200, {"success": True, "result": [{"product_id": 27, "product_symbol": "BTCUSD", "size": 2},
                                            {"product_id": 28, "product_symbol": "ETHUSD", "size": -3}]}),
        (200, native),
        (200, {"success": True, "result": [{"product_id": 27, "product_symbol": "BTCUSD", "size": 2}]}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.exit_all_positions(session, _router_token=ROUTER_TOKEN)
    assert result["raw_response"] == original
    assert result["skipped_products"] == original["result"]["skipped_products"]
    assert result["native_errors"] == original["result"]["errors"]
    assert result["result_lists"]["orders"] == original["result"]["orders"]
    assert result["total"] == 2
    assert result["success"] == 1
    assert len(result["errors"]) == 1
    assert type(result["success"]) is int
    assert result["acknowledgement_only"] is True
    assert result["complete"] is False
    assert "closed" not in result and "flat" not in result
    result["skipped_products"][0]["reason"] = "changed"
    assert native == original
    assert transport.calls[2][0] == "POST"
    assert transport.calls[2][1].endswith("/v2/positions/close_all")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    None, "unknown", {}, {"success": "true"}, {"success": True, "result": {}},
    {"success": True, "result": {"opaque": "shape"}}, {"success": True, "result": [{}]},
])
async def test_unknown_bulk_outcome_is_not_success_even_when_order_disappears(outcome: object) -> None:
    adapter, _transport = _adapter([
        _session_ok(),
        (200, _page([{"id": 7, "product_symbol": "BTCUSD", "state": "open"}])),
        (200, outcome),
        (200, _page([])),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.cancel_all_orders(session, _router_token=ROUTER_TOKEN)
    assert result["success"] == 0
    assert result["total"] == len(result["errors"]) == 1
    assert result["complete"] is False
    assert result["raw_response"] == outcome
    assert result["order_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["order_book", "order_history", "trade_book"])
async def test_order_history_and_fills_follow_every_documented_cursor(method: str) -> None:
    from urllib.parse import parse_qs, urlsplit

    if method == "trade_book":
        rows = [{"id": 1, "order_id": 7, "product_symbol": "BTCUSD", "size": 1, "price": "59000.50"},
                {"id": 2, "order_id": 7, "product_symbol": "BTCUSD", "size": 2, "price": "59000.50"}]
    else:
        rows = [{"id": 1, "product_symbol": "BTCUSD", "size": 10, "unfilled_size": 2, "state": "open"},
                {"id": 2, "product_symbol": "BTCUSD", "size": 10, "unfilled_size": 10, "state": "pending"}]
    adapter, transport = _adapter([_session_ok(), (200, _page(rows[:1], after="opaque +/cursor")),
                                  (200, _page(rows[1:]))])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await getattr(adapter, method)(session)
    assert len(result) == 2
    assert len(transport.calls) == 3
    queries = [parse_qs(urlsplit(call[1]).query) for call in transport.calls[1:]]
    assert queries[1]["after"] == ["opaque +/cursor"]
    assert queries[0]["page_size"] == queries[1]["page_size"] == ["100"]
    if method == "order_book":
        assert queries[0]["states"] == queries[1]["states"] == ["open,pending"]
        assert result[1]["status"] == "PENDING"
        assert result[1]["attempt_state"] == "UNKNOWN"
    if method == "trade_book":
        assert [row["orderid"] for row in result] == ["7", "7"]
        assert [row["fill_id"] for row in result] == [1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["order_book", "order_history", "trade_book", "positions"])
@pytest.mark.parametrize("payload", [None, {}, {"success": True, "result": {}},
                                     {"success": True, "result": [None]}, {"success": True, "result": [{}]}])
async def test_malformed_or_missing_books_refuse_instead_of_empty_or_flat(method: str, payload: object) -> None:
    adapter, _transport = _adapter([_session_ok(), (200, payload)])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerReadResponseInvalid):
        await getattr(adapter, method)(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("meta", [None, {}, {"before": None}, {"after": []}, {"after": ""}])
async def test_missing_or_malformed_cursor_evidence_refuses_even_an_empty_book(meta: object) -> None:
    adapter, _transport = _adapter([_session_ok(), (200, {"success": True, "result": [], "meta": meta})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.order_book(session)


@pytest.mark.asyncio
async def test_repeated_cursor_or_duplicate_identity_is_not_a_complete_book() -> None:
    rows = [{"id": 7, "product_symbol": "BTCUSD", "size": 2, "state": "open"}]
    for pages in ([(_page(rows, after="repeat")), (_page([], after="repeat"))],
                  [(_page(rows, after="next")), (_page([{**rows[0], "size": 3}]))]):
        adapter, _transport = _adapter([_session_ok(), *[(200, page) for page in pages]])
        session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
        with pytest.raises(BrokerReadResponseInvalid):
            await adapter.order_book(session)


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [
    [{"product_symbol": "BTCUSD"}], [{"product_symbol": "BTCUSD", "size": 1.5}],
    [{"product_symbol": "BTCUSD", "size": 2}, {"product_symbol": "BTCUSD", "size": -2}],
    [{"product_symbol": "BTCUSD", "product_id": 27, "size": 2},
     {"product_symbol": "ETHUSD", "product_id": 27, "size": 2}],
    [{"product_symbol": "BTCUSD", "product_id": 27, "size": 2},
     {"product_symbol": "BTCUSD", "product_id": 28, "size": 2}],
])
async def test_positions_require_exact_signed_size_and_unambiguous_product_identity(rows: list[dict]) -> None:
    adapter, _transport = _adapter([_session_ok(), (200, {"success": True, "result": rows})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerReadResponseInvalid):
        await adapter.positions(session)


@pytest.mark.asyncio
async def test_signed_short_positions_and_explicit_flat_rows_remain_distinct() -> None:
    adapter, _transport = _adapter([_session_ok(), (200, {"success": True, "result": [
        {"product_symbol": "BTCUSD", "size": "-123456789012345678901234567890"},
        {"product_symbol": "ETHUSD", "size": "0"},
    ]})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.positions(session)
    assert len(result) == 1
    assert result[0]["quantity"] == "-123456789012345678901234567890"
    assert result[0]["quantity_unit"] == "contracts"


@pytest.mark.asyncio
async def test_incomplete_post_cancel_book_retains_outcome_but_never_claims_success() -> None:
    native = {"success": True}
    adapter, _transport = _adapter([
        _session_ok(), (200, _page([{"id": 7, "product_symbol": "BTCUSD", "state": "pending"}])),
        (200, native), (200, {"success": True, "result": []}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.cancel_all_orders(session, _router_token=ROUTER_TOKEN)
    assert result["raw_response"] == native
    assert result["total"] == len(result["errors"]) == 1
    assert result["success"] == 0
    assert result["readback_available"] is False
    assert result["complete"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [
    {"success": True, "result": {"skipped_products": "unrecognised"}},
    {"success": True, "result": {"errors": {"id": 7, "code": "rejected"}}},
    {"success": True, "result": {"errors": [{"id": 9, "error": "unmatched"}]}},
    {"success": True, "result": [{"id": 7, "errors": [{"code": "rejected"}]}]},
])
async def test_opaque_or_unmatched_native_failures_never_become_bulk_success(native: dict) -> None:
    adapter, _transport = _adapter([
        _session_ok(), (200, _page([{"id": 7, "product_symbol": "BTCUSD", "state": "pending"}])),
        (200, native), (200, _page([])),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.cancel_all_orders(session, _router_token=ROUTER_TOKEN)
    assert result["raw_response"] == native
    assert result["success"] == 0
    assert len(result["errors"]) == result["total"] == 1


@pytest.mark.asyncio
async def test_documented_opaque_fill_and_settlement_order_ids_are_preserved() -> None:
    rows = [{
        "id": "071b551365574d0aad99557931137dbd", "order_id": "12345678-1234-1234-1234-123456789abc",
        "fill_type": "settlement", "product_symbol": "BTCUSD", "product_id": 27, "size": "2",
        "price": "59000.50", "meta_data": {"order_size": "1", "order_unfilled_size": "0"},
    }]
    adapter, _transport = _adapter([_session_ok(), (200, _page(rows))])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.trade_book(session)
    assert result[0]["fill_id"] == rows[0]["id"]
    assert result[0]["orderid"] == rows[0]["order_id"]
    assert result[0]["quantity"] == "2"
    assert result[0]["native"] == rows[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"expected_position_size": 2.5}, {"quantity": 1},
                                       {"product_symbol": "ETHUSD"}, {"emergency_tag": "x" * 33}])
async def test_reducing_intent_conflicts_or_fractional_contract_context_refuse_before_write(changes: dict) -> None:
    adapter, transport = _adapter([
        _session_ok(), (200, {"success": True, "result": [{"product_symbol": "BTCUSD", "size": 2}]}),
        (200, {"success": True, "result": {"id": 99}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    intent = {"symbol": "BTCUSD", "exchange": "CRYPTO", "product": "NRML", "expected_position_size": 2,
              "size": 2, "emergency_tag": "fixture-exit", **changes}
    with pytest.raises(BrokerError):
        await adapter.place_reducing_order(session, intent, _router_token=ROUTER_TOKEN)
    assert all(call[0] == "GET" for call in transport.calls)


@pytest.mark.asyncio
async def test_modify_preserves_documented_native_trail_and_boolean_options() -> None:
    import json

    adapter, transport = _adapter([_session_ok(), (200, {"success": True, "result": {"id": 7}})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    await adapter.modify_order(session, "7", {
        "product_id": 27, "size": 10, "trail_amount": "50.00", "post_only": False, "mmp": "disabled",
    }, _router_token=ROUTER_TOKEN)
    body = json.loads(transport.calls[-1][3])
    assert body["trail_amount"] == "50.00"
    assert body["post_only"] is False
    assert body["mmp"] == "disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    {"success": True, "result": {"id": 99, "error": {"code": "rejected"}}},
    {"success": True, "error": {"code": "rejected"}, "result": {"id": 99}},
    {"success": True, "result": {"id": True}},
    {"result": {"id": 99}},
])
async def test_error_ids_or_missing_acknowledgement_never_become_placement_success(outcome: dict) -> None:
    adapter, _transport = _adapter([_session_ok(), (200, outcome)])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerError):
        await adapter.place_order(session, _order(), _router_token=ROUTER_TOKEN)


@pytest.mark.asyncio
@pytest.mark.parametrize("looked_up", [{"id": 7}, {"id": 8, "product_id": 27}, {"id": 7, "product_id": True}])
async def test_cancel_refuses_missing_or_conflicting_product_lookup_before_delete(looked_up: dict) -> None:
    adapter, transport = _adapter([
        _session_ok(), (200, {"success": True, "result": looked_up}),
        (200, {"success": True, "result": {"id": 7}}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(BrokerError):
        await adapter.cancel_order(session, "7", _router_token=ROUTER_TOKEN)
    assert all(call[0] == "GET" for call in transport.calls)


@pytest.mark.asyncio
async def test_explicit_native_conditional_intent_survives_actual_signed_wire_body() -> None:
    import json

    body = {
        "product_symbol": "BTCUSD", "size": 10, "side": "sell", "order_type": "limit_order",
        "limit_price": "59000.50", "time_in_force": "gtc", "reduce_only": True, "post_only": False,
        "client_order_id": "fixture-native", "stop_order_type": "take_profit_order", "stop_price": "61000.00",
        "stop_trigger_method": "spot_price", "bracket_stop_loss_price": "56000.00",
        "bracket_stop_loss_limit_price": "55000.50", "bracket_take_profit_limit_price": "62000.50",
        "bracket_stop_trigger_method": "last_traded_price",
    }
    adapter, transport = _adapter([_session_ok(), (200, {"success": True, "result": {"id": 99}})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    with pytest.raises(SafetyBypassError):
        await adapter.exchange_call(session, "place_order", body=body)
    await adapter.exchange_call(session, "place_order", body=body, _router_token=ROUTER_TOKEN)
    assert json.loads(transport.calls[-1][3]) == body
    assert json.loads(transport.calls[-1][3])["reduce_only"] is True
    assert json.loads(transport.calls[-1][3])["post_only"] is False
    assert len(transport.calls) == 2


@pytest.mark.asyncio
async def test_order_details_keeps_closed_without_remainder_unknown_and_preserves_native() -> None:
    row = {"id": 7, "product_symbol": "BTCUSD", "size": 10, "state": "closed", "reduce_only": True,
           "client_order_id": "fixture-intent", "cancellation_reason": "unknown_reason"}
    adapter, _transport = _adapter([_session_ok(), (200, {"success": True, "result": row})])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    result = await adapter.order_details(session, "7")
    assert result["native"] == row
    assert result["status"] == result["attempt_state"] == "UNKNOWN"
    assert result["quantity"] == "10"
    assert "filled_quantity" not in result and "remaining_quantity" not in result
