"""Tests for the IndMoney (INDstocks) adapter — fake HTTP transport + synthetic
WebSocket frames; no SDK, no network, no credentials needed."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import BrokerError, RateLimitError, SessionExpired
from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    EMERGENCY_INTENT_SOURCE,
    EmergencyBrokerTarget,
    EmergencyWritePolicy,
    GatedEmergencyBrokerDispatcher,
    SafetyBypassError,
    gate_broker_write,
    set_safety_gate_secret,
)
from flinttrade_gateway.brokers import indmoney_mapping as m
from flinttrade_gateway.brokers.indmoney import INDMONEY_CAPABILITIES, IndMoneyAdapter, _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

DOC_ORDER_BOOK = {
    "status": "success",
    "data": [
        {
            "id": "GTT-2914581", "name": "NIFTY 3 JUL 27400 CE", "security_id": "58757",
            "txn_type": "SELL", "exchange": "NSE", "segment": "DERIVATIVE", "product": "MARGIN",
            "order_type": "OCO", "traded_qty": 0, "requested_qty": 75, "requested_price": "",
            "sl_trigger_price": "0.3", "sl_limit_price": "0.2", "tgt_trigger_price": "0.75",
            "status": "CANCELLED", "extra_info": "",
        },
        {
            "id": "DRV-28131451", "name": "NIFTY 3 JUL 25700 CE", "security_id": "56998",
            "txn_type": "BUY", "exchange": "NSE", "segment": "DERIVATIVE", "product": "MARGIN",
            "order_type": "MARKET", "validity": "DAY", "traded_qty": 75, "requested_qty": 75,
            "requested_price": "43.55", "traded_price": "43.55", "sl_trigger_price": "",
            "tgt_trigger_price": "", "status": "SUCCESS", "extra_info": "",
        },
    ],
}


class FakeTransport:
    """Programmable stand-in for the httpx transport (records every call)."""

    def __init__(self, responses: dict | None = None):
        self.calls: list[dict] = []
        self.responses = responses or {}

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        path = url.replace(m.BASE_URL, "")
        self.calls.append(
            {"method": method, "path": path, "headers": headers, "params": params, "json": json_body}
        )
        key = (method, path)
        if key in self.responses:
            value = self.responses[key]
            return value if isinstance(value, tuple) else (200, value)
        return 200, {"status": "success", "data": {}}

    def paths(self) -> list[str]:
        return [c["path"] for c in self.calls]


_EMERGENCY_SCOPES = (
    ("derivative", "margin"),
    ("derivative", "intraday"),
    ("equity", "cnc"),
    ("equity", "intraday"),
)


class EmergencyTransport(FakeTransport):
    """Parameter-aware broker snapshot transport for emergency tests."""

    def __init__(
        self,
        *,
        orders: object | None = None,
        order_snapshots: list[object] | None = None,
        order_envelope: object | None = None,
        position_snapshots: list[dict[tuple[str, str], object]] | None = None,
        placed_order_id: str = "EQ-EXIT-1",
        placement_envelope: object | None = None,
        cancellation_envelope: object | None = None,
        instruments_csv: str | None = None,
    ) -> None:
        super().__init__()
        self.orders = [] if orders is None else orders
        self.order_snapshots = order_snapshots
        self.order_envelope = order_envelope
        self.position_snapshots = position_snapshots or [{}]
        self.placed_order_id = placed_order_id
        self.placement_envelope = placement_envelope
        self.cancellation_envelope = cancellation_envelope
        self.instruments_csv = instruments_csv or (
            "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME,LOT_UNITS\n"
            "NSE,FNO,202,NIFTY25JULFUT,NIFTY,75\n"
            "BSE,FNO,303,SENSEX25JULFUT,SENSEX,25\n"
        )
        self.position_reads = 0
        self.order_reads = 0

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        path = url.replace(m.BASE_URL, "")
        self.calls.append(
            {"method": method, "path": path, "headers": headers, "params": params, "json": json_body}
        )
        if method == "GET" and path == "/order-book":
            if self.order_envelope is not None:
                return 200, self.order_envelope
            orders = self.orders
            if self.order_snapshots is not None:
                orders = self.order_snapshots[min(self.order_reads, len(self.order_snapshots) - 1)]
                self.order_reads += 1
            return 200, {"status": "success", "data": orders}
        if method == "GET" and path == "/portfolio/positions":
            cycle = min(self.position_reads // len(_EMERGENCY_SCOPES), len(self.position_snapshots) - 1)
            self.position_reads += 1
            scope = (str((params or {}).get("segment")), str((params or {}).get("product")))
            configured = self.position_snapshots[cycle].get(scope, [])
            if isinstance(configured, dict) and "__envelope__" in configured:
                return 200, configured["__envelope__"]
            data = (
                configured
                if isinstance(configured, dict)
                else {"net_positions": configured, "day_positions": []}
            )
            return 200, {"status": "success", "data": data}
        if method == "GET" and path == "/market/instruments":
            return 200, self.instruments_csv
        if method == "POST" and path == "/order":
            if self.placement_envelope is not None:
                return 200, self.placement_envelope
            return 200, {"status": "success", "data": {"order_id": self.placed_order_id}}
        if method == "POST" and path in {"/order/cancel", "/smart/order/cancel"}:
            if self.cancellation_envelope is not None:
                return 200, self.cancellation_envelope
            return 200, {"status": "success", "data": {}}
        return 200, {"status": "success", "data": {}}


def _adapter(transport, **kwargs):
    return IndMoneyAdapter(
        http_factory=lambda: transport,
        security_resolver=kwargs.pop("security_resolver", lambda s, e: "2885"),
        **kwargs,
    )


async def _session(adapter):
    return await adapter.login({"access_token": "TOK", "user_id": "U1"})


# ---------------------------------------------------------------------------
# Identity, capabilities, auth lifecycle
# ---------------------------------------------------------------------------


def test_identity_and_capabilities() -> None:
    adapter = IndMoneyAdapter()
    assert adapter.broker_id == "indmoney"
    caps = adapter.capabilities
    assert caps is INDMONEY_CAPABILITIES
    assert caps.gtt_native is True and caps.option_chain_supported is False
    assert caps.rate_limit_orders_per_sec == 10 and caps.order_modifications_per_order == 25
    assert caps.streaming_max_connections_per_user == 3
    assert caps.streaming_max_symbols_per_connection == 3000
    assert caps.algo_tag_required is True


@pytest.mark.asyncio
async def test_login_returns_session_and_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(FakeTransport())
    monkeypatch.setattr("flinttrade_gateway.brokers.indmoney.next_6am_ist_timestamp", lambda: 1_788_307_200.0)
    session = await _session(adapter)
    assert session.adapter_id == "indmoney"
    assert session.access_token == "TOK" and session.account_id == "U1"
    assert session.expires_at == 1_788_307_200.0
    with pytest.raises(BrokerError, match="access_token"):
        await adapter.login({})


@pytest.mark.asyncio
async def test_refresh_and_logout_are_benign() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    assert await adapter.refresh(session) is session  # manual dashboard-reset token cycle
    await adapter.logout(session)
    await adapter.logout(session)  # idempotent
    assert "transport" not in session.extra


@pytest.mark.asyncio
async def test_auth_header_is_bare_token() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.profile(session)
    headers = transport.calls[0]["headers"]
    assert headers["Authorization"] == "TOK"  # no "Bearer" prefix (conventions doc)


# ---------------------------------------------------------------------------
# Gated writes — regular orders
# ---------------------------------------------------------------------------


def _order(**overrides) -> Order:
    base = dict(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                product="CNC", quantity="1", price="2450")
    base.update(overrides)
    return Order(**base)


@pytest.mark.asyncio
async def test_place_order_is_gated() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport, security_resolver=None)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, _order())  # no router token
    assert transport.calls == []  # never reached the broker


@pytest.mark.asyncio
async def test_place_order_with_router_token() -> None:
    transport = FakeTransport({
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-1", "order_status": "O-PENDING"}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    oid = await adapter.place_order(session, _order(), _router_token=_ROUTER_TOKEN)
    assert oid == "EQ-1"
    call = transport.calls[0]
    assert call["method"] == "POST" and call["path"] == "/order"
    assert call["json"]["security_id"] == "2885"
    assert call["json"]["segment"] == "EQUITY" and call["json"]["product"] == "CNC"
    assert call["json"]["limit_price"] == 2450.0
    assert call["json"]["algo_id"] == "99999"  # mandatory algo id auto-filled
    assert call["json"]["is_amo"] is False
    assert session.extra["indmoney_order_families"] == {"EQ-1": "regular"}


@pytest.mark.asyncio
async def test_place_order_with_router_token_auto_resolves_from_instruments() -> None:
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\nNSE,E,2885,RELIANCE-EQ,RELIANCE\n"
    transport = FakeTransport({
        ("GET", "/market/instruments"): (200, csv_text),
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-11"}},
    })
    adapter = _adapter(transport, security_resolver=None)
    session = await _session(adapter)
    oid = await adapter.place_order(session, _order(), _router_token=_ROUTER_TOKEN)
    assert oid == "EQ-11"
    assert transport.paths() == ["/market/instruments", "/order"]
    assert transport.calls[0]["params"] == {"source": "equity"}
    assert transport.calls[1]["json"]["security_id"] == "2885"


@pytest.mark.asyncio
async def test_place_order_session_algo_id_wins() -> None:
    transport = FakeTransport({
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-2"}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    session.algo_id = "ALGO42"
    await adapter.place_order(session, _order(), _router_token=_ROUTER_TOKEN)
    assert transport.calls[0]["json"]["algo_id"] == "ALGO42"


@pytest.mark.asyncio
async def test_place_order_market_has_no_limit_price() -> None:
    transport = FakeTransport({
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-3"}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.place_order(session, _order(pricetype="MARKET", price="0"), _router_token=_ROUTER_TOKEN)
    payload = transport.calls[0]["json"]
    assert payload["order_type"] == "MARKET" and "limit_price" not in payload


@pytest.mark.asyncio
async def test_place_amo_variety_sets_flag() -> None:
    transport = FakeTransport({
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-4"}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.place_order(session, _order(variety="amo"), _router_token=_ROUTER_TOKEN)
    assert transport.calls[0]["json"]["is_amo"] is True


@pytest.mark.asyncio
async def test_place_order_sl_pricetype_fails_closed() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(m.IndMoneyMappingError, match="trigger"):
        await adapter.place_order(
            session, _order(pricetype="SL", trigger_price="2400"), _router_token=_ROUTER_TOKEN
        )
    assert transport.calls == []  # rejected before any HTTP


@pytest.mark.asyncio
async def test_unsupported_variety_raises() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    order = _order()
    object.__setattr__(order, "variety", "iceberg")
    with pytest.raises(BrokerError, match="variety"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_unresolvable_symbol_raises() -> None:
    adapter = IndMoneyAdapter(http_factory=lambda: FakeTransport())  # no resolver
    session = await _session(adapter)
    with pytest.raises(BrokerError, match="security_id"):
        await adapter.place_order(session, _order(symbol="OBSCURE"), _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_numeric_symbol_passes_through_without_resolver() -> None:
    transport = FakeTransport({
        ("POST", "/order"): {"status": "success", "data": {"order_id": "EQ-5"}},
    })
    adapter = IndMoneyAdapter(http_factory=lambda: transport)  # no resolver
    session = await _session(adapter)
    await adapter.place_order(session, _order(symbol="500112", exchange="BSE", price="850"),
                              _router_token=_ROUTER_TOKEN)
    payload = transport.calls[0]["json"]
    assert payload["security_id"] == "500112"
    assert payload["algo_id"] == "9999999999999999"  # BSE algo id


# ---------------------------------------------------------------------------
# Gated writes — smart orders (GTT family)
# ---------------------------------------------------------------------------

SMART_RESP = {
    "status": "success",
    "data": {"order_data": [{"order_id": "DRV-28131451", "order_status": "CREATED",
                             "child_order_details": {"order_id": "GTT-2914581", "order_status": "CREATED"}}]},
}


def _gtt_order(**overrides) -> SimpleNamespace:
    """A duck-typed GTT order carrying explicit, doc-valid leg limit prices.

    The mapping reads every leg price off the order by attribute; leg limit
    prices (``sl_limit_price``/``tgt_limit_price``) are mandatory and must
    satisfy the documented strict inequalities (smart-orders.md:192-194), so the
    smart-order path is exercised with a SL limit below its trigger and a target
    limit above its trigger.
    """
    base = dict(symbol="51011", action="BUY", exchange="NFO", pricetype="LIMIT",
                product="NRML", quantity="75", price="37", trigger_price="0", variety="gtt",
                stop_loss_price="34", target_price="41", sl_limit_price="33", tgt_limit_price="42")
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_gtt_variety_dispatches_to_smart_order() -> None:
    transport = FakeTransport({("POST", "/smart/order"): SMART_RESP})
    adapter = _adapter(transport, security_resolver=lambda s, e: "51011")
    session = await _session(adapter)
    oid = await adapter.place_order(session, _gtt_order(), _router_token=_ROUTER_TOKEN)
    assert oid == "DRV-28131451"  # parent id returned
    assert adapter.last_child_order_id == "GTT-2914581"  # child surfaced
    assert session.extra["indmoney_order_families"] == {
        "DRV-28131451": "smart",
        "GTT-2914581": "smart",
    }
    payload = transport.calls[0]["json"]
    assert payload["sl_trigger_price"] == 34.0 and payload["tgt_trigger_price"] == 41.0
    # Explicit leg limits, honouring the documented strict inequalities.
    assert payload["sl_limit_price"] == 33.0 and payload["tgt_limit_price"] == 42.0
    assert payload["sl_limit_price"] < payload["sl_trigger_price"]
    assert payload["tgt_limit_price"] > payload["tgt_trigger_price"]
    assert payload["validity"] == "DAY"


@pytest.mark.asyncio
async def test_trigger_variety_builds_trigger_payload() -> None:
    transport = FakeTransport({
        ("POST", "/smart/order"): {"status": "success", "data": {"order_data": [{"order_id": "EQ-9"}]}},
    })
    adapter = _adapter(transport, security_resolver=lambda s, e: "3045")
    session = await _session(adapter)
    order = _order(pricetype="MARKET", price="0", variety="trigger", trigger_price="1520")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "EQ-9" and adapter.last_child_order_id is None
    payload = transport.calls[0]["json"]
    assert payload["order_type"] == "TRIGGER" and payload["trigger_price"] == 1520.0


@pytest.mark.asyncio
async def test_smart_order_still_requires_router_token() -> None:
    # The gating invariant must hold for EVERY variety, not just regular orders.
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    order = _order(variety="gtt", stop_loss_price="2400")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)  # no token
    assert transport.calls == []


@pytest.mark.asyncio
async def test_gtt_without_legs_fails_closed() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(m.IndMoneyMappingError, match="leg"):
        await adapter.place_order(session, _order(variety="gtt"), _router_token=_ROUTER_TOKEN)
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Gated writes — modify / cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modify_and_cancel_are_gated() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await adapter.modify_order(session, "DRV-1", {"qty": 5, "limit_price": 10})
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_order(session, "DRV-1")
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_smart_order(session, "DRV-1")
    assert transport.calls == []


@pytest.mark.asyncio
async def test_modify_normal_order_uses_prefix_segment() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.modify_order(session, "DRV-2049", {"qty": 75, "limit_price": 73}, _router_token=_ROUTER_TOKEN)
    call = transport.calls[0]
    assert call["path"] == "/order/modify"
    assert call["json"] == {"order_id": "DRV-2049", "segment": "DERIVATIVE", "qty": 75, "limit_price": 73.0}


@pytest.mark.asyncio
async def test_modify_gtt_id_routes_to_smart_modify() -> None:
    transport = FakeTransport({("GET", "/order-book"): DOC_ORDER_BOOK})
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.modify_order(
        session, "GTT-2914581", {"qty": 75, "sl_trigger_price": 0.4, "sl_limit_price": 0.3},
        _router_token=_ROUTER_TOKEN,
    )
    # Segment is not inferable from a GTT- id, so the order book was consulted.
    assert transport.paths() == ["/order-book", "/smart/order/modify"]
    payload = transport.calls[1]["json"]
    assert payload["segment"] == "DERIVATIVE"  # found in the order book
    assert payload["sl_trigger_price"] == 0.4 and payload["sl_limit_price"] == 0.3
    assert payload["algo_id"] == "99999"


@pytest.mark.asyncio
async def test_modify_smart_variety_routes_parent_to_smart_endpoint() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.modify_order(
        session, "DRV-123", {"variety": "gtt", "qty": 20, "limit_price": 0.35, "order_type": "LIMIT"},
        _router_token=_ROUTER_TOKEN,
    )
    assert transport.calls[0]["path"] == "/smart/order/modify"
    assert transport.calls[0]["json"]["segment"] == "DERIVATIVE"


@pytest.mark.asyncio
async def test_cancel_normal_and_smart_routing() -> None:
    transport = FakeTransport({("GET", "/order-book"): DOC_ORDER_BOOK})
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.cancel_order(session, "DRV-2049", _router_token=_ROUTER_TOKEN)
    assert transport.calls[-1]["path"] == "/order/cancel"
    assert transport.calls[-1]["json"] == {"order_id": "DRV-2049", "segment": "DERIVATIVE"}

    await adapter.cancel_order(session, "GTT-2914581", _router_token=_ROUTER_TOKEN)
    # GTT- id → smart cancel endpoint, segment resolved from the order book.
    assert transport.calls[-1]["path"] == "/smart/order/cancel"
    assert transport.calls[-1]["json"] == {"order_id": "GTT-2914581", "segment": "DERIVATIVE"}


@pytest.mark.asyncio
async def test_cancel_smart_order_forces_smart_path_for_parent() -> None:
    transport = FakeTransport()
    adapter = _adapter(transport)
    session = await _session(adapter)
    await adapter.cancel_smart_order(session, "DRV-28131451", _router_token=_ROUTER_TOKEN)
    assert transport.calls[0]["path"] == "/smart/order/cancel"
    assert transport.calls[0]["json"]["segment"] == "DERIVATIVE"


# ---------------------------------------------------------------------------
# Reads — orders, trades, portfolio, funds, profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_book_maps_rows() -> None:
    transport = FakeTransport({("GET", "/order-book"): DOC_ORDER_BOOK})
    adapter = _adapter(transport)
    session = await _session(adapter)
    rows = await adapter.order_book(session)
    assert len(rows) == 2
    assert rows[0]["orderid"] == "GTT-2914581" and rows[0]["exchange"] == "NFO"
    assert rows[1]["status"] == "SUCCESS" and rows[1]["product"] == "NRML"


@pytest.mark.asyncio
async def test_order_details_sends_json_body_on_get() -> None:
    transport = FakeTransport({
        ("GET", "/order"): {"status": "success", "data": dict(DOC_ORDER_BOOK["data"][1])},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    detail = await adapter.order_details(session, "DRV-28131451")
    assert detail["orderid"] == "DRV-28131451" and detail["average_price"] == "43.55"
    call = transport.calls[0]
    assert call["method"] == "GET" and call["json"] == {"order_id": "DRV-28131451", "segment": "DERIVATIVE"}


@pytest.mark.asyncio
async def test_order_trades_maps_confirmations() -> None:
    transport = FakeTransport({
        ("GET", "/trades/DRV-2049"): {"status": "success", "data": [{
            "order_id": "DRV-2049", "trading_symbol": "RELIANCE-EQ", "exchange_segment": "NSE_EQ",
            "transaction_type": "BUY", "product_type": "CNC", "quantity": 5, "price": 2500.45,
            "trade_timestamp": "2025-05-12T10:15:35Z",
        }]},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    trades = await adapter.order_trades(session, "DRV-2049")
    assert len(trades) == 1
    assert trades[0]["symbol"] == "RELIANCE-EQ" and trades[0]["exchange"] == "NSE"


@pytest.mark.asyncio
async def test_trade_book_aggregates_both_segments() -> None:
    fill = {"fill_id": 1, "exch_order_id": "X1", "quantity": 5, "price": 1.5,
            "trade_date": "2025-11-11T17:48:23+05:30", "scrip_code": "99133"}
    transport = FakeTransport({
        ("GET", "/trade-book"): {"status": "success", "data": [fill]},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    trades = await adapter.trade_book(session)
    assert len(trades) == 2  # one per segment from the shared canned response
    segments = [c["params"]["segment"] for c in transport.calls]
    assert segments == ["EQUITY", "DERIVATIVE"]


@pytest.mark.asyncio
async def test_positions_aggregates_combos_and_dedupes() -> None:
    pos = {
        "security_id": "67890", "trading_symbol": "NIFTY25MAYFUT", "exchange_segment": "NSE_FNO",
        "net_quantity": 100, "average_price": 18500.0, "last_traded_price": 18550.5,
        "pnl_absolute": 5050.0,
    }
    transport = FakeTransport({
        ("GET", "/portfolio/positions"): {"status": "success",
                                          "data": {"net_positions": [pos], "day_positions": []}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    positions = await adapter.positions(session)
    # The same symbol surfaces under four combos but with distinct products
    # (NRML/MIS/CNC/MIS) — the (symbol, product) dedupe keeps three.
    assert len(transport.calls) == 4
    assert {(p["symbol"], p["product"]) for p in positions} == {
        ("NIFTY25MAYFUT", "NRML"), ("NIFTY25MAYFUT", "MIS"), ("NIFTY25MAYFUT", "CNC"),
    }
    combos = [(c["params"]["segment"], c["params"]["product"]) for c in transport.calls]
    assert combos == [("derivative", "margin"), ("derivative", "intraday"),
                      ("equity", "cnc"), ("equity", "intraday")]


@pytest.mark.asyncio
async def test_positions_segment_preserves_day_net_split() -> None:
    pos = {"trading_symbol": "X", "exchange_segment": "NSE_EQ", "net_quantity": 1,
           "average_price": 10, "pnl_absolute": 0}
    transport = FakeTransport({
        ("GET", "/portfolio/positions"): {"status": "success",
                                          "data": {"net_positions": [pos], "day_positions": [pos]}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    split = await adapter.positions_segment(session, "equity", "intraday")
    assert len(split["net_positions"]) == 1 and len(split["day_positions"]) == 1
    assert split["net_positions"][0]["product"] == "MIS"


@pytest.mark.asyncio
async def test_holdings_and_funds_and_profile() -> None:
    transport = FakeTransport({
        ("GET", "/portfolio/holdings"): {"status": "success", "data": [{
            "trading_symbol": "RELIANCE-EQ", "exchange_segment": "NSE_EQ", "isin": "INE002A01018",
            "quantity": 50, "average_price": 2200.0, "last_traded_price": 2505.1,
            "pnl_absolute": 15255.0, "pnl_percent": 13.87,
        }]},
        ("GET", "/funds"): {"status": "success", "data": {
            "sod_balance": 4996.47, "withdrawal_balance": 2983.47,
        }},
        ("GET", "/user/profile"): {"status": "success", "data": {
            "user_id": "1234567", "is_nse_onboarded": True,
        }},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    holdings = await adapter.holdings(session)
    assert holdings[0]["symbol"] == "RELIANCE-EQ" and holdings[0]["quantity"] == "50"
    funds = await adapter.funds(session)
    assert funds["available_balance"] == "2983.47" and funds["total_balance"] == "4996.47"
    profile = await adapter.profile(session)
    assert profile["user_id"] == "1234567"


@pytest.mark.asyncio
async def test_smart_orders_filters_gtt_family() -> None:
    transport = FakeTransport({("GET", "/order-book"): DOC_ORDER_BOOK})
    adapter = _adapter(transport)
    session = await _session(adapter)
    smart = await adapter.smart_orders(session)
    assert [r["orderid"] for r in smart] == ["GTT-2914581"]


# ---------------------------------------------------------------------------
# Pre-trade reads — margin, instruments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_margin_calculator_reads_estimate() -> None:
    transport = FakeTransport({
        ("GET", "/margin"): {"status": "success", "data": {
            "total_margin": 750, "span_margin": 0,
            "charges": {"brokerage": 5, "gst": 0.9, "total_charges": 5.9},
        }},
    })
    adapter = _adapter(transport, security_resolver=lambda s, e: "40131")
    session = await _session(adapter)
    order = _order(exchange="NFO", product="NRML", quantity="75", price="10")
    # No router token needed — margin calc is a read-only pre-trade estimate.
    margin = await adapter.margin_calculator(session, order)
    assert margin["required_margin"] == "750" and margin["charges"]["total_charges"] == 5.9
    body = transport.calls[0]["json"]
    assert body["securityID"] == "40131" and body["txnType"] == "BUY"


@pytest.mark.asyncio
async def test_instruments_parses_csv() -> None:
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL\nNSE,E,2885,RELIANCE-EQ\n"
    transport = FakeTransport({("GET", "/market/instruments"): (200, csv_text)})
    adapter = _adapter(transport)
    session = await _session(adapter)
    rows = await adapter.instruments(session, "equity")
    assert rows == [{"EXCH": "NSE", "SEGMENT": "E", "SECURITY_ID": "2885", "TRADING_SYMBOL": "RELIANCE-EQ"}]
    assert transport.calls[0]["params"] == {"source": "equity"}


@pytest.mark.asyncio
async def test_quotes_auto_resolve_from_instruments_master_and_cache() -> None:
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\nNSE,E,2885,RELIANCE-EQ,RELIANCE\n"
    transport = FakeTransport({
        ("GET", "/market/instruments"): (200, csv_text),
        ("GET", "/market/quotes/full"): FULL_QUOTE,
        ("GET", "/market/quotes/mkt"): {"status": "success", "data": {"NSE_2885": {
            "market_depth": {
                "aggregate": {"total_buy": "100", "total_sell": "50"},
                "depth": [{"buy": {"quantity": "10", "price": "788.60"},
                           "sell": {"quantity": "7", "price": "789.15"}}],
            },
        }}},
    })
    adapter = _adapter(transport, security_resolver=None)
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    depth = await adapter.market_depth(session, ["NSE:RELIANCE"])
    assert quotes[0].symbol == "RELIANCE" and quotes[0].ltp == 788.8
    assert depth["NSE:RELIANCE"]["bids"][0] == {"price": 788.60, "quantity": 10}
    assert transport.paths() == ["/market/instruments", "/market/quotes/full", "/market/quotes/mkt"]
    assert transport.calls[1]["params"]["scrip-codes"] == "NSE_2885"
    assert transport.calls[2]["params"]["scrip-codes"] == "NSE_2885"


@pytest.mark.asyncio
async def test_margin_and_historical_auto_resolve_from_cached_instruments() -> None:
    csv_text = "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,SYMBOL_NAME\nNSE,E,2885,RELIANCE-EQ,RELIANCE\n"
    transport = FakeTransport({
        ("GET", "/market/instruments"): (200, csv_text),
        ("GET", "/margin"): {"status": "success", "data": {
            "total_margin": 500, "charges": {"brokerage": 5, "total_charges": 5.5},
        }},
        ("GET", "/market/historical/1day"): {"status": "success", "data": {"candles": []}},
    })
    adapter = _adapter(transport, security_resolver=None)
    session = await _session(adapter)
    margin = await adapter.margin_calculator(session, _order(product="MIS", pricetype="MARKET", price="0"))
    candles = await adapter.historical(session, {
        "symbol": "RELIANCE", "exchange": "NSE", "interval": "1d",
        "from_date": "2025-06-01", "to_date": "2025-06-02",
    })
    assert margin["required_margin"] == "500"
    assert candles.symbol == "RELIANCE" and candles.bars == []
    assert transport.paths() == ["/market/instruments", "/margin", "/market/historical/1day"]
    assert transport.calls[1]["json"]["securityID"] == "2885"
    assert transport.calls[2]["params"]["scrip-codes"] == "NSE_2885"


# ---------------------------------------------------------------------------
# Market data — quotes, ltp, depth, historical
# ---------------------------------------------------------------------------

FULL_QUOTE = {
    "status": "success",
    "data": {"NSE_2885": {
        "live_price": 788.8, "day_open": 792.5, "day_high": 795.5, "day_low": 788.35,
        "prev_close": 792.3, "volume": 3546732,
        "market_depth": {"depth": [
            {"buy": {"quantity": "6.00", "price": "788.95"}, "sell": {"quantity": "21.00", "price": "789.00"}},
        ]},
    }},
}


@pytest.mark.asyncio
async def test_quotes_map_to_models() -> None:
    transport = FakeTransport({("GET", "/market/quotes/full"): FULL_QUOTE})
    adapter = _adapter(
        transport, security_resolver=lambda s, e: "2885" if s == "RELIANCE" else "9999"
    )
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE", "NSE:MISSING"])
    assert len(quotes) == 1  # the scrip absent from the payload is skipped
    assert quotes[0].symbol == "RELIANCE" and quotes[0].ltp == 788.8
    assert quotes[0].bid == 788.95 and quotes[0].ask == 789.00
    assert transport.calls[0]["params"]["scrip-codes"] == "NSE_2885,NSE_9999"


@pytest.mark.asyncio
async def test_ltp_extension() -> None:
    transport = FakeTransport({
        ("GET", "/market/quotes/ltp"): {"status": "success", "data": {"NSE_2885": {"live_price": 792.5}}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    out = await adapter.ltp(session, ["NSE:RELIANCE"])
    assert out == {"NSE:RELIANCE": 792.5}


@pytest.mark.asyncio
async def test_market_depth_extension() -> None:
    transport = FakeTransport({
        ("GET", "/market/quotes/mkt"): {"status": "success", "data": {"NSE_2885": {
            "market_depth": {
                "aggregate": {"total_buy": "5,82,909", "total_sell": "11,01,938"},
                "depth": [{"buy": {"quantity": "2,318", "price": "788.60"},
                           "sell": {"quantity": "1,792", "price": "789.15"}}],
            },
        }}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    depth = await adapter.market_depth(session, ["NSE:RELIANCE"])
    ladder = depth["NSE:RELIANCE"]
    assert ladder["total_buy"] == 582909.0
    assert ladder["bids"][0] == {"price": 788.60, "quantity": 2318}


@pytest.mark.asyncio
async def test_historical_builds_interval_path_and_params() -> None:
    transport = FakeTransport({
        ("GET", "/market/historical/5minute"): {"status": "success", "data": {"candles": [
            [1678886400000, 2500.0, 2501.5, 2499.5, 2501.0, 500],
        ]}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    candles = await adapter.historical(session, {
        "symbol": "RELIANCE", "exchange": "NSE", "interval": "5m",
        "start_time": 1750055540000, "end_time": 1750141940000,
    })
    assert candles.symbol == "RELIANCE" and len(candles.bars) == 1
    assert candles.bars[0].open == 2500.0
    params = transport.calls[0]["params"]
    assert params == {"scrip-codes": "NSE_2885", "start_time": 1750055540000, "end_time": 1750141940000}


@pytest.mark.asyncio
async def test_historical_accepts_date_strings_and_enforces_range() -> None:
    transport = FakeTransport({
        ("GET", "/market/historical/1day"): {"status": "success", "data": {"candles": []}},
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    candles = await adapter.historical(session, {
        "symbol": "RELIANCE", "exchange": "NSE", "interval": "1d",
        "from_date": "2025-06-01", "to_date": "2025-06-05",
    })
    assert candles.bars == []
    # A 30-day window violates the 7-day cap for minute candles — fails closed.
    with pytest.raises(m.IndMoneyMappingError, match="maximum"):
        await adapter.historical(session, {
            "symbol": "RELIANCE", "exchange": "NSE", "interval": "1m",
            "from_date": "2025-05-01", "to_date": "2025-05-31",
        })
    with pytest.raises(BrokerError, match="start_time"):
        await adapter.historical(session, {"symbol": "RELIANCE", "interval": "1m"})


# ---------------------------------------------------------------------------
# Utility family (Coming Soon broker-side)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_utility_family_raises_coming_soon() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="Coming Soon"):
        await adapter.option_chain(session, {"symbol": "NIFTY"})
    with pytest.raises(NotImplementedError, match="Coming Soon"):
        await adapter.option_chain_symbols(session, "NIDX_40000001")
    with pytest.raises(NotImplementedError, match="Coming Soon"):
        await adapter.greeks(session, ["NFO_43797"])


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_builds_feed_map_and_stream_yields_ticks() -> None:
    frames = [
        json.dumps({"mode": "ltp", "instrument": "2885", "timestamp": 1750138351089, "data": {"ltp": 1426}}),
        json.dumps({"type": "heartbeat"}),  # must be skipped
    ]

    async def fake_feed(_session):
        for frame in frames:
            yield frame

    adapter = _adapter(FakeTransport(), feed_factory=fake_feed)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"], mode="LTP")
    assert adapter._feed_map["2885"] == ("RELIANCE", "NSE")

    ticks = [t async for t in adapter.stream(session)]
    assert len(ticks) == 1
    assert ticks[0].symbol == "RELIANCE" and ticks[0].exchange == "NSE"
    assert ticks[0].ltp == 1426.0 and ticks[0].timestamp == "1750138351089"


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_feed_map() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert "2885" in adapter._feed_map
    await adapter.unsubscribe(session, ["NSE:RELIANCE"])
    assert "2885" not in adapter._feed_map and "2885" not in adapter._feed_modes


@pytest.mark.asyncio
async def test_stream_without_feed_factory_raises() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="feed_factory"):
        async for _ in adapter.stream(session):  # pragma: no cover - never yields
            pass


@pytest.mark.asyncio
async def test_order_update_stream_decodes_frames() -> None:
    frames = [
        json.dumps({"type": "order", "order_id": "INDM1", "order_status": "PARTIALLY_EXECUTED",
                    "filled_quantity": 5, "remaining_quantity": 5, "average_price": 2500.4,
                    "timestamp": 1678886530456}),
        "heartbeat",  # noise — skipped
    ]

    async def fake_order_feed(_session):
        for frame in frames:
            yield frame

    adapter = _adapter(FakeTransport(), order_feed_factory=fake_order_feed)
    session = await _session(adapter)
    updates = [u async for u in adapter.order_update_stream(session)]
    assert updates == [{
        "orderid": "INDM1", "status": "PARTIALLY_EXECUTED", "filled_quantity": "5",
        "remaining_quantity": "5", "average_price": "2500.4", "timestamp": "1678886530456",
    }]


@pytest.mark.asyncio
async def test_order_update_stream_without_factory_raises() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="order_feed_factory"):
        async for _ in adapter.order_update_stream(session):  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# Error mapping through the transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_error_maps_to_session_expired() -> None:
    transport = FakeTransport({
        ("GET", "/funds"): (403, {"status": "error", "message": "Invalid token",
                                  "error_type": "TokenException"}),
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(SessionExpired, match="Invalid token"):
        await adapter.funds(session)


@pytest.mark.asyncio
async def test_rate_limit_maps_to_rate_limit_error() -> None:
    transport = FakeTransport({
        ("GET", "/order-book"): (429, {"status": "error", "message": "Too many requests"}),
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(RateLimitError):
        await adapter.order_book(session)


@pytest.mark.asyncio
async def test_error_status_in_200_body_still_raises() -> None:
    transport = FakeTransport({
        ("GET", "/funds"): (200, {"status": "error", "message": "odd but possible",
                                  "error_type": "GeneralException"}),
    })
    adapter = _adapter(transport)
    session = await _session(adapter)
    with pytest.raises(BrokerError, match="odd but possible"):
        await adapter.funds(session)


@pytest.mark.asyncio
async def test_reconcile_clean_on_empty_state() -> None:
    # Empty broker books + the default EMPTY local state agree → clean report.
    # The diff semantics themselves are covered by tests/test_reconciliation.py.
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "indmoney"
    assert report.clean and report.error == ""


# ---------------------------------------------------------------------------
# Broker-authoritative emergency reduction
# ---------------------------------------------------------------------------


_CANCEL_POLICY = EmergencyWritePolicy(name="indmoney_cancel", verbs=("cancel_all_orders",))
_EXIT_POLICY = EmergencyWritePolicy(name="indmoney_exit", verbs=("exit_all_positions",))
_FLATTEN_POLICY = EmergencyWritePolicy(
    name="indmoney_flatten",
    verbs=("cancel_all_orders", "exit_all_positions"),
)


def _broker_order(
    order_id: str,
    *,
    status: str = "PENDING",
    security_id: str = "101",
    symbol: str = "RELIANCE-EQ",
    exchange: str = "NSE",
    segment: str = "EQUITY",
    product: str = "CNC",
    action: str = "BUY",
    order_type: str = "LIMIT",
    requested_quantity: object = 5,
    filled_quantity: object = 0,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": order_id,
        "status": status,
        "security_id": security_id,
        "name": symbol,
        "exchange": exchange,
        "segment": segment,
        "product": product,
        "txn_type": action,
        "order_type": order_type,
        "requested_qty": requested_quantity,
        "traded_qty": filled_quantity,
        **extra,
    }


def _broker_position(
    *,
    security_id: str = "101",
    symbol: str = "RELIANCE-EQ",
    exchange_segment: str = "NSE_EQ",
    quantity: object = 5,
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "trading_symbol": symbol,
        "exchange_segment": exchange_segment,
        "net_quantity": quantity,
        "average_price": 2500,
        "last_traded_price": 2510,
        "pnl_absolute": 50,
        "position_type": "open",
    }


async def _emergency_adapter(transport: EmergencyTransport) -> tuple[IndMoneyAdapter, object]:
    adapter = _adapter(transport)
    return adapter, await _session(adapter)


@pytest.mark.asyncio
async def test_emergency_plan_proves_two_quiet_books() -> None:
    transport = EmergencyTransport()
    adapter, session = await _emergency_adapter(transport)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_FLATTEN_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.writes == () and plan.pending_verbs == frozenset()
    assert transport.paths() == ["/order-book", *["/portfolio/positions"] * 4]


@pytest.mark.asyncio
async def test_emergency_plan_cancels_regular_and_smart_orders_exactly() -> None:
    transport = EmergencyTransport(
        orders=[
            _broker_order("EQ-1"),
            _broker_order("EQ-2", order_type="TRIGGER", trigger_price=2490),
            _broker_order("GTT-3", order_type="OCO", sl_trigger_price=2400),
            _broker_order("EQ-DONE", status="SUCCESS"),
        ]
    )
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert [(write.verb, write.payload) for write in plan.writes] == [
        ("cancel_order", {"_op": "cancel_order", "order_id": "EQ-1", "segment": "EQUITY"}),
        (
            "cancel_smart_order",
            {"_op": "cancel_smart_order", "order_id": "EQ-2", "segment": "EQUITY"},
        ),
        (
            "cancel_smart_order",
            {"_op": "cancel_smart_order", "order_id": "GTT-3", "segment": "EQUITY"},
        ),
    ]


@pytest.mark.asyncio
async def test_emergency_cancel_batches_are_bounded_to_ten() -> None:
    transport = EmergencyTransport(orders=[_broker_order(f"EQ-{index}") for index in range(12)])
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {f"EQ-{index}": "regular" for index in range(12)}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert len(plan.writes) == 10
    assert [write.payload["order_id"] for write in plan.writes] == [f"EQ-{index}" for index in range(10)]


@pytest.mark.asyncio
async def test_emergency_protected_cancel_is_not_replayed() -> None:
    transport = EmergencyTransport(orders=[_broker_order("EQ-1")])
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset({"EQ-1"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset({"cancel_all_orders"})


@pytest.mark.asyncio
async def test_emergency_plan_builds_exact_long_and_short_reductions() -> None:
    transport = EmergencyTransport(
        position_snapshots=[
            {
                ("equity", "cnc"): [_broker_position(security_id="101", quantity=5)],
                ("derivative", "margin"): [
                    _broker_position(
                        security_id="202",
                        symbol="NIFTY25JULFUT",
                        exchange_segment="NSE_FNO",
                        quantity=-75,
                    )
                ],
            }
        ]
    )
    adapter, session = await _emergency_adapter(transport)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert len(plan.writes) == 2
    by_security = {str(write.payload["security_id"]): write.payload for write in plan.writes}
    assert by_security["101"]["action"] == "SELL"
    assert by_security["101"]["quantity"] == "5"
    assert by_security["101"]["expected_position_quantity"] == "5"
    assert by_security["202"]["action"] == "BUY"
    assert by_security["202"]["quantity"] == "75"
    assert by_security["202"]["expected_position_quantity"] == "-75"
    assert all(str(payload["emergency_tag"]).startswith("fte-indmoney-") for payload in by_security.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "position", "expected_product"),
    [
        (
            ("derivative", "intraday"),
            _broker_position(
                security_id="202",
                symbol="NIFTY25JULFUT",
                exchange_segment="NSE_FNO",
                quantity=75,
            ),
            "MIS",
        ),
        (("equity", "intraday"), _broker_position(quantity=-5), "MIS"),
    ],
)
async def test_emergency_plan_covers_each_intraday_position_scope(
    scope: tuple[str, str],
    position: dict[str, object],
    expected_product: str,
) -> None:
    transport = EmergencyTransport(position_snapshots=[{scope: [position]}])
    adapter, session = await _emergency_adapter(transport)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert len(plan.writes) == 1
    assert plan.writes[0].payload["product"] == expected_product
    assert plan.writes[0].payload["quantity"] == str(abs(int(position["net_quantity"])))


@pytest.mark.asyncio
async def test_emergency_unidentified_exit_blocks_every_write() -> None:
    transport = EmergencyTransport(
        orders=[_broker_order("EQ-1")],
        position_snapshots=[{("equity", "cnc"): [_broker_position()]}],
    )
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_FLATTEN_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
        unidentified_exit_inflight=True,
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset({"cancel_all_orders", "exit_all_positions"})


@pytest.mark.asyncio
async def test_emergency_missing_protected_exit_id_blocks_replay() -> None:
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): [_broker_position()]}]
    )
    adapter, session = await _emergency_adapter(transport)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EQ-MISSING"}),
        protected_exit_tags=frozenset({"fte-indmoney-prior"}),
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
async def test_emergency_partial_exit_blocks_duplicate_for_same_episode() -> None:
    current = {
        "security_id": "101",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "6",
    }
    tag = IndMoneyAdapter._emergency_exit_tag(current, quantity=10)
    transport = EmergencyTransport(
        orders=[
            _broker_order(
                "EQ-EXIT-1",
                status="PARTIALLY FILLED",
                action="SELL",
                requested_quantity=10,
                filled_quantity=4,
            )
        ],
        position_snapshots=[{("equity", "cnc"): [_broker_position(quantity=6)]}],
    )
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-EXIT-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EQ-EXIT-1"}),
        protected_exit_tags=frozenset({tag}),
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
async def test_emergency_conflicting_exit_is_cancelled_before_replan() -> None:
    current = {
        "security_id": "101",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
    }
    transport = EmergencyTransport(
        orders=[
            _broker_order(
                "EQ-EXIT-1",
                action="SELL",
                requested_quantity=10,
                filled_quantity=0,
            )
        ],
        position_snapshots=[{("equity", "cnc"): [_broker_position(quantity=5)]}],
    )
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-EXIT-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EQ-EXIT-1"}),
        protected_exit_tags=frozenset({IndMoneyAdapter._emergency_exit_tag(current)}),
    )

    assert [(write.parent_verb, write.verb, write.payload["order_id"]) for write in plan.writes] == [
        ("exit_all_positions", "cancel_order", "EQ-EXIT-1")
    ]


@pytest.mark.asyncio
async def test_emergency_unmatched_completed_exit_blocks_another_reduction() -> None:
    transport = EmergencyTransport(
        orders=[
            _broker_order(
                "EQ-EXIT-1",
                status="SUCCESS",
                security_id="999",
                action="SELL",
                requested_quantity=5,
                filled_quantity=5,
            )
        ],
        position_snapshots=[{("equity", "cnc"): [_broker_position(quantity=5)]}],
    )
    adapter, session = await _emergency_adapter(transport)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EQ-EXIT-1"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.writes == ()
    assert plan.pending_verbs == frozenset({"exit_all_positions"})


@pytest.mark.asyncio
async def test_emergency_malformed_completed_exit_fails_closed() -> None:
    transport = EmergencyTransport(
        orders=[
            _broker_order(
                "EQ-EXIT-1",
                status="SUCCESS",
                security_id="",
                action="SELL",
                requested_quantity=5,
                filled_quantity=5,
            )
        ],
        position_snapshots=[{("equity", "cnc"): [_broker_position(quantity=5)]}],
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="exit security id"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_order_ids=frozenset({"EQ-EXIT-1"}),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "orders",
    [
        {},
        [None],
        [_broker_order("")],
        [_broker_order("EQ-1"), _broker_order("EQ-1")],
    ],
)
async def test_emergency_malformed_order_book_fails_closed(orders: object) -> None:
    transport = EmergencyTransport(orders=orders)
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-1": "regular"}

    with pytest.raises(BrokerError, match="emergency order"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_CANCEL_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_ambiguous_active_parent_fails_closed_after_restart() -> None:
    transport = EmergencyTransport(orders=[_broker_order("DRV-PARENT", order_type="MARKET")])
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="no authoritative regular/smart family evidence"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_CANCEL_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_local_smart_parent_evidence_selects_smart_cancel() -> None:
    transport = EmergencyTransport(orders=[_broker_order("DRV-PARENT", order_type="MARKET")])
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"DRV-PARENT": "smart"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert [(write.verb, write.payload["order_id"]) for write in plan.writes] == [
        ("cancel_smart_order", "DRV-PARENT")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"status": "failure", "message": "broker refused"},
        {"status": "success"},
        {"status": 1, "data": []},
    ],
)
async def test_emergency_order_envelope_must_be_explicit_success(envelope: object) -> None:
    transport = EmergencyTransport(order_envelope=envelope)
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError):
        await adapter.plan_emergency_reduction(
            session,
            policy=_CANCEL_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [None, "", 1])
async def test_emergency_order_status_is_required(status: object) -> None:
    transport = EmergencyTransport(orders=[_broker_order("GTT-1", status=status)])
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="order status"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_CANCEL_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_unknown_nonempty_status_remains_cancellable() -> None:
    transport = EmergencyTransport(orders=[_broker_order("EQ-1", status="BROKER_NEW_STATE")])
    adapter, session = await _emergency_adapter(transport)
    session.extra["indmoney_order_families"] = {"EQ-1": "regular"}

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert [write.payload["order_id"] for write in plan.writes] == ["EQ-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    [
        {"net_positions": []},
        [_broker_position(quantity="1.5")],
        [_broker_position(quantity=1), _broker_position(quantity=2)],
    ],
)
async def test_emergency_malformed_position_book_fails_closed(configured: object) -> None:
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): configured}]
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="emergency position"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_nonempty_day_positions_fail_closed() -> None:
    transport = EmergencyTransport(
        position_snapshots=[
            {
                ("equity", "cnc"): {
                    "net_positions": [],
                    "day_positions": [_broker_position(quantity=5)],
                }
            }
        ]
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="day-position book cannot be reconciled"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"status": "failure", "message": "broker refused"},
        {"status": "success"},
        {"status": "success", "data": []},
    ],
)
async def test_emergency_position_envelope_must_be_explicit_success(envelope: object) -> None:
    transport = EmergencyTransport(
        position_snapshots=[
            {("derivative", "margin"): {"__envelope__": envelope}}
        ]
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_duplicate_identical_position_identity_fails_closed() -> None:
    position = _broker_position(quantity=5)
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): [position, dict(position)]}]
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="duplicate identity"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_derivative_reduction_requires_whole_lot() -> None:
    transport = EmergencyTransport(
        position_snapshots=[
            {
                ("derivative", "margin"): [
                    _broker_position(
                        security_id="202",
                        symbol="NIFTY25JULFUT",
                        exchange_segment="NSE_FNO",
                        quantity=74,
                    )
                ]
            }
        ]
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError, match="whole lot"):
        await adapter.plan_emergency_reduction(
            session,
            policy=_EXIT_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_reducing_order_requires_router_token_before_readback() -> None:
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): [_broker_position()]}]
    )
    adapter, session = await _emergency_adapter(transport)
    payload = {
        "_op": "place_reducing_order",
        "security_id": "101",
        "symbol": "RELIANCE-EQ",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
        "expected_position_quantity": "5",
        "action": "SELL",
        "pricetype": "MARKET",
        "price": "0",
        "trigger_price": "0",
        "variety": "regular",
        "emergency_tag": "fte-indmoney-placeholder",
    }

    with pytest.raises(SafetyBypassError):
        await adapter.place_reducing_order(session, payload)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_reducing_order_rechecks_position_then_places_exact_market_order() -> None:
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): [_broker_position()]}],
        placed_order_id="EQ-EXIT-9",
    )
    adapter, session = await _emergency_adapter(transport)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    payload = dict(plan.writes[0].payload)

    order_id = await adapter.place_reducing_order(session, payload, _router_token=_ROUTER_TOKEN)

    assert order_id == "EQ-EXIT-9"
    placement = next(call for call in transport.calls if call["method"] == "POST")
    assert placement["path"] == "/order"
    assert placement["json"] == {
        "txn_type": "SELL",
        "exchange": "NSE",
        "segment": "EQUITY",
        "product": "CNC",
        "qty": 5,
        "order_type": "MARKET",
        "validity": "DAY",
        "security_id": "101",
        "is_amo": False,
        "algo_id": "99999",
    }


@pytest.mark.asyncio
async def test_reducing_order_rejects_non_success_write_envelope() -> None:
    transport = EmergencyTransport(
        position_snapshots=[{("equity", "cnc"): [_broker_position()]}],
        placement_envelope={"status": "failure", "data": {"order_id": "EQ-UNTRUSTED"}},
    )
    adapter, session = await _emergency_adapter(transport)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    with pytest.raises(BrokerError):
        await adapter.place_reducing_order(
            session,
            dict(plan.writes[0].payload),
            _router_token=_ROUTER_TOKEN,
        )


@pytest.mark.asyncio
async def test_emergency_cancel_rejects_non_success_write_envelope() -> None:
    transport = EmergencyTransport(
        orders=[_broker_order("EQ-1")],
        cancellation_envelope={"status": "failure", "data": {}},
    )
    adapter, session = await _emergency_adapter(transport)

    with pytest.raises(BrokerError):
        await adapter.cancel_order(
            session,
            "EQ-1",
            segment="EQUITY",
            _router_token=_ROUTER_TOKEN,
        )


@pytest.mark.asyncio
async def test_reducing_order_refuses_changed_position_before_post() -> None:
    transport = EmergencyTransport(
        position_snapshots=[
            {("equity", "cnc"): [_broker_position(quantity=5)]},
            {("equity", "cnc"): [_broker_position(quantity=4)]},
        ]
    )
    adapter, session = await _emergency_adapter(transport)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_EXIT_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    with pytest.raises(BrokerError, match="position changed"):
        await adapter.place_reducing_order(
            session,
            dict(plan.writes[0].payload),
            _router_token=_ROUTER_TOKEN,
        )
    assert not any(call["method"] == "POST" for call in transport.calls)


@pytest.mark.asyncio
async def test_emergency_smart_cancel_traverses_real_broker_router() -> None:
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")
    transport = EmergencyTransport(
        orders=[_broker_order("EQ-SMART-1", order_type="TRIGGER", trigger_price=2490)]
    )
    adapter, session = await _emergency_adapter(transport)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=_CANCEL_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    write = plan.writes[0]
    request_ctx = RequestContext(
        jti="jti-indmoney",
        actor_type="human",
        actor_id="operator",
        mode="live",
        intent_source=EMERGENCY_INTENT_SOURCE,
    )
    safety_ctx = gate_broker_write(
        write.verb,
        write.payload,
        request_ctx,
        "indmoney",
        account_id="U1",
        intent_source=EMERGENCY_INTENT_SOURCE,
    )
    router = BrokerRouter(
        {"indmoney": adapter},
        lambda _ctx, _adapter_id, _account_id: session,
    )

    await router.execute_gated(
        request_ctx,
        verb=write.verb,
        payload=write.payload,
        safety_ctx=safety_ctx,
        adapter_id="indmoney",
        account_id="U1",
    )

    assert transport.calls[-1]["path"] == "/smart/order/cancel"
    assert transport.calls[-1]["json"] == {"order_id": "EQ-SMART-1", "segment": "EQUITY"}


def test_full_emergency_dispatch_cancels_regular_order_with_signed_segment() -> None:
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")
    transport = EmergencyTransport(
        order_snapshots=[[_broker_order("EQ-REGULAR-1")], [], []]
    )
    adapter = _adapter(transport)
    session = asyncio.run(_session(adapter))
    session.extra["indmoney_order_families"] = {"EQ-REGULAR-1": "regular"}
    request_ctx = RequestContext(
        jti="jti-indmoney-cancel",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="indmoney:U1",
    )
    target = EmergencyBrokerTarget(
        request_ctx=request_ctx,
        adapter_id="indmoney",
        account_id="U1",
    )
    router = BrokerRouter(
        {"indmoney": adapter},
        lambda _ctx, _adapter_id, _account_id: session,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=4,
        planned_quiet_reads=2,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(_CANCEL_POLICY, reason="adapter cancellation proof")

    assert result.complete
    assert result.succeeded("cancel_all_orders")
    cancellations = [
        call for call in transport.calls
        if call["method"] == "POST" and call["path"] == "/order/cancel"
    ]
    assert [call["json"] for call in cancellations] == [
        {"order_id": "EQ-REGULAR-1", "segment": "EQUITY"}
    ]


def test_full_emergency_dispatch_reduces_indmoney_then_proves_quiet() -> None:
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")
    initial = {("equity", "cnc"): [_broker_position(quantity=5)]}
    transport = EmergencyTransport(
        position_snapshots=[initial, initial, {}, {}],
        placed_order_id="EQ-FULL-1",
    )
    adapter = _adapter(transport)
    session = asyncio.run(_session(adapter))
    request_ctx = RequestContext(
        jti="jti-indmoney-full",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="indmoney:U1",
    )
    target = EmergencyBrokerTarget(
        request_ctx=request_ctx,
        adapter_id="indmoney",
        account_id="U1",
    )
    router = BrokerRouter(
        {"indmoney": adapter},
        lambda _ctx, _adapter_id, _account_id: session,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=6,
        planned_quiet_reads=2,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(_EXIT_POLICY, reason="adapter integration proof")

    assert result.complete
    assert result.succeeded("exit_all_positions")
    placements = [call for call in transport.calls if call["method"] == "POST" and call["path"] == "/order"]
    assert len(placements) == 1
    assert placements[0]["json"]["qty"] == 5
