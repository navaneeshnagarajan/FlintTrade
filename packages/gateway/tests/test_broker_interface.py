"""Tests for broker_interface — Protocol, models, BrokerRegistry, OpenAlgoBroker.

Uses mock OpenAlgoClient objects to avoid requiring a live OpenAlgo instance.

Run with::

    python -m pytest packages/gateway/tests/test_broker_interface.py -v --import-mode=importlib
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**method_returns: Any) -> MagicMock:
    """Return a MagicMock client with specified method return values."""
    client = MagicMock()
    for method, return_value in method_returns.items():
        getattr(client, method).return_value = return_value
    return client


def _make_broker(client: Any | None = None):
    """Return an OpenAlgoBroker backed by the given mock client."""
    from packages.gateway.src.broker_interface import OpenAlgoBroker

    if client is None:
        client = _make_client()
    return OpenAlgoBroker(client=client)


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestBrokerModels:
    """Validate pydantic model construction and defaults."""

    def test_broker_credentials_defaults(self):
        """BrokerCredentials has sensible empty-string defaults."""
        from packages.gateway.src.broker_interface import BrokerCredentials

        creds = BrokerCredentials()
        assert creds.api_key == ""
        assert creds.extra == {}

    def test_auth_result_success(self):
        """AuthResult captures success state."""
        from packages.gateway.src.broker_interface import AuthResult

        result = AuthResult(success=True, access_token="tok123")
        assert result.success is True
        assert result.access_token == "tok123"
        assert result.error is None

    def test_auth_result_failure(self):
        """AuthResult captures failure with error message."""
        from packages.gateway.src.broker_interface import AuthResult

        result = AuthResult(success=False, error="Invalid credentials")
        assert result.success is False
        assert result.error == "Invalid credentials"

    def test_order_request_defaults(self):
        """OrderRequest defaults to MARKET, MIS, DAY."""
        from packages.gateway.src.broker_interface import OrderRequest

        order = OrderRequest(
            symbol="NIFTY26APR24500CE",
            exchange="NFO",
            side="BUY",
            quantity=50,
        )
        assert order.order_type == "MARKET"
        assert order.product == "MIS"
        assert order.validity == "DAY"
        assert order.price == 0.0

    def test_order_response_defaults(self):
        """OrderResponse defaults to empty strings."""
        from packages.gateway.src.broker_interface import OrderResponse

        resp = OrderResponse(success=True)
        assert resp.order_id == ""
        assert resp.raw == {}

    def test_position_model(self):
        """Position model stores all fields correctly."""
        from packages.gateway.src.broker_interface import Position

        pos = Position(symbol="RELIANCE", exchange="NSE", quantity=100, avg_price=2500.0, ltp=2550.0)
        assert pos.pnl == 0.0  # default
        assert pos.quantity == 100

    def test_funds_info_defaults_inr(self):
        """FundsInfo defaults currency to INR."""
        from packages.gateway.src.broker_interface import FundsInfo

        fi = FundsInfo()
        assert fi.currency == "INR"
        assert fi.available_cash == 0.0

    def test_quote_model(self):
        """Quote model captures all OHLCV fields."""
        from packages.gateway.src.broker_interface import Quote

        q = Quote(symbol="NIFTY", exchange="NSE_INDEX", ltp=22000.5, high=22100.0)
        assert q.ltp == pytest.approx(22000.5)
        assert q.oi == 0  # default

    def test_holding_defaults_cnc(self):
        """Holding defaults product to CNC."""
        from packages.gateway.src.broker_interface import Holding

        h = Holding(symbol="TCS", exchange="NSE")
        assert h.product == "CNC"


# ---------------------------------------------------------------------------
# BrokerInterface Protocol tests
# ---------------------------------------------------------------------------


class TestBrokerInterfaceProtocol:
    """Verify Protocol conformance checks at runtime."""

    def test_openalgo_broker_is_broker_interface(self):
        """OpenAlgoBroker satisfies the BrokerInterface Protocol."""
        from packages.gateway.src.broker_interface import BrokerInterface, OpenAlgoBroker

        broker = OpenAlgoBroker(client=MagicMock())
        assert isinstance(broker, BrokerInterface)

    def test_non_conforming_object_fails_isinstance(self):
        """An object missing required methods fails BrokerInterface isinstance check."""
        from packages.gateway.src.broker_interface import BrokerInterface

        class Incomplete:
            def authenticate(self, credentials):
                ...
            # Missing all other methods

        assert not isinstance(Incomplete(), BrokerInterface)

    def test_duck_typed_adapter_passes(self):
        """A duck-typed class with all methods satisfies the Protocol."""
        from packages.gateway.src.broker_interface import (
            AuthResult,
            BrokerCredentials,
            BrokerInterface,
            FundsInfo,
            Holding,
            Order,
            OrderRequest,
            OrderResponse,
            Position,
            Quote,
        )

        class FakeAdapter:
            def authenticate(self, credentials: BrokerCredentials) -> AuthResult:
                return AuthResult(success=True)

            def place_order(self, order: OrderRequest) -> OrderResponse:
                return OrderResponse(success=True)

            def modify_order(self, order_id: str, modifications: dict) -> OrderResponse:
                return OrderResponse(success=True)

            def cancel_order(self, order_id: str) -> bool:
                return True

            def get_positions(self) -> list[Position]:
                return []

            def get_orders(self) -> list[Order]:
                return []

            def get_holdings(self) -> list[Holding]:
                return []

            def get_funds(self) -> FundsInfo:
                return FundsInfo()

            def get_quote(self, symbol: str, exchange: str) -> Quote:
                return Quote(symbol=symbol, exchange=exchange)

            def subscribe_ticks(self, symbols, callback):
                pass

            def unsubscribe_ticks(self, symbols):
                pass

        assert isinstance(FakeAdapter(), BrokerInterface)


# ---------------------------------------------------------------------------
# BrokerRegistry tests
# ---------------------------------------------------------------------------


class TestBrokerRegistry:
    """Tests for BrokerRegistry register/lookup/list operations."""

    def _make_registry(self):
        from packages.gateway.src.broker_interface import BrokerRegistry

        return BrokerRegistry()

    def test_register_and_get_broker(self):
        """Registered broker is retrievable by name."""
        registry = self._make_registry()
        broker = _make_broker()
        registry.register("openalgo", broker)
        retrieved = registry.get_broker("openalgo")
        assert retrieved is broker

    def test_get_broker_unknown_raises_key_error(self):
        """Retrieving an unknown broker raises KeyError."""
        registry = self._make_registry()
        with pytest.raises(KeyError, match="phantom"):
            registry.get_broker("phantom")

    def test_register_non_conforming_adapter_raises(self):
        """Registering an object that does not implement the Protocol raises TypeError."""
        registry = self._make_registry()
        with pytest.raises(TypeError, match="BrokerInterface"):
            registry.register("bad", object())  # type: ignore[arg-type]

    def test_unregister(self):
        """Unregistering removes the adapter."""
        registry = self._make_registry()
        broker = _make_broker()
        registry.register("x", broker)
        registry.unregister("x")
        assert not registry.is_registered("x")

    def test_unregister_missing_raises_key_error(self):
        """Unregistering a missing name raises KeyError."""
        registry = self._make_registry()
        with pytest.raises(KeyError):
            registry.unregister("nonexistent")

    def test_list_brokers_sorted(self):
        """list_brokers returns sorted list of names."""
        registry = self._make_registry()
        registry.register("zerodha", _make_broker())
        registry.register("angel", _make_broker())
        registry.register("mstock", _make_broker())
        names = registry.list_brokers()
        assert names == sorted(names)
        assert "zerodha" in names

    def test_is_registered(self):
        """is_registered returns True for registered names."""
        registry = self._make_registry()
        registry.register("openalgo", _make_broker())
        assert registry.is_registered("openalgo") is True
        assert registry.is_registered("ghost") is False

    def test_register_replaces_existing(self):
        """Re-registering under same name silently replaces the adapter."""
        registry = self._make_registry()
        broker1 = _make_broker()
        broker2 = _make_broker()
        registry.register("openalgo", broker1)
        registry.register("openalgo", broker2)
        assert registry.get_broker("openalgo") is broker2
        assert len(registry.list_brokers()) == 1


# ---------------------------------------------------------------------------
# OpenAlgoBroker — authenticate
# ---------------------------------------------------------------------------


class TestOpenAlgoBrokerAuthenticate:
    """Tests for OpenAlgoBroker.authenticate."""

    def test_successful_ping(self):
        """Returns AuthResult(success=True) when ping returns success."""
        from packages.gateway.src.broker_interface import BrokerCredentials

        client = _make_client(ping={"status": "success"})
        broker = _make_broker(client)
        result = broker.authenticate(BrokerCredentials(api_key="test_key"))
        assert result.success is True
        assert result.access_token == "test_key"
        assert result.error is None

    def test_failed_ping(self):
        """Returns AuthResult(success=False) when ping returns error status."""
        from packages.gateway.src.broker_interface import BrokerCredentials

        client = _make_client(ping={"status": "error", "message": "Unauthorized"})
        broker = _make_broker(client)
        result = broker.authenticate(BrokerCredentials(api_key="bad_key"))
        assert result.success is False

    def test_exception_during_ping(self):
        """Exception in ping is caught; returns AuthResult(success=False)."""
        from packages.gateway.src.broker_interface import BrokerCredentials

        client = MagicMock()
        client.ping.side_effect = ConnectionError("Server unreachable")
        broker = _make_broker(client)
        result = broker.authenticate(BrokerCredentials())
        assert result.success is False
        assert "unreachable" in result.error.lower()


# ---------------------------------------------------------------------------
# OpenAlgoBroker — place_order / modify_order / cancel_order
# ---------------------------------------------------------------------------


class TestOpenAlgoBrokerOrders:
    """Tests for order management methods."""

    def test_place_order_success(self):
        """place_order returns OrderResponse(success=True) with order_id."""
        from packages.gateway.src.broker_interface import OrderRequest

        client = _make_client(
            place_order={"status": "success", "orderid": "OA12345"}
        )
        broker = _make_broker(client)
        order = OrderRequest(
            symbol="RELIANCE", exchange="NSE", side="BUY", quantity=10
        )
        resp = broker.place_order(order)
        assert resp.success is True
        assert resp.order_id == "OA12345"

    def test_place_order_failure(self):
        """place_order returns success=False when broker rejects."""
        from packages.gateway.src.broker_interface import OrderRequest

        client = _make_client(
            place_order={"status": "error", "message": "Insufficient funds"}
        )
        broker = _make_broker(client)
        order = OrderRequest(symbol="X", exchange="NSE", side="BUY", quantity=1)
        resp = broker.place_order(order)
        assert resp.success is False

    def test_place_order_exception(self):
        """Exception during place_order returns success=False."""
        from packages.gateway.src.broker_interface import OrderRequest

        client = MagicMock()
        client.place_order.side_effect = RuntimeError("timeout")
        broker = _make_broker(client)
        resp = broker.place_order(
            OrderRequest(symbol="Y", exchange="NSE", side="SELL", quantity=5)
        )
        assert resp.success is False
        assert "timeout" in resp.message

    def test_modify_order_success(self):
        """modify_order returns success=True and original order_id."""
        client = _make_client(modify_order={"status": "success"})
        broker = _make_broker(client)
        resp = broker.modify_order("ORD001", {"price": 2600.0})
        assert resp.success is True
        assert resp.order_id == "ORD001"

    def test_cancel_order_success(self):
        """cancel_order returns True when broker confirms cancellation."""
        client = _make_client(cancel_order={"status": "success"})
        broker = _make_broker(client)
        assert broker.cancel_order("ORD002") is True

    def test_cancel_order_failure(self):
        """cancel_order returns False on failure response."""
        client = _make_client(cancel_order={"status": "error"})
        broker = _make_broker(client)
        assert broker.cancel_order("ORD003") is False

    def test_cancel_order_exception(self):
        """Exception in cancel_order is caught and returns False."""
        client = MagicMock()
        client.cancel_order.side_effect = Exception("network error")
        broker = _make_broker(client)
        assert broker.cancel_order("ORD004") is False


# ---------------------------------------------------------------------------
# OpenAlgoBroker — account data
# ---------------------------------------------------------------------------


class TestOpenAlgoBrokerAccountData:
    """Tests for positions, orders, holdings, funds."""

    def test_get_positions_list(self):
        """get_positions returns normalised Position list."""
        client = _make_client(
            get_positions=[
                {
                    "symbol": "NIFTY26APR24500CE",
                    "exchange": "NFO",
                    "product": "MIS",
                    "quantity": 50,
                    "average_price": 120.0,
                    "ltp": 145.0,
                    "pnl": 1250.0,
                }
            ]
        )
        broker = _make_broker(client)
        positions = broker.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.symbol == "NIFTY26APR24500CE"
        assert pos.quantity == 50
        assert pos.ltp == pytest.approx(145.0)

    def test_get_positions_wrapped_in_data_key(self):
        """get_positions handles {'data': [...]} response shape."""
        client = _make_client(
            get_positions={"data": [{"symbol": "INFY", "exchange": "NSE"}]}
        )
        broker = _make_broker(client)
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "INFY"

    def test_get_positions_exception_returns_empty(self):
        """Exception in get_positions is swallowed and returns []."""
        client = MagicMock()
        client.get_positions.side_effect = Exception("timeout")
        broker = _make_broker(client)
        assert broker.get_positions() == []

    def test_get_orders_normalised(self):
        """get_orders returns Order list with correct fields."""
        client = _make_client(
            get_order_book=[
                {
                    "orderid": "ORD001",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 10,
                    "status": "COMPLETE",
                    "price_type": "LIMIT",
                    "price": 2800.0,
                }
            ]
        )
        broker = _make_broker(client)
        orders = broker.get_orders()
        assert len(orders) == 1
        assert orders[0].order_id == "ORD001"
        assert orders[0].status == "COMPLETE"

    def test_get_holdings_normalised(self):
        """get_holdings returns Holding list."""
        client = _make_client(
            get_holdings=[
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "quantity": 5,
                    "average_price": 3500.0,
                    "ltp": 3700.0,
                    "pnl": 1000.0,
                }
            ]
        )
        broker = _make_broker(client)
        holdings = broker.get_holdings()
        assert len(holdings) == 1
        assert holdings[0].symbol == "TCS"
        assert holdings[0].product == "CNC"

    def test_get_funds_parsed(self):
        """get_funds parses the nested data dict."""
        client = _make_client(
            get_funds={"data": {"availablecash": 50000.0, "utilisedmargin": 20000.0}}
        )
        broker = _make_broker(client)
        funds = broker.get_funds()
        assert funds.available_cash == pytest.approx(50000.0)
        assert funds.used_margin == pytest.approx(20000.0)
        assert funds.currency == "INR"

    def test_get_funds_exception_returns_defaults(self):
        """Exception in get_funds returns default FundsInfo."""
        client = MagicMock()
        client.get_funds.side_effect = Exception("network error")
        broker = _make_broker(client)
        funds = broker.get_funds()
        assert funds.available_cash == 0.0

    def test_get_quote_parsed(self):
        """get_quote builds Quote from data key."""
        client = _make_client(
            get_quotes={"data": {"ltp": 22000.5, "volume": 123456, "oi": 99000}}
        )
        broker = _make_broker(client)
        quote = broker.get_quote("NIFTY", "NSE_INDEX")
        assert quote.symbol == "NIFTY"
        assert quote.ltp == pytest.approx(22000.5)
        assert quote.oi == 99000

    def test_get_quote_exception_returns_empty(self):
        """Exception in get_quote returns empty Quote."""
        client = MagicMock()
        client.get_quotes.side_effect = RuntimeError("boom")
        broker = _make_broker(client)
        quote = broker.get_quote("X", "NSE")
        assert quote.ltp == 0.0
        assert quote.symbol == "X"


# ---------------------------------------------------------------------------
# OpenAlgoBroker — tick subscription
# ---------------------------------------------------------------------------


class TestOpenAlgoBrokerStreaming:
    """Tests for subscribe_ticks and unsubscribe_ticks."""

    def test_subscribe_delegates_to_client(self):
        """subscribe_ticks calls client.subscribe with correct args."""
        client = MagicMock()
        broker = _make_broker(client)
        cb = MagicMock()
        broker.subscribe_ticks(["NIFTY:NSE_INDEX"], cb)
        client.subscribe.assert_called_once_with(symbols=["NIFTY:NSE_INDEX"], callback=cb)

    def test_unsubscribe_delegates_to_client(self):
        """unsubscribe_ticks calls client.unsubscribe."""
        client = MagicMock()
        broker = _make_broker(client)
        broker.unsubscribe_ticks(["NIFTY:NSE_INDEX"])
        client.unsubscribe.assert_called_once_with(symbols=["NIFTY:NSE_INDEX"])

    def test_subscribe_missing_method_logs_warning(self):
        """subscribe_ticks handles missing subscribe method gracefully."""
        client = MagicMock(spec=[])  # empty spec — no subscribe
        broker = _make_broker(client)
        # Should not raise
        broker.subscribe_ticks(["NIFTY"], lambda x: None)

    def test_unsubscribe_missing_method_logs_warning(self):
        """unsubscribe_ticks handles missing method gracefully."""
        client = MagicMock(spec=[])
        broker = _make_broker(client)
        broker.unsubscribe_ticks(["NIFTY"])  # should not raise
