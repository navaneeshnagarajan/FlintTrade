"""Token-bucket rate limiter — per-user and global limits.

Provides :class:`RateLimiter` and the :func:`rate_limit` Flask decorator.

Algorithm
---------
Each ``(user_id, endpoint)`` pair has its own token bucket.  There is also
a global bucket per ``endpoint``.  A request is allowed only when BOTH
buckets have at least one token.  Tokens refill continuously at the
configured rate; the implementation uses the *leaky-bucket* refill model
(tokens added proportional to elapsed wall-clock time, capped at bucket
capacity).

Usage::

    limiter = RateLimiter(global_rate=100, per_user_rate=10)

    # Inside a Flask view
    allowed, retry_ms = limiter.check("alice", "orders")
    if not allowed:
        return jsonify({"error": "rate limit exceeded"}), 429

    # Or use the decorator (requires RateLimiter stored on app.config)
    @app.route("/v1/orders", methods=["POST"])
    @rate_limit("orders", user_rate=10, global_rate=100)
    def place_order():
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import jsonify, request

logger = logging.getLogger("flinttrade.rate_limiter")

F = TypeVar("F", bound=Callable[..., Any])


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    """A single token-bucket state for one (subject, endpoint) pair.

    Attributes:
        capacity: Maximum number of tokens (= burst limit).
        rate: Tokens added per second.
        tokens: Current token count (float).
        last_refill: Monotonic timestamp of the last refill.
    """

    capacity: float
    rate: float  # tokens per second
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)

    def consume(self) -> tuple[bool, float]:
        """Attempt to consume one token.

        Refills the bucket based on elapsed time before checking.

        Returns:
            Tuple of ``(allowed, retry_after_ms)`` where ``retry_after_ms``
            is the milliseconds until the next token is available (0 if
            allowed).
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0
        # Time until next token is available
        wait_s = (1.0 - self.tokens) / self.rate
        return False, round(wait_s * 1000)


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


@dataclass
class _EndpointConfig:
    """Rate-limit configuration for one endpoint.

    Attributes:
        user_rate: Per-user token refill rate (tokens/s).
        global_rate: Global token refill rate (tokens/s).
    """

    user_rate: int
    global_rate: int


class RateLimiter:
    """Token-bucket rate limiter with per-user and global limits.

    Args:
        global_rate: Default global token refill rate (requests/second).
        per_user_rate: Default per-user token refill rate (requests/second).
        window_seconds: Bucket capacity expressed as the number of seconds
            worth of tokens.  E.g. ``window_seconds=1`` means a burst equal
            to one second of traffic.

    Example::

        limiter = RateLimiter(global_rate=100, per_user_rate=10)
        allowed, retry_ms = limiter.check("alice", "orders")
        if not allowed:
            # Wait retry_ms before retrying
            ...
    """

    def __init__(
        self,
        global_rate: int = 100,
        per_user_rate: int = 10,
        window_seconds: int = 1,
    ) -> None:
        self._default_global_rate = global_rate
        self._default_user_rate = per_user_rate
        self._window_seconds = window_seconds
        # Per-endpoint config overrides
        self._endpoint_configs: dict[str, _EndpointConfig] = {}
        # State: user buckets keyed by (user_id, endpoint)
        self._user_buckets: dict[tuple[str, str], _Bucket] = {}
        # State: global buckets keyed by endpoint
        self._global_buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, user_id: str, endpoint: str) -> tuple[bool, int]:
        """Check whether a request is within rate limits.

        Consumes one token from both the per-user and global buckets.
        If either bucket is exhausted the request is denied.

        Args:
            user_id: Identifier for the requesting user.
            endpoint: Logical endpoint name (e.g. ``"orders"``).

        Returns:
            Tuple ``(allowed, retry_after_ms)``.  When ``allowed`` is
            ``False``, ``retry_after_ms`` is the number of milliseconds
            the caller should wait before retrying.
        """
        cfg = self._endpoint_configs.get(endpoint)
        user_rate = cfg.user_rate if cfg else self._default_user_rate
        global_rate = cfg.global_rate if cfg else self._default_global_rate

        with self._lock:
            user_bucket = self._get_user_bucket(user_id, endpoint, user_rate)
            global_bucket = self._get_global_bucket(endpoint, global_rate)

            user_allowed, user_retry = user_bucket.consume()
            global_allowed, global_retry = global_bucket.consume()

            if not user_allowed:
                # Put the global token back — user was blocked first
                global_bucket.tokens = min(global_bucket.capacity, global_bucket.tokens + 1.0)
                return False, user_retry
            if not global_allowed:
                # Put the user token back — global was the constraint
                user_bucket.tokens = min(user_bucket.capacity, user_bucket.tokens + 1.0)
                return False, global_retry

        return True, 0

    def get_limits(self, endpoint: str) -> dict[str, int]:
        """Return the configured rate limits for an endpoint.

        Args:
            endpoint: The endpoint name to query.

        Returns:
            Dict with ``user_rate`` and ``global_rate`` (requests/s).
        """
        cfg = self._endpoint_configs.get(endpoint)
        return {
            "user_rate": cfg.user_rate if cfg else self._default_user_rate,
            "global_rate": cfg.global_rate if cfg else self._default_global_rate,
        }

    def set_limit(self, endpoint: str, user_rate: int, global_rate: int) -> None:
        """Override rate limits for a specific endpoint.

        Args:
            endpoint: The endpoint name to configure.
            user_rate: Per-user requests per second.
            global_rate: Global requests per second across all users.
        """
        with self._lock:
            self._endpoint_configs[endpoint] = _EndpointConfig(
                user_rate=user_rate, global_rate=global_rate
            )
            # Invalidate existing buckets for this endpoint so they
            # are recreated with the new capacity on next check.
            self._user_buckets = {
                k: v for k, v in self._user_buckets.items() if k[1] != endpoint
            }
            if endpoint in self._global_buckets:
                del self._global_buckets[endpoint]
        logger.debug(
            "Set rate limits for %s — user=%d/s global=%d/s",
            endpoint,
            user_rate,
            global_rate,
        )

    def stats(self) -> dict[str, Any]:
        """Return current token counts and configuration.

        Returns:
            Dict with ``global_buckets`` and ``user_buckets`` sub-dicts,
            each mapping endpoint/key names to current token counts.
        """
        with self._lock:
            global_stats = {
                ep: {
                    "tokens": round(b.tokens, 3),
                    "capacity": b.capacity,
                    "rate": b.rate,
                }
                for ep, b in self._global_buckets.items()
            }
            user_stats = {
                f"{uid}:{ep}": {
                    "tokens": round(b.tokens, 3),
                    "capacity": b.capacity,
                    "rate": b.rate,
                }
                for (uid, ep), b in self._user_buckets.items()
            }
        return {
            "global_buckets": global_stats,
            "user_buckets": user_stats,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_user_bucket(self, user_id: str, endpoint: str, rate: int) -> _Bucket:
        """Return or create the per-user bucket.  Caller must hold ``_lock``."""
        key = (user_id, endpoint)
        if key not in self._user_buckets:
            capacity = float(rate * self._window_seconds)
            self._user_buckets[key] = _Bucket(
                capacity=capacity, rate=float(rate), tokens=capacity
            )
        return self._user_buckets[key]

    def _get_global_bucket(self, endpoint: str, rate: int) -> _Bucket:
        """Return or create the global bucket.  Caller must hold ``_lock``."""
        if endpoint not in self._global_buckets:
            capacity = float(rate * self._window_seconds)
            self._global_buckets[endpoint] = _Bucket(
                capacity=capacity, rate=float(rate), tokens=capacity
            )
        return self._global_buckets[endpoint]


# ---------------------------------------------------------------------------
# Flask decorator
# ---------------------------------------------------------------------------


def rate_limit(
    endpoint: str,
    user_rate: int = 10,
    global_rate: int = 100,
    user_id_header: str = "X-User-ID",
) -> Callable[[F], F]:
    """Flask view decorator that enforces token-bucket rate limits.

    The :class:`RateLimiter` instance is read from
    ``flask.current_app.config["RATE_LIMITER"]``.  If no limiter is
    configured, the request is allowed through without throttling (fail-open
    is intentional to avoid blocking requests in environments where the
    limiter is not set up).

    The user identifier is taken from (in priority order):

    1. ``X-User-ID`` request header (or *user_id_header* if customised)
    2. ``X-API-Key`` request header
    3. The client IP address (``request.remote_addr``)

    Args:
        endpoint: Logical endpoint name used for bucket keying.
        user_rate: Per-user token refill rate (requests/second).
        global_rate: Global token refill rate (requests/second).
        user_id_header: Header to read the user ID from.

    Returns:
        Decorator that wraps Flask view functions.

    Example::

        @app.route("/v1/orders", methods=["POST"])
        @rate_limit("orders", user_rate=10, global_rate=100)
        def place_order():
            ...
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from flask import current_app  # noqa: PLC0415

            limiter: RateLimiter | None = current_app.config.get("RATE_LIMITER")
            if limiter is None:
                # No limiter configured — allow through
                return func(*args, **kwargs)

            # Ensure endpoint config is registered with the supplied rates
            limits = limiter.get_limits(endpoint)
            if limits["user_rate"] != user_rate or limits["global_rate"] != global_rate:
                limiter.set_limit(endpoint, user_rate, global_rate)

            # Determine user identifier
            user_id = (
                request.headers.get(user_id_header)
                or request.headers.get("X-API-Key")
                or request.remote_addr
                or "anonymous"
            )

            allowed, retry_ms = limiter.check(user_id, endpoint)
            if not allowed:
                response = jsonify(
                    {
                        "status": "error",
                        "message": "Rate limit exceeded",
                        "retry_after_ms": retry_ms,
                    }
                )
                response.status_code = 429
                response.headers["Retry-After"] = str(max(1, retry_ms // 1000))
                return response

            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
