"""Tests for order_analytics.py — execution quality metrics.

All tests are pure in-memory; no broker connections or DuckDB required.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_test_dir, "..", "..", ".."))
sys.path.insert(0, os.path.join(_test_dir, "..", "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _order(
    status: str = "complete",
    price: float = 100.0,
    average_price: float = 100.0,
    quantity: int = 10,
    filled_quantity: int | None = None,
    symbol: str = "NIFTY",
    action: str = "BUY",
    order_timestamp: str = "2026-04-09T09:15:00",
    fill_timestamp: str = "2026-04-09T09:15:01",
    rejection_reason: str = "",
) -> dict:
    """Construct a minimal order dict for testing."""
    o: dict = {
        "status": status,
        "price": price,
        "average_price": average_price,
        "quantity": quantity,
        "symbol": symbol,
        "action": action,
        "order_timestamp": order_timestamp,
        "fill_timestamp": fill_timestamp,
    }
    if filled_quantity is not None:
        o["filled_quantity"] = filled_quantity
    if rejection_reason:
        o["rejection_reason"] = rejection_reason
    return o


def _make_analytics(orders):
    from order_analytics import OrderAnalytics
    return OrderAnalytics(orders)


# ---------------------------------------------------------------------------
# fill_rate
# ---------------------------------------------------------------------------


class TestFillRate:
    def test_empty_orders(self):
        a = _make_analytics([])
        assert a.fill_rate() == 0.0

    def test_all_filled(self):
        orders = [_order(status="complete") for _ in range(5)]
        a = _make_analytics(orders)
        assert a.fill_rate() == 100.0

    def test_none_filled(self):
        orders = [_order(status="rejected") for _ in range(4)]
        a = _make_analytics(orders)
        assert a.fill_rate() == 0.0

    def test_half_filled(self):
        orders = [_order(status="complete")] * 3 + [_order(status="rejected")] * 3
        a = _make_analytics(orders)
        assert a.fill_rate() == pytest.approx(50.0)

    def test_filled_status_variants(self):
        orders = [
            _order(status="filled"),
            _order(status="traded"),
            _order(status="COMPLETE"),
        ]
        a = _make_analytics(orders)
        assert a.fill_rate() == 100.0

    def test_filled_by_quantity(self):
        """Order without 'complete' status but filled_quantity >= quantity counts as filled."""
        o = _order(status="open")
        o["filled_quantity"] = 10
        o["quantity"] = 10
        a = _make_analytics([o])
        assert a.fill_rate() == 100.0

    def test_partially_filled_not_counted(self):
        o = _order(status="open")
        o["filled_quantity"] = 5
        o["quantity"] = 10
        a = _make_analytics([o])
        assert a.fill_rate() == 0.0

    def test_single_filled(self):
        a = _make_analytics([_order(status="complete")])
        assert a.fill_rate() == 100.0

    def test_fill_rate_precision(self):
        orders = [_order(status="complete")] * 1 + [_order(status="rejected")] * 2
        a = _make_analytics(orders)
        assert a.fill_rate() == pytest.approx(100 / 3)


# ---------------------------------------------------------------------------
# average_slippage
# ---------------------------------------------------------------------------


class TestAverageSlippage:
    def test_no_slippage_data(self):
        o = _order()
        del o["price"]
        a = _make_analytics([o])
        assert a.average_slippage() == 0.0

    def test_zero_slippage(self):
        orders = [_order(price=100.0, average_price=100.0) for _ in range(5)]
        a = _make_analytics(orders)
        assert a.average_slippage() == pytest.approx(0.0)

    def test_positive_slippage_buy(self):
        """BUY filled above intended → positive slippage."""
        o = _order(action="BUY", price=100.0, average_price=100.1)
        a = _make_analytics([o])
        # (100.1 - 100.0) / 100.0 * 10000 = 10 bps
        assert a.average_slippage() == pytest.approx(10.0)

    def test_negative_slippage_buy(self):
        """BUY filled below intended → negative slippage (better than expected)."""
        o = _order(action="BUY", price=100.0, average_price=99.9)
        a = _make_analytics([o])
        assert a.average_slippage() == pytest.approx(-10.0)

    def test_positive_slippage_sell(self):
        """SELL filled below intended → positive slippage."""
        o = _order(action="SELL", price=100.0, average_price=99.9)
        a = _make_analytics([o])
        assert a.average_slippage() == pytest.approx(10.0)

    def test_slippage_only_for_filled(self):
        """Rejected orders are excluded from slippage calculation."""
        orders = [
            _order(status="complete", price=100.0, average_price=100.5),
            _order(status="rejected", price=100.0, average_price=200.0),
        ]
        a = _make_analytics(orders)
        # Only the first order: (100.5 - 100.0) / 100.0 * 10000 = 50 bps
        assert a.average_slippage() == pytest.approx(50.0)

    def test_average_across_multiple(self):
        orders = [
            _order(price=100.0, average_price=100.1),  # +10 bps
            _order(price=100.0, average_price=100.3),  # +30 bps
        ]
        a = _make_analytics(orders)
        assert a.average_slippage() == pytest.approx(20.0)

    def test_zero_intended_price_skipped(self):
        o = _order(price=0.0, average_price=100.0)
        a = _make_analytics([o])
        assert a.average_slippage() == 0.0


# ---------------------------------------------------------------------------
# execution_speed
# ---------------------------------------------------------------------------


class TestExecutionSpeed:
    def test_no_timing_data(self):
        o = _order()
        del o["fill_timestamp"]
        a = _make_analytics([o])
        speed = a.execution_speed()
        assert speed["average_ms"] == 0.0
        assert speed["p50_ms"] == 0.0
        assert speed["p95_ms"] == 0.0
        assert speed["p99_ms"] == 0.0

    def test_single_order_one_second(self):
        o = _order(
            order_timestamp="2026-04-09T09:15:00",
            fill_timestamp="2026-04-09T09:15:01",
        )
        a = _make_analytics([o])
        speed = a.execution_speed()
        assert speed["average_ms"] == pytest.approx(1000.0)
        assert speed["p50_ms"] == pytest.approx(1000.0)

    def test_only_filled_orders_counted(self):
        orders = [
            _order(
                status="complete",
                order_timestamp="2026-04-09T09:15:00",
                fill_timestamp="2026-04-09T09:15:01",
            ),
            _order(
                status="rejected",
                order_timestamp="2026-04-09T09:15:00",
                fill_timestamp="2026-04-09T09:15:10",  # should be excluded
            ),
        ]
        a = _make_analytics(orders)
        speed = a.execution_speed()
        assert speed["average_ms"] == pytest.approx(1000.0)

    def test_percentiles(self):
        """p95 should be higher than p50 for a spread of latencies."""
        import datetime as dt

        base = dt.datetime(2026, 4, 9, 9, 15, 0)
        orders = []
        for i in range(1, 101):
            place = base.strftime("%Y-%m-%dT%H:%M:%S")
            fill = (base + dt.timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%S")
            orders.append(_order(order_timestamp=place, fill_timestamp=fill))
        a = _make_analytics(orders)
        speed = a.execution_speed()
        assert speed["p95_ms"] > speed["p50_ms"]
        assert speed["p99_ms"] >= speed["p95_ms"]

    def test_epoch_timestamps(self):
        """Accept Unix epoch floats as timestamps."""
        import datetime as dt

        base_epoch = dt.datetime(2026, 4, 9, 9, 15, 0).timestamp()
        o = _order(
            order_timestamp=base_epoch,
            fill_timestamp=base_epoch + 2.0,
        )
        a = _make_analytics([o])
        speed = a.execution_speed()
        assert speed["average_ms"] == pytest.approx(2000.0)


# ---------------------------------------------------------------------------
# rejection_analysis
# ---------------------------------------------------------------------------


class TestRejectionAnalysis:
    def test_no_rejections(self):
        a = _make_analytics([_order(status="complete")])
        assert a.rejection_analysis() == {}

    def test_single_rejection(self):
        o = _order(status="rejected", rejection_reason="Insufficient margin")
        a = _make_analytics([o])
        result = a.rejection_analysis()
        assert result == {"Insufficient margin": 1}

    def test_multiple_reasons(self):
        orders = [
            _order(status="rejected", rejection_reason="Insufficient margin"),
            _order(status="rejected", rejection_reason="Insufficient margin"),
            _order(status="rejected", rejection_reason="Price out of range"),
        ]
        a = _make_analytics(orders)
        result = a.rejection_analysis()
        assert result["Insufficient margin"] == 2
        assert result["Price out of range"] == 1

    def test_sorted_descending(self):
        orders = [
            _order(status="rejected", rejection_reason="A"),
            _order(status="rejected", rejection_reason="B"),
            _order(status="rejected", rejection_reason="B"),
            _order(status="rejected", rejection_reason="C"),
            _order(status="rejected", rejection_reason="C"),
            _order(status="rejected", rejection_reason="C"),
        ]
        a = _make_analytics(orders)
        result = a.rejection_analysis()
        keys = list(result.keys())
        assert keys[0] == "C"
        assert keys[1] == "B"

    def test_unknown_reason_fallback(self):
        o = _order(status="rejected")
        a = _make_analytics([o])
        result = a.rejection_analysis()
        assert "Unknown" in result


# ---------------------------------------------------------------------------
# by_hour
# ---------------------------------------------------------------------------


class TestByHour:
    def test_empty_orders_no_timestamp(self):
        o = {"status": "complete", "symbol": "NIFTY", "price": 100.0}
        a = _make_analytics([o])
        # No timestamps → no hourly breakdown
        result = a.by_hour()
        assert result == {}

    def test_grouping_by_hour(self):
        orders = [
            _order(order_timestamp="2026-04-09T09:15:00", fill_timestamp="2026-04-09T09:15:01"),
            _order(order_timestamp="2026-04-09T09:30:00", fill_timestamp="2026-04-09T09:30:01"),
            _order(
                status="rejected",
                order_timestamp="2026-04-09T10:00:00",
                fill_timestamp="2026-04-09T10:00:01",
            ),
        ]
        a = _make_analytics(orders)
        result = a.by_hour()
        # Hours present in IST — 09:15 IST epoch is 03:45 UTC, offset +5:30 → hour 9
        assert any(h in result for h in range(0, 24))

    def test_fill_rate_in_hour_breakdown(self):
        orders = [
            _order(status="complete", order_timestamp="2026-04-09T09:15:00"),
            _order(status="rejected", order_timestamp="2026-04-09T09:20:00"),
        ]
        a = _make_analytics(orders)
        result = a.by_hour()
        for h, stats in result.items():
            assert "fill_rate_pct" in stats
            assert "avg_slippage_bps" in stats
            assert "order_count" in stats

    def test_100_percent_hour(self):
        orders = [
            _order(status="complete", order_timestamp="2026-04-09T09:15:00"),
            _order(status="complete", order_timestamp="2026-04-09T09:20:00"),
        ]
        a = _make_analytics(orders)
        result = a.by_hour()
        for h, stats in result.items():
            assert stats["fill_rate_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# by_symbol
# ---------------------------------------------------------------------------


class TestBySymbol:
    def test_multiple_symbols(self):
        orders = [
            _order(symbol="NIFTY", status="complete"),
            _order(symbol="NIFTY", status="rejected"),
            _order(symbol="BANKNIFTY", status="complete"),
        ]
        a = _make_analytics(orders)
        result = a.by_symbol()
        assert "NIFTY" in result
        assert "BANKNIFTY" in result

    def test_fill_rate_per_symbol(self):
        orders = [
            _order(symbol="NIFTY", status="complete"),
            _order(symbol="NIFTY", status="rejected"),
        ]
        a = _make_analytics(orders)
        result = a.by_symbol()
        assert result["NIFTY"]["fill_rate_pct"] == pytest.approx(50.0)

    def test_volume_accumulation(self):
        orders = [
            _order(symbol="NIFTY", status="complete", quantity=10, filled_quantity=10),
            _order(symbol="NIFTY", status="complete", quantity=15, filled_quantity=15),
        ]
        a = _make_analytics(orders)
        result = a.by_symbol()
        assert result["NIFTY"]["total_volume"] == pytest.approx(25.0)

    def test_tradingsymbol_key_fallback(self):
        o = {
            "tradingsymbol": "RELIANCE",
            "status": "complete",
            "price": 100.0,
            "average_price": 100.0,
        }
        a = _make_analytics([o])
        result = a.by_symbol()
        assert "RELIANCE" in result

    def test_order_count_per_symbol(self):
        orders = [_order(symbol="NIFTY") for _ in range(7)]
        a = _make_analytics(orders)
        result = a.by_symbol()
        assert result["NIFTY"]["order_count"] == 7.0


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_empty_summary(self):
        from order_analytics import OrderExecutionSummary

        a = _make_analytics([])
        s = a.summary()
        assert isinstance(s, OrderExecutionSummary)
        assert s.total_orders == 0
        assert s.fill_rate_pct == 0.0

    def test_summary_types(self):
        from order_analytics import OrderExecutionSummary

        orders = [_order() for _ in range(10)]
        a = _make_analytics(orders)
        s = a.summary()
        assert isinstance(s, OrderExecutionSummary)
        assert isinstance(s.total_orders, int)
        assert isinstance(s.filled, int)
        assert isinstance(s.rejected, int)
        assert isinstance(s.cancelled, int)
        assert isinstance(s.fill_rate_pct, float)
        assert isinstance(s.avg_slippage_bps, float)
        assert isinstance(s.median_execution_ms, float)
        assert isinstance(s.p95_execution_ms, float)
        assert isinstance(s.best_hour, int)
        assert isinstance(s.worst_hour, int)
        assert isinstance(s.top_rejection_reasons, list)

    def test_summary_counts(self):
        orders = (
            [_order(status="complete")] * 6
            + [_order(status="rejected", rejection_reason="Margin")] * 2
            + [_order(status="cancelled")] * 2
        )
        a = _make_analytics(orders)
        s = a.summary()
        assert s.total_orders == 10
        assert s.filled == 6
        assert s.rejected == 2
        assert s.cancelled == 2
        assert s.fill_rate_pct == pytest.approx(60.0)

    def test_summary_serialisable(self):
        import json

        orders = [_order() for _ in range(5)]
        a = _make_analytics(orders)
        s = a.summary()
        # model_dump() should produce JSON-serialisable data
        data = s.model_dump()
        json.dumps(data)  # should not raise

    def test_top_rejection_reasons_capped(self):
        reasons = ["A", "B", "C", "D", "E", "F"]
        orders = [
            _order(status="rejected", rejection_reason=r)
            for r in reasons
        ]
        a = _make_analytics(orders)
        s = a.summary()
        assert len(s.top_rejection_reasons) <= 5

    def test_fill_rate_pct_bounds(self):
        orders = [_order(status="complete")] * 10
        a = _make_analytics(orders)
        s = a.summary()
        assert 0.0 <= s.fill_rate_pct <= 100.0

    def test_execution_ms_non_negative(self):
        orders = [_order() for _ in range(5)]
        a = _make_analytics(orders)
        s = a.summary()
        assert s.median_execution_ms >= 0.0
        assert s.p95_execution_ms >= 0.0


# ---------------------------------------------------------------------------
# Flask endpoint
# ---------------------------------------------------------------------------


class TestExecutionAnalyticsEndpoint:
    @pytest.fixture()
    def client(self):
        from flask import Flask
        from order_analytics import order_analytics_bp

        app = Flask(__name__)
        app.register_blueprint(order_analytics_bp, url_prefix="/ft-api/v1")
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c

    def test_missing_body(self, client):
        resp = client.post("/ft-api/v1/analytics/execution")
        assert resp.status_code == 400

    def test_missing_orders_key(self, client):
        resp = client.post(
            "/ft-api/v1/analytics/execution",
            json={"foo": "bar"},
        )
        assert resp.status_code == 400

    def test_orders_not_list(self, client):
        resp = client.post(
            "/ft-api/v1/analytics/execution",
            json={"orders": "not-a-list"},
        )
        assert resp.status_code == 400

    def test_valid_request(self, client):
        orders = [_order() for _ in range(5)]
        resp = client.post(
            "/ft-api/v1/analytics/execution",
            json={"orders": orders},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        assert "data" in body
        data = body["data"]
        assert data["total_orders"] == 5

    def test_empty_orders(self, client):
        resp = client.post(
            "/ft-api/v1/analytics/execution",
            json={"orders": []},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["total_orders"] == 0
