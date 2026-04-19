"""Thread-safe in-process pub/sub event bus for FlintTrade internal events.

Provides a lightweight publish/subscribe mechanism for decoupling order
side-effects, safety triggers, strategy lifecycle events, and market
signals from the code that produces them.

Subscriptions are identified by an integer ID so they can be cancelled
cleanly.  Handlers execute synchronously on the caller's thread by
default but are isolated — an exception in one handler never affects
other handlers or the publisher.

A bounded ring buffer retains the most recent *history_size* events so
that late subscribers or debugging tools can inspect recent activity.

All documented event names are defined in :data:`EVENT_NAMES`.

Singleton pattern: import ``bus`` from this module for the shared instance.

Example::

    from packages.core.src.event_bus import bus

    sub_id = bus.subscribe("order.placed", lambda p: print(p))
    bus.publish("order.placed", {"symbol": "NIFTY", "qty": 50})
    bus.unsubscribe(sub_id)
    history = bus.history("order.*")
"""

from __future__ import annotations

import fnmatch
import logging
import threading
from collections import deque
from typing import Callable

logger = logging.getLogger("flinttrade.core.event_bus")

# ---------------------------------------------------------------------------
# Documented event names
# ---------------------------------------------------------------------------

EVENT_NAMES: frozenset[str] = frozenset(
    {
        # Order lifecycle
        "order.placed",
        "order.modified",
        "order.cancelled",
        "order.filled",
        "order.rejected",
        # Position lifecycle
        "position.opened",
        "position.closed",
        "position.modified",
        # Market state
        "market.open",
        "market.close",
        "market.holiday",
        # Tick stream
        "tick.received",
        "tick.stale",
        # Safety system
        "safety.triggered",
        "safety.reset",
        # Strategy lifecycle
        "strategy.started",
        "strategy.stopped",
        "strategy.error",
    }
)


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe in-process publish/subscribe event bus.

    Handlers are called synchronously in the order they were registered.
    Each handler is wrapped in exception isolation — a crash in one handler
    is logged but does not prevent other handlers from running.

    A bounded in-memory ring buffer retains the last *history_size*
    published events so they can be queried via :meth:`history`.

    Args:
        history_size: Maximum number of events to retain in the ring
            buffer (default 500).

    Example::

        bus = EventBus()
        sid = bus.subscribe("order.placed", lambda p: print(p["symbol"]))
        bus.publish("order.placed", {"symbol": "NIFTY", "qty": 50})
        assert len(bus.history("order.*")) == 1
        bus.unsubscribe(sid)
    """

    def __init__(self, history_size: int = 500) -> None:
        # _handlers: event_name -> {subscription_id: callable}
        self._handlers: dict[str, dict[int, Callable[[dict], None]]] = {}
        self._lock = threading.Lock()
        self._next_id: int = 1

        # Ring buffer for event history (entry_id, event, payload, timestamp)
        self._history: deque[dict] = deque(maxlen=max(1, history_size))

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event: str,
        handler: Callable[[dict], None],
    ) -> int:
        """Register a handler for *event*.

        Args:
            event: Event name (e.g. ``"order.placed"``).  Glob patterns
                are NOT supported at subscribe time — each subscription
                is for a single exact event name.
            handler: Callable that receives the event payload dict when
                the event is published.

        Returns:
            Subscription ID (positive integer).  Pass this to
            :meth:`unsubscribe` to cancel.
        """
        with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            if event not in self._handlers:
                self._handlers[event] = {}
            self._handlers[event][sub_id] = handler

        logger.debug(
            "EventBus: subscribed sub_id=%d to '%s' handler=%s",
            sub_id,
            event,
            getattr(handler, "__name__", repr(handler)),
        )
        return sub_id

    def unsubscribe(self, subscription_id: int) -> bool:
        """Cancel a subscription by its ID.

        Args:
            subscription_id: The ID returned by :meth:`subscribe`.

        Returns:
            True if the subscription was found and removed, False if the
            ID was not registered (already cancelled or never created).
        """
        with self._lock:
            for event_name, subs in self._handlers.items():
                if subscription_id in subs:
                    del subs[subscription_id]
                    logger.debug(
                        "EventBus: unsubscribed sub_id=%d from '%s'",
                        subscription_id,
                        event_name,
                    )
                    return True
        return False

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def publish(self, event: str, payload: dict) -> None:
        """Publish *event* with *payload* to all registered handlers.

        Execution is synchronous.  Each handler is called in registration
        order within a try/except so that a misbehaving handler cannot
        disrupt the rest.  The event is always appended to the ring
        buffer regardless of handler results.

        Args:
            event: Event name (e.g. ``"order.placed"``).
            payload: Arbitrary dict passed verbatim to each handler.
        """
        with self._lock:
            handlers = dict(self._handlers.get(event, {}))

        # Append to history before invoking handlers so that a handler
        # querying history() sees the current event.
        import time as _time

        self._history.append(
            {
                "event": event,
                "payload": payload,
                "timestamp": _time.time(),
            }
        )

        for sub_id, handler in handlers.items():
            try:
                handler(payload)
            except Exception:
                logger.exception(
                    "EventBus: handler sub_id=%d raised on event '%s'",
                    sub_id,
                    event,
                )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def history(
        self,
        event_pattern: str = "*",
        limit: int = 100,
    ) -> list[dict]:
        """Return recent events from the ring buffer.

        Args:
            event_pattern: Shell-style glob pattern applied to event
                names (e.g. ``"order.*"`` matches all order events,
                ``"*"`` returns everything).
            limit: Maximum number of entries to return (default 100).

        Returns:
            List of dicts with keys ``event``, ``payload``, ``timestamp``
            (Unix float).  Most recent entries are last.
        """
        limit = max(1, min(int(limit), len(self._history) or 1))

        # Ring buffer access is lock-free for reads (deque is thread-safe
        # for append/iteration in CPython).
        all_events = list(self._history)

        if event_pattern != "*":
            all_events = [
                e for e in all_events if fnmatch.fnmatch(e["event"], event_pattern)
            ]

        return all_events[-limit:]

    def subscriber_count(self, event: str | None = None) -> int:
        """Return the number of active subscriptions.

        Args:
            event: When provided, count subscriptions for this event only.

        Returns:
            Integer subscription count.
        """
        with self._lock:
            if event is not None:
                return len(self._handlers.get(event, {}))
            return sum(len(subs) for subs in self._handlers.values())

    def clear_history(self) -> None:
        """Discard all entries in the ring buffer (useful in tests)."""
        self._history.clear()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Shared EventBus instance.  Import this for normal use.
bus: EventBus = EventBus()
