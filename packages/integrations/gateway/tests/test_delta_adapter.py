"""Delta Exchange native adapter: signing, venue lock, gated writes, and v2 coverage."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from flinttrade_core.exceptions import BrokerError, CredentialsInvalid, UnsupportedCapabilityError
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
        (200, {"success": True, "result": [{"id": 1, "product_symbol": "BTCUSD", "size": 1, "state": "open"}]}),
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
        (200, {"success": True, "result": [{"id": 7, "product_symbol": "BTCUSD", "state": "open"}]}),
        (200, {"success": True, "result": {"success": True}}),
        (200, {"success": True, "result": []}),
    ])
    session = await adapter.login({"api_key": "key", "api_secret": _SECRET, "environment": "india_testnet"})
    summary = await adapter.cancel_all_orders(session, _router_token=ROUTER_TOKEN)
    assert summary == {
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
