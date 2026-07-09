"""Tests for packages/services/engine/src/split_orders.py.

No live OpenAlgo connection required — all routing is mocked.
"""

from __future__ import annotations

import asyncio

import pytest

from flinttrade_engine.split_orders import (
    MAX_CHUNKS,
    ChunkResult,
    SplitOrderExecutor,
    SplitResult,
    SplitValidationError,
    _validate_split_params,
)
from flinttrade_engine.bracket_order import BracketOrderError, BracketPrincipal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_PRINCIPAL = BracketPrincipal(
    actor_id="tester", jti="jti-1", adapter_id="openalgo", account_id="default"
)


def _place_leg_from(outcomes: list):  # type: ignore[no-untyped-def]
    """Build a fake gated ``place_leg(order, principal)``.

    Each outcome is an order-id ``str`` (success) or a ``BracketOrderError`` to
    raise (safety block / gate refusal / dispatch fault).
    """
    it = iter(outcomes)

    def place_leg(order, principal):  # type: ignore[no-untyped-def]
        outcome = next(it)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return place_leg


def _make_executor(outcomes: list | None = None) -> SplitOrderExecutor:
    return SplitOrderExecutor(place_leg=_place_leg_from(outcomes or ["C001"]))


def _exec_split(
    outcomes: list,
    total_quantity: int = 300,
    chunk_size: int = 75,
    delay_seconds: float = 0.0,
    action: str = "BUY",
    order_type: str = "MARKET",
    price: float = 0.0,
    trigger_price: float = 0.0,
) -> SplitResult:
    executor = _make_executor(outcomes)
    return _run(
        executor.execute_split(
            symbol="NIFTY25MAYFUT",
            exchange="NFO",
            total_quantity=total_quantity,
            chunk_size=chunk_size,
            action=action,  # type: ignore[arg-type]
            principal=_PRINCIPAL,
            delay_seconds=delay_seconds,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
        )
    )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidateSplitParams:
    """_validate_split_params catches invalid inputs."""

    def test_empty_symbol_raises(self):
        with pytest.raises(SplitValidationError, match="symbol"):
            _validate_split_params("", "NSE", 100, 25, "BUY", "MARKET", 0, 0)

    def test_empty_exchange_raises(self):
        with pytest.raises(SplitValidationError, match="exchange"):
            _validate_split_params("SYM", "", 100, 25, "BUY", "MARKET", 0, 0)

    def test_invalid_action_raises(self):
        with pytest.raises(SplitValidationError, match="action"):
            _validate_split_params("SYM", "NSE", 100, 25, "HOLD", "MARKET", 0, 0)

    def test_zero_total_quantity_raises(self):
        with pytest.raises(SplitValidationError, match="total_quantity"):
            _validate_split_params("SYM", "NSE", 0, 25, "BUY", "MARKET", 0, 0)

    def test_negative_chunk_size_raises(self):
        with pytest.raises(SplitValidationError, match="chunk_size"):
            _validate_split_params("SYM", "NSE", 100, -1, "BUY", "MARKET", 0, 0)

    def test_chunk_size_exceeds_total_raises(self):
        with pytest.raises(SplitValidationError, match="chunk_size"):
            _validate_split_params("SYM", "NSE", 50, 100, "BUY", "MARKET", 0, 0)

    def test_limit_order_without_price_raises(self):
        with pytest.raises(SplitValidationError, match="price"):
            _validate_split_params("SYM", "NSE", 100, 25, "BUY", "LIMIT", 0, 0)

    def test_sl_order_without_trigger_raises(self):
        with pytest.raises(SplitValidationError, match="trigger_price"):
            _validate_split_params("SYM", "NSE", 100, 25, "SELL", "SL", 150.0, 0)

    def test_exceeds_max_chunks_raises(self):
        # 10001 / 100 = 100.01 → 101 chunks > MAX_CHUNKS
        with pytest.raises(SplitValidationError, match="MAX_CHUNKS"):
            _validate_split_params("SYM", "NSE", MAX_CHUNKS * 100 + 1, 100, "BUY", "MARKET", 0, 0)

    def test_valid_params_do_not_raise(self):
        _validate_split_params("NIFTY", "NFO", 300, 75, "BUY", "MARKET", 0, 0)
        _validate_split_params("INFY", "NSE", 100, 25, "SELL", "LIMIT", 1500.0, 0)


# ---------------------------------------------------------------------------
# Chunking arithmetic
# ---------------------------------------------------------------------------


class TestChunkingArithmetic:
    """Verify correct number and sizes of chunks are generated."""

    def test_even_division(self):
        """300 / 75 = 4 full chunks, no remainder."""
        result = _exec_split([f"C{i}" for i in range(4)], total_quantity=300, chunk_size=75)
        assert result.success
        assert len(result.chunks) == 4
        assert all(c.quantity == 75 for c in result.chunks)

    def test_with_remainder(self):
        """310 / 75 = 4 full + 1 partial (10)."""
        result = _exec_split([f"C{i}" for i in range(5)], total_quantity=310, chunk_size=75)
        assert result.success
        assert len(result.chunks) == 5
        full_chunks = result.chunks[:4]
        remainder_chunk = result.chunks[4]
        assert all(c.quantity == 75 for c in full_chunks)
        assert remainder_chunk.quantity == 10

    def test_single_chunk_equal_total(self):
        """chunk_size == total_quantity → exactly 1 chunk."""
        result = _exec_split(["SOLO"], total_quantity=50, chunk_size=50)
        assert result.success
        assert len(result.chunks) == 1
        assert result.chunks[0].quantity == 50

    def test_placed_quantity_sum(self):
        """placed_quantity should equal total_quantity on full success."""
        result = _exec_split([f"Q{i}" for i in range(4)], total_quantity=300, chunk_size=75)
        assert result.placed_quantity == 300


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class TestSplitFailureHandling:
    """Execution stops on first failed chunk; partial results are preserved."""

    def test_first_chunk_failure_returns_error(self):
        result = _exec_split([BracketOrderError("Risk blocked")], total_quantity=300, chunk_size=75)
        assert not result.success
        assert result.placed_count == 0
        assert len(result.chunks) == 1
        assert not result.chunks[0].success

    def test_partial_success_stops_at_failure(self):
        """Two chunks succeed, third fails — only 2 chunks in result."""
        result = _exec_split(
            ["C1", "C2", BracketOrderError("Halt")], total_quantity=225, chunk_size=75
        )
        assert not result.success
        assert result.placed_count == 2
        assert result.failed_count == 1
        assert len(result.chunks) == 3

    def test_dispatch_exception_is_handled(self):
        def explode(order, principal):  # type: ignore[no-untyped-def]
            raise ConnectionError("broker down")

        executor = SplitOrderExecutor(place_leg=explode)
        result = _run(
            executor.execute_split(
                symbol="X", exchange="NSE", total_quantity=100, chunk_size=50,
                action="BUY", principal=_PRINCIPAL,
            )
        )
        assert not result.success
        assert "broker down" in result.error

    def test_validation_failure_returns_error_result(self):
        executor = _make_executor()
        result = _run(
            executor.execute_split(
                symbol="",  # invalid
                exchange="NSE",
                total_quantity=100,
                chunk_size=50,
                action="BUY",
                principal=_PRINCIPAL,
            )
        )
        assert not result.success
        assert "symbol" in result.error.lower()


# ---------------------------------------------------------------------------
# SplitResult properties
# ---------------------------------------------------------------------------


class TestSplitResultProperties:
    def _make_result(self, chunk_data: list[tuple[int, bool]]) -> SplitResult:
        chunks = [
            ChunkResult(
                chunk_index=idx,
                quantity=qty,
                success=ok,
                order_id=f"ID{idx}" if ok else "",
            )
            for idx, (qty, ok) in enumerate(chunk_data, start=1)
        ]
        return SplitResult(
            success=all(ok for _, ok in chunk_data),
            symbol="SYM",
            exchange="NSE",
            action="BUY",
            total_quantity=sum(q for q, _ in chunk_data),
            chunk_size=chunk_data[0][0] if chunk_data else 0,
            chunks=chunks,
        )

    def test_placed_quantity(self):
        r = self._make_result([(75, True), (75, True), (75, False)])
        assert r.placed_quantity == 150

    def test_order_ids(self):
        r = self._make_result([(75, True), (75, False), (75, True)])
        assert r.order_ids == ["ID1", "ID3"]

    def test_placed_count_failed_count(self):
        r = self._make_result([(75, True), (75, False)])
        assert r.placed_count == 1
        assert r.failed_count == 1
