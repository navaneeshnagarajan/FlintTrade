"""Tests for packages/core/src/event_bus.py.

Covers: subscribe, publish, unsubscribe, history, thread safety,
        subscriber_count, clear_history, exception isolation, glob patterns.
"""

from __future__ import annotations

import threading

import pytest

from packages.core.src.event_bus import EventBus, bus


@pytest.fixture
def eb() -> EventBus:
    """Fresh isolated EventBus for each test."""
    return EventBus(history_size=200)


# ---------------------------------------------------------------------------
# subscribe / publish
# ---------------------------------------------------------------------------


def test_subscribe_returns_positive_int(eb: EventBus) -> None:
    """subscribe() returns a positive integer subscription ID."""
    sid = eb.subscribe("order.placed", lambda p: None)
    assert isinstance(sid, int)
    assert sid > 0


def test_publish_calls_handler(eb: EventBus) -> None:
    """A subscribed handler is called when its event is published."""
    received: list[dict] = []
    eb.subscribe("order.placed", received.append)
    eb.publish("order.placed", {"symbol": "NIFTY"})
    assert len(received) == 1
    assert received[0]["symbol"] == "NIFTY"


def test_publish_multiple_handlers(eb: EventBus) -> None:
    """Multiple handlers subscribed to the same event are all called."""
    counts: list[int] = []
    eb.subscribe("order.placed", lambda p: counts.append(1))
    eb.subscribe("order.placed", lambda p: counts.append(2))
    eb.publish("order.placed", {})
    assert len(counts) == 2


def test_publish_does_not_call_unrelated_handlers(eb: EventBus) -> None:
    """Handler for event A is NOT called when event B is published."""
    received: list[dict] = []
    eb.subscribe("order.placed", received.append)
    eb.publish("order.cancelled", {"symbol": "NIFTY"})
    assert received == []


def test_publish_empty_payload(eb: EventBus) -> None:
    """publish() accepts an empty dict as payload without raising."""
    eb.subscribe("market.open", lambda p: None)
    eb.publish("market.open", {})  # No exception.


def test_publish_unknown_event_no_error(eb: EventBus) -> None:
    """Publishing to an event with no subscribers does not raise."""
    eb.publish("totally.unknown.event", {"x": 1})  # Should be silent.


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


def test_unsubscribe_stops_delivery(eb: EventBus) -> None:
    """After unsubscribe, the handler is no longer called on publish."""
    received: list[dict] = []
    sid = eb.subscribe("order.placed", received.append)
    eb.unsubscribe(sid)
    eb.publish("order.placed", {"symbol": "NIFTY"})
    assert received == []


def test_unsubscribe_returns_true_on_success(eb: EventBus) -> None:
    """unsubscribe() returns True when the subscription exists."""
    sid = eb.subscribe("order.placed", lambda p: None)
    assert eb.unsubscribe(sid) is True


def test_unsubscribe_returns_false_for_unknown_id(eb: EventBus) -> None:
    """unsubscribe() returns False when the ID was never registered."""
    assert eb.unsubscribe(99999) is False


def test_unsubscribe_selective(eb: EventBus) -> None:
    """Unsubscribing one handler does not affect other handlers."""
    calls_a: list[int] = []
    calls_b: list[int] = []

    sid_a = eb.subscribe("order.placed", lambda p: calls_a.append(1))
    eb.subscribe("order.placed", lambda p: calls_b.append(1))

    eb.unsubscribe(sid_a)
    eb.publish("order.placed", {})

    assert calls_a == []
    assert calls_b == [1]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


def test_history_records_published_events(eb: EventBus) -> None:
    """history() returns events that were published."""
    eb.publish("order.placed", {"qty": 10})
    eb.publish("order.cancelled", {"qty": 5})
    h = eb.history()
    assert len(h) == 2
    events = {e["event"] for e in h}
    assert "order.placed" in events
    assert "order.cancelled" in events


def test_history_glob_pattern(eb: EventBus) -> None:
    """history(event_pattern='order.*') filters to matching events."""
    eb.publish("order.placed", {})
    eb.publish("order.filled", {})
    eb.publish("market.open", {})

    order_hist = eb.history("order.*")
    assert len(order_hist) == 2
    assert all(e["event"].startswith("order.") for e in order_hist)


def test_history_limit(eb: EventBus) -> None:
    """history(limit=N) returns at most N entries."""
    for i in range(10):
        eb.publish("tick.received", {"i": i})
    h = eb.history("*", limit=5)
    assert len(h) == 5


def test_history_clear(eb: EventBus) -> None:
    """clear_history() discards all ring buffer entries."""
    eb.publish("order.placed", {})
    assert len(eb.history()) == 1
    eb.clear_history()
    assert len(eb.history()) == 0


def test_history_ring_buffer_bounded(eb: EventBus) -> None:
    """Ring buffer drops oldest entries once history_size is exceeded."""
    small_bus = EventBus(history_size=5)
    for i in range(10):
        small_bus.publish("tick.received", {"i": i})
    h = small_bus.history()
    assert len(h) == 5
    # Most recent 5 should have i in range [5, 9]
    payloads = [e["payload"]["i"] for e in h]
    assert min(payloads) >= 5


# ---------------------------------------------------------------------------
# Exception isolation
# ---------------------------------------------------------------------------


def test_exception_in_handler_does_not_propagate(eb: EventBus) -> None:
    """A crashing handler must not prevent subsequent handlers from running."""
    results: list[str] = []

    def bad_handler(p: dict) -> None:
        raise RuntimeError("I always crash")

    def good_handler(p: dict) -> None:
        results.append("ok")

    eb.subscribe("order.placed", bad_handler)
    eb.subscribe("order.placed", good_handler)

    eb.publish("order.placed", {})  # Should not raise.
    assert results == ["ok"]


# ---------------------------------------------------------------------------
# subscriber_count
# ---------------------------------------------------------------------------


def test_subscriber_count_all(eb: EventBus) -> None:
    """subscriber_count() returns total subscriptions across all events."""
    eb.subscribe("order.placed", lambda p: None)
    eb.subscribe("order.placed", lambda p: None)
    eb.subscribe("market.open", lambda p: None)
    assert eb.subscriber_count() == 3


def test_subscriber_count_per_event(eb: EventBus) -> None:
    """subscriber_count(event) returns subscriptions for that event only."""
    eb.subscribe("order.placed", lambda p: None)
    eb.subscribe("order.placed", lambda p: None)
    eb.subscribe("market.open", lambda p: None)
    assert eb.subscriber_count("order.placed") == 2
    assert eb.subscriber_count("market.open") == 1
    assert eb.subscriber_count("unknown.event") == 0


def test_subscriber_count_decrements_on_unsubscribe(eb: EventBus) -> None:
    """Unsubscribing reduces the subscriber count."""
    sid = eb.subscribe("order.placed", lambda p: None)
    assert eb.subscriber_count("order.placed") == 1
    eb.unsubscribe(sid)
    assert eb.subscriber_count("order.placed") == 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_concurrent_publish_subscribe(eb: EventBus) -> None:
    """Concurrent subscribes and publishes complete without data loss or errors."""
    results: list[dict] = []
    lock = threading.Lock()

    def handler(p: dict) -> None:
        with lock:
            results.append(p)

    # Register one handler before spawning threads
    eb.subscribe("tick.received", handler)

    publish_count = 100
    threads = []
    for i in range(publish_count):
        t = threading.Thread(
            target=eb.publish,
            args=("tick.received", {"i": i}),
        )
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert len(results) == publish_count


def test_concurrent_subscribe_unsubscribe(eb: EventBus) -> None:
    """Simultaneous subscribe/unsubscribe from multiple threads is safe."""
    errors: list[Exception] = []

    def worker() -> None:
        try:
            sid = eb.subscribe("order.placed", lambda p: None)
            eb.publish("order.placed", {})
            eb.unsubscribe(sid)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


def test_module_singleton_exists() -> None:
    """The module-level ``bus`` singleton is an EventBus instance."""
    assert isinstance(bus, EventBus)


def test_module_singleton_is_shared() -> None:
    """Importing ``bus`` twice yields the same object."""
    from packages.core.src.event_bus import bus as bus2

    assert bus is bus2
