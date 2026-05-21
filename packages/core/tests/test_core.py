"""Tests for FlintTrade core package.

DO NOT RUN — these are written for pytest but require a live OpenAlgo instance
for integration tests. Unit tests use monkeypatching and mocks.
"""

import os
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


# ======================================================================
# Config tests
# ======================================================================


class TestConfig:
    """Test Settings loading and validation."""

    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.setenv("OPENALGO_API_KEY", "test_key_123")
        monkeypatch.setenv("OPENALGO_PORT", "5000")
        monkeypatch.setenv("OPENALGO_WS_PORT", "8765")
        monkeypatch.setenv("OPENALGO_PORT", "5000")

        from packages.core.src.config import Settings

        s = Settings.from_env()
        assert s.openalgo_host == "http://127.0.0.1:5000"
        assert s.openalgo_api_key == "test_key_123"
        assert s.openalgo_ws_port == 8765

    def test_from_env_missing_host(self, monkeypatch):
        monkeypatch.delenv("OPENALGO_HOST", raising=False)
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)

        from packages.core.src.config import Settings
        from packages.core.src.exceptions import ConfigError

        with pytest.raises(ConfigError, match="OPENALGO_HOST"):
            Settings.from_env()

    def test_from_env_missing_key(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)

        from packages.core.src.config import Settings
        from packages.core.src.exceptions import ConfigError

        with pytest.raises(ConfigError, match="OPENALGO_API_KEY"):
            Settings.from_env()

    def test_host_must_be_url(self):
        from packages.core.src.config import Settings

        with pytest.raises(ValueError, match="http"):
            Settings(openalgo_host="not-a-url", openalgo_api_key="key123")

    def test_key_rejects_placeholder(self):
        from packages.core.src.config import Settings

        with pytest.raises(ValueError, match="real API key"):
            Settings(
                openalgo_host="http://localhost:5000",
                openalgo_api_key="your_openalgo_api_key_here",
            )

    def test_host_trailing_slash_stripped(self):
        from packages.core.src.config import Settings

        s = Settings(openalgo_host="http://localhost:5000/", openalgo_api_key="key123")
        assert s.openalgo_host == "http://localhost:5000"

    def test_default_strategy(self):
        from packages.core.src.config import Settings

        s = Settings(openalgo_host="http://localhost:5000", openalgo_api_key="key123")
        assert s.strategy == "Flint"


# ======================================================================
# Exception tests
# ======================================================================


class TestExceptions:
    """Test exception hierarchy and attributes."""

    def test_base_exception(self):
        from packages.core.src.exceptions import FlintTradeError

        exc = FlintTradeError("boom")
        assert str(exc) == "boom"

    def test_api_error_attributes(self):
        from packages.core.src.exceptions import APIError

        exc = APIError(400, "Bad request", "/placeorder")
        assert exc.status_code == 400
        assert exc.message == "Bad request"
        assert exc.endpoint == "/placeorder"
        assert "400" in str(exc)

    def test_rate_limit_error(self):
        from packages.core.src.exceptions import RateLimitError

        exc = RateLimitError("/placeorder", retry_after=2.0)
        assert exc.status_code == 429
        assert exc.retry_after == 2.0

    def test_auth_error(self):
        from packages.core.src.exceptions import AuthError

        exc = AuthError("/funds")
        assert exc.status_code == 401

    def test_config_error(self):
        from packages.core.src.exceptions import ConfigError, FlintTradeError

        exc = ConfigError("missing key")
        assert isinstance(exc, FlintTradeError)

    def test_inheritance_chain(self):
        from packages.core.src.exceptions import (
            APIError,
            AuthError,
            FlintTradeError,
            RateLimitError,
        )

        assert issubclass(APIError, FlintTradeError)
        assert issubclass(RateLimitError, APIError)
        assert issubclass(AuthError, APIError)


# ======================================================================
# Model tests
# ======================================================================


class TestModels:
    """Test Pydantic models for validation and defaults."""

    def test_order_defaults(self):
        from packages.core.src.models import Order

        o = Order(symbol="RELIANCE", action="BUY")
        assert o.exchange.value == "NSE"
        assert o.pricetype.value == "MARKET"
        assert o.product.value == "MIS"
        assert o.quantity == "1"
        assert o.strategy == "Flint"

    def test_smart_order_has_position_size(self):
        from packages.core.src.models import SmartOrder

        o = SmartOrder(symbol="TCS", action="SELL", position_size="5")
        assert o.position_size == "5"

    def test_options_order(self):
        from packages.core.src.models import OptionsOrder

        o = OptionsOrder(underlying="NIFTY", expiry_date="260326")
        assert o.exchange.value == "NFO"
        assert o.offset == "0"
        assert o.option_type.value == "CE"

    def test_options_multi_order_legs(self):
        from packages.core.src.models import OptionsLeg, OptionsMultiOrder

        order = OptionsMultiOrder(
            underlying="NIFTY",
            expiry_date="260326",
            legs=[
                OptionsLeg(offset="0", option_type="CE", action="SELL", quantity="75"),
                OptionsLeg(offset="0", option_type="PE", action="SELL", quantity="75"),
            ],
        )
        assert len(order.legs) == 2
        assert order.legs[0].action.value == "SELL"

    def test_basket_order(self):
        from packages.core.src.models import BasketOrder, BasketOrderItem

        basket = BasketOrder(
            orders=[
                BasketOrderItem(symbol="RELIANCE"),
                BasketOrderItem(symbol="TCS", action="SELL"),
            ]
        )
        assert len(basket.orders) == 2

    def test_split_order(self):
        from packages.core.src.models import SplitOrder

        o = SplitOrder(symbol="RELIANCE", action="BUY", splitsize="25")
        assert o.splitsize == "25"

    def test_modify_order(self):
        from packages.core.src.models import ModifyOrder

        o = ModifyOrder(orderid="123", symbol="RELIANCE", price="2550")
        assert o.orderid == "123"
        assert o.pricetype.value == "LIMIT"

    def test_quote_defaults(self):
        from packages.core.src.models import Quote

        q = Quote()
        assert q.ltp == 0.0
        assert q.volume == 0

    def test_depth_levels(self):
        from packages.core.src.models import Depth, DepthLevel

        d = Depth(
            symbol="RELIANCE",
            exchange="NSE",
            bids=[DepthLevel(price=2500.0, quantity=100, orders=5)],
            asks=[DepthLevel(price=2501.0, quantity=50, orders=3)],
        )
        assert len(d.bids) == 1
        assert d.asks[0].price == 2501.0

    def test_ohlcv(self):
        from packages.core.src.models import OHLCV

        bar = OHLCV(timestamp="2026-03-14T09:15:00", open=100, high=105, low=99, close=103, volume=10000)
        assert bar.close == 103

    def test_fund(self):
        from packages.core.src.models import Fund

        f = Fund(available_balance="100000", used_margin="25000", total_balance="125000")
        assert f.available_balance == "100000"

    def test_position(self):
        from packages.core.src.models import Position

        p = Position(symbol="RELIANCE", exchange="NSE", quantity="10", pnl="500")
        assert p.pnl == "500"

    def test_holding(self):
        from packages.core.src.models import Holding

        h = Holding(symbol="TCS", quantity="5", average_price="3500")
        assert h.average_price == "3500"

    def test_trade(self):
        from packages.core.src.models import Trade

        t = Trade(orderid="123", symbol="INFY", action="BUY", price="1500")
        assert t.price == "1500"

    def test_option_greek(self):
        from packages.core.src.models import OptionGreek

        g = OptionGreek(symbol="NIFTY26MAR2524000CE", delta=0.5, iv=18.5)
        assert g.delta == 0.5

    def test_option_chain(self):
        from packages.core.src.models import OptionChain, OptionChainStrike

        chain = OptionChain(
            underlying="NIFTY",
            exchange="NFO",
            strikes=[OptionChainStrike(strike_price=24000, ce_ltp=150, pe_ltp=120)],
        )
        assert len(chain.strikes) == 1
        assert chain.strikes[0].strike_price == 24000

    def test_order_response(self):
        from packages.core.src.models import OrderResponse

        r = OrderResponse(status="success", orderid="456")
        assert r.status == "success"

    def test_enum_values(self):
        from packages.core.src.models import Action, Exchange, PriceType, Product

        assert Action.BUY.value == "BUY"
        assert Exchange.NFO.value == "NFO"
        assert PriceType.SL_M.value == "SL-M"
        assert Product.NRML.value == "NRML"


# ======================================================================
# Client initialization tests
# ======================================================================


class TestClientInit:
    """Test OpenAlgoClient construction and structure."""

    def _make_client(self):
        from packages.core.src.config import Settings
        from packages.core.src.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        return OpenAlgoClient(settings)

    def test_client_creates(self):
        client = self._make_client()
        assert client._base == "http://127.0.0.1:5000/api/v1"

    def test_client_context_manager(self):
        """Test that async context manager attributes exist."""
        from packages.core.src.config import Settings
        from packages.core.src.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        client = OpenAlgoClient(settings)
        assert client._api_key == "test123"
        assert hasattr(client, "__aenter__")
        assert hasattr(client, "__aexit__")

    def test_all_endpoint_methods_exist(self):
        client = self._make_client()
        expected_methods = [
            "place_order",
            "place_smart_order",
            "place_options_order",
            "place_options_multi_order",
            "place_basket_order",
            "place_split_order",
            "modify_order",
            "cancel_order",
            "cancel_all_orders",
            "close_position",
            "order_status",
            "open_position",
            "quotes",
            "multi_quotes",
            "depth",
            "history",
            "intervals",
            "option_chain",
            "option_greeks",
            "multi_option_greeks",
            "option_symbol",
            "synthetic_future",
            "expiry",
            "symbol",
            "search",
            "ticker",
            "funds",
            "margin",
            "orderbook",
            "tradebook",
            "positionbook",
            "holdings",
            "ping",
            "holidays",
            "timings",
            "telegram",
            "instruments",
            "analyzer_status",
            "analyzer_toggle",
            # v2.0.0.1 endpoints
            "health",
            "gex",
            "iv_smile",
            "max_pain",
            "oi_profile",
            # v2.0.0.2 endpoints
            "broker_capabilities",
            # v2.0.0.9 / v2.0.1.1 endpoints
            "place_gtt",
            "modify_gtt",
            "cancel_gtt",
            "gtt_orderbook",
        ]
        for method_name in expected_methods:
            assert hasattr(client, method_name), f"Missing method: {method_name}"
            assert callable(getattr(client, method_name)), f"Not callable: {method_name}"

    def test_search_forwards_exchange_when_provided(self):
        """OpenAlgo v2.0.1.x exposes an exchange filter on /api/v1/search."""
        from packages.core.src.openalgo_client import OpenAlgoClient
        import inspect

        sig = inspect.signature(OpenAlgoClient.search)
        params = sig.parameters
        assert "query" in params
        assert "exchange" in params
        # exchange must be optional so callers that omit it preserve the
        # broker-wide search behaviour from earlier versions.
        assert params["exchange"].default is None


# ======================================================================
# Rate limiter tests
# ======================================================================


class TestRateLimiter:
    """Test the token-bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_limiter_allows_burst(self):
        from packages.core.src.openalgo_client import _RateLimiter

        rl = _RateLimiter(10, 1.0)
        start = time.monotonic()
        for _ in range(10):
            await rl.acquire()
        elapsed = time.monotonic() - start
        # First 10 should be near-instant (within the burst)
        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_limiter_throttles_past_burst(self):
        from packages.core.src.openalgo_client import _RateLimiter

        rl = _RateLimiter(2, 1.0)
        # Exhaust burst
        await rl.acquire()
        await rl.acquire()
        # Third call should sleep
        start = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.1  # Should have waited


# ======================================================================
# Error handling tests (async)
# ======================================================================


class TestErrorHandling:
    """Test that API errors are raised correctly."""

    def _make_client(self):
        from packages.core.src.config import Settings
        from packages.core.src.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        return OpenAlgoClient(settings)

    @pytest.mark.asyncio
    async def test_auth_error_on_401(self):
        from packages.core.src.exceptions import AuthError

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.content = b'{"message": "Invalid API key"}'
        mock_resp.json.return_value = {"message": "Invalid API key"}

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(AuthError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_rate_limit_error_on_429(self):
        from packages.core.src.exceptions import RateLimitError

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "1"}

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(RateLimitError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_api_error_on_500(self):
        from packages.core.src.exceptions import APIError

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.content = b'{"message": "Internal error"}'
        mock_resp.json.return_value = {"message": "Internal error"}
        mock_resp.text = "Internal error"

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(APIError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        import httpx

        from packages.core.src.exceptions import APIError

        client = self._make_client()
        client._http.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(APIError, match="Failed after 3 retries"):
            await client.ping()

    @pytest.mark.asyncio
    async def test_error_status_in_response_body(self):
        from packages.core.src.exceptions import APIError

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"status": "error", "message": "Symbol not found"}'
        mock_resp.json.return_value = {"status": "error", "message": "Symbol not found"}

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(APIError, match="Symbol not found"):
            await client.quotes("INVALID")


# ======================================================================
# Package-level import tests
# ======================================================================


class TestPackageExports:
    """Verify that __init__.py exports everything."""

    def test_all_exports(self):
        from packages.core.src import __all__

        assert "OpenAlgoClient" in __all__
        assert "Settings" in __all__
        assert "FlintTradeConfig" in __all__
        assert "Workspace" in __all__
        assert "Order" in __all__
        assert "Quote" in __all__
        assert "APIError" in __all__
        assert "FlintTradeError" in __all__

    def test_package_version(self):
        from packages.core.src import __version__

        assert __version__ == "0.1.0-alpha"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
