"""Per-broker API rate limiting (DATA & INFRA: customizable rate limits + latency).

Each broker publishes its API limits in :class:`Capabilities`
(``rate_limit_orders_per_sec`` / ``rate_limit_data_per_sec`` …). This module turns
that static metadata — plus any operator override — into an *enforced* per-broker
throttle so FlintTrade never trips a broker's ban for exceeding its rate, while
keeping latency tight (it only delays a call when genuinely over the limit).

:class:`BrokerRateLimiter` is a small async token bucket keyed by
``(broker_id, kind)`` where ``kind`` is ``"order"`` or ``"data"``. The
``BrokerRouter`` calls ``await acquire(adapter_id, kind)`` before each dispatch —
a purely throttling step that sits *below* the gate, so it can only slow a call,
never skip the safety gate. The clock and sleep are injectable, so the buckets
are tested deterministically without real time.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .capabilities import Capabilities


class _Bucket:
    """A single token bucket: ``rate`` tokens/sec, ``rate`` burst capacity."""

    __slots__ = ("rate", "tokens", "updated")

    def __init__(self, rate: float, clock: Callable[[], float]) -> None:
        self.rate = rate
        self.tokens = float(rate)  # start full (allow an initial burst up to rate)
        self.updated = clock()

    def take(self, now: float) -> float:
        """Consume one token; return seconds to wait (0 if a token was available)."""
        # Refill for elapsed time (capped at the burst capacity = rate).
        self.tokens = min(self.rate, self.tokens + (now - self.updated) * self.rate)
        self.updated = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / self.rate


class BrokerRateLimiter:
    """Enforces per-broker order/data API rate limits via async token buckets.

    Args:
        limits: ``{broker_id: {"order": per_sec, "data": per_sec}}``. A broker or
            kind with no positive limit is treated as unlimited (no throttle).
        clock: ``() -> float`` monotonic seconds (injected in tests).
        sleep: ``(seconds) -> Awaitable`` (injected in tests).
    """

    def __init__(
        self,
        limits: dict[str, dict[str, float]],
        *,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._limits = limits
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @classmethod
    def from_capabilities(
        cls,
        capabilities: dict[str, Capabilities],
        overrides: dict[str, dict[str, float]] | None = None,
        **kwargs: Any,
    ) -> BrokerRateLimiter:
        """Build limits from each broker's capability metadata, applying overrides.

        ``overrides[broker_id][kind]`` (kind = ``order``/``data``) wins over the
        capability default, so the operator can customise a broker's rate.
        """
        overrides = overrides or {}
        limits: dict[str, dict[str, float]] = {}
        for broker_id, cap in capabilities.items():
            ov_raw = overrides.get(broker_id, {})
            ov = ov_raw if isinstance(ov_raw, dict) else {}
            order = ov.get("order", cap.rate_limit_orders_per_sec or 0)
            data = ov.get("data", cap.rate_limit_data_per_sec or 0)
            limits[broker_id] = {"order": float(order), "data": float(data)}
        # Allow overrides for brokers not in the capability map too. Skip any
        # non-dict values so a documentation key (e.g. a "_comment" string — the
        # workspace.json convention) is tolerated rather than crashing the build.
        for broker_id, ov in overrides.items():
            if not isinstance(ov, dict):
                continue
            limits.setdefault(broker_id, {"order": float(ov.get("order", 0)), "data": float(ov.get("data", 0))})
        return cls(limits, **kwargs)

    def _rate(self, broker_id: str, kind: str) -> float:
        return float(self._limits.get(broker_id, {}).get(kind, 0) or 0)

    async def acquire(self, broker_id: str, kind: str = "order") -> None:
        """Block until a token is available for ``(broker_id, kind)``.

        Returns immediately when no positive limit is configured (unlimited).
        """
        rate = self._rate(broker_id, kind)
        if rate <= 0:
            return
        key = (broker_id, kind)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:  # serialise token accounting per (broker, kind)
            bucket = self._buckets.get(key)
            if bucket is None or bucket.rate != rate:
                bucket = _Bucket(rate, self._clock)
                self._buckets[key] = bucket
            wait = bucket.take(self._clock())
        if wait > 0:
            await self._sleep(wait)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return the current effective per-broker limits (a deep copy).

        ``{broker_id: {"order": per_sec, "data": per_sec}}``. Read by the
        rate-limits settings API so the UI shows the live values.
        """
        return {broker_id: dict(kinds) for broker_id, kinds in self._limits.items()}

    def apply_override(
        self,
        broker_id: str,
        *,
        order: float | None = None,
        data: float | None = None,
    ) -> None:
        """Update a broker's order/data limit at runtime (0 = unlimited).

        Only the supplied kinds change; the rest keep their current value. The
        next :meth:`acquire` rebuilds the affected bucket automatically because
        it recreates a bucket whenever the configured rate differs (see the
        ``bucket.rate != rate`` check), so no bucket bookkeeping is needed here.
        """
        current = dict(self._limits.get(broker_id, {}))
        if order is not None:
            current["order"] = float(order)
        if data is not None:
            current["data"] = float(data)
        self._limits[broker_id] = current
