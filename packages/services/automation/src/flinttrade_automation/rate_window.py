"""Shared sliding-window send rate limiter (U16).

One implementation for the per-minute alert throttle that was previously
duplicated verbatim in both WhatsApp transports. Alert-delivery throttling
only — the ORDER rate limits live in the gated execution chain
(``BrokerRouter._throttle``) and are untouched by this class.
"""

from __future__ import annotations

import time


class SlidingWindowRateLimit:
    """Allow at most ``max_events`` in the trailing ``window_seconds``.

    Example::

        limiter = SlidingWindowRateLimit(max_events=30, window_seconds=60.0)
        if limiter.allow():
            send(...)
            limiter.record()
    """

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = int(max_events)
        self.window_seconds = float(window_seconds)
        self._timestamps: list[float] = []

    def allow(self) -> bool:
        """True when another event fits in the current window (prunes old)."""
        cutoff = time.time() - self.window_seconds
        self._timestamps = [ts for ts in self._timestamps if ts > cutoff]
        return len(self._timestamps) < self.max_events

    def record(self) -> None:
        """Record one event at the current time."""
        self._timestamps.append(time.time())
