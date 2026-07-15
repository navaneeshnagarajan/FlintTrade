"""Tests for the Dhan adapter (mock dhanhq client; no SDK / creds needed)."""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


def test_recent_triggered_alert_remains_unresolved_during_settlement_window():
    triggered_at = datetime.now(timezone.utc) - timedelta(seconds=30)

    assert DhanAdapter._trigger_still_settling({"triggered_at": triggered_at.isoformat()})


def test_old_triggered_alert_expires_from_settlement_window():
    triggered_at = datetime.now(timezone.utc) - timedelta(minutes=10)

    assert not DhanAdapter._trigger_still_settling({"triggered_at": triggered_at.isoformat()})


@pytest.mark.parametrize("triggered_at", [None, "", "not-a-timestamp"])
def test_unknown_trigger_time_fails_closed(triggered_at):
    assert DhanAdapter._trigger_still_settling({"triggered_at": triggered_at})


class MockHTTP:
    """Stand-in for the SDK's DhanHTTP transport (direct-endpoint paths)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    def _respond(self, method: str, endpoint: str, payload: dict | None = None) -> dict:
        self.calls.append((method, endpoint, payload))
        return self.responses.get(
            (method, endpoint), {"status": "success", "data": {"orderId": "OID1", "orderStatus": "TRANSIT"}}
        )

    def get(self, endpoint):
        return self._respond("GET", endpoint)

    def post(self, endpoint, payload):
        return self._respond("POST", endpoint, payload)

    def put(self, endpoint, payload):
        return self._respond("PUT", endpoint, payload)

    def delete(self, endpoint):
        return self._respond("DELETE", endpoint)


class MockDhan:
    """Stand-in for the synchronous dhanhq 2.2.0 client."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.dhan_http = MockHTTP()

    def place_order(self, **kw):
        self.calls.append(("place", kw))
        return {"status": "success", "data": {"orderId": "OID1", "orderStatus": "TRANSIT"}}

    def place_super_order(self, **kw):
        self.calls.append(("super", kw))
        return {"status": "success", "data": {"orderId": "SUP1", "orderStatus": "TRANSIT"}}

    def place_slice_order(self, **kw):
        self.calls.append(("slice", kw))
        return {"status": "success", "data": {"orderId": "SLC1", "orderStatus": "TRANSIT"}}

    def place_forever(self, **kw):
        self.calls.append(("forever", kw))
        return {"status": "success", "data": {"orderId": "GTT1", "orderStatus": "TRANSIT"}}

    def margin_calculator(self, **kw):
        self.calls.append(("margin", kw))
        return {
            "status": "success",
            "data": {
                "totalMargin": 14500.0,
                "spanMargin": 12000.0,
                "exposureMargin": 2500.0,
                "availableBalance": 50000.0,
            },
        }

    def expiry_list(self, under_security_id, under_exchange_segment):
        self.calls.append(("expiry", (under_security_id, under_exchange_segment)))
        return {"status": "success", "data": {"data": ["2026-06-26", "2026-07-31"]}}

    def kill_switch(self, action):
        self.calls.append(("kill", action))
        return {"status": "success", "data": {"killSwitchStatus": action}}

    def get_trade_history(self, from_date, to_date, page_number):
        self.calls.append(("trade_history", (from_date, to_date, page_number)))
        return {
            "status": "success",
            "data": [
                {"orderId": "1", "customSymbol": "TCS", "tradedQuantity": 5, "tradedPrice": 3499},
            ],
        }

    def ledger_report(self, from_date, to_date):
        self.calls.append(("ledger", (from_date, to_date)))
        return {"status": "success", "data": [{"voucherdate": "2026-06-01", "debit": 0, "credit": 5000}]}

    def modify_order(self, **kw):
        self.calls.append(("modify", kw))
        return {"status": "success", "data": {"orderId": "OID1"}}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {"status": "success", "data": {"orderId": order_id}}

    def get_order_list(self):
        return {
            "status": "success",
            "data": [
                {
                    "orderId": "1",
                    "tradingSymbol": "TCS",
                    "exchangeSegment": "NSE_EQ",
                    "transactionType": "BUY",
                    "orderType": "LIMIT",
                    "productType": "CNC",
                    "orderStatus": "PENDING",
                    "quantity": 5,
                    "price": 3500,
                },
            ],
        }

    def get_trade_book(self):
        return {
            "status": "success",
            "data": [
                {
                    "orderId": "1",
                    "tradingSymbol": "TCS",
                    "exchangeSegment": "NSE_EQ",
                    "transactionType": "BUY",
                    "tradedQuantity": 5,
                    "tradedPrice": 3499,
                },
            ],
        }

    def get_positions(self):
        return {
            "status": "success",
            "data": [
                {
                    "tradingSymbol": "INFY",
                    "exchangeSegment": "NSE_EQ",
                    "productType": "CNC",
                    "netQty": 10,
                    "costPrice": 1500,
                },
            ],
        }

    def get_holdings(self):
        return {
            "status": "success",
            "data": [
                {"tradingSymbol": "SBIN", "exchange": "NSE", "totalQty": 50, "avgCostPrice": 600},
            ],
        }

    def get_fund_limits(self):
        return {"status": "success", "data": {"availabelBalance": 50000, "utilizedAmount": 12000}}

    def quote_data(self, securities):
        self.calls.append(("quote", securities))
        return {
            "status": "success",
            "data": {
                "NSE_EQ": {
                    "11536": {
                        "last_price": 2901.5,
                        "ohlc": {"open": 2890, "high": 2910, "low": 2885, "close": 2888},
                        "volume": 1_200_000,
                    }
                }
            },
        }

    def intraday_minute_data(
        self, security_id, exchange_segment, instrument_type, from_date, to_date, interval=1, oi=False
    ):
        self.calls.append(("intraday", security_id, interval))
        return {
            "status": "success",
            "data": {
                "open": [100, 101],
                "high": [102, 103],
                "low": [99, 100],
                "close": [101, 102],
                "volume": [1000, 1500],
                "timestamp": [1, 2],
            },
        }

    def historical_daily_data(
        self, security_id, exchange_segment, instrument_type, from_date, to_date, expiry_code=0, oi=False
    ):
        self.calls.append(("daily", security_id))
        return {
            "status": "success",
            "data": {
                "open": [100],
                "high": [102],
                "low": [99],
                "close": [101],
                "volume": [1000],
                "timestamp": [1],
            },
        }

    def option_chain(self, under_security_id, under_exchange_segment, expiry):
        self.calls.append(("option_chain", under_security_id, expiry))
        return {
            "status": "success",
            "data": {
                "oc": {
                    "24000.000000": {
                        "ce": {"last_price": 150, "oi": 1000, "greeks": {"delta": 0.5}},
                        "pe": {"last_price": 140, "oi": 1200, "greeks": {"delta": -0.5}},
                    }
                }
            },
        }


class _TestSecurityResolver:
    def __call__(self, symbol: str, exchange: str) -> str:
        if (symbol, exchange) == ("NIFTY-Jul2026-25000-CE", "NFO"):
            return "49081"
        return "11536"

    @staticmethod
    def reverse(security_id: str, exchange: str) -> dict[str, object]:
        if (security_id, exchange) != ("49081", "NFO"):
            raise ValueError("unknown test contract")
        return {
            "security_id": "49081",
            "exchange": "NFO",
            "symbol": "NIFTY-Jul2026-25000-CE",
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }


def _adapter(mock):
    return DhanAdapter(client_factory=lambda _s: mock, security_resolver=_TestSecurityResolver())


async def _session(adapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


@pytest.mark.asyncio
async def test_login_returns_session():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    assert session.adapter_id == "dhan"
    assert session.account_id == "C1"
    assert session.access_token == "TOK"


@pytest.mark.asyncio
async def test_login_requires_access_token():
    from flinttrade_core.exceptions import BrokerError

    with pytest.raises(BrokerError, match="access_token"):
        await DhanAdapter().login({"client_id": "C1"})


@pytest.mark.asyncio
async def test_login_with_pin_totp_mints_a_token():
    """PIN + TOTP path: login() orchestrates generate_token() to mint a fresh
    24h access token, then logs in with it (no console token needed)."""
    from unittest.mock import MagicMock

    login_helper = MagicMock()
    login_helper.generate_token.return_value = {"accessToken": "MINTED-TOK", "expiryTime": "..."}
    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        login_factory=lambda _client_id: login_helper,
    )
    session = await adapter.login({"client_id": "C1", "pin": "1234", "totp": "654321"})
    assert session.access_token == "MINTED-TOK"
    assert session.account_id == "C1"
    login_helper.generate_token.assert_called_once_with("1234", "654321")


@pytest.mark.asyncio
async def test_login_with_oauth_token_id_consumes_a_token():
    """Dhan app-consent OAuth returns a tokenId, which login() consumes into a
    normal 24h access token before building the Dhan session."""
    from unittest.mock import MagicMock

    login_helper = MagicMock()
    login_helper.consume_token_id.return_value = {"accessToken": "OAUTH-TOK", "expiryTime": "..."}
    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        login_factory=lambda _client_id: login_helper,
    )
    session = await adapter.login(
        {
            "client_id": "C1",
            "token_id": "TOKENID1",
            "app_id": "APPID",
            "app_secret": "SECRET",
        }
    )
    assert session.access_token == "OAUTH-TOK"
    assert session.account_id == "C1"
    login_helper.consume_token_id.assert_called_once_with("TOKENID1", "APPID", "SECRET")


@pytest.mark.asyncio
async def test_login_with_oauth_token_id_hides_failed_token_payload():
    from flinttrade_core.exceptions import BrokerError
    from unittest.mock import MagicMock

    login_helper = MagicMock()
    login_helper.consume_token_id.return_value = {
        "status": "failure",
        "dhanClientId": "C1",
        "message": "secret.person@example.com",
    }
    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        login_factory=lambda _client_id: login_helper,
    )
    with pytest.raises(BrokerError) as excinfo:
        await adapter.login(
            {
                "client_id": "C1",
                "token_id": "TOKENID1",
                "app_id": "APPID",
                "app_secret": "SECRET",
            }
        )
    assert str(excinfo.value) == "Dhan OAuth token consumption failed"
    assert "secret.person@example.com" not in str(excinfo.value)
    assert "TOKENID1" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_login_with_pin_totp_hides_failed_token_payload():
    from flinttrade_core.exceptions import BrokerError
    from unittest.mock import MagicMock

    login_helper = MagicMock()
    login_helper.generate_token.return_value = {
        "status": "failure",
        "dhanClientId": "C1",
        "message": "9999999999",
    }
    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        login_factory=lambda _client_id: login_helper,
    )
    with pytest.raises(BrokerError) as excinfo:
        await adapter.login({"client_id": "C1", "pin": "1234", "totp": "654321"})
    assert str(excinfo.value) == "Dhan PIN+TOTP token generation failed"
    assert "9999999999" not in str(excinfo.value)
    assert "654321" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_login_pin_totp_requires_client_id():
    from flinttrade_core.exceptions import BrokerError

    with pytest.raises(BrokerError, match="client_id"):
        await DhanAdapter().login({"pin": "1234", "totp": "654321"})


@pytest.mark.asyncio
async def test_place_order_is_gated():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)  # no router token
    assert mock.calls == []  # never reached the SDK


@pytest.mark.asyncio
async def test_place_order_with_router_token():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="3", price="2900"
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "OID1"
    kind, kw = mock.calls[0]
    assert kind == "place"
    assert kw["security_id"] == "11536"
    assert kw["exchange_segment"] == "NSE_EQ"
    assert kw["order_type"] == "LIMIT"
    assert kw["product_type"] == "CNC"


@pytest.mark.asyncio
async def test_bracket_order_dispatches_to_super_order():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="5",
        price="2900",
        variety="bracket",
        target_price="2950",
        stop_loss_price="2870",
        trailing_jump="5",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "SUP1"
    kind, kw = mock.calls[0]
    assert kind == "super"  # routed to place_super_order, not place_order
    assert kw["targetPrice"] == 2950.0 and kw["stopLossPrice"] == 2870.0 and kw["trailingJump"] == 5.0


@pytest.mark.asyncio
async def test_cover_order_has_stop_loss_only():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="5",
        price="2900",
        variety="cover",
        target_price="2950",
        stop_loss_price="2870",
    )
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    kind, kw = mock.calls[0]
    assert kind == "super" and kw["stopLossPrice"] == 2870.0
    assert kw["targetPrice"] == 0.0  # cover orders drop the target leg


@pytest.mark.asyncio
async def test_iceberg_order_dispatches_to_slice_order():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="SELL",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="5000",
        price="2900",
        variety="iceberg",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "SLC1"
    assert mock.calls[0][0] == "slice"


@pytest.mark.asyncio
async def test_gtt_order_dispatches_to_place_forever():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="5",
        price="2900",
        trigger_price="2890",
        variety="gtt",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "GTT1"
    kind, kw = mock.calls[0]
    assert kind == "forever" and kw["trigger_Price"] == 2890.0 and kw["order_flag"] == "SINGLE"


@pytest.mark.asyncio
async def test_gtt_oco_order_dispatches_to_place_forever_with_second_leg():
    """The OCO leg trio on a gtt Order flips the forever order to OCO and maps
    the forever.md price1/triggerPrice1/quantity1 fields — same gated method."""
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="5",
        price="2900",
        trigger_price="2890",
        variety="gtt",
        price1="2800",
        trigger_price1="2805",
        quantity1="5",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "GTT1"
    kind, kw = mock.calls[0]
    assert kind == "forever" and kw["order_flag"] == "OCO"
    assert kw["price1"] == 2800.0 and kw["trigger_Price1"] == 2805.0 and kw["quantity1"] == 5


@pytest.mark.asyncio
async def test_gtt_partial_oco_leg_fails_closed():
    from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="5",
        price="2900",
        trigger_price="2890",
        variety="gtt",
        price1="2800",
    )  # trigger_price1 + quantity1 missing
    with pytest.raises(DhanMappingError, match="OCO"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []  # never reached the broker


@pytest.mark.asyncio
async def test_gtt_without_trigger_fails_closed():
    from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="5",
        price="2900",
        variety="gtt",
    )  # no trigger_price
    with pytest.raises(DhanMappingError, match="trigger_price"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls == []  # never reached the broker


@pytest.mark.asyncio
async def test_advanced_order_still_requires_router_token():
    # The gating invariant must hold for EVERY variety, not just regular orders.
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="5",
        price="2900",
        variety="bracket",
        stop_loss_price="2870",
    )
    with pytest.raises(SafetyBypassError):
        await adapter.place_order(session, order)  # no token
    assert mock.calls == []  # never reached the SDK


@pytest.mark.asyncio
async def test_amo_order_posts_orders_payload_with_amotime():
    """An ``amo`` variety POSTs /orders directly via DhanHTTP with
    afterMarketOrder + amoTime on the wire, instead of the SDK place_order
    (which drops amoTime). The SDK place_order is never touched."""
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="5",
        price="2900",
        variety="amo",
    )
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "OID1"
    assert mock.calls == []  # the SDK place_order endpoint was NOT used
    method, endpoint, payload = mock.dhan_http.calls[0]
    assert (method, endpoint) == ("POST", "/orders")
    assert payload["afterMarketOrder"] is True and payload["amoTime"] == "OPEN"


@pytest.mark.asyncio
async def test_amo_order_is_advertised_in_capabilities():
    # AMO is advertised in order_types, so dispatch must support it (regression:
    # it previously fell through to the unsupported-variety BrokerError).
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES
    from flinttrade_gateway.capabilities import OrderTypes

    assert DHAN_CAPABILITIES.order_types & OrderTypes.AMO


@pytest.mark.asyncio
async def test_capabilities_historical_metadata_is_honest():
    """Regression: the 5000 candles-per-request cap was fabricated and 90 days is
    the per-request range, not the lookback (historical-data.md)."""
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES

    assert DHAN_CAPABILITIES.historical_max_candles_per_request == 0  # unknown, not 5000
    # ~5 years of intraday history; 90 is the per-request range cap, not lookback.
    assert DHAN_CAPABILITIES.historical_max_lookback_days_intraday == 1825


@pytest.mark.asyncio
async def test_quotes_handle_double_nested_live_payload():
    """Regression: live quotes are double-wrapped (data.data.<SEGMENT>); the
    adapter must still surface a Quote (market-quote.md doc-exact envelope)."""

    class _DoubleWrapped(MockDhan):
        def quote_data(self, securities):
            return {
                "status": "success",
                "data": {
                    "data": {
                        "NSE_EQ": {
                            "11536": {
                                "last_price": 4525.55,
                                "ohlc": {"open": 4521.45, "close": 4507.85, "high": 4530, "low": 4500},
                                "oi": 0,
                                "volume": 0,
                            }
                        }
                    },
                    "status": "success",
                },
            }

    adapter = _adapter(_DoubleWrapped())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    assert len(quotes) == 1
    assert quotes[0].ltp == 4525.55 and quotes[0].open == 4521.45


@pytest.mark.asyncio
async def test_option_chain_handles_double_nested_live_payload():
    """Regression: live option chain is data.data.{oc} (option-chain.md); the
    adapter must return non-empty strikes through the double-nest."""

    class _DoubleWrapped(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {
                "status": "success",
                "data": {
                    "data": {
                        "last_price": 25642.8,
                        "oc": {
                            "25650.000000": {
                                "ce": {"last_price": 134, "oi": 3786445, "greeks": {"delta": 0.53871}},
                                "pe": {"last_price": 132.8, "oi": 3096145, "greeks": {"delta": -0.46732}},
                            },
                        },
                    },
                    "status": "success",
                },
            }

    adapter = DhanAdapter(client_factory=lambda _s: _DoubleWrapped())  # NIFTY index fast path
    session = await _session(adapter)
    oc = await adapter.option_chain(session, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2026-06-25"})
    assert len(oc.strikes) == 1
    assert oc.strikes[0].strike_price == 25650.0 and oc.strikes[0].ce_ltp == 134.0


@pytest.mark.asyncio
async def test_unsupported_variety_raises():
    from flinttrade_core.exceptions import BrokerError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1")
    object.__setattr__(order, "variety", "exotic")
    with pytest.raises(BrokerError, match="variety"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_margin_calculator_reads_estimate():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="2900"
    )
    # No router token needed — margin calc is a read-only pre-trade estimate.
    margin = await adapter.margin_calculator(session, order)
    assert margin["total_margin"] == "14500.0" and margin["available_balance"] == "50000.0"
    assert mock.calls[0][0] == "margin"


@pytest.mark.asyncio
async def test_expiry_list_returns_dates():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    expiries = await adapter.expiry_list(session, "NIFTY", "NSE_INDEX")
    assert expiries == ["2026-06-26", "2026-07-31"]


@pytest.mark.asyncio
async def test_trade_history_and_ledger_reads():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    trades = await adapter.trade_history(session, "2026-06-01", "2026-06-05", 0)
    assert len(trades) == 1 and trades[0]["customSymbol"] == "TCS"
    assert mock.calls[0] == ("trade_history", ("2026-06-01", "2026-06-05", 0))
    ledger = await adapter.ledger(session, "2026-06-01", "2026-06-05")
    assert len(ledger) == 1 and ledger[0]["credit"] == 5000


@pytest.mark.asyncio
async def test_kill_switch_validates_and_relays():
    from flinttrade_core.exceptions import BrokerError

    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    resp = await adapter.kill_switch(session, "activate")  # case-insensitive
    assert resp["killSwitchStatus"] == "ACTIVATE"
    assert mock.calls[0] == ("kill", "ACTIVATE")
    with pytest.raises(BrokerError, match="ACTIVATE or DEACTIVATE"):
        await adapter.kill_switch(session, "maybe")


@pytest.mark.asyncio
async def test_kill_switch_non_dict_response_fallback():
    class _ScalarKill(MockDhan):
        def kill_switch(self, action):
            return "ACTIVATED"  # some builds return a bare string

    adapter = _adapter(_ScalarKill())
    session = await _session(adapter)
    resp = await adapter.kill_switch(session, "ACTIVATE")
    assert resp == {"status": "ACTIVATED"}  # wrapped, not crashed


@pytest.mark.asyncio
async def test_modify_and_cancel_gated_and_call_sdk():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(session, "OID1", {"quantity": 4, "price": 2950}, _router_token=_ROUTER_TOKEN)
    await adapter.cancel_order(session, "OID1", _router_token=_ROUTER_TOKEN)
    assert [c[0] for c in mock.calls] == ["modify", "cancel"]


@pytest.mark.asyncio
async def test_cancel_all_orders_refuses_adapter_expansion_and_plans_every_family():
    from flinttrade_core.exceptions import UnsupportedCapabilityError
    from flinttrade_engine.safety import EmergencyWritePolicy

    class SweepHTTP(MockHTTP):
        def __init__(self, owner):
            super().__init__()
            self.owner = owner

        def get(self, endpoint):
            self.calls.append(("GET", endpoint, None))
            if endpoint == "/alerts/orders":
                rows = (
                    []
                    if self.owner.conditional_cancelled
                    else [
                        {"alertId": "ALERT-1", "alertStatus": "ACTIVE", "orders": []},
                    ]
                )
                return {"status": "success", "data": rows}
            return {"status": "success", "data": {}}

        def delete(self, endpoint):
            self.calls.append(("DELETE", endpoint, None))
            if endpoint == "/alerts/orders/ALERT-1":
                self.owner.conditional_cancelled = True
            return {"status": "success", "data": {"alertId": "ALERT-1"}}

    class OrdersDhan(MockDhan):
        def __init__(self):
            super().__init__()
            self.regular_cancelled = False
            self.forever_cancelled = False
            self.super_cancelled = False
            self.conditional_cancelled = False
            self.dhan_http = SweepHTTP(self)

        def get_order_list(self):
            rows = [
                {
                    "orderId": "2",
                    "tradingSymbol": "INFY",
                    "exchangeSegment": "NSE_EQ",
                    "transactionType": "BUY",
                    "orderType": "LIMIT",
                    "productType": "CNC",
                    "orderStatus": "TRADED",
                    "quantity": 5,
                    "price": 1500,
                },
            ]
            if not self.regular_cancelled:
                rows.insert(
                    0,
                    {
                        "orderId": "1",
                        "tradingSymbol": "TCS",
                        "exchangeSegment": "NSE_EQ",
                        "transactionType": "BUY",
                        "orderType": "LIMIT",
                        "productType": "CNC",
                        "orderStatus": "PENDING",
                        "quantity": 5,
                        "price": 3500,
                    },
                )
            return {"status": "success", "data": rows}

        def cancel_order(self, order_id):
            self.calls.append(("cancel", order_id))
            self.regular_cancelled = True
            return {"status": "success", "data": {"orderId": order_id}}

        def get_forever(self):
            rows = (
                []
                if self.forever_cancelled
                else [
                    {"orderId": "GTT-1", "orderStatus": "PENDING"},
                ]
            )
            return {"status": "success", "data": rows}

        def cancel_forever(self, order_id):
            self.calls.append(("cancel_forever", order_id))
            self.forever_cancelled = True
            return {"status": "success", "data": {"orderId": order_id}}

        def get_super_order_list(self):
            rows = (
                []
                if self.super_cancelled
                else [
                    {"orderId": "SUPER-1", "orderStatus": "PENDING"},
                ]
            )
            return {"status": "success", "data": rows}

        def cancel_super_order(self, order_id, leg_name):
            self.calls.append(("cancel_super", order_id, leg_name))
            self.super_cancelled = True
            return {"status": "success", "data": {"orderId": order_id}}

    mock = OrdersDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(SafetyBypassError):
        await adapter.cancel_all_orders(session)
    with pytest.raises(UnsupportedCapabilityError, match="no native bulk-cancel"):
        await adapter.cancel_all_orders(session, _router_token=_ROUTER_TOKEN)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=EmergencyWritePolicy(name="dhan_cancel_plan", verbs=("cancel_all_orders",)),
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert [(write.verb, dict(write.payload)) for write in plan.writes] == [
        ("cancel_conditional_trigger", {"_op": "cancel_conditional_trigger", "alert_id": "ALERT-1"}),
        ("cancel_forever", {"_op": "cancel_forever", "order_id": "GTT-1"}),
        ("cancel_order", {"_op": "cancel_order", "order_id": "1"}),
        ("cancel_super_order", {"_op": "cancel_super_order", "order_id": "SUPER-1", "leg": "ENTRY_LEG"}),
    ]
    assert mock.calls == []
    assert not any(call[0] == "DELETE" for call in mock.dhan_http.calls)


@pytest.mark.asyncio
async def test_emergency_plan_fails_closed_when_pending_order_has_no_canonical_id():
    from flinttrade_engine.safety import EmergencyWritePolicy
    from flinttrade_gateway.brokers.dhan_mapping import DhanMappingError

    class MalformedActiveOrderDhan(MockDhan):
        def get_order_list(self):
            return {"status": "success", "data": [{"orderStatus": "PENDING"}]}

        def get_forever(self):
            return {"status": "success", "data": []}

        def get_super_order_list(self):
            return {"status": "success", "data": []}

    mock = MalformedActiveOrderDhan()
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": []}
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(DhanMappingError, match="canonical Dhan order id"):
        await adapter.plan_emergency_reduction(
            session,
            policy=EmergencyWritePolicy(name="dhan_malformed_active_order", verbs=("cancel_all_orders",)),
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_emergency_plan_never_cancels_a_protected_exit_order_id():
    from flinttrade_engine.safety import EmergencyWritePolicy

    class ProtectedExitDhan(MockDhan):
        def get_order_list(self):
            return {
                "status": "success",
                "data": [{"orderId": "EXIT-1", "orderStatus": "PENDING"}],
            }

        def get_forever(self):
            return {"status": "success", "data": []}

        def get_super_order_list(self):
            return {"status": "success", "data": []}

    mock = ProtectedExitDhan()
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": []}
    adapter = _adapter(mock)
    session = await _session(adapter)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=EmergencyWritePolicy(name="protected_dhan_exit", verbs=("cancel_all_orders",)),
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset({"EXIT-1"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_unidentified_dhan_exit_intent_blocks_every_cancellation_write():
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class UnidentifiedExitDhan(MockDhan):
        def get_forever(self):
            return {"status": "success", "data": []}

        def get_super_order_list(self):
            return {"status": "success", "data": []}

    mock = UnidentifiedExitDhan()
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": []}
    adapter = _adapter(mock)
    session = await _session(adapter)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
        unidentified_exit_inflight=True,
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders", "exit_all_positions"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_emergency_plan_keeps_position_pending_when_net_quantity_is_missing():
    from flinttrade_engine.safety import EmergencyWritePolicy

    class MalformedPositionDhan(MockDhan):
        def get_positions(self):
            return {
                "status": "success",
                "data": [
                    {
                        "tradingSymbol": "TCS",
                        "exchangeSegment": "NSE_EQ",
                        "productType": "INTRADAY",
                    }
                ],
            }

    adapter = _adapter(MalformedPositionDhan())
    session = await _session(adapter)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=EmergencyWritePolicy(name="dhan_malformed_position", verbs=("exit_all_positions",)),
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert [(write.verb, dict(write.payload)) for write in plan.writes] == [
        ("exit_all_positions", {"_op": "exit_all_positions"})
    ]


@pytest.mark.asyncio
async def test_order_readback_reports_an_accepted_but_still_active_order():
    class StickyDhan(MockDhan):
        def get_forever(self):
            return {"status": "success", "data": []}

        def get_super_order_list(self):
            return {"status": "success", "data": []}

    mock = StickyDhan()
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": []}
    adapter = _adapter(mock)
    session = await _session(adapter)

    active = await adapter._settled_active_order_targets(session)

    assert set(active) == {("regular", "1")}


def test_dhan_emergency_cancel_mints_one_gate_per_concrete_family_and_preserves_partial_outcome():
    import asyncio

    from flinttrade_core.exceptions import BrokerError
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_engine.safety import (
        EmergencyBrokerTarget,
        EmergencyWritePolicy,
        GatedEmergencyBrokerDispatcher,
        SafetyGate,
        set_safety_gate_secret,
    )
    from flinttrade_gateway.router import BrokerRouter

    set_safety_gate_secret(b"dhan-concrete-cancel-test-key-0001")

    class SweepHTTP(MockHTTP):
        def __init__(self, owner):
            super().__init__()
            self.owner = owner

        def get(self, endpoint):
            if endpoint == "/alerts/orders":
                rows = (
                    [{"alertId": "ALERT-1", "alertStatus": "ACTIVE", "orders": []}]
                    if "conditional" in self.owner.active
                    else []
                )
                return {"status": "success", "data": rows}
            return super().get(endpoint)

        def delete(self, endpoint):
            self.calls.append(("DELETE", endpoint, None))
            if endpoint == "/alerts/orders/ALERT-1":
                self.owner.cancel_calls.append(("conditional", "ALERT-1"))
                self.owner.active.discard("conditional")
            return {"status": "success", "data": {}}

    class PartialSweepDhan(MockDhan):
        def __init__(self):
            super().__init__()
            self.active = {"regular", "forever", "super", "conditional"}
            self.cancel_calls: list[tuple[str, str]] = []
            self.dhan_http = SweepHTTP(self)

        def get_order_list(self):
            rows = []
            if "regular" in self.active:
                rows.append(
                    {
                        "orderId": "REG-1",
                        "tradingSymbol": "TCS",
                        "exchangeSegment": "NSE_EQ",
                        "transactionType": "BUY",
                        "orderType": "LIMIT",
                        "productType": "CNC",
                        "orderStatus": "PENDING",
                        "quantity": 1,
                        "price": 1,
                    }
                )
            return {"status": "success", "data": rows}

        def cancel_order(self, order_id):
            self.cancel_calls.append(("regular", order_id))
            self.active.discard("regular")
            return {"status": "success", "data": {"orderId": order_id}}

        def get_forever(self):
            rows = [{"orderId": "GTT-1", "orderStatus": "PENDING"}] if "forever" in self.active else []
            return {"status": "success", "data": rows}

        def cancel_forever(self, order_id):
            self.cancel_calls.append(("forever", order_id))
            raise BrokerError("deliberate per-order refusal")

        def get_super_order_list(self):
            rows = [{"orderId": "SUPER-1", "orderStatus": "PENDING"}] if "super" in self.active else []
            return {"status": "success", "data": rows}

        def cancel_super_order(self, order_id, leg_name):
            assert leg_name == "ENTRY_LEG"
            self.cancel_calls.append(("super", order_id))
            self.active.discard("super")
            return {"status": "success", "data": {"orderId": order_id}}

    mock = PartialSweepDhan()
    adapter = _adapter(mock)
    session = asyncio.run(_session(adapter))
    request_ctx = RequestContext(
        jti="dhan-concrete-cancel-probe",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="dhan:C1",
    )
    target = EmergencyBrokerTarget(
        request_ctx=request_ctx,
        adapter_id="dhan",
        account_id="C1",
    )
    consumed_gate_ids: list[str] = []
    gate = SafetyGate()

    def consume_gate(gate_id: str) -> bool:
        consumed_gate_ids.append(gate_id)
        return gate.consume(gate_id)

    router = BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _adapter_id, _account_id: session,
        consume_gate=consume_gate,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=8,
        planned_readback_delay_seconds=0,
    )
    cancel_policy = EmergencyWritePolicy(
        name="dhan_concrete_cancel_probe",
        verbs=("cancel_all_orders",),
    )

    result = dispatcher.dispatch(cancel_policy, reason="review probe")

    assert result.complete is False
    assert result.failure_codes == ("partial_broker_result",)
    assert set(mock.cancel_calls) == {
        ("regular", "REG-1"),
        ("forever", "GTT-1"),
        ("super", "SUPER-1"),
        ("conditional", "ALERT-1"),
    }
    assert mock.active == {"forever"}
    assert len(consumed_gate_ids) == 4
    assert len(set(consumed_gate_ids)) == 4


@pytest.mark.asyncio
async def test_order_readback_catches_order_created_after_first_quiet_read(monkeypatch):
    import flinttrade_gateway.brokers.dhan as dhan_module

    late_order = {("regular", "LATE-1"): {"orderid": "LATE-1", "status": "PENDING"}}

    class TriggerRaceAdapter(DhanAdapter):
        def __init__(self):
            super().__init__(client_factory=lambda _session: MockDhan())
            self.snapshots = iter(({}, {}, late_order, late_order, late_order, late_order))

        async def _active_order_targets(self, session):
            return next(self.snapshots)

    monkeypatch.setattr(dhan_module, "_EMERGENCY_READBACK_DELAY_SECONDS", 0)
    adapter = TriggerRaceAdapter()
    session = await _session(adapter)

    active = await adapter._settled_active_order_targets(session)

    assert set(active) == {("regular", "LATE-1")}


@pytest.mark.asyncio
async def test_order_readback_catches_order_created_after_second_quiet_read(monkeypatch):
    import flinttrade_gateway.brokers.dhan as dhan_module

    late_order = {("regular", "LATE-2"): {"orderid": "LATE-2", "status": "PENDING"}}

    class TriggerRaceAdapter(DhanAdapter):
        def __init__(self):
            super().__init__(client_factory=lambda _session: MockDhan())
            self.snapshots = iter(({}, {}, {}, late_order, late_order, late_order))

        async def _active_order_targets(self, session):
            return next(self.snapshots)

    monkeypatch.setattr(dhan_module, "_EMERGENCY_READBACK_DELAY_SECONDS", 0)
    adapter = TriggerRaceAdapter()
    session = await _session(adapter)

    active = await adapter._settled_active_order_targets(session)

    assert set(active) == {("regular", "LATE-2")}


@pytest.mark.asyncio
async def test_order_readback_catches_order_created_after_third_quiet_read(monkeypatch):
    import flinttrade_gateway.brokers.dhan as dhan_module

    late_order = {("regular", "LATE-3"): {"orderid": "LATE-3", "status": "PENDING"}}

    class TriggerRaceAdapter(DhanAdapter):
        def __init__(self):
            super().__init__(client_factory=lambda _session: MockDhan())
            self.snapshots = iter(({}, {}, {}, {}, late_order, late_order))

        async def _active_order_targets(self, session):
            return next(self.snapshots)

    monkeypatch.setattr(dhan_module, "_EMERGENCY_READBACK_DELAY_SECONDS", 0)
    adapter = TriggerRaceAdapter()
    session = await _session(adapter)

    active = await adapter._settled_active_order_targets(session)

    assert set(active) == {("regular", "LATE-3")}


@pytest.mark.asyncio
async def test_order_readback_accepts_terminal_quiet_window_after_transient_order(monkeypatch):
    import flinttrade_gateway.brokers.dhan as dhan_module

    transient = {("regular", "TRANSIENT-1"): {"orderid": "TRANSIENT-1", "status": "PENDING"}}

    class SettlingAdapter(DhanAdapter):
        def __init__(self):
            super().__init__(client_factory=lambda _session: MockDhan())
            self.snapshots = iter(({}, transient, {}, {}, {}, {}))

        async def _active_order_targets(self, session):
            return next(self.snapshots)

    monkeypatch.setattr(dhan_module, "_EMERGENCY_READBACK_DELAY_SECONDS", 0)
    adapter = SettlingAdapter()
    session = await _session(adapter)

    active = await adapter._settled_active_order_targets(session)

    assert active == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "leg_details",
    [
        None,
        "malformed",
        [{"legName": "TARGET_LEG"}],
        [{"legName": "TARGET_LEG", "orderStatus": "TRADED"}],
    ],
)
async def test_traded_super_order_with_untrusted_legs_remains_unresolved(leg_details):
    class MalformedSuperOrderDhan(MockDhan):
        def get_order_list(self):
            return {"status": "success", "data": []}

        def get_forever(self):
            return {"status": "success", "data": []}

        def get_super_order_list(self):
            return {
                "status": "success",
                "data": [
                    {
                        "orderId": "SUPER-UNRESOLVED",
                        "orderStatus": "TRADED",
                        "legDetails": leg_details,
                    }
                ],
            }

    mock = MalformedSuperOrderDhan()
    mock.dhan_http.responses[("GET", "/alerts/orders")] = {"status": "success", "data": []}
    adapter = _adapter(mock)
    session = await _session(adapter)

    active = await adapter._active_order_targets(session)

    assert set(active) == {("super", "SUPER-UNRESOLVED")}


@pytest.mark.asyncio
async def test_reads_map_correctly():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    orders = await adapter.order_book(session)
    assert orders[0]["symbol"] == "TCS" and orders[0]["exchange"] == "NSE"
    positions = await adapter.positions(session)
    assert positions[0]["symbol"] == "INFY" and positions[0]["quantity"] == "10"
    trades = await adapter.trade_book(session)
    assert trades[0]["price"] == "3499"
    holdings = await adapter.holdings(session)
    assert holdings[0]["symbol"] == "SBIN"
    funds = await adapter.funds(session)
    assert funds["available_balance"] == "50000"


@pytest.mark.asyncio
async def test_holdings_empty_broker_response_returns_empty_list():
    class EmptyHoldingsDhan(MockDhan):
        def get_holdings(self):
            return {"status": "failure", "remarks": {"error_message": "No holdings available"}}

    adapter = _adapter(EmptyHoldingsDhan())
    session = await _session(adapter)

    assert await adapter.holdings(session) == []


@pytest.mark.asyncio
async def test_unresolvable_symbol_raises():
    from flinttrade_core.exceptions import BrokerError

    adapter = DhanAdapter(client_factory=lambda _s: MockDhan())  # no resolver
    session = await _session(adapter)
    order = Order(symbol="OBSCURE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(BrokerError, match="security_id"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_quotes_map_to_models():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    quotes = await adapter.quotes(session, ["NSE:RELIANCE"])
    assert len(quotes) == 1
    assert quotes[0].symbol == "RELIANCE"
    assert quotes[0].ltp == 2901.5
    assert quotes[0].open == 2890.0


@pytest.mark.asyncio
async def test_historical_intraday_and_daily():
    mock = MockDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    intraday = await adapter.historical(
        session,
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "from_date": "2026-06-01", "to_date": "2026-06-05"},
    )
    assert intraday.symbol == "RELIANCE" and len(intraday.bars) == 2
    assert intraday.bars[0].open == 100.0
    assert ("intraday", "11536", 5) in mock.calls

    daily = await adapter.historical(
        session,
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "D", "from_date": "2026-01-01", "to_date": "2026-06-05"},
    )
    assert len(daily.bars) == 1
    assert any(c[0] == "daily" for c in mock.calls)


@pytest.mark.asyncio
async def test_option_chain_maps_to_model():
    mock = MockDhan()
    adapter = _adapter(mock)  # NIFTY/NSE_INDEX uses the index fast path
    session = await _session(adapter)
    oc = await adapter.option_chain(session, {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2026-06-25"})
    assert oc.underlying == "NIFTY"
    assert len(oc.strikes) == 1
    assert oc.strikes[0].strike_price == 24000.0
    assert oc.strikes[0].ce_ltp == 150.0 and oc.strikes[0].pe_oi == 1200
    assert ("option_chain", "13", "2026-06-25") in mock.calls  # NIFTY index id


@pytest.mark.asyncio
async def test_portfolio_greeks_reads_each_unique_chain_once_and_requires_vega() -> None:
    class CompleteGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            self.calls.append(("option_chain", under_security_id, expiry))
            return {
                "status": "success",
                "data": {
                    "oc": {
                        "25000.000000": {
                            "ce": {
                                "security_id": "49081",
                                "implied_volatility": 18.4,
                                "greeks": {
                                    "delta": 0.52,
                                    "gamma": 0.001,
                                    "theta": -5.0,
                                    "vega": 6.4,
                                }
                            },
                            "pe": {
                                "security_id": "49082",
                                "implied_volatility": 19.1,
                                "greeks": {
                                    "delta": -0.48,
                                    "gamma": 0.001,
                                    "theta": -5.1,
                                    "vega": 6.2,
                                }
                            },
                        }
                    }
                },
            }

    mock = CompleteGreeksDhan()
    adapter = _adapter(mock)
    session = await _session(adapter)
    positions = [
        {
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }
    ]

    first = await adapter.portfolio_greeks(session, positions)
    second = await adapter.portfolio_greeks(session, positions)

    assert first == second == [
        {
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "ltp": 0.0,
            "iv": 18.4,
            "delta": 0.52,
            "gamma": 0.001,
            "theta": -5.0,
            "vega": 6.4,
        }
    ]
    assert [call for call in mock.calls if call[0] == "option_chain"] == [
        ("option_chain", "13", "2026-07-30")
    ]


@pytest.mark.asyncio
async def test_portfolio_greeks_resolves_new_contract_through_scrip_master() -> None:
    from flinttrade_gateway.brokers import dhan_mapping as M

    class CompleteGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            self.calls.append(("option_chain", under_security_id, expiry))
            return {
                "status": "success",
                "data": {
                    "oc": {
                        "25000.000000": {
                            "ce": {
                                "security_id": "49081",
                                "implied_volatility": 18.4,
                                "greeks": {
                                    "delta": 0.52,
                                    "gamma": 0.001,
                                    "theta": -5.0,
                                    "vega": 6.4,
                                }
                            }
                        }
                    }
                },
            }

    resolver = M.build_security_resolver([{
        "SEM_EXM_EXCH_ID": "NSE",
        "SEM_SEGMENT": "D",
        "SEM_SMST_SECURITY_ID": "49081",
        "SEM_TRADING_SYMBOL": "NIFTY-Jul2026-25000-CE",
        "SEM_OPTION_TYPE": "CE",
        "SEM_EXPIRY_DATE": "2026-07-30",
        "SEM_STRIKE_PRICE": "25000",
        "UNDERLYING_SYMBOL": "NIFTY",
    }])
    mock = CompleteGreeksDhan()
    adapter = DhanAdapter(
        client_factory=lambda _session: mock,
        security_resolver=resolver,
    )
    session = await _session(adapter)
    positions = [{
        "symbol": "NIFTY-Jul2026-25000-CE",
        "instrument_id": "",
        "exchange": "NFO",
        "quantity": 75.0,
        "option_type": "CE",
        "expiry": "",
        "strike_price": 0.0,
        "underlying": "",
    }]

    greeks = await adapter.portfolio_greeks(session, positions)

    assert greeks == [{
        "symbol": "NIFTY-Jul2026-25000-CE",
        "instrument_id": "49081",
        "exchange": "NFO",
        "ltp": 0.0,
        "iv": 18.4,
        "delta": 0.52,
        "gamma": 0.001,
        "theta": -5.0,
        "vega": 6.4,
    }]
    assert [call for call in mock.calls if call[0] == "option_chain"] == [
        ("option_chain", "13", "2026-07-30")
    ]


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_a_chain_leg_for_another_security_id() -> None:
    from flinttrade_core.exceptions import BrokerError

    class MismatchedGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {
                "status": "success",
                "data": {
                    "oc": {
                        "25000.000000": {
                            "ce": {
                                "security_id": "99999",
                                "greeks": {
                                    "delta": 0.52,
                                    "gamma": 0.001,
                                    "theta": -5.0,
                                    "vega": 6.4,
                                },
                            }
                        }
                    }
                },
            }

    adapter = _adapter(MismatchedGreeksDhan())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="security identity"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_a_complete_symbol_security_id_mismatch() -> None:
    from flinttrade_core.exceptions import BrokerError
    from flinttrade_gateway.brokers import dhan_mapping as M

    resolver = M.build_security_resolver([
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "49081",
            "SEM_TRADING_SYMBOL": "NIFTY-Jul2026-25000-CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_EXPIRY_DATE": "2026-07-30",
            "SEM_STRIKE_PRICE": "25000",
            "UNDERLYING_SYMBOL": "NIFTY",
        },
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "49082",
            "SEM_TRADING_SYMBOL": "NIFTY-Jul2026-25100-CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_EXPIRY_DATE": "2026-07-30",
            "SEM_STRIKE_PRICE": "25100",
            "UNDERLYING_SYMBOL": "NIFTY",
        },
    ])
    adapter = DhanAdapter(
        client_factory=lambda _session: MockDhan(),
        security_resolver=resolver,
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="authoritative contract identity"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49082",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_100.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_empty_string_greeks_as_incomplete() -> None:
    from flinttrade_core.exceptions import BrokerError

    class EmptyGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {
                "status": "success",
                "data": {
                    "oc": {
                        "25000.000000": {
                            "ce": {
                                "security_id": "49081",
                                "greeks": {"delta": "", "gamma": "", "theta": "", "vega": ""},
                            }
                        }
                    }
                },
            }

    adapter = _adapter(EmptyGreeksDhan())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="complete Greek"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_missing_iv_as_incomplete() -> None:
    from flinttrade_core.exceptions import BrokerError

    class MissingIvDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {
                "status": "success",
                "data": {"oc": {"25000.000000": {"ce": {
                    "security_id": "49081",
                    "greeks": {"delta": 0.52, "gamma": 0.001, "theta": -5.0, "vega": 6.4},
                }}}},
            }

    adapter = _adapter(MissingIvDhan())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="complete Greek"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_portfolio_greeks_resolves_bankex_through_the_bse_index_master() -> None:
    from flinttrade_gateway.brokers import dhan_mapping as M

    class BankexGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            assert (under_security_id, under_exchange_segment, expiry) == ("69", "IDX_I", "2026-07-30")
            return {
                "status": "success",
                "data": {
                    "oc": {
                        "60000.000000": {
                            "ce": {
                                "security_id": "71001",
                                "implied_volatility": 20.1,
                                "greeks": {
                                    "delta": 0.51,
                                    "gamma": 0.001,
                                    "theta": -5.0,
                                    "vega": 7.2,
                                },
                            }
                        }
                    }
                },
            }

    resolver = M.build_security_resolver([
        {
            "SEM_EXM_EXCH_ID": "BSE",
            "SEM_SEGMENT": "I",
            "SEM_SMST_SECURITY_ID": "69",
            "SEM_TRADING_SYMBOL": "BANKEX",
        },
        {
            "SEM_EXM_EXCH_ID": "BSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "71001",
            "SEM_TRADING_SYMBOL": "BANKEX-Jul2026-60000-CE",
            "SEM_OPTION_TYPE": "CE",
            "SEM_EXPIRY_DATE": "2026-07-30",
            "SEM_STRIKE_PRICE": "60000",
            "UNDERLYING_SYMBOL": "BANKEX",
        },
    ])
    adapter = DhanAdapter(
        client_factory=lambda _session: BankexGreeksDhan(),
        security_resolver=resolver,
    )
    session = await _session(adapter)

    rows = await adapter.portfolio_greeks(session, [{
        "symbol": "BANKEX-Jul2026-60000-CE",
        "instrument_id": "71001",
        "exchange": "BFO",
        "quantity": 30.0,
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 60_000.0,
        "underlying": "BANKEX",
    }])

    assert rows[0]["instrument_id"] == "71001"
    assert rows[0]["delta"] == pytest.approx(0.51)
    assert rows[0]["vega"] == pytest.approx(7.2)


@pytest.mark.asyncio
async def test_portfolio_greeks_wraps_a_dhan_chain_failure_as_broker_error() -> None:
    from flinttrade_core.exceptions import BrokerError
    from flinttrade_gateway.brokers import dhan_mapping as M

    class FailedChainDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {
                "status": "failure",
                "remarks": {"error_message": "option chain unavailable"},
            }

    resolver = M.build_security_resolver([{
        "SEM_EXM_EXCH_ID": "NSE",
        "SEM_SEGMENT": "D",
        "SEM_SMST_SECURITY_ID": "49081",
        "SEM_TRADING_SYMBOL": "NIFTY-Jul2026-25000-CE",
        "SEM_OPTION_TYPE": "CE",
        "SEM_EXPIRY_DATE": "2026-07-30",
        "SEM_STRIKE_PRICE": "25000",
        "UNDERLYING_SYMBOL": "NIFTY",
    }])
    adapter = DhanAdapter(
        client_factory=lambda _session: FailedChainDhan(),
        security_resolver=resolver,
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option-chain Greek read failed"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY-Jul2026-25000-CE",
            "instrument_id": "49081",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_option_greeks_resolves_compact_master_display_alias_and_normalised_expiry() -> None:
    from flinttrade_gateway.brokers import dhan_mapping as M

    class DisplayAliasGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            assert (under_security_id, under_exchange_segment, expiry) == ("10940", "NSE_EQ", "2026-07-28")
            return {
                "status": "success",
                "data": {"oc": {"3600.000000": {"ce": {
                    "security_id": "100003",
                    "last_price": 42.5,
                    "oi": 1200,
                    "implied_volatility": 18.4,
                    "greeks": {
                        "delta": 0.52,
                        "gamma": 0.001,
                        "theta": -5.0,
                        "vega": 6.4,
                    },
                }}}},
            }

    resolver = M.build_security_resolver([
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "E",
            "SEM_SMST_SECURITY_ID": "10940",
            "SEM_TRADING_SYMBOL": "DIVISLAB",
        },
        {
            "SEM_EXM_EXCH_ID": "NSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "100003",
            "SEM_TRADING_SYMBOL": "DIVISLAB-Jul2026-3600-CE",
            "SEM_CUSTOM_SYMBOL": "DIVISLAB 28 JUL 3600 CALL",
            "SEM_EXPIRY_DATE": "2026-07-28 14:30:00",
            "SEM_STRIKE_PRICE": "3600.00000",
            "SEM_OPTION_TYPE": "CE",
        },
    ])
    adapter = DhanAdapter(
        client_factory=lambda _session: DisplayAliasGreeksDhan(),
        security_resolver=resolver,
    )
    session = await _session(adapter)

    rows = await adapter.option_greeks(session, ["NFO:DIVISLAB 28 JUL 3600 CALL"])

    assert rows == [{
        "symbol": "DIVISLAB 28 JUL 3600 CALL",
        "instrument_id": "100003",
        "exchange": "NFO",
        "ltp": 42.5,
        "iv": 18.4,
        "delta": 0.52,
        "gamma": 0.001,
        "theta": -5.0,
        "vega": 6.4,
        "oi": 1200,
    }]


@pytest.mark.asyncio
async def test_option_greeks_uses_trading_symbol_underlying_for_bfo_stock_options() -> None:
    from flinttrade_gateway.brokers import dhan_mapping as M

    class BfoStockGreeksDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            assert (under_security_id, under_exchange_segment, expiry) == ("500", "BSE_EQ", "2026-07-30")
            return {
                "status": "success",
                "data": {"oc": {"1030.000000": {"ce": {
                    "security_id": "1136055",
                    "implied_volatility": 21.2,
                    "greeks": {
                        "delta": 0.5,
                        "gamma": 0.001,
                        "theta": -4.0,
                        "vega": 5.0,
                    },
                }}}},
            }

    resolver = M.build_security_resolver([
        {
            "SEM_EXM_EXCH_ID": "BSE",
            "SEM_SEGMENT": "E",
            "SEM_SMST_SECURITY_ID": "500",
            "SEM_TRADING_SYMBOL": "PNBHOUSING",
        },
        {
            "SEM_EXM_EXCH_ID": "BSE",
            "SEM_SEGMENT": "D",
            "SEM_SMST_SECURITY_ID": "1136055",
            "SEM_TRADING_SYMBOL": "PNBHOUSING-Jul2026-1030-CE",
            "SEM_CUSTOM_SYMBOL": "PNBHOUSING 30 JUL 1030 CALL",
            "SEM_EXPIRY_DATE": "2026-07-30 15:30:00",
            "SEM_STRIKE_PRICE": "1030.00000",
            "SEM_OPTION_TYPE": "CE",
            "SM_SYMBOL_NAME": "PNHFOPT",
        },
    ])
    adapter = DhanAdapter(
        client_factory=lambda _session: BfoStockGreeksDhan(),
        security_resolver=resolver,
    )
    session = await _session(adapter)

    rows = await adapter.option_greeks(session, ["BFO:PNBHOUSING 30 JUL 1030 CALL"])

    assert rows[0]["instrument_id"] == "1136055"
    assert rows[0]["delta"] == 0.5


@pytest.mark.asyncio
async def test_option_chain_wraps_malformed_structures_as_broker_error() -> None:
    from flinttrade_core.exceptions import BrokerError

    class MalformedChainDhan(MockDhan):
        def option_chain(self, under_security_id, under_exchange_segment, expiry):
            return {"status": "success", "data": {"oc": {"25000": {"ce": {"greeks": "bad"}}}}}

    adapter = _adapter(MalformedChainDhan())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option-chain response is invalid"):
        await adapter.option_chain(
            session,
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2026-07-30"},
        )


@pytest.mark.asyncio
async def test_public_option_reads_wrap_security_resolver_failures_as_broker_errors() -> None:
    from flinttrade_core.exceptions import BrokerError
    from flinttrade_gateway.brokers import dhan_mapping as M

    def fail_resolver(_symbol: str, _exchange: str) -> str:
        raise M.DhanMappingError("missing security id")

    adapter = DhanAdapter(
        client_factory=lambda _session: MockDhan(),
        security_resolver=fail_resolver,
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option-chain response is invalid"):
        await adapter.option_chain(
            session,
            {"symbol": "RELIANCE", "exchange": "NSE", "expiry": "2026-07-30"},
        )
    with pytest.raises(BrokerError, match="lacks authoritative contract identity"):
        await adapter.option_greeks(session, ["NFO:NIFTY 30 JUL 25000 CALL"])


@pytest.mark.asyncio
async def test_public_greek_reads_wrap_runtime_master_failures_as_broker_errors() -> None:
    from urllib.error import URLError

    from flinttrade_core.exceptions import BrokerError

    def fail_resolver(_symbol: str, _exchange: str) -> str:
        raise URLError("scrip master is unavailable")

    adapter = DhanAdapter(
        client_factory=lambda _session: MockDhan(),
        security_resolver=fail_resolver,
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option symbol lacks authoritative contract identity"):
        await adapter.option_greeks(session, ["NFO:NIFTY 30 JUL 25000 CALL"])
    with pytest.raises(BrokerError, match="option position lacks authoritative contract identity"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY 30 JUL 25000 CALL",
            "instrument_id": "",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "2026-07-30",
            "strike_price": 25_000.0,
            "underlying": "NIFTY",
        }])


@pytest.mark.asyncio
async def test_subscribe_builds_feed_map_and_stream_yields_ticks():
    frames = [struct.pack("<BHBIfI", 15, 16, 1, 11536, 2901.5, 1)]

    async def fake_feed(_session):
        for frame in frames:
            yield frame

    adapter = DhanAdapter(
        client_factory=lambda _s: MockDhan(),
        security_resolver=lambda s, e: "11536",
        feed_factory=fake_feed,
    )
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert adapter._feed_map["11536"] == ("RELIANCE", "NSE")

    ticks = [t async for t in adapter.stream(session)]
    assert len(ticks) == 1
    assert ticks[0].symbol == "RELIANCE"
    assert ticks[0].ltp == 2901.5


@pytest.mark.asyncio
async def test_unsubscribe_removes_from_feed_map():
    adapter = _adapter(MockDhan())
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert "11536" in adapter._feed_map
    await adapter.unsubscribe(session, ["NSE:RELIANCE"])
    assert "11536" not in adapter._feed_map


@pytest.mark.asyncio
async def test_index_fast_path_resolution():
    mock = MockDhan()
    adapter = DhanAdapter(client_factory=lambda _s: mock)  # no resolver — index fast path
    session = await _session(adapter)
    order = Order(symbol="NIFTY", action="BUY", exchange="NSE_INDEX", pricetype="MARKET", product="MIS", quantity="1")
    await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert mock.calls[0][1]["security_id"] == "13"  # NIFTY index id
