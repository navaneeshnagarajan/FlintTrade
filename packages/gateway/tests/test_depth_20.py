"""Tests for packages.gateway.src.ws_proxy.depth_20.

Covers:
- DepthLevel dataclass
- Depth20Tick dataclass and to_dict()
- parse_depth_20_payload(): list-of-lists format, list-of-dicts format,
  missing fields (defaults), truncation to 20 levels, provided totals,
  computed totals, missing symbol/exchange raises KeyError
- _parse_levels(): malformed entry raises ValueError, short list raises ValueError
- Depth20Aggregator.aggregate_to_5(): truncation, re-computed totals,
  fewer-than-5 levels pass-through
- Depth20Aggregator.order_book_imbalance(): positive, negative, neutral, empty book
- Depth20Aggregator.weighted_mid_price(): normal, empty book
- Depth20Aggregator.spread(): normal, empty book
- MockBrokerAdapter.build_depth20_tick(): returns Depth20Tick with 20 levels
"""

from __future__ import annotations

import time

import pytest

from ws_proxy.depth_20 import (
    Depth20Aggregator,
    Depth20Tick,
    DepthLevel,
    _parse_levels,
    parse_depth_20_payload,
)
from ws_proxy.mock_adapter import MockBrokerAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_levels_list(n: int, base_price: float = 100.0, side: str = "bids") -> list[list]:
    """Generate n list-of-lists depth levels."""
    sign = -1 if side == "bids" else 1
    return [[base_price + sign * i * 0.5, 100 + i * 10, i + 1] for i in range(n)]


def _make_raw(n_bids: int = 5, n_asks: int = 5) -> dict:
    """Build a minimal raw depth payload."""
    bids = _make_levels_list(n_bids, 100.0, "bids")
    asks = _make_levels_list(n_asks, 100.5, "asks")
    return {
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "timestamp": 1714000000.0,
        "ltp": 100.25,
        "bids": bids,
        "asks": asks,
        "total_buy_qty": sum(lvl[1] for lvl in bids),
        "total_sell_qty": sum(lvl[1] for lvl in asks),
    }


# ---------------------------------------------------------------------------
# DepthLevel
# ---------------------------------------------------------------------------


class TestDepthLevel:
    def test_fields_stored(self) -> None:
        lvl = DepthLevel(price=100.5, quantity=200, orders=3)
        assert lvl.price == 100.5
        assert lvl.quantity == 200
        assert lvl.orders == 3


# ---------------------------------------------------------------------------
# Depth20Tick
# ---------------------------------------------------------------------------


class TestDepth20Tick:
    def test_to_dict_keys(self) -> None:
        tick = Depth20Tick(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            timestamp=1714000000.0,
            bids=[DepthLevel(99.5, 100, 2)],
            asks=[DepthLevel(100.5, 80, 1)],
            total_buy_qty=100,
            total_sell_qty=80,
            ltp=100.0,
        )
        d = tick.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["exchange"] == "NSE_INDEX"
        assert d["ltp"] == 100.0
        assert isinstance(d["bids"], list)
        assert d["bids"][0] == {"price": 99.5, "qty": 100, "orders": 2}
        assert isinstance(d["asks"], list)
        assert d["total_buy_qty"] == 100
        assert d["total_sell_qty"] == 80


# ---------------------------------------------------------------------------
# parse_depth_20_payload()
# ---------------------------------------------------------------------------


class TestParseDepth20Payload:
    def test_basic_parse_list_of_lists(self) -> None:
        raw = _make_raw(5, 5)
        tick = parse_depth_20_payload(raw)
        assert tick.symbol == "NIFTY"
        assert tick.exchange == "NSE_INDEX"
        assert len(tick.bids) == 5
        assert len(tick.asks) == 5
        assert isinstance(tick.bids[0], DepthLevel)

    def test_list_of_dicts_format(self) -> None:
        raw = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "bids": [{"price": 99.5, "qty": 100, "orders": 2}],
            "asks": [{"price": 100.5, "qty": 80, "orders": 1}],
        }
        tick = parse_depth_20_payload(raw)
        assert tick.bids[0].price == 99.5
        assert tick.asks[0].quantity == 80

    def test_truncated_to_20_levels(self) -> None:
        raw = _make_raw(25, 25)
        tick = parse_depth_20_payload(raw)
        assert len(tick.bids) <= 20
        assert len(tick.asks) <= 20

    def test_provided_totals_used(self) -> None:
        raw = _make_raw(3, 3)
        raw["total_buy_qty"] = 9999
        raw["total_sell_qty"] = 8888
        tick = parse_depth_20_payload(raw)
        assert tick.total_buy_qty == 9999
        assert tick.total_sell_qty == 8888

    def test_computed_totals_when_absent(self) -> None:
        raw = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "bids": [[100.0, 200, 3]],
            "asks": [[100.5, 150, 2]],
        }
        tick = parse_depth_20_payload(raw)
        assert tick.total_buy_qty == 200
        assert tick.total_sell_qty == 150

    def test_missing_symbol_raises(self) -> None:
        raw = {"exchange": "NSE_INDEX", "bids": [], "asks": []}
        with pytest.raises(KeyError):
            parse_depth_20_payload(raw)

    def test_timestamp_defaults_to_now(self) -> None:
        raw = {"symbol": "TEST", "exchange": "NSE", "bids": [], "asks": []}
        before = time.time()
        tick = parse_depth_20_payload(raw)
        assert tick.timestamp >= before

    def test_ltp_defaults_to_zero(self) -> None:
        raw = {"symbol": "TEST", "exchange": "NSE", "bids": [], "asks": []}
        tick = parse_depth_20_payload(raw)
        assert tick.ltp == 0.0

    def test_malformed_level_raises(self) -> None:
        raw = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "bids": [[100.0, 200]],  # only 2 elements
            "asks": [],
        }
        with pytest.raises(ValueError, match="expected"):
            parse_depth_20_payload(raw)

    def test_unrecognised_level_type_raises(self) -> None:
        raw = {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "bids": ["not_a_level"],
            "asks": [],
        }
        with pytest.raises(ValueError, match="unrecognised"):
            parse_depth_20_payload(raw)


# ---------------------------------------------------------------------------
# Depth20Aggregator.aggregate_to_5()
# ---------------------------------------------------------------------------


class TestAggregateToFive:
    def _make_tick(self, n: int) -> Depth20Tick:
        bids = [DepthLevel(100.0 - i * 0.5, 100, 1) for i in range(n)]
        asks = [DepthLevel(100.5 + i * 0.5, 100, 1) for i in range(n)]
        return Depth20Tick(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            timestamp=1714000000.0,
            bids=bids,
            asks=asks,
            total_buy_qty=n * 100,
            total_sell_qty=n * 100,
        )

    def test_truncates_to_5_levels(self) -> None:
        agg = Depth20Aggregator()
        tick20 = self._make_tick(20)
        tick5 = agg.aggregate_to_5(tick20)
        assert len(tick5.bids) == 5
        assert len(tick5.asks) == 5

    def test_totals_recalculated(self) -> None:
        agg = Depth20Aggregator()
        tick20 = self._make_tick(20)
        tick5 = agg.aggregate_to_5(tick20)
        assert tick5.total_buy_qty == 5 * 100
        assert tick5.total_sell_qty == 5 * 100

    def test_fewer_than_5_levels_passes_through(self) -> None:
        agg = Depth20Aggregator()
        tick3 = self._make_tick(3)
        result = agg.aggregate_to_5(tick3)
        assert len(result.bids) == 3
        assert len(result.asks) == 3

    def test_metadata_preserved(self) -> None:
        agg = Depth20Aggregator()
        tick = self._make_tick(10)
        result = agg.aggregate_to_5(tick)
        assert result.symbol == "NIFTY"
        assert result.exchange == "NSE_INDEX"


# ---------------------------------------------------------------------------
# Depth20Aggregator.order_book_imbalance()
# ---------------------------------------------------------------------------


class TestOrderBookImbalance:
    def _tick(self, buy: int, sell: int) -> Depth20Tick:
        return Depth20Tick(
            symbol="T",
            exchange="E",
            timestamp=0.0,
            total_buy_qty=buy,
            total_sell_qty=sell,
        )

    def test_buy_heavy_positive(self) -> None:
        agg = Depth20Aggregator()
        result = agg.order_book_imbalance(self._tick(800, 200))
        assert result == pytest.approx(0.6)

    def test_sell_heavy_negative(self) -> None:
        agg = Depth20Aggregator()
        result = agg.order_book_imbalance(self._tick(200, 800))
        assert result == pytest.approx(-0.6)

    def test_balanced_zero(self) -> None:
        agg = Depth20Aggregator()
        result = agg.order_book_imbalance(self._tick(500, 500))
        assert result == pytest.approx(0.0)

    def test_empty_book_returns_zero(self) -> None:
        agg = Depth20Aggregator()
        result = agg.order_book_imbalance(self._tick(0, 0))
        assert result == 0.0

    def test_range_constraint(self) -> None:
        agg = Depth20Aggregator()
        for buy, sell in [(1000, 0), (0, 1000), (500, 500), (300, 700)]:
            result = agg.order_book_imbalance(self._tick(buy, sell))
            assert -1.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Depth20Aggregator.weighted_mid_price() and spread()
# ---------------------------------------------------------------------------


class TestAggregatorHelpers:
    def _tick_with_levels(self) -> Depth20Tick:
        return Depth20Tick(
            symbol="T",
            exchange="E",
            timestamp=0.0,
            bids=[DepthLevel(price=99.0, quantity=200, orders=3)],
            asks=[DepthLevel(price=101.0, quantity=100, orders=2)],
            total_buy_qty=200,
            total_sell_qty=100,
        )

    def test_weighted_mid_price_not_zero(self) -> None:
        agg = Depth20Aggregator()
        wmp = agg.weighted_mid_price(self._tick_with_levels())
        # weighted: (99 * 100 + 101 * 200) / 300 = (9900 + 20200) / 300 ≈ 100.33
        assert wmp == pytest.approx((99.0 * 100 + 101.0 * 200) / 300, rel=1e-5)

    def test_weighted_mid_price_empty_book(self) -> None:
        agg = Depth20Aggregator()
        tick = Depth20Tick(symbol="T", exchange="E", timestamp=0.0)
        assert agg.weighted_mid_price(tick) == 0.0

    def test_spread_normal(self) -> None:
        agg = Depth20Aggregator()
        spread = agg.spread(self._tick_with_levels())
        assert spread == pytest.approx(2.0)

    def test_spread_empty_book(self) -> None:
        agg = Depth20Aggregator()
        tick = Depth20Tick(symbol="T", exchange="E", timestamp=0.0)
        assert agg.spread(tick) == 0.0


# ---------------------------------------------------------------------------
# MockBrokerAdapter.build_depth20_tick()
# ---------------------------------------------------------------------------


class TestMockAdapterDepth20:
    def test_build_depth20_tick_returns_depth20tick(self) -> None:
        adapter = MockBrokerAdapter()
        tick = adapter.build_depth20_tick("NIFTY", "NSE_INDEX")
        assert isinstance(tick, Depth20Tick)

    def test_build_depth20_tick_has_20_levels(self) -> None:
        adapter = MockBrokerAdapter()
        tick = adapter.build_depth20_tick("NIFTY", "NSE_INDEX")
        assert len(tick.bids) == 20
        assert len(tick.asks) == 20

    def test_build_depth20_tick_symbol(self) -> None:
        adapter = MockBrokerAdapter()
        tick = adapter.build_depth20_tick("BANKNIFTY", "NSE_INDEX")
        assert tick.symbol == "BANKNIFTY"
        assert tick.exchange == "NSE_INDEX"
