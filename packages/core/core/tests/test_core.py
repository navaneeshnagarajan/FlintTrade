"""Tests for FlintTrade core package.

Unit tests exercise native domain models and package exports.
"""

import os

import pytest


# ======================================================================
# Config tests
# ======================================================================


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

    def test_config_error(self):
        from flinttrade_core.exceptions import ConfigError, FlintTradeError

        exc = ConfigError("missing key")
        assert isinstance(exc, FlintTradeError)

    def test_inheritance_chain(self):
        from flinttrade_core.exceptions import APIError, FlintTradeError

        assert issubclass(APIError, FlintTradeError)


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


# ======================================================================
# Rate limiter tests
# ======================================================================


# ======================================================================
# Error handling tests (async)
# ======================================================================


# ======================================================================
# Package-level import tests
# ======================================================================


class TestPackageExports:
    """Verify that __init__.py exports everything."""

    def test_all_exports(self):
        from flinttrade_core import __all__

        assert "BrokerClient" in __all__
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
