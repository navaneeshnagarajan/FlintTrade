"""Per-broker API rate limiting (DATA & INFRA: customizable rate limits + latency).

Each broker publishes its API limits in :class:`Capabilities`
(``rate_limit_orders_per_sec`` / ``rate_limit_data_per_sec`` …). This module turns
that static metadata — plus any operator override — into an *enforced* per-broker
throttle so FlintTrade never trips a broker's ban for exceeding its rate, while
keeping latency tight (it only delays a call when genuinely over the limit).

:class:`BrokerRateLimiter` is a small async token bucket keyed by
``(broker_id, kind)`` where ``kind`` is ``"order"``, ``"data"`` or ``"quote"``.
Quote admission also consumes the generic data budget atomically. The
``BrokerRouter`` calls ``await acquire(adapter_id, kind)`` before each dispatch —
a purely throttling step that sits *below* the gate, so it can only slow a call,
never skip the safety gate. The clock and sleep are injectable, so the buckets
are tested deterministically without real time.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any, Awaitable, Callable

from .capabilities import Capabilities


class _Bucket:
    """A token bucket with room for at least one request at fractional rates."""

    __slots__ = ("rate", "tokens", "updated")

    def __init__(self, rate: float, now: float) -> None:
        self.rate = rate
        self.tokens = max(1.0, rate)
        self.updated = now

    def refill(self, now: float) -> None:
        """Refill without spending a token before all applicable budgets agree."""
        self.tokens = min(max(1.0, self.rate), self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    def set_rate(self, rate: float, now: float) -> None:
        """Account for elapsed time at the old rate without minting new credit."""
        self.refill(now)
        self.rate = rate
        self.tokens = min(self.tokens, max(1.0, rate))


class BrokerRateLimiter:
    """Enforces per-broker order/data/quote API rate limits via async token buckets.

    Args:
        limits: ``{broker_id: {"order": per_sec, "data": per_sec, "quote": per_sec}}``. A broker or
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
        self._limits = {
            broker_id: {kind: self._finite_rate(rate) for kind, rate in kinds.items()}
            for broker_id, kinds in limits.items()
        }
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        # threading.Lock, NOT asyncio.Lock: the shared BrokerRouter is awaited
        # from several thread domains with independent event loops (Flask
        # request threads run asyncio.run per request; smart-route/agent job
        # threads run their own loops for minutes). asyncio primitives bind to
        # one loop and are not thread-safe — under cross-loop contention they
        # either under-throttle or raise "bound to a different event loop".
        # The held section is purely synchronous token accounting, so a plain
        # threading.Lock is correct; only the (lock-free) sleep is async.
        self._lock = threading.Lock()

    @classmethod
    def from_capabilities(
        cls,
        capabilities: dict[str, Capabilities],
        overrides: dict[str, dict[str, float]] | None = None,
        **kwargs: Any,
    ) -> BrokerRateLimiter:
        """Build limits from each broker's capability metadata, applying overrides.

        ``overrides[broker_id][kind]`` (kind = ``order``/``data``/``quote``) wins over the
        capability default, so the operator can customise a broker's rate.
        Malformed/non-finite persisted overrides retain the capability default;
        they must not make construction fail and disable the whole limiter.
        """
        overrides = overrides or {}
        limits: dict[str, dict[str, float]] = {}
        for broker_id, cap in capabilities.items():
            ov_raw = overrides.get(broker_id, {})
            ov = ov_raw if isinstance(ov_raw, dict) else {}
            defaults = {"order": cap.rate_limit_orders_per_sec, "data": cap.rate_limit_data_per_sec}
            quote = getattr(cap, "rate_limit_quote_per_sec", None)
            if quote is not None or "quote" in ov:
                defaults["quote"] = quote
            limits[broker_id] = {
                kind: cls._override_rate(ov.get(kind, default), default)
                for kind, default in defaults.items()
            }
        # Allow overrides for brokers not in the capability map too. Skip any
        # non-dict values so a documentation key (e.g. a "_comment" string — the
        # workspace.json convention) is tolerated rather than crashing the build.
        for broker_id, ov in overrides.items():
            if not isinstance(ov, dict):
                continue
            limits.setdefault(broker_id, {
                kind: cls._override_rate(ov.get(kind, 0), 0) for kind in ("order", "data", "quote")
            })
        return cls(limits, **kwargs)

    @classmethod
    def _override_rate(cls, value: object, default: float | None) -> float:
        try:
            return cls._finite_rate(value)
        except (TypeError, ValueError, OverflowError):
            return cls._finite_rate(default or 0)

    def _rate(self, broker_id: str, kind: str) -> float:
        return float(self._limits.get(broker_id, {}).get(kind, 0) or 0)

    @staticmethod
    def _finite_rate(rate: Any) -> float:
        value = float(rate)
        if not math.isfinite(value):
            raise ValueError("rate limits must be finite")
        return value

    async def acquire(self, broker_id: str, kind: str = "order") -> None:
        """Wait for and consume a token from every applicable budget.

        Quotes (including quote-backed depth) share both quote and generic data
        limits. Tokens are consumed together only when every bucket is ready.
        A cancelled sleep holds no reservation and spends no partial budget.
        Synchronous accounting is shared across threads and event loops; every
        wake rechecks current rates and competes for a real refilled token.
        """
        kinds = ("data", "quote") if kind == "quote" else (kind,)
        while True:
            with self._lock:
                now = self._clock()
                buckets = []
                wait = 0.0
                for applicable_kind in kinds:
                    rate = self._rate(broker_id, applicable_kind)
                    if rate <= 0:
                        continue
                    key = (broker_id, applicable_kind)
                    bucket = self._buckets.get(key)
                    if bucket is None:
                        bucket = _Bucket(rate, now)
                        self._buckets[key] = bucket
                    bucket.refill(now)
                    buckets.append(bucket)
                    wait = max(wait, (1.0 - bucket.tokens) / rate)
                if wait <= 0:
                    for bucket in buckets:
                        bucket.tokens -= 1.0
                    return
            await self._sleep(wait)

    def snapshot(self) -> dict[str, dict[str, float]]:
        """Return the current effective per-broker limits (a deep copy).

        ``{broker_id: {"order": per_sec, "data": per_sec, "quote": per_sec}}``. Read by the
        rate-limits settings API so the UI shows the live values.
        """
        with self._lock:
            return {broker_id: dict(kinds) for broker_id, kinds in self._limits.items()}

    def apply_override(
        self,
        broker_id: str,
        *,
        order: float | None = None,
        data: float | None = None,
        quote: float | None = None,
    ) -> None:
        """Update selected limits at runtime (0 = unlimited), preserving credit.

        Refill existing buckets at their old rates before applying new rates.
        Waiters recheck the updated limits after waking; changing a positive
        rate must not reset an exhausted bucket to a fresh burst.
        """
        updates = {
            kind: self._finite_rate(rate)
            for kind, rate in (("order", order), ("data", data), ("quote", quote))
            if rate is not None
        }
        with self._lock:
            now = self._clock()
            current = dict(self._limits.get(broker_id, {}))
            for kind, rate in updates.items():
                key = (broker_id, kind)
                bucket = self._buckets.get(key)
                if rate <= 0:
                    self._buckets.pop(key, None)
                elif bucket is not None:
                    bucket.set_rate(rate, now)
                current[kind] = rate
            self._limits[broker_id] = current
