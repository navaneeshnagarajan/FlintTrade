"""Tests for CLOSED_MANUAL detection and BackgroundReconciler.

All inputs are synthetic dicts.  No broker calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pos(
    symbol: str,
    qty: int,
    avg_price: float = 100.0,
    exchange: str = "NSE",
    product: str = "MIS",
) -> dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": str(qty),
        "average_price": str(avg_price),
    }


# ===========================================================================
# CLOSED_MANUAL detection
# ===========================================================================


class TestClosedManualDetection:
    """CLOSED_MANUAL is raised when a non-zero local position is absent from broker."""

    def _engine(self):
        from flinttrade_engine.reconciliation import ReconciliationEngine
        return ReconciliationEngine(price_tolerance_pct=0.1)

    def test_closed_manual_detected_when_position_missing_from_broker(self):
        from flinttrade_engine.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        # INFY is open locally but missing from broker positionbook
        local = [_pos("RELIANCE", 10), _pos("INFY", 5)]
        result = engine.reconcile_positions(broker, local)
        kinds = [m.kind for m in result.mismatches]
        assert MismatchKind.CLOSED_MANUAL in kinds

    def test_closed_manual_mismatch_has_correct_symbol(self):
        from flinttrade_engine.reconciliation import MismatchKind
        engine = self._engine()
        broker = []
        local = [_pos("TCS", 15)]
        result = engine.reconcile_positions(broker, local)
        cm = [m for m in result.mismatches if m.kind == MismatchKind.CLOSED_MANUAL]
        assert len(cm) == 1
        assert cm[0].symbol == "TCS"
        assert cm[0].local_value == 15

    def test_closed_manual_not_raised_for_zero_qty_local(self):
        """Stale zero-qty positions (already closed in our records) must not flag."""
        from flinttrade_engine.reconciliation import MismatchKind
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 10), _pos("WIPRO", 0)]
        result = engine.reconcile_positions(broker, local)
        kinds = [m.kind for m in result.mismatches]
        assert MismatchKind.CLOSED_MANUAL not in kinds

    def test_multiple_closed_manual_events(self):
        from flinttrade_engine.reconciliation import MismatchKind
        engine = self._engine()
        broker = []
        local = [_pos("TCS", 10), _pos("INFY", 5), _pos("WIPRO", 0)]
        result = engine.reconcile_positions(broker, local)
        cm = [m for m in result.mismatches if m.kind == MismatchKind.CLOSED_MANUAL]
        symbols = {m.symbol for m in cm}
        assert "TCS" in symbols
        assert "INFY" in symbols
        # WIPRO has qty=0 — should NOT appear
        assert "WIPRO" not in symbols

    def test_closed_manual_detail_contains_key(self):
        from flinttrade_engine.reconciliation import MismatchKind
        engine = self._engine()
        broker = []
        local = [_pos("HDFC", 20, exchange="NSE", product="CNC")]
        result = engine.reconcile_positions(broker, local)
        cm = next(m for m in result.mismatches if m.kind == MismatchKind.CLOSED_MANUAL)
        # detail should mention the composite key or relevant info
        assert cm.detail != ""

    def test_normal_missing_in_broker_not_replaced_by_closed_manual(self):
        """The old MISSING_IN_BROKER logic for zero-qty should still be clean."""
        engine = self._engine()
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 10), _pos("ICICIBANK", 0)]
        result = engine.reconcile_positions(broker, local)
        assert result.clean


# ===========================================================================
# BackgroundReconciler
# ===========================================================================


class TestBackgroundReconciler:
    """BackgroundReconciler async behaviour."""

    def _make_reconciler(
        self,
        broker_positions=None,
        local_positions=None,
        on_closed_manual=None,
        interval_seconds=60,
    ):
        from flinttrade_engine.reconciliation import BackgroundReconciler

        broker_positions = broker_positions or []
        local_positions = local_positions or []

        async def get_broker():
            return broker_positions

        def get_local():
            return local_positions

        return BackgroundReconciler(
            get_broker_positions=get_broker,
            get_local_positions=get_local,
            on_closed_manual=on_closed_manual,
            interval_seconds=interval_seconds,
        )

    def test_start_and_stop(self):
        reconciler = self._make_reconciler()

        async def _run():
            await reconciler.start()
            assert reconciler.is_running
            await reconciler.stop()
            assert not reconciler.is_running

        asyncio.run(_run())

    def test_start_is_idempotent(self):
        reconciler = self._make_reconciler()

        async def _run():
            await reconciler.start()
            task1 = reconciler._task
            await reconciler.start()  # second call — should no-op
            assert reconciler._task is task1
            await reconciler.stop()

        asyncio.run(_run())

    def test_run_once_returns_clean_result_when_positions_match(self):
        broker = [_pos("RELIANCE", 10)]
        local = [_pos("RELIANCE", 10)]
        reconciler = self._make_reconciler(broker, local)

        async def _run():
            result = await reconciler._run_once()
            return result

        result = asyncio.run(_run())
        assert result.clean

    def test_run_once_detects_closed_manual(self):
        from flinttrade_engine.reconciliation import MismatchKind
        broker = []
        local = [_pos("NIFTY25APRFUT", 75)]
        reconciler = self._make_reconciler(broker, local)

        async def _run():
            return await reconciler._run_once()

        result = asyncio.run(_run())
        assert any(m.kind == MismatchKind.CLOSED_MANUAL for m in result.mismatches)

    def test_on_closed_manual_callback_called(self):
        callback = AsyncMock()
        broker = []
        local = [_pos("BANKNIFTY25APRFUT", 25)]
        reconciler = self._make_reconciler(
            broker, local, on_closed_manual=callback
        )

        asyncio.run(reconciler._run_once())
        callback.assert_awaited_once()
        args = callback.call_args.args
        assert args[0] == "BANKNIFTY25APRFUT"
        assert args[1] == 25

    def test_on_closed_manual_callback_failure_does_not_propagate(self):
        """Callback raising an exception must not crash the reconciler."""
        async def bad_callback(symbol, qty):
            raise RuntimeError("database down")

        broker = []
        local = [_pos("TCS", 10)]
        reconciler = self._make_reconciler(
            broker, local, on_closed_manual=bad_callback
        )

        # Should complete without raising
        asyncio.run(reconciler._run_once())

    def test_run_once_returns_empty_result_on_broker_fetch_failure(self):
        from flinttrade_engine.reconciliation import BackgroundReconciler

        async def failing_broker():
            raise ConnectionError("broker unreachable")

        reconciler = BackgroundReconciler(
            get_broker_positions=failing_broker,
            get_local_positions=lambda: [_pos("INFY", 10)],
        )
        result = asyncio.run(reconciler._run_once())
        # Returns an empty result — does not raise
        assert result.checked_count == 0

    def test_multiple_closed_manual_callbacks_fired(self):
        calls: list[tuple[str, int]] = []

        async def capture(symbol, qty):
            calls.append((symbol, qty))

        broker = []
        local = [_pos("TCS", 5), _pos("INFY", 10), _pos("WIPRO", 0)]
        reconciler = self._make_reconciler(broker, local, on_closed_manual=capture)
        asyncio.run(reconciler._run_once())
        # WIPRO has qty=0 — should NOT trigger callback
        assert len(calls) == 2
        symbols = {c[0] for c in calls}
        assert "TCS" in symbols
        assert "INFY" in symbols
        assert "WIPRO" not in symbols


def test_duplicate_snapshot_is_refused():
    import pytest
    from flinttrade_engine.reconciliation import ReconciliationEngine

    with pytest.raises(ValueError, match="duplicate"):
        ReconciliationEngine().reconcile_positions([_pos("TEST", 1), _pos("TEST", 2)], [])


def test_nonfinite_snapshot_is_refused():
    import pytest
    from flinttrade_engine.reconciliation import ReconciliationEngine

    with pytest.raises(ValueError, match="non-finite"):
        ReconciliationEngine().reconcile_positions([_pos("TEST", 1, float("nan"))], [])


def test_read_failure_never_reports_clean_or_external_close():
    from flinttrade_engine.reconciliation import BackgroundReconciler

    async def unavailable():
        raise ConnectionError("unavailable")

    callback = AsyncMock()
    result = asyncio.run(BackgroundReconciler(unavailable, lambda: [_pos("TEST", 1)], callback)._run_once())
    assert not result.clean
    assert result.error
    assert result.checked_count == 0
    callback.assert_not_called()


@pytest.mark.parametrize("quantity", [2.5, "2.5", True, False, "nan", "inf"])
@pytest.mark.parametrize("positions", [True, False])
def test_nonintegral_or_boolean_quantity_cannot_compare_clean(quantity, positions):
    from flinttrade_engine.reconciliation import ReconciliationEngine

    broker = {"symbol": "TEST", "order_id": "synthetic", "quantity": quantity}
    local = broker | {"quantity": 2}
    method = ReconciliationEngine().reconcile_positions if positions else ReconciliationEngine().reconcile_orders
    with pytest.raises(ValueError, match="quantity"):
        method([broker], [local])


@pytest.mark.parametrize("positions,row", [
    (True, {"symbol": " ", "quantity": 1}),
    (False, {"symbol": "TEST", "quantity": 1}),
    (False, {"symbol": "TEST", "order_id": " ", "quantity": 1}),
])
def test_missing_snapshot_identity_is_refused(positions, row):
    from flinttrade_engine.reconciliation import ReconciliationEngine

    method = ReconciliationEngine().reconcile_positions if positions else ReconciliationEngine().reconcile_orders
    with pytest.raises(ValueError, match="symbol|identity"):
        method([row], [])


@pytest.mark.parametrize("invalid", [
    {"symbol": "TEST", "quantity": 1.9},
    {"symbol": "TEST", "quantity": True},
    {"quantity": 1},
])
@pytest.mark.parametrize("invalid_side", ["broker", "local"])
def test_snapshot_validation_failure_never_emits_external_close(invalid, invalid_side):
    from flinttrade_engine.reconciliation import BackgroundReconciler

    async def broker():
        return [invalid] if invalid_side == "broker" else []

    local = [invalid] if invalid_side == "local" else [_pos("TEST", 1)]
    callback = AsyncMock()
    result = asyncio.run(BackgroundReconciler(broker, lambda: local, callback)._run_once())
    assert not result.clean
    assert result.error
    assert result.checked_count == 0
    callback.assert_not_called()


def test_integral_quantity_projection_keeps_exact_units_and_sparse_positions():
    from flinttrade_engine.reconciliation import ReconciliationEngine

    value = 9_007_199_254_740_993
    broker = {"symbol": "TEST", "quantity": str(value)}
    local = {"symbol": "TEST", "quantity": str(value + 1)}
    result = ReconciliationEngine().reconcile_positions([broker], [local])
    assert result.mismatch_count == 1
    assert result.mismatches[0].broker_value == value
    assert result.mismatches[0].local_value == value + 1
