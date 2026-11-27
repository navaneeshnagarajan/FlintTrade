"""Per-broker API rate limiting (DATA & INFRA: customizable rate limits + latency).

Each broker publishes its API limits in :class:`Capabilities`
(``rate_limit_orders_per_sec`` / ``rate_limit_data_per_sec`` …). This module turns
that static metadata — plus any operator override — into an *enforced* per-broker
throttle so FlintTrade never trips a broker's ban for exceeding its rate, while
keeping latency tight (it only delays a call when genuinely over the limit).

:class:`BrokerRateLimiter` is a small async token bucket keyed by
``(broker_id, kind, exchange)`` where ``kind`` is ``"order"``, ``"data"`` or
``"quote"``. Only order buckets carry an exchange; data and quote buckets are
per broker.
Quote admission also consumes the generic data budget atomically. The
``BrokerRouter`` calls :meth:`BrokerRateLimiter.admit_order` before each order
write and ``await acquire(adapter_id, kind)`` before each data or quote call.
Both sit below the gate, so they can only refuse or delay a call, never skip
the safety gate. The clock and sleep are injectable, so the buckets are tested
deterministically without real time.

Order writes (place, modify and cancel share one ``"order"`` budget) are
limited to :data:`ORDER_RATE_LIMIT` per second for each broker on each
exchange, so NSE and BSE orders through one broker each get their own 10 per
second. The eleventh order in that second is refused with the
``order-rate-threshold`` message and is not delayed. NFO and CDS count as NSE,
BFO and BCD count as BSE. A modify or cancel whose exchange is unknown spends
from both the NSE and the BSE budget of that broker, so it never takes either
over the limit. A capability default, workspace override or settings change
can lower the limit but can never raise it or switch it off: a higher value,
``0`` or a missing value is clamped to the limit with a warning.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from typing import Any, Awaitable, Callable

from .capabilities import Capabilities

logger = logging.getLogger("flinttrade.gateway.rate_limiter")

#: Order writes per second for each broker on each exchange. Place, modify and
#: cancel share it. Not configurable above this value.
ORDER_RATE_LIMIT: float = 10.0

#: Exchange that owns each order segment for the order budget.
_ORDER_VENUES: dict[str, str] = {
    "NSE": "NSE",
    "NFO": "NSE",
    "CDS": "NSE",
    "BSE": "BSE",
    "BFO": "BSE",
    "BCD": "BSE",
    "MCX": "MCX",
}

# Floating-point refill can land a hair under a whole token. Without slack a
# waiter sleeps for a rounding error, and with a coarse clock it spins.
_TOKEN_EPSILON = 1e-9


#: Budgets an order with an unknown exchange spends from.
_UNKNOWN_ORDER_VENUES: tuple[str, ...] = ("NSE", "BSE")


def order_venue(exchange: str | None) -> str | None:
    """Exchange whose order budget a segment uses, or ``None`` when blank."""
    segment = (exchange or "").strip().upper()
    if not segment:
        return None
    return _ORDER_VENUES.get(segment, segment)


def cap_order_rate(rate: float, *, broker_id: str = "") -> float:
    """Clamp an order rate to the order limit.

    Rates above the limit, and ``0`` or negative values (which would switch the
    throttle off), become :data:`ORDER_RATE_LIMIT` with a warning. A positive
    rate at or below the limit is kept.
    """
    if 0 < rate <= ORDER_RATE_LIMIT:
        return rate
    logger.warning(
        "Order rate %s/s for %s clamped to %s orders per second per exchange",
        "unlimited" if rate <= 0 else f"{rate:g}",
        broker_id or "broker",
        f"{ORDER_RATE_LIMIT:g}",
    )
    return ORDER_RATE_LIMIT


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
        limits: ``{broker_id: {"order": per_sec, "data": per_sec, "quote": per_sec}}``. A data or
            quote kind with no positive limit is treated as unlimited (no throttle). Order
            limits are always clamped to :data:`ORDER_RATE_LIMIT`, and a broker
            with no order limit gets that limit. Each exchange has its own order bucket.
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
            broker_id: {
                kind: (
                    cap_order_rate(self._finite_rate(rate), broker_id=broker_id)
                    if kind == "order"
                    else self._finite_rate(rate)
                )
                for kind, rate in kinds.items()
            }
            for broker_id, kinds in limits.items()
        }
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._buckets: dict[tuple[str, str, str], _Bucket] = {}
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
            defaults = {
                "order": cap.rate_limit_orders_per_sec or ORDER_RATE_LIMIT,
                "data": cap.rate_limit_data_per_sec,
            }
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
                "order": cls._override_rate(ov.get("order", ORDER_RATE_LIMIT), ORDER_RATE_LIMIT),
                **{kind: cls._override_rate(ov.get(kind, 0), 0) for kind in ("data", "quote")},
            })
        return cls(limits, **kwargs)

    @classmethod
    def _override_rate(cls, value: object, default: float | None) -> float:
        try:
            return cls._finite_rate(value)
        except (TypeError, ValueError, OverflowError):
            return cls._finite_rate(default or 0)

    def _rate(self, broker_id: str, kind: str) -> float:
        if kind == "order":
            # Every broker is held to the order limit, including one that has
            # no configured limits at all.
            return float(self._limits.get(broker_id, {}).get(kind, ORDER_RATE_LIMIT))
        return float(self._limits.get(broker_id, {}).get(kind, 0) or 0)

    @staticmethod
    def _finite_rate(rate: Any) -> float:
        value = float(rate)
        if not math.isfinite(value):
            raise ValueError("rate limits must be finite")
        return value

    def clear(self) -> None:
        """Drop every token bucket. Tests use this so cases do not share burst state."""
        with self._lock:
            self._buckets.clear()

    def admit_order(self, broker_id: str, *, exchange: str | None = None) -> None:
        """Consume one order token, or refuse with the published rate rule.

        An order spends from the budget of its exchange (see :func:`order_venue`).
        An order with no exchange spends from both the NSE and the BSE budget
        of the broker and is refused unless both have a token.
        """
        from flinttrade_core.order_rules import order_rate_exceeded  # noqa: PLC0415

        venue = order_venue(exchange)
        with self._lock:
            now = self._clock()
            if venue is None:
                keys = [(broker_id, "order", name) for name in _UNKNOWN_ORDER_VENUES]
            else:
                keys = [(broker_id, "order", venue)]
            buckets = []
            for key in keys:
                rate = self._rate(broker_id, "order")
                if rate <= 0:
                    continue
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _Bucket(rate, now)
                    self._buckets[key] = bucket
                bucket.refill(now)
                if bucket.tokens + _TOKEN_EPSILON < 1.0:
                    raise order_rate_exceeded()
                buckets.append(bucket)
            for bucket in buckets:
                bucket.tokens -= 1.0

    async def acquire(
        self,
        broker_id: str,
        kind: str = "order",
        *,
        exchange: str | None = None,
        before_retry: Callable[[], None] | None = None,
    ) -> None:
        """Consume a token from every applicable budget.

        An order is admitted or refused immediately (see :meth:`admit_order`).
        Data and quote calls wait for a token.

        Quotes (including quote-backed depth) share both quote and generic data
        limits. Tokens are consumed together only when every bucket is ready.
        A cancelled sleep holds no reservation and spends no partial budget.
        Synchronous accounting is shared across threads and event loops; every
        wake rechecks current rates and competes for a real refilled token.
        An optional ``before_retry`` callback runs outside the accounting lock
        after each sleep and may raise to abandon a stale request without
        spending tokens. Such waits recheck at least once per second, including
        fractional rates, so retired read grants do not wait through a queue.
        """
        if kind == "order":
            self.admit_order(broker_id, exchange=exchange)
            return
        kinds = ("data", "quote") if kind == "quote" else (kind,)
        venue = ""
        while True:
            with self._lock:
                now = self._clock()
                if venue is None:
                    keys = [(broker_id, "order", name) for name in _UNKNOWN_ORDER_VENUES]
                else:
                    keys = [(broker_id, applicable_kind, venue) for applicable_kind in kinds]
                buckets = []
                wait = 0.0
                for key in keys:
                    rate = self._rate(broker_id, key[1])
                    if rate <= 0:
                        continue
                    bucket = self._buckets.get(key)
                    if bucket is None:
                        bucket = _Bucket(rate, now)
                        self._buckets[key] = bucket
                    bucket.refill(now)
                    buckets.append(bucket)
                    wait = max(wait, (1.0 - bucket.tokens) / rate)
                if wait <= _TOKEN_EPSILON:
                    for bucket in buckets:
                        bucket.tokens -= 1.0
                    return
            await self._sleep(min(wait, 1.0) if before_retry is not None else wait)
            if before_retry is not None:
                before_retry()

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
        """Update selected limits at runtime, preserving credit.

        ``0`` means unlimited for data and quote. An order rate is clamped to
        :data:`ORDER_RATE_LIMIT`, so it can be lowered but never raised
        above that or switched off.

        Refill existing buckets at their old rates before applying new rates.
        Waiters recheck the updated limits after waking; changing a positive
        rate must not reset an exhausted bucket to a fresh burst.
        """
        updates = {
            kind: self._finite_rate(rate)
            for kind, rate in (("order", order), ("data", data), ("quote", quote))
            if rate is not None
        }
        if "order" in updates:
            updates["order"] = cap_order_rate(updates["order"], broker_id=broker_id)
        with self._lock:
            now = self._clock()
            current = dict(self._limits.get(broker_id, {}))
            for kind, rate in updates.items():
                keys = [key for key in self._buckets if key[0] == broker_id and key[1] == kind]
                for key in keys:
                    if rate <= 0:
                        self._buckets.pop(key)
                    else:
                        self._buckets[key].set_rate(rate, now)
                current[kind] = rate
            self._limits[broker_id] = current
