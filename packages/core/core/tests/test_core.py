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

    @pytest.fixture(autouse=True)
    def _isolated_workspace(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.setenv("OPENALGO_API_KEY", "test_key_123")
        monkeypatch.setenv("OPENALGO_PORT", "5000")
        monkeypatch.setenv("OPENALGO_WS_PORT", "8765")
        monkeypatch.setenv("OPENALGO_PORT", "5000")

        from flinttrade_core.config import Settings

        s = Settings.from_env()
        assert s.openalgo_host == "http://127.0.0.1:5000"
        assert s.openalgo_api_key == "test_key_123"
        assert s.openalgo_port == 5000
        assert s.openalgo_ws_port == 8765

    def test_from_env_uses_defaults_without_openalgo(self, monkeypatch):
        monkeypatch.delenv("OPENALGO_HOST", raising=False)
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)

        from flinttrade_core.config import Settings

        s = Settings.from_env()
        assert s.openalgo_host == "http://127.0.0.1:5000"
        assert s.openalgo_api_key == ""
        assert s.openalgo_port == 5000

    def test_from_env_allows_missing_openalgo_key(self, monkeypatch):
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)

        from flinttrade_core.config import Settings

        s = Settings.from_env()
        assert s.openalgo_api_key == ""

    def test_workspace_openalgo_overrides_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.setenv("OPENALGO_API_KEY", "env-key")

        from flinttrade_core.workspace import Workspace
        from flinttrade_core.config import Settings

        workspace = Workspace()
        workspace.initialise()
        workspace.set("openalgo.host", "http://127.0.0.1")
        workspace.set("openalgo.port", 5002)
        workspace.set("openalgo.api_key", "workspace-key")
        workspace.set("openalgo.ws_port", 8767)

        s = Settings.from_env()
        assert s.openalgo_host == "http://127.0.0.1"
        assert s.openalgo_port == 5002
        assert s.openalgo_api_key == "workspace-key"
        assert s.openalgo_ws_port == 8767

    def test_openalgo_rest_base_url_uses_fallback_port(self):
        from flinttrade_core.config import Settings, openalgo_rest_base_url

        settings = Settings(openalgo_host="http://127.0.0.1", openalgo_port=5010, openalgo_api_key="key123")
        assert openalgo_rest_base_url(settings) == "http://127.0.0.1:5010"

    def test_openalgo_rest_base_url_preserves_explicit_host_port(self):
        from flinttrade_core.config import Settings, openalgo_rest_base_url

        settings = Settings(openalgo_host="http://127.0.0.1:5002", openalgo_port=5010, openalgo_api_key="key123")
        assert openalgo_rest_base_url(settings) == "http://127.0.0.1:5002"

    def test_openalgo_ports_must_be_valid(self):
        from flinttrade_core.config import Settings

        with pytest.raises(ValueError, match="between 1 and 65535"):
            Settings(openalgo_host="http://localhost:5000", openalgo_api_key="key123", openalgo_port=0)

    def test_host_must_be_url(self):
        from flinttrade_core.config import Settings

        with pytest.raises(ValueError, match="http"):
            Settings(openalgo_host="not-a-url", openalgo_api_key="key123")

    def test_key_rejects_placeholder(self):
        from flinttrade_core.config import Settings

        with pytest.raises(ValueError, match="real API key"):
            Settings(
                openalgo_host="http://localhost:5000",
                openalgo_api_key="your_openalgo_api_key_here",
            )

    def test_host_trailing_slash_stripped(self):
        from flinttrade_core.config import Settings

        s = Settings(openalgo_host="http://localhost:5000/", openalgo_api_key="key123")
        assert s.openalgo_host == "http://localhost:5000"

    def test_default_strategy(self):
        from flinttrade_core.config import Settings

        s = Settings(openalgo_host="http://localhost:5000", openalgo_api_key="key123")
        assert s.strategy == "Flint"


# ======================================================================
# Exception tests
# ======================================================================


class TestExceptions:
    """Test exception hierarchy and attributes."""

    def test_base_exception(self):
        from flinttrade_core.exceptions import FlintTradeError

        exc = FlintTradeError("boom")
        assert str(exc) == "boom"

    def test_api_error_attributes(self):
        from flinttrade_core.exceptions import APIError

        exc = APIError(400, "Bad request", "/placeorder")
        assert exc.status_code == 400
        assert exc.message == "Bad request"
        assert exc.endpoint == "/placeorder"
        assert "400" in str(exc)

    def test_rate_limit_error(self):
        from flinttrade_core.exceptions import OpenAlgoRateLimitError

        exc = OpenAlgoRateLimitError("/placeorder", retry_after=2.0)
        assert exc.status_code == 429
        assert exc.retry_after == 2.0

    def test_auth_error(self):
        from flinttrade_core.exceptions import OpenAlgoAuthError

        exc = OpenAlgoAuthError("/funds")
        assert exc.status_code == 401

    def test_config_error(self):
        from flinttrade_core.exceptions import ConfigError, FlintTradeError

        exc = ConfigError("missing key")
        assert isinstance(exc, FlintTradeError)

    def test_inheritance_chain(self):
        from flinttrade_core.exceptions import (
            APIError,
            OpenAlgoAuthError,
            FlintTradeError,
            OpenAlgoRateLimitError,
        )

        assert issubclass(APIError, FlintTradeError)
        assert issubclass(OpenAlgoRateLimitError, APIError)
        assert issubclass(OpenAlgoAuthError, APIError)


# ======================================================================
# Model tests
# ======================================================================


class TestModels:
    """Test Pydantic models for validation and defaults."""

    def test_order_defaults(self):
        from flinttrade_core.models import Order

        o = Order(symbol="RELIANCE", action="BUY")
        assert o.exchange.value == "NSE"
        assert o.pricetype.value == "MARKET"
        assert o.product.value == "MIS"
        assert o.quantity == "1"
        assert o.strategy == "Flint"

    def test_smart_order_has_position_size(self):
        from flinttrade_core.models import SmartOrder

        o = SmartOrder(symbol="TCS", action="SELL", position_size="5")
        assert o.position_size == "5"

    def test_options_order(self):
        from flinttrade_core.models import OptionsOrder

        o = OptionsOrder(underlying="NIFTY", expiry_date="260326")
        assert o.exchange.value == "NFO"
        assert o.offset == "0"
        assert o.option_type.value == "CE"

    def test_options_multi_order_legs(self):
        from flinttrade_core.models import OptionsLeg, OptionsMultiOrder

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
        from flinttrade_core.models import BasketOrder, BasketOrderItem

        basket = BasketOrder(
            orders=[
                BasketOrderItem(symbol="RELIANCE"),
                BasketOrderItem(symbol="TCS", action="SELL"),
            ]
        )
        assert len(basket.orders) == 2

    def test_split_order(self):
        from flinttrade_core.models import SplitOrder

        o = SplitOrder(symbol="RELIANCE", action="BUY", splitsize="25")
        assert o.splitsize == "25"

    def test_modify_order(self):
        from flinttrade_core.models import ModifyOrder

        o = ModifyOrder(orderid="123", symbol="RELIANCE", price="2550")
        assert o.orderid == "123"
        assert o.pricetype.value == "LIMIT"

    def test_quote_defaults(self):
        from flinttrade_core.models import Quote

        q = Quote()
        assert q.ltp == 0.0
        assert q.volume == 0

    def test_depth_levels(self):
        from flinttrade_core.models import Depth, DepthLevel

        d = Depth(
            symbol="RELIANCE",
            exchange="NSE",
            bids=[DepthLevel(price=2500.0, quantity=100, orders=5)],
            asks=[DepthLevel(price=2501.0, quantity=50, orders=3)],
        )
        assert len(d.bids) == 1
        assert d.asks[0].price == 2501.0

    def test_ohlcv(self):
        from flinttrade_core.models import OHLCV

        bar = OHLCV(timestamp="2026-03-14T09:15:00", open=100, high=105, low=99, close=103, volume=10000)
        assert bar.close == 103

    def test_fund(self):
        from flinttrade_core.models import Fund

        f = Fund(
            available_balance="100000",
            used_margin="25000",
            total_balance="125000",
            opening_risk_capital="150000",
        )
        assert f.available_balance == "100000"
        assert f.opening_risk_capital == "150000"
        assert Fund().opening_risk_capital == "0"

    def test_position(self):
        from flinttrade_core.models import Position

        p = Position(
            symbol="USDINR",
            exchange="CDS",
            quantity="10",
            pnl="500",
            multiplier=1000.0,
            fx_rate=83.25,
            close_price=0.0025,
        )
        assert p.pnl == "500"
        assert p.multiplier == 1000.0
        assert p.fx_rate == 83.25
        assert p.close_price == 0.0025

    def test_holding(self):
        from flinttrade_core.models import Holding

        h = Holding(
            symbol="TCS",
            exchange="NSE",
            product="CNC",
            quantity="5",
            average_price="3500",
            multiplier=1.0,
            fx_rate=1.0,
            close_price=3490.0,
        )
        assert h.average_price == "3500"
        assert (h.exchange, h.product) == ("NSE", "CNC")
        assert (h.multiplier, h.fx_rate, h.close_price) == (1.0, 1.0, 3490.0)

    def test_trade(self):
        from flinttrade_core.models import Trade

        t = Trade(
            orderid="123",
            symbol="INFY",
            action="BUY",
            price="1500",
            multiplier=1.0,
            fx_rate=1.0,
        )
        assert t.price == "1500"
        assert (t.multiplier, t.fx_rate) == (1.0, 1.0)

    def test_option_greek(self):
        from flinttrade_core.models import OptionGreek

        g = OptionGreek(symbol="NIFTY26MAR2524000CE", delta=0.5, iv=18.5)
        assert g.delta == 0.5

    def test_option_chain(self):
        from flinttrade_core.models import OptionChain, OptionChainStrike

        chain = OptionChain(
            underlying="NIFTY",
            exchange="NFO",
            spot_price=24050.0,
            strikes=[OptionChainStrike(strike_price=24000, ce_ltp=150, pe_ltp=120)],
        )
        assert len(chain.strikes) == 1
        assert chain.spot_price == 24050.0
        assert chain.strikes[0].strike_price == 24000

        with pytest.raises(ValueError, match="spot_price must be numeric"):
            OptionChain(spot_price=True)

    def test_order_response(self):
        from flinttrade_core.models import OrderResponse

        r = OrderResponse(status="success", orderid="456")
        assert r.status == "success"

    def test_enum_values(self):
        from flinttrade_core.models import Action, Exchange, PriceType, Product

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
        from flinttrade_core.config import Settings
        from flinttrade_core.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        return OpenAlgoClient(settings)

    def test_client_creates(self):
        client = self._make_client()
        assert client._base == "http://127.0.0.1:5000/api/v1"

    def test_client_context_manager(self):
        """Test that async context manager attributes exist."""
        from flinttrade_core.config import Settings
        from flinttrade_core.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        client = OpenAlgoClient(settings)
        assert client._api_key == "test123"
        assert hasattr(client, "__aenter__")
        assert hasattr(client, "__aexit__")

    def test_resolver_prefers_configured_app_client(self):
        """Routes should reuse app.config['CLIENT'] instead of rebuilding it."""
        from flinttrade_core.openalgo_client import get_openalgo_client, resolve_openalgo_client

        configured_client = MagicMock()
        app = MagicMock()
        app.config = {"CLIENT": configured_client}

        client, owns_client = resolve_openalgo_client(app)

        assert client is configured_client
        assert owns_client is False
        assert get_openalgo_client(app) is configured_client

    def test_resolver_falls_back_to_owned_client(self, monkeypatch, tmp_path):
        """Standalone callers still get an env/workspace-backed client to close."""
        import asyncio

        from flinttrade_core.openalgo_client import OpenAlgoClient, resolve_openalgo_client

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setenv("OPENALGO_HOST", "http://127.0.0.1:5000")
        monkeypatch.setenv("OPENALGO_API_KEY", "test123")

        client, owns_client = resolve_openalgo_client()

        assert isinstance(client, OpenAlgoClient)
        assert owns_client is True
        assert client.settings.openalgo_api_key == "test123"
        asyncio.run(client.close())

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
            # HG1 (2026-07-06): the former v2.0.0.1/v2.0.0.2 wrappers (health,
            # gex, iv_smile, max_pain, oi_profile, broker_capabilities,
            # pnl_symbols, leverage_settings) were removed — they called routes
            # that do not exist upstream (guaranteed 404s, zero callers); the
            # analytics live natively in flinttrade_screener.
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
        from flinttrade_core.openalgo_client import OpenAlgoClient
        import inspect

        sig = inspect.signature(OpenAlgoClient.search)
        params = sig.parameters
        assert "query" in params
        assert "exchange" in params
        # exchange must be optional so callers that omit it preserve the
        # broker-wide search behaviour from earlier versions.
        assert params["exchange"].default is None

    @pytest.mark.asyncio
    async def test_option_chain_sends_expiry_and_normalises_chain_shape(self):
        client = self._make_client()
        client._post = AsyncMock(return_value={
            "status": "success",
            "data": {
                "underlying": "NIFTY",
                "exchange": "NFO",
                "expiry_date": "26MAR26",
                "spot": 24050.0,
                "chain": [
                    {
                        "strike": 24000,
                        "ce": {"ltp": 150, "oi": 100, "volume": 50, "iv": 12.5},
                        "pe": {"ltp": 120, "oi": 80, "volume": 40, "iv": 13.0},
                    },
                ],
            },
        })

        chain = await client.option_chain("NIFTY", "NFO", "2026-03-26")

        endpoint, payload = client._post.await_args.args[:2]
        assert endpoint == "optionchain"
        assert payload["symbol"] == "NIFTY"
        assert payload["underlying"] == "NIFTY"
        assert payload["exchange"] == "NFO"
        assert payload["expiry"] == "2026-03-26"
        assert payload["expiry_date"] == "20260326"
        assert chain.underlying == "NIFTY"
        assert chain.expiry_date == "26MAR26"
        assert chain.spot_price == 24050.0
        assert chain.strikes[0].strike_price == 24000
        assert chain.strikes[0].ce_oi == 100
        assert chain.strikes[0].pe_ltp == 120
        await client.close()

    @pytest.mark.asyncio
    async def test_multi_quotes_normalises_documented_results_envelope(self):
        client = self._make_client()
        client._post = AsyncMock(return_value={
            "status": "success",
            "results": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "data": {
                        "open": 1542.3,
                        "high": 1571.6,
                        "low": 1540.5,
                        "ltp": 1569.9,
                        "prev_close": 1539.7,
                        "ask": 1569.9,
                        "bid": 0,
                        "oi": 0,
                        "volume": 14054299,
                    },
                },
                {
                    "symbol": "NIFTY26JULFUT",
                    "exchange": "NFO",
                    "data": {
                        "close": 24875.0,
                        "ltp": 24910.5,
                        "oi": 123456,
                        "volume": 654321,
                    },
                },
            ],
        })

        quotes = await client.multi_quotes([
            {"symbol": "RELIANCE", "exchange": "NSE"},
            {"symbol": "NIFTY26JULFUT", "exchange": "NFO"},
        ])

        assert [(quote.symbol, quote.exchange) for quote in quotes] == [
            ("RELIANCE", "NSE"),
            ("NIFTY26JULFUT", "NFO"),
        ]
        assert quotes[0].ltp == 1569.9
        assert quotes[0].prev_close == 1539.7
        assert quotes[1].ltp == 24910.5
        assert quotes[1].prev_close == 0.0
        await client.close()

    @pytest.mark.asyncio
    async def test_multi_quotes_retains_flat_list_compatibility(self):
        client = self._make_client()
        client._post = AsyncMock(return_value=[
            {
                "symbol": "USDINR26JULFUT",
                "exchange": "CDS",
                "ltp": 83.45,
                "prev_close": 83.2,
            },
        ])

        quotes = await client.multi_quotes([{"symbol": "USDINR26JULFUT", "exchange": "CDS"}])

        assert len(quotes) == 1
        assert quotes[0].ltp == 83.45
        assert quotes[0].prev_close == 83.2
        await client.close()

    @pytest.mark.asyncio
    async def test_tradebook_maps_documented_average_price_and_keeps_fill_time(self):
        client = self._make_client()
        client._post = AsyncMock(return_value={
            "status": "success",
            "data": [
                {
                    "action": "BUY",
                    "symbol": "NIFTY26JULFUT",
                    "exchange": "NFO",
                    "orderid": "250408000989443",
                    "product": "NRML",
                    "quantity": 65,
                    "average_price": 24875.25,
                    "timestamp": "13:58:03",
                    "trade_value": 1616891.25,
                },
                {
                    "action": "SELL",
                    "symbol": "USDINR26JULFUT",
                    "exchange": "CDS",
                    "orderid": "250408001086129",
                    "product": "NRML",
                    "quantity": 1,
                    "average_price": 83.45,
                    "timestamp": "14:28:49",
                    "multiplier": 1000.0,
                    "fx_rate": 1.0,
                },
            ],
        })

        trades = await client.tradebook()

        assert trades[0].quantity == "65"
        assert trades[0].price == "24875.25"
        assert trades[0].timestamp == "13:58:03"
        assert getattr(trades[0], "multiplier", None) is None
        assert getattr(trades[0], "fx_rate", None) is None
        assert trades[1].price == "83.45"
        assert trades[1].timestamp == "14:28:49"
        assert getattr(trades[1], "multiplier") == 1000.0
        assert getattr(trades[1], "fx_rate") == 1.0
        await client.close()

    @pytest.mark.asyncio
    async def test_funds_accepts_current_openalgo_fields_without_trusting_m2m(self):
        client = self._make_client()
        client._post = AsyncMock(return_value={
            "status": "success",
            "data": {
                "availablecash": "320.66",
                "collateral": "500.00",
                "m2mrealized": "999999.00",
                "m2munrealized": "-888888.00",
                "utiliseddebits": "679.34",
            },
        })

        funds = await client.funds()

        assert funds.available_balance == "320.66"
        assert funds.used_margin == "679.34"
        assert funds.total_balance == "1000.00"
        assert funds.opening_risk_capital == "0"
        assert funds.extra["m2mrealized"] == "999999.00"
        assert funds.extra["m2munrealized"] == "-888888.00"
        await client.close()

    @pytest.mark.asyncio
    async def test_funds_uses_only_explicit_opening_balance_for_risk_capital(self):
        client = self._make_client()
        client._post = AsyncMock(return_value={
            "status": "success",
            "data": {
                "availablecash": "400.00",
                "utiliseddebits": "600.00",
                "openingcashlimit": "1250.00",
            },
        })

        funds = await client.funds()

        assert funds.total_balance == "1000.00"
        assert funds.opening_risk_capital == "1250.00"
        await client.close()


# ======================================================================
# Rate limiter tests
# ======================================================================


class TestRateLimiter:
    """Test the token-bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_limiter_allows_burst(self):
        from flinttrade_core.openalgo_client import _RateLimiter

        rl = _RateLimiter(10, 1.0)
        start = time.monotonic()
        for _ in range(10):
            await rl.acquire()
        elapsed = time.monotonic() - start
        # First 10 should be near-instant (within the burst)
        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_limiter_throttles_past_burst(self):
        from flinttrade_core.openalgo_client import _RateLimiter

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
        from flinttrade_core.config import Settings
        from flinttrade_core.openalgo_client import OpenAlgoClient

        settings = Settings(openalgo_host="http://127.0.0.1:5000", openalgo_api_key="test123")
        return OpenAlgoClient(settings)

    @pytest.fixture
    async def client(self):
        client = self._make_client()
        try:
            yield client
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_auth_error_on_401(self, client):
        from flinttrade_core.exceptions import OpenAlgoAuthError

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.content = b'{"message": "Invalid API key"}'
        mock_resp.json.return_value = {"message": "Invalid API key"}

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(OpenAlgoAuthError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_rate_limit_error_on_429(self, client):
        from flinttrade_core.exceptions import OpenAlgoRateLimitError

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "1"}

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(OpenAlgoRateLimitError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_api_error_on_500(self, client):
        from flinttrade_core.exceptions import APIError

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.content = b'{"message": "Internal error"}'
        mock_resp.json.return_value = {"message": "Internal error"}
        mock_resp.text = "Internal error"

        client._http.post = AsyncMock(return_value=mock_resp)
        with pytest.raises(APIError):
            await client.ping()

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self, client):
        import httpx

        from flinttrade_core.exceptions import APIError

        client._http.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(APIError, match="Failed after 3 retries"):
            await client.ping()

    @pytest.mark.asyncio
    async def test_error_status_in_response_body(self, client):
        from flinttrade_core.exceptions import APIError

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
        from flinttrade_core import __all__

        assert "OpenAlgoClient" in __all__
        assert "Settings" in __all__
        assert "FlintTradeConfig" in __all__
        assert "Workspace" in __all__
        assert "Order" in __all__
        assert "Quote" in __all__
        assert "APIError" in __all__
        assert "FlintTradeError" in __all__

    def test_package_version(self):
        from flinttrade_core import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_core", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
