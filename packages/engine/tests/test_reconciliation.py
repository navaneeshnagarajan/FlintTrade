"""Tests for ReconciliationEngine.

DO NOT RUN live — all inputs are synthetic dicts. No broker calls.
"""

from __future__ import annotations


# ======================================================================
# Helpers
# ======================================================================


def _pos(symbol: str, qty: int, avg_price: float = 100.0, exchange: str = "NSE", product: str = "MIS") -> dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": str(qty),
        "average_price": str(avg_price),
    }


def _order(order_id: str, status: str, qty: int = 1) -> dict:
    return {
        "orderid": order_id,
        "status": status,
        "quantity": str(qty),
    }


# ======================================================================
# ReconciliationResult — property tests
# ======================================================================


class TestReconciliationResult:
    def test_clean_when_no_mismatches(self):
        from packages.engine.src.reconciliation import ReconciliationResult
        result = ReconciliationResult(mismatches=[], checked_count=5)
        assert result.clean
        assert not result.has_mismatches
        assert result.mismatch_count == 0

    def test_not_clean_when_mismatches_present(self):
        from packages.engine.src.reconciliation import ReconciliationResult, Mismatch, MismatchKind
        m = Mismatch(kind=MismatchKind.MISSING_IN_LOCAL, symbol="NIFTY")
        result = ReconciliationResult(mismatches=[m], checked_count=3)
        assert not result.clean
        assert result.has_mismatches
        assert result.mismatch_count == 1

    def test_summary_clean(self):
        from packages.engine.src.reconciliation import ReconciliationResult
        result = ReconciliationResult(mismatches=[], checked_count=10)
        assert "clean" in result.summary()
        assert "10" in result.summary()

    def test_summary_with_mismatches(self):
        from packages.engine.src.reconciliation import ReconciliationResult, Mismatch, MismatchKind
        mismatches = [
            Mismatch(kind=MismatchKind.MISSING_IN_LOCAL, symbol="A"),
            Mismatch(kind=MismatchKind.QUANTITY_MISMATCH, symbol="B"),
            Mismatch(kind=MismatchKind.MISSING_IN_LOCAL, symbol="C"),
        ]
        result = ReconciliationResult(mismatches=mismatches, checked_count=5)
        summary = result.summary()
        assert "missing_in_local=2" in summary
        assert "quantity_mismatch=1" in summary


# ======================================================================
# reconcile_positions
# ======================================================================


class TestReconcilePositions:
    def _engine(self):
        from packages.engine.src.reconciliation import ReconciliationEngine
        return ReconciliationEngine(price_tolerance_pct=0.1)

    def test_identical_positions_are_clean(self):
        engine = self._engine()
        positions = [_pos("RELIANCE", 10), _pos("TCS", 5)]
        result = engine.reconcile_positions(positions, positions)
        assert result.clean
        assert result.checked_count == 2

    def test_missing_in_local_detected(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_pos("RELIANCE", 10), _pos("INFY", 5)]
        local = [_pos("RELIANCE", 10)]  # INFY missing locally
        result = engine.reconcile_positions(broker, local)
        assert result.has_mismatches
        kinds = [m.kind for m in result.mismatches]
        assert MismatchKind.MISSING_IN_LOCAL in kinds

    def test_missing_in_broker_detected_for_nonzero_qty(self):
        """A non-zero local position absent from the broker is now CLOSED_MANUAL.

        This represents an external close (manual trade or broker risk system)
        rather than a generic MISSING_IN_BROKER discrepancy.
        """
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 10), _pos("INFY", 5)]  # INFY not in broker
        result = engine.reconcile_positions(broker, local)
        assert result.has_mismatches
        kinds = [m.kind for m in result.mismatches]
        # Changed from MISSING_IN_BROKER → CLOSED_MANUAL: a position that was
        # open locally but has disappeared from the broker was closed externally.
        assert MismatchKind.CLOSED_MANUAL in kinds

    def test_missing_in_broker_ignored_for_zero_qty(self):
        """Zero-quantity local positions (already closed) should not raise mismatch."""
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 10), _pos("INFY", 0)]  # INFY closed (qty=0)
        result = engine.reconcile_positions(broker, local)
        assert result.clean

    def test_quantity_mismatch_detected(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 8)]  # broker says 10, local says 8
        result = engine.reconcile_positions(broker, local)
        assert result.has_mismatches
        m = result.mismatches[0]
        assert m.kind == MismatchKind.QUANTITY_MISMATCH
        assert m.broker_value == 10
        assert m.local_value == 8

    def test_price_mismatch_detected_beyond_tolerance(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        # avg price differs by 5 % — well beyond 0.1 % tolerance
        broker = [_pos("RELIANCE", 10, avg_price=2500.0)]
        local = [_pos("RELIANCE", 10, avg_price=2625.0)]
        result = engine.reconcile_positions(broker, local)
        assert result.has_mismatches
        assert any(m.kind == MismatchKind.PRICE_MISMATCH for m in result.mismatches)

    def test_price_within_tolerance_is_clean(self):
        engine = self._engine()
        # 0.05 % diff — within 0.1 % tolerance
        broker = [_pos("RELIANCE", 10, avg_price=2500.0)]
        local = [_pos("RELIANCE", 10, avg_price=2500.0 * 1.0005)]
        result = engine.reconcile_positions(broker, local)
        assert result.clean

    def test_empty_both_sides_is_clean(self):
        engine = self._engine()
        result = engine.reconcile_positions([], [])
        assert result.clean
        assert result.checked_count == 0


# ======================================================================
# reconcile_orders
# ======================================================================


class TestReconcileOrders:
    def _engine(self):
        from packages.engine.src.reconciliation import ReconciliationEngine
        return ReconciliationEngine()

    def test_identical_orders_are_clean(self):
        engine = self._engine()
        orders = [_order("ORD001", "OPEN", 10), _order("ORD002", "COMPLETE", 5)]
        result = engine.reconcile_orders(orders, orders)
        assert result.clean
        assert result.checked_count == 2

    def test_missing_in_local_detected(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_order("ORD001", "OPEN"), _order("ORD002", "OPEN")]
        local = [_order("ORD001", "OPEN")]
        result = engine.reconcile_orders(broker, local)
        assert result.has_mismatches
        assert any(m.kind == MismatchKind.MISSING_IN_LOCAL for m in result.mismatches)

    def test_missing_open_order_in_broker_flagged(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_order("ORD001", "OPEN")]
        local = [_order("ORD001", "OPEN"), _order("ORD002", "OPEN")]  # ORD002 not on broker
        result = engine.reconcile_orders(broker, local)
        assert result.has_mismatches
        assert any(m.kind == MismatchKind.MISSING_IN_BROKER for m in result.mismatches)

    def test_completed_order_missing_from_broker_not_flagged(self):
        """Completed/cancelled orders absent from broker are expected after archival."""
        engine = self._engine()
        broker = [_order("ORD001", "OPEN")]
        local = [
            _order("ORD001", "OPEN"),
            _order("ORD002", "COMPLETE"),   # completed — should not flag
            _order("ORD003", "CANCELLED"),  # cancelled — should not flag
        ]
        result = engine.reconcile_orders(broker, local)
        assert result.clean

    def test_status_mismatch_detected(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_order("ORD001", "COMPLETE")]
        local = [_order("ORD001", "OPEN")]  # local still shows OPEN
        result = engine.reconcile_orders(broker, local)
        assert result.has_mismatches
        m = next(x for x in result.mismatches if x.kind == MismatchKind.STATUS_MISMATCH)
        assert m.broker_value == "COMPLETE"
        assert m.local_value == "OPEN"

    def test_quantity_mismatch_in_orders_detected(self):
        from packages.engine.src.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_order("ORD001", "OPEN", qty=50)]
        local = [_order("ORD001", "OPEN", qty=25)]
        result = engine.reconcile_orders(broker, local)
        assert result.has_mismatches
        assert any(m.kind == MismatchKind.QUANTITY_MISMATCH for m in result.mismatches)

    def test_empty_both_sides_is_clean(self):
        engine = self._engine()
        result = engine.reconcile_orders([], [])
        assert result.clean

    def test_mismatch_str_representation(self):
        from packages.engine.src.reconciliation import Mismatch, MismatchKind
        m = Mismatch(
            kind=MismatchKind.QUANTITY_MISMATCH,
            symbol="NIFTY",
            broker_value=10,
            local_value=8,
        )
        s = str(m)
        assert "quantity_mismatch" in s
        assert "NIFTY" in s
        assert "10" in s
        assert "8" in s
