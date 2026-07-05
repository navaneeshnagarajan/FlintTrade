"""Tests for the IndMoney (INDstocks) adapter — fake HTTP transport + synthetic
WebSocket frames; no SDK, no network, no credentials needed."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import BrokerError, RateLimitError, SessionExpired
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers import indmoney_mapping as m
from flinttrade_gateway.brokers.indmoney import INDMONEY_CAPABILITIES, IndMoneyAdapter, _ROUTER_TOKEN

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
async def test_login_returns_session_and_requires_token() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    assert session.adapter_id == "indmoney"
    assert session.access_token == "TOK" and session.account_id == "U1"
    with pytest.raises(BrokerError, match="access_token"):
        await adapter.login({})


@pytest.mark.asyncio
async def test_refresh_and_logout_are_benign() -> None:
    adapter = _adapter(FakeTransport())
    session = await _session(adapter)
    assert await adapter.refresh(session) is session  # manual 24 h token cycle
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
