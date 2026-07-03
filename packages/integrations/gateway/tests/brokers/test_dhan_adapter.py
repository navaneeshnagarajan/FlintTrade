"""Tests for the Dhan adapter's full v2.x parity surface (mock SDK; no dhanhq install).

Covers the management/read surfaces added for feature parity: forever (GTT) and
super-order management, order reads by id/correlation id, convert position,
conditional triggers (v2.5), Trader's Control (kill-switch status + P&L exit +
Exit All), EDIS, the auth/token/static-IP surface, the scrip-master helper, the
expired-options history, the order-update stream and the 20/200-level depth
streams. The gated-write invariant (§8) is asserted for every trade-affecting
method. The base place/modify/cancel + portfolio surface is covered by
``tests/test_dhan_adapter.py``.
"""

from __future__ import annotations

import json
import struct
from typing import Any, AsyncIterator

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN
from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

pytestmark = pytest.mark.unit


class MockHTTP:
    """Stand-in for the SDK's DhanHTTP transport (v2.5 endpoints)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    def _respond(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        self.calls.append((method, endpoint, payload))
        return self.responses.get((method, endpoint), {"status": "success", "data": {}})

    def get(self, endpoint):
        return self._respond("GET", endpoint)

    def post(self, endpoint, payload):
        return self._respond("POST", endpoint, payload)

    def put(self, endpoint, payload):
        return self._respond("PUT", endpoint, payload)

    def delete(self, endpoint):
        return self._respond("DELETE", endpoint)


class MockDhan:
    """Stand-in for the synchronous dhanhq 2.2.0 client (parity surface)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.dhan_http = MockHTTP()

    # forever (GTT)
    def modify_forever(self, **kw):
        self.calls.append(("modify_forever", kw))
        return {"status": "success", "data": {"orderId": kw["order_id"]}}

    def cancel_forever(self, order_id):
        self.calls.append(("cancel_forever", order_id))
        return {"status": "success", "data": {"orderId": order_id}}

    def get_forever(self):
        self.calls.append(("get_forever",))
        return {"status": "success", "data": [
            {"orderId": "GTT1", "orderStatus": "PENDING", "orderFlag": "SINGLE",
             "tradingSymbol": "HDFCBANK", "exchangeSegment": "NSE_EQ", "transactionType": "BUY",
             "orderType": "LIMIT", "productType": "CNC", "quantity": 5, "price": 1428,
             "triggerPrice": 1427},
            "junk",
        ]}

    # super orders
    def modify_super_order(self, **kw):
        self.calls.append(("modify_super", kw))
        return {"status": "success", "data": {"orderId": kw["order_id"]}}

    def cancel_super_order(self, order_id, order_leg):
        self.calls.append(("cancel_super", order_id, order_leg))
        return {"status": "success", "data": {"orderId": order_id}}

    def get_super_order_list(self):
        self.calls.append(("super_list",))
        return {"status": "success", "data": [
            {"orderId": "SUP1", "orderStatus": "PENDING", "tradingSymbol": "RELIANCE",
             "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "orderType": "LIMIT",
             "productType": "INTRADAY", "quantity": 5, "price": 2900, "targetPrice": 2950,
             "stopLossPrice": 2870, "legDetails": [{"legName": "STOP_LOSS_LEG"}]},
        ]}

    # order reads
    def get_order_by_id(self, order_id):
        self.calls.append(("order_by_id", order_id))
        return {"status": "success", "data": [
            {"orderId": order_id, "orderStatus": "TRADED", "tradingSymbol": "TCS",
             "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "orderType": "LIMIT",
             "productType": "CNC", "quantity": 5, "price": 3500},
        ]}

    def get_order_by_correlationID(self, correlation_id):
        self.calls.append(("order_by_corr", correlation_id))
        return {"status": "success", "data": {
            "orderId": "OID9", "orderStatus": "PENDING", "tradingSymbol": "INFY",
            "exchangeSegment": "NSE_EQ", "transactionType": "SELL", "orderType": "MARKET",
            "productType": "INTRADAY", "quantity": 10, "price": 0,
        }}

    # portfolio writes
    def convert_position(self, **kw):
        self.calls.append(("convert", kw))
        return {"status": "success", "data": ""}

    # trader's control
    def kill_switch(self, action):
        self.calls.append(("kill", action))
        return {"status": "success", "data": {"killSwitchStatus": action}}

    def status_kill_switch(self):
        self.calls.append(("kill_status",))
        return {"status": "success", "data": {"dhanClientId": "C1", "killSwitchStatus": "ACTIVATE"}}

    # EDIS
    def generate_tpin(self):
        self.calls.append(("tpin",))
        return {"status": "success", "remarks": "OTP sent", "data": ""}

    def edis_inquiry(self, isin):
        self.calls.append(("edis_inquiry", isin))
        return {"status": "success", "data": {"isin": isin, "totalQty": 10, "aprvdQty": 4,
                                              "status": "SUCCESS"}}

    # expired options
    def expired_options_data(self, **kw):
        self.calls.append(("expired_options", kw))
        return {"status": "success", "data": {"data": {
            "ce": {"open": [354, 360.3], "timestamp": [1, 2]}, "pe": None,
        }}}


class MockLogin:
    """Stand-in for the SDK's DhanLogin auth helper."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.calls: list[tuple] = []

    def user_profile(self, access_token):
        self.calls.append(("profile", access_token))
        return {"dhanClientId": self.client_id, "tokenValidity": "30/06/2026 15:37"}

    def generate_token(self, pin, totp):
        self.calls.append(("generate", pin, totp))
        return {"dhanClientId": self.client_id, "accessToken": "NEWTOK",
                "expiryTime": "2026-06-13T00:00:00"}

    def renew_token(self, access_token):
        self.calls.append(("renew", access_token))
        return {"accessToken": "RENEWED", "expiryTime": "2026-06-13T00:00:00"}

    def set_ip(self, access_token, ip, ip_flag, dhan_client_id=None):
        self.calls.append(("set_ip", ip, ip_flag))
        return {"status": "success", "data": {"message": "IP saved successfully", "status": "SUCCESS"}}

    def modify_ip(self, access_token, ip, ip_flag, dhan_client_id=None):
        self.calls.append(("modify_ip", ip, ip_flag))
        return {"status": "success", "data": {"message": "IP saved successfully", "status": "SUCCESS"}}

    def get_ip(self, access_token):
        self.calls.append(("get_ip",))
        return {"status": "success", "data": {"primaryIP": "10.0.0.1", "secondaryIP": ""}}


def _adapter(mock: MockDhan, login: MockLogin | None = None, **extra: Any) -> DhanAdapter:
    return DhanAdapter(
        client_factory=lambda _s: mock,
        security_resolver=lambda s, e: "11536",
        login_factory=(lambda cid: login) if login is not None else None,
        **extra,
    )


async def _session(adapter: DhanAdapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


_CONDITION = {
    "comparisonType": "TECHNICAL_WITH_VALUE",
    "exchangeSegment": "NSE_EQ",
    "securityId": "11536",
    "operator": "CROSSING_UP",
    "comparingValue": 250,
    "timeFrame": "DAY",
    "expDate": "2026-12-31",
    "frequency": "ONCE",
}


def _leg_order() -> Order:
    return Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                 product="CNC", quantity="10", price="250")


# ---------------------------------------------------------------------------
# Gating: every trade-affecting method requires the router token
# ---------------------------------------------------------------------------


async def test_every_new_write_surface_is_gated() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    attempts = [
        adapter.modify_forever(session, "GTT1", {"quantity": 1}),
        adapter.cancel_forever(session, "GTT1"),
        adapter.modify_super_order(session, "SUP1", {"leg_name": "TARGET_LEG", "target_price": 2950}),
        adapter.cancel_super_order(session, "SUP1", "TARGET_LEG"),
        adapter.convert_position(session, {"symbol": "RELIANCE", "from_product": "MIS",
                                           "to_product": "CNC", "position_type": "LONG",
                                           "exchange": "NSE", "quantity": 1}),
        adapter.place_conditional_trigger(session, _CONDITION, [_leg_order()]),
        adapter.modify_conditional_trigger(session, "12345", _CONDITION, [_leg_order()]),
        adapter.cancel_conditional_trigger(session, "12345"),
        adapter.exit_all_positions(session),
    ]
    for coro in attempts:
        with pytest.raises(SafetyBypassError):
            await coro
    assert mock.calls == []  # the SDK was never reached
    assert mock.dhan_http.calls == []  # nor the raw HTTP transport


# ---------------------------------------------------------------------------
# Forever (GTT) management
# ---------------------------------------------------------------------------


async def test_forever_modify_cancel_and_list() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_forever(
        session, "GTT1", {"pricetype": "LIMIT", "quantity": 10, "price": 1430, "trigger_price": 1429},
        _router_token=_ROUTER_TOKEN,
    )
    kind, kw = mock.calls[0]
    assert kind == "modify_forever" and kw["order_id"] == "GTT1" and kw["trigger_price"] == 1429.0
    await adapter.cancel_forever(session, "GTT1", _router_token=_ROUTER_TOKEN)
    assert mock.calls[1] == ("cancel_forever", "GTT1")
    rows = await adapter.forever_orders(session)
    assert len(rows) == 1  # the junk row is dropped
    assert rows[0]["orderid"] == "GTT1" and rows[0]["exchange"] == "NSE" and rows[0]["product"] == "CNC"


# ---------------------------------------------------------------------------
# Super order management
# ---------------------------------------------------------------------------


async def test_super_order_modify_cancel_and_list() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_super_order(
        session, "SUP1", {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 2860, "trailing_jump": 5},
        _router_token=_ROUTER_TOKEN,
    )
    kind, kw = mock.calls[0]
    assert kind == "modify_super" and kw["leg_name"] == "STOP_LOSS_LEG" and kw["stopLossPrice"] == 2860.0
    await adapter.cancel_super_order(session, "SUP1", "target_leg", _router_token=_ROUTER_TOKEN)
    assert mock.calls[1] == ("cancel_super", "SUP1", "TARGET_LEG")
    rows = await adapter.super_orders(session)
    assert rows[0]["orderid"] == "SUP1" and rows[0]["legs"] == [{"legName": "STOP_LOSS_LEG"}]


async def test_cancel_super_order_rejects_unknown_leg() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(BrokerError, match="leg"):
        await adapter.cancel_super_order(session, "SUP1", "MIDDLE_LEG", _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


# ---------------------------------------------------------------------------
# Order reads
# ---------------------------------------------------------------------------


async def test_get_order_by_id_unwraps_single_element_array() -> None:
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    order = await adapter.get_order_by_id(session, "OID1")
    assert order["orderid"] == "OID1" and order["symbol"] == "TCS" and order["exchange"] == "NSE"


async def test_get_order_by_correlation_id() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = await adapter.get_order_by_correlation_id(session, "FT-1")
    assert mock.calls[0] == ("order_by_corr", "FT-1")
    assert order["orderid"] == "OID9" and order["action"] == "SELL" and order["product"] == "MIS"


# ---------------------------------------------------------------------------
# Convert position
# ---------------------------------------------------------------------------


async def test_convert_position_maps_and_calls_sdk() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.convert_position(
        session,
        {"symbol": "RELIANCE", "exchange": "NSE", "from_product": "MIS", "to_product": "CNC",
         "position_type": "LONG", "quantity": 40},
        _router_token=_ROUTER_TOKEN,
    )
    kind, kw = mock.calls[0]
    assert kind == "convert"
    assert kw["from_product_type"] == "INTRADAY" and kw["to_product_type"] == "CNC"
    assert kw["security_id"] == "11536" and kw["convert_qty"] == 40


async def test_convert_position_fails_closed_before_broker() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(DhanMappingError, match="positive quantity"):
        await adapter.convert_position(
            session,
            {"symbol": "RELIANCE", "exchange": "NSE", "from_product": "MIS", "to_product": "CNC",
             "position_type": "LONG", "quantity": 0},
            _router_token=_ROUTER_TOKEN,
        )
    assert mock.calls == []


# ---------------------------------------------------------------------------
# Conditional triggers (v2.5 via DhanHTTP)
# ---------------------------------------------------------------------------


async def test_place_conditional_trigger_posts_doc_endpoint() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("POST", "/alerts/orders")] = {
        "status": "success", "data": {"alertId": "12345", "alertStatus": "ACTIVE"},
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    alert_id = await adapter.place_conditional_trigger(
        session, _CONDITION, [_leg_order()], _router_token=_ROUTER_TOKEN
    )
    assert alert_id == "12345"
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("POST", "/alerts/orders")
    assert payload["condition"]["operator"] == "CROSSING_UP"
    assert payload["orders"][0]["securityId"] == "11536" and payload["orders"][0]["discQuantity"] == "0"


async def test_modify_and_cancel_conditional_trigger() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("PUT", "/alerts/orders/12345")] = {
        "status": "success", "data": {"alertId": "12345", "alertStatus": "ACTIVE"},
    }
    mock.dhan_http.responses[("DELETE", "/alerts/orders/12345")] = {
        "status": "success", "data": {"alertId": "12345", "alertStatus": "CANCELLED"},
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_conditional_trigger(
        session, "12345", _CONDITION, [_leg_order()], _router_token=_ROUTER_TOKEN
    )
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("PUT", "/alerts/orders/12345") and payload["alertId"] == "12345"
    await adapter.cancel_conditional_trigger(session, "12345", _router_token=_ROUTER_TOKEN)
    assert mock.dhan_http.calls[1] == ("DELETE", "/alerts/orders/12345", None)


async def test_conditional_trigger_reads() -> None:
    mock = MockDhan()
    record = {"alertId": "12345", "alertStatus": "ACTIVE", "condition": _CONDITION, "orders": []}
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": [record]}
    mock.dhan_http.responses[("GET", "/alerts/orders/12345")] = {"status": "success", "data": record}
    adapter = _adapter(mock)
    session = await _session(adapter)
    triggers = await adapter.conditional_triggers(session)
    assert len(triggers) == 1 and triggers[0]["alert_id"] == "12345"
    one = await adapter.get_conditional_trigger(session, "12345")
    assert one["status"] == "ACTIVE" and one["condition"]["securityId"] == "11536"


async def test_conditional_trigger_failure_raises() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("POST", "/alerts/orders")] = {
        "status": "failure", "remarks": {"error_message": "segment not enabled"}, "data": "",
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(DhanMappingError, match="segment not enabled"):
        await adapter.place_conditional_trigger(session, _CONDITION, [_leg_order()],
                                                _router_token=_ROUTER_TOKEN)


# ---------------------------------------------------------------------------
# Trader's Control: status / P&L exit / Exit All
# ---------------------------------------------------------------------------


async def test_kill_switch_status_read() -> None:
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    status = await adapter.kill_switch_status(session)
    assert status["killSwitchStatus"] == "ACTIVATE"


async def test_pnl_exit_set_get_stop() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("POST", "/pnlExit")] = {
        "status": "success", "data": {"pnlExitStatus": "ACTIVE", "message": "configured"},
    }
    mock.dhan_http.responses[("GET", "/pnlExit")] = {
        "status": "success", "data": {"pnlExitStatus": "ACTIVE", "profit": "1500.0", "loss": "500.0"},
    }
    mock.dhan_http.responses[("DELETE", "/pnlExit")] = {
        "status": "success", "data": {"pnlExitStatus": "DISABLED", "message": "stopped"},
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    set_resp = await adapter.set_pnl_exit(session, 1500, 500, ["MIS"], enable_kill_switch=True)
    assert set_resp["pnlExitStatus"] == "ACTIVE"
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("POST", "/pnlExit")
    assert payload == {"profitValue": "1500.0", "lossValue": "500.0",
                       "productType": ["INTRADAY"], "enableKillSwitch": True}
    get_resp = await adapter.get_pnl_exit(session)
    assert get_resp["profit"] == "1500.0"
    stop_resp = await adapter.stop_pnl_exit(session)
    assert stop_resp["pnlExitStatus"] == "DISABLED"
    assert mock.dhan_http.calls[2] == ("DELETE", "/pnlExit", None)


async def test_pnl_exit_validation_fails_closed() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(DhanMappingError, match="profit_value or loss_value"):
        await adapter.set_pnl_exit(session, 0, 0)
    assert mock.dhan_http.calls == []


async def test_exit_all_positions_gated_delete() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("DELETE", "/positions")] = {
        "status": "success",
        "data": {"status": "SUCCESS", "message": "All orders and positions exited successfully"},
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    resp = await adapter.exit_all_positions(session, _router_token=_ROUTER_TOKEN)
    assert resp["status"] == "SUCCESS"
    assert mock.dhan_http.calls == [("DELETE", "/positions", None)]


# ---------------------------------------------------------------------------
# EDIS
# ---------------------------------------------------------------------------


async def test_generate_tpin_and_inquiry() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    tpin = await adapter.generate_tpin(session)
    assert tpin["remarks"] == "OTP sent"
    inquiry = await adapter.edis_inquiry(session, "INE733E01010")
    assert mock.calls[1] == ("edis_inquiry", "INE733E01010")
    assert inquiry["aprvdQty"] == 4
    default = await adapter.edis_inquiry(session)
    assert mock.calls[2] == ("edis_inquiry", "ALL") and default["isin"] == "ALL"


async def test_edis_form_is_headless_and_unescapes() -> None:
    mock = MockDhan()
    mock.dhan_http.responses[("POST", "/edis/form")] = {
        "status": "success",
        "data": {"dhanClientId": "C1", "edisFormHtml": "<form action=\\\"https://edis.cdslindia.com\\\">"},
    }
    adapter = _adapter(mock)
    session = await _session(adapter)
    form = await adapter.edis_form(session, "INE733E01010", 1, "NSE", bulk=True)
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("POST", "/edis/form")
    assert payload == {"isin": "INE733E01010", "qty": 1, "exchange": "NSE", "segment": "EQ", "bulk": True}
    # the escaped backslashes are stripped for direct rendering — no browser opened
    assert form["edis_form_html"] == '<form action="https://edis.cdslindia.com">'


# ---------------------------------------------------------------------------
# Auth surface: profile / token / static IP
# ---------------------------------------------------------------------------


async def test_user_profile_and_token_helpers() -> None:
    login = MockLogin("C1")
    adapter = _adapter(MockDhan(), login=login)
    session = await _session(adapter)
    profile = await adapter.user_profile(session)
    assert profile["dhanClientId"] == "C1" and login.calls[0] == ("profile", "TOK")
    generated = await adapter.generate_token("C1", "123456", "000000")
    assert generated["accessToken"] == "NEWTOK" and login.calls[1] == ("generate", "123456", "000000")
    renewed = await adapter.renew_token(session)
    assert renewed["accessToken"] == "RENEWED" and login.calls[2] == ("renew", "TOK")


async def test_static_ip_management() -> None:
    login = MockLogin("C1")
    adapter = _adapter(MockDhan(), login=login)
    session = await _session(adapter)
    set_resp = await adapter.set_ip(session, "10.200.10.10", "primary")
    assert set_resp["status"] == "SUCCESS" and login.calls[0] == ("set_ip", "10.200.10.10", "PRIMARY")
    await adapter.modify_ip(session, "10.200.10.11", "SECONDARY")
    assert login.calls[1] == ("modify_ip", "10.200.10.11", "SECONDARY")
    ips = await adapter.get_ip(session)
    assert ips["primaryIP"] == "10.0.0.1" and login.calls[2] == ("get_ip",)


# ---------------------------------------------------------------------------
# Scrip master helper
# ---------------------------------------------------------------------------


async def test_fetch_security_list_parses_csv_rows() -> None:
    csv_text = (
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_TRADING_SYMBOL\n"
        "NSE,E,11536,TCS\nBSE,E,532540,TCS\n"
    )
    seen: list[str] = []

    def downloader(url: str) -> str:
        seen.append(url)
        return csv_text

    adapter = _adapter(MockDhan())
    rows = await adapter.fetch_security_list("compact", downloader=downloader)
    assert seen == ["https://images.dhan.co/api-data/api-scrip-master.csv"]
    assert rows[0]["SEM_SMST_SECURITY_ID"] == "11536" and rows[1]["SEM_EXM_EXCH_ID"] == "BSE"
    # rows feed straight into the mapping-layer resolver
    from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver

    resolve = build_security_resolver(rows)
    assert resolve("TCS", "NSE") == "11536"


async def test_fetch_security_list_rejects_unknown_mode() -> None:
    adapter = _adapter(MockDhan())
    with pytest.raises(BrokerError, match="compact"):
        await adapter.fetch_security_list("gigantic")


# ---------------------------------------------------------------------------
# Expired (rolling) options data
# ---------------------------------------------------------------------------


async def test_expired_options_maps_request_and_response() -> None:
    mock = MockDhan()
    adapter = DhanAdapter(client_factory=lambda _s: mock)  # NIFTY resolves via index fast path
    session = await _session(adapter)
    out = await adapter.expired_options(session, {
        "symbol": "NIFTY", "exchange": "NFO", "instrument": "OPTIDX", "expiry_flag": "MONTH",
        "expiry_code": 1, "strike": "ATM", "option_type": "CALL",
        "required_data": ["open", "close"], "from_date": "2021-08-01", "to_date": "2021-09-01",
        "interval": 1,
    })
    kind, kw = mock.calls[0]
    assert kind == "expired_options"
    assert kw["security_id"] == "13" and kw["exchange_segment"] == "NSE_FNO"
    assert kw["expiry_flag"] == "MONTH" and kw["drv_option_type"] == "CALL"
    assert out["ce"]["open"] == [354, 360.3] and out["pe"] is None


async def test_expired_options_validates_before_broker() -> None:
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(DhanMappingError, match="interval"):
        await adapter.expired_options(session, {"symbol": "NIFTY", "interval": 7,
                                                "from_date": "2025-01-01", "to_date": "2025-01-30"})
    assert mock.calls == []


# ---------------------------------------------------------------------------
# Subscribe modes
# ---------------------------------------------------------------------------


async def test_subscribe_records_mode_request_codes() -> None:
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"], mode="TICKER")
    assert adapter._feed_modes["11536"] == 15
    await adapter.subscribe(session, ["NSE:RELIANCE"], mode="QUOTE")
    assert adapter._feed_modes["11536"] == 17
    await adapter.subscribe(session, ["NSE:RELIANCE"])  # default FULL
    assert adapter._feed_modes["11536"] == 21
    await adapter.unsubscribe(session, ["NSE:RELIANCE"])
    assert "11536" not in adapter._feed_modes and "11536" not in adapter._feed_map


async def test_subscribe_rejects_unknown_mode() -> None:
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    with pytest.raises(DhanMappingError, match="feed mode"):
        await adapter.subscribe(session, ["NSE:RELIANCE"], mode="HYPER")


# ---------------------------------------------------------------------------
# Order-update stream
# ---------------------------------------------------------------------------

_ORDER_ALERT = {
    "Type": "order_alert",
    "Data": {"OrderNo": "1124091136546", "Status": "Traded", "Symbol": "IDEA", "Exchange": "NSE",
             "TxnType": "B", "OrderType": "LMT", "Product": "C", "Quantity": 1, "TradedQty": 1,
             "Price": 13, "AvgTradedPrice": 13},
}


async def test_stream_order_updates_decodes_and_skips() -> None:
    async def fake_frames(_session) -> AsyncIterator[Any]:
        yield {"Type": "heartbeat"}  # skipped
        yield _ORDER_ALERT  # dict frame
        yield json.dumps(_ORDER_ALERT)  # raw JSON text frame

    adapter = _adapter(MockDhan(), order_feed_factory=fake_frames)
    session = await _session(adapter)
    updates = [u async for u in adapter.stream_order_updates(session)]
    assert len(updates) == 2
    assert updates[0]["orderid"] == "1124091136546" and updates[0]["status"] == "Traded"
    assert updates[1]["action"] == "BUY" and updates[1]["product"] == "CNC"


# ---------------------------------------------------------------------------
# Depth streams (20 / 200 level)
# ---------------------------------------------------------------------------


def _depth_frame(msg_code: int, security_id: int, rows: list[tuple[float, int, int]]) -> bytes:
    body = b"".join(struct.pack("<dII", price, qty, orders) for price, qty, orders in rows)
    return struct.pack("<hBBiI", 12 + len(body), msg_code, 1, security_id, len(rows)) + body


async def test_stream_depth_decodes_and_routes_symbols() -> None:
    frame = _depth_frame(41, 11536, [(2901.5, 100, 3)]) + _depth_frame(51, 11536, [(2902.0, 80, 4)])
    levels_seen: list[int] = []

    async def fake_depth(_session, level: int) -> AsyncIterator[bytes]:
        levels_seen.append(level)
        yield frame

    adapter = _adapter(MockDhan(), depth_feed_factory=fake_depth)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    messages = [msg async for msg in adapter.stream_depth(session, level=20)]
    assert levels_seen == [20]
    assert [msg["side"] for msg in messages] == ["bid", "ask"]
    assert messages[0]["symbol"] == "RELIANCE" and messages[0]["exchange"] == "NSE"
    assert messages[0]["depth"][0] == {"price": 2901.5, "quantity": 100, "orders": 3}


async def test_stream_depth_200_level_uses_same_decoder() -> None:
    async def fake_depth(_session, level: int) -> AsyncIterator[bytes]:
        yield _depth_frame(41, 11536, [(2901.5 - i, 10, 1) for i in range(25)])

    adapter = _adapter(MockDhan(), depth_feed_factory=fake_depth)
    session = await _session(adapter)
    messages = [msg async for msg in adapter.stream_depth(session, level=200)]
    assert len(messages) == 1 and len(messages[0]["depth"]) == 25 and messages[0]["rows"] == 25


async def test_stream_depth_requires_factory_and_valid_level() -> None:
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="depth_feed_factory"):
        async for _ in adapter.stream_depth(session):
            pass  # pragma: no cover - generator raises on first advance

    async def fake_depth(_session, level: int) -> AsyncIterator[bytes]:
        yield b""  # pragma: no cover - level validation raises first

    adapter = _adapter(MockDhan(), depth_feed_factory=fake_depth)
    with pytest.raises(BrokerError, match="depth level"):
        async for _ in adapter.stream_depth(session, level=7):
            pass  # pragma: no cover


# ---------------------------------------------------------------------------
# G7 — replayable-credential payload
# ---------------------------------------------------------------------------


def test_replay_credentials_drops_totp_and_keeps_minted_token() -> None:
    from flinttrade_gateway.brokers._base import Session

    adapter = DhanAdapter(client_factory=lambda _s: object())
    session = Session(access_token="minted-24h", expires_at=9e9, account_id="111", adapter_id="dhan")
    replay = adapter.replay_credentials(
        {"client_id": "111", "pin": "1234", "totp": "000111"}, session
    )
    assert replay == {"client_id": "111", "pin": "1234", "access_token": "minted-24h"}
