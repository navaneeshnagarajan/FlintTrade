"""Unit tests for the algo-order tagging guard."""

from __future__ import annotations

import pytest

from flinttrade_engine.algo_tag_guard import (
    AlgoTagConfig,
    AlgoTagGuard,
    AlgoTagLimitError,
)

pytestmark = pytest.mark.unit


def _guard(now_holder, **configs):
    return AlgoTagGuard(configs, clock=lambda: now_holder[0])


def test_returns_algo_id_and_allows_up_to_cap():
    now = [100.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="ALGO123", max_orders_per_sec=2))
    assert guard.tag_order("dhan", "NSE") == "ALGO123"
    assert guard.tag_order("dhan", "NSE") == "ALGO123"
    assert guard.usage("dhan", "NSE") == 2


def test_raises_when_cap_exceeded():
    now = [0.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="A", max_orders_per_sec=2))
    guard.tag_order("dhan", "NSE")
    guard.tag_order("dhan", "NSE")
    with pytest.raises(AlgoTagLimitError, match="rate limit"):
        guard.tag_order("dhan", "NSE")


def test_window_resets_after_one_second():
    now = [0.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="A", max_orders_per_sec=1))
    guard.tag_order("dhan", "NSE")
    with pytest.raises(AlgoTagLimitError):
        guard.tag_order("dhan", "NSE")
    now[0] = 1.1  # advance past the 1s window
    assert guard.tag_order("dhan", "NSE") == "A"


def test_exchanges_are_counted_separately():
    now = [0.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="A", max_orders_per_sec=1))
    guard.tag_order("dhan", "NSE")
    # MCX has its own counter, so it is still allowed.
    assert guard.tag_order("dhan", "MCX") == "A"


def test_unknown_broker_is_refused():
    now = [0.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="A", max_orders_per_sec=5))
    with pytest.raises(AlgoTagLimitError, match="No algo-tag configuration"):
        guard.tag_order("upstox", "NSE")


def test_algo_id_for_lookup():
    now = [0.0]
    guard = _guard(now, dhan=AlgoTagConfig(algo_id="ZZ9", max_orders_per_sec=1))
    assert guard.algo_id_for("dhan") == "ZZ9"
    assert guard.algo_id_for("kotak") is None
