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
    @rate_limit("orders", user_rate=10, global_rate=100, identity="jwt")
    def place_order():
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
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


_OVERRIDES_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS rate_limit_overrides (
    user_id   TEXT NOT NULL,
    endpoint  TEXT NOT NULL,
    user_rate INTEGER NOT NULL,
    PRIMARY KEY (user_id, endpoint)
)
"""


class RateLimiter:
    """Token-bucket rate limiter with per-user and global limits.

    Supports per-user rate overrides that are optionally persisted to
    DuckDB so they survive process restarts.

    Args:
        global_rate: Default global token refill rate (requests/second).
        per_user_rate: Default per-user token refill rate (requests/second).
        window_seconds: Bucket capacity expressed as the number of seconds
            worth of tokens.  E.g. ``window_seconds=1`` means a burst equal
            to one second of traffic.
        overrides_db: Path to a DuckDB file used to persist per-user
            overrides.  Pass ``None`` (default) to disable persistence
            (overrides live in memory only).

    Example::

        limiter = RateLimiter(global_rate=100, per_user_rate=10)
        allowed, retry_ms = limiter.check("alice", "orders")
        if not allowed:
            # Wait retry_ms before retrying
            ...

        # Grant a trusted user a higher limit:
        limiter.set_user_override("alice", "orders", 50)
    """

    def __init__(
        self,
        global_rate: int = 100,
        per_user_rate: int = 10,
        window_seconds: int = 1,
        overrides_db: Path | str | None = None,
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

        # Per-user overrides: (user_id, endpoint) → rate
        self._user_overrides: dict[tuple[str, str], int] = {}
        self._overrides_conn: Any = None
        if overrides_db is not None:
            self._init_overrides_db(overrides_db)

    def _init_overrides_db(self, db_path: Path | str) -> None:
        """Open (or create) the overrides DuckDB and load existing rows.

        Args:
            db_path: Path to the DuckDB file or ``":memory:"``.
        """
        try:
            import duckdb  # noqa: PLC0415

            if isinstance(db_path, Path):
                db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = duckdb.connect(str(db_path))
            else:
                conn = duckdb.connect(str(db_path))

            conn.execute(_OVERRIDES_CREATE_SQL)

            rows = conn.execute(
                "SELECT user_id, endpoint, user_rate FROM rate_limit_overrides"
            ).fetchall()
            for row in rows:
                self._user_overrides[(row[0], row[1])] = row[2]

            self._overrides_conn = conn
            logger.debug(
                "Loaded %d rate-limit overrides from %s", len(rows), db_path
            )
        except Exception as exc:
            logger.warning(
                "Cannot initialise overrides DB (%s): %s — overrides will be in-memory only",
                db_path,
                exc,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_user_override(
        self, user_id: str, endpoint: str, user_rate: int
    ) -> None:
        """Override the per-user rate for a specific user and endpoint.

        Useful for granting trusted users a higher limit than the default.
        The override is persisted to DuckDB (if *overrides_db* was provided
        at construction time) so it survives process restarts.

        Args:
            user_id: User identifier to override.
            endpoint: Logical endpoint name.
            user_rate: New per-user token refill rate (requests/second).
                Must be a positive integer.

        Raises:
            ValueError: If *user_rate* is not positive.
        """
        if user_rate <= 0:
            raise ValueError(f"user_rate must be positive, got {user_rate}")

        with self._lock:
            self._user_overrides[(user_id, endpoint)] = user_rate
            # Invalidate the existing bucket so the new rate takes effect
            # on the next check().
            self._user_buckets.pop((user_id, endpoint), None)

            if self._overrides_conn is not None:
                try:
                    self._overrides_conn.execute(
                        """
                        INSERT INTO rate_limit_overrides (user_id, endpoint, user_rate)
                        VALUES (?, ?, ?)
                        ON CONFLICT(user_id, endpoint) DO UPDATE SET user_rate = excluded.user_rate
                        """,
                        [user_id, endpoint, user_rate],
                    )
                except Exception as exc:
                    logger.warning("Failed to persist override: %s", exc)

        logger.info(
            "Rate-limit override set: user=%s endpoint=%s rate=%d/s",
            user_id,
            endpoint,
            user_rate,
        )

    def remove_user_override(self, user_id: str, endpoint: str) -> bool:
        """Remove a previously set per-user rate override.

        Args:
            user_id: User identifier.
            endpoint: Logical endpoint name.

        Returns:
            ``True`` if an override existed and was removed, ``False`` if
            no override was registered for this combination.
        """
        with self._lock:
            existed = (user_id, endpoint) in self._user_overrides
            if existed:
                del self._user_overrides[(user_id, endpoint)]
                self._user_buckets.pop((user_id, endpoint), None)

                if self._overrides_conn is not None:
                    try:
                        self._overrides_conn.execute(
                            "DELETE FROM rate_limit_overrides "
                            "WHERE user_id = ? AND endpoint = ?",
                            [user_id, endpoint],
                        )
                    except Exception as exc:
                        logger.warning("Failed to delete override: %s", exc)

        if existed:
            logger.info(
                "Rate-limit override removed: user=%s endpoint=%s",
                user_id,
                endpoint,
            )
        return existed

    def list_overrides(self) -> list[dict[str, Any]]:
        """Return all active per-user rate overrides.

        Returns:
            List of dicts with ``user_id``, ``endpoint``, and ``user_rate``
            fields, sorted by ``user_id`` then ``endpoint``.
        """
        with self._lock:
            return [
                {"user_id": uid, "endpoint": ep, "user_rate": rate}
                for (uid, ep), rate in sorted(
                    self._user_overrides.items(),
                    key=lambda kv: (kv[0][0], kv[0][1]),
                )
            ]

    def check(
        self,
        user_id: str,
        endpoint: str,
        *,
        override_user_id: str | None = None,
    ) -> tuple[bool, int]:
        """Check whether a request is within rate limits.

        Consumes one token from both the per-user and global buckets.
        If either bucket is exhausted the request is denied.

        Args:
            user_id: Identifier for the requesting user.
            endpoint: Logical endpoint name (e.g. ``"orders"``).
            override_user_id: Public operator-facing identity used only for
                override lookup when the bucket key is namespaced internally.

        Returns:
            Tuple ``(allowed, retry_after_ms)``.  When ``allowed`` is
            ``False``, ``retry_after_ms`` is the number of milliseconds
            the caller should wait before retrying.
        """
        cfg = self._endpoint_configs.get(endpoint)
        user_rate = cfg.user_rate if cfg else self._default_user_rate
        global_rate = cfg.global_rate if cfg else self._default_global_rate

        # Apply per-user override if one is registered.
        override_key = override_user_id if override_user_id is not None else user_id
        user_rate = self._user_overrides.get((override_key, endpoint), user_rate)

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

    def reset(self) -> None:
        """Clear all per-user and global token buckets (refills to full).

        Endpoint configs and user overrides are preserved — only the live
        bucket state is dropped, so the next request for any key starts with a
        full burst. Used by tests that reuse a module-scoped app across many
        rapid requests; not called on the production request path.
        """
        with self._lock:
            self._user_buckets.clear()
            self._global_buckets.clear()

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


def _header_rate_limit_user_id(user_id_header: str) -> str:
    """Return the unauthenticated / header-keyed bucket identity."""
    return (
        request.headers.get(user_id_header)
        or request.headers.get("X-API-Key")
        or request.remote_addr
        or "anonymous"
    )


def _verified_jwt_subject() -> str | None:
    """Return the verified session ``sub``, or ``None`` if it cannot be trusted.

    Uses :func:`flinttrade_core.auth_routes.decode_token` so expired, forged,
    or revoked tokens never become a bucket key. Does not read ``X-User-ID``.
    """
    import jwt  # noqa: PLC0415

    from .auth_routes import decode_token  # noqa: PLC0415

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    if payload.get("type") != "session":
        return None
    sub = payload.get("sub")
    if isinstance(sub, str) and sub.strip():
        return sub.strip()
    return None


def _jwt_rate_limit_identity() -> tuple[str, str | None]:
    """Return internal bucket key plus public override identity for JWT routes."""
    subject = _verified_jwt_subject()
    if subject is not None:
        return f"jwt:{subject}", subject
    # Invalid/missing JWTs are unauthenticated on these routes. Keep them in
    # one IP-scoped namespace: client-provided API/user headers must not mint
    # fresh buckets or collide with a legitimate JWT subject.
    return f"unauthenticated:{request.remote_addr or 'anonymous'}", None


def _jwt_rate_limit_user_id() -> str:
    """Compatibility helper returning only the internal JWT bucket key."""
    return _jwt_rate_limit_identity()[0]


def rate_limit(
    endpoint: str,
    user_rate: int = 10,
    global_rate: int = 100,
    user_id_header: str = "X-User-ID",
    *,
    identity: str = "header",
) -> Callable[[F], F]:
    """Flask view decorator that enforces token-bucket rate limits.

    The :class:`RateLimiter` instance is read from
    ``flask.current_app.config["RATE_LIMITER"]``.  If no limiter is
    configured, the request is allowed through without throttling (fail-open
    is intentional to avoid blocking requests in environments where the
    limiter is not set up).

    Bucket identity depends on *identity*:

    * ``"header"`` (default, unauthenticated / header-keyed callers) uses, in
      order: ``X-User-ID`` (or *user_id_header*), ``X-API-Key``, then
      ``request.remote_addr``.
    * ``"jwt"`` binds the bucket to the verified JWT ``sub`` from
      :func:`flinttrade_core.auth_routes.decode_token`. Client identity
      headers are ignored. Missing or invalid tokens share an IP-scoped,
      namespace-separated unauthenticated bucket. Identity is resolved inside
      this wrapper so it does not depend on an outer auth decorator having run.

    Args:
        endpoint: Logical endpoint name used for bucket keying.
        user_rate: Per-user token refill rate (requests/second).
        global_rate: Global token refill rate (requests/second).
        user_id_header: Header to read the user ID from when *identity* is
            ``"header"``.
        identity: ``"header"`` or ``"jwt"``.

    Returns:
        Decorator that wraps Flask view functions.

    Example::

        @app.route("/v1/orders", methods=["POST"])
        @rate_limit("orders", user_rate=10, global_rate=100, identity="jwt")
        def place_order():
            ...
    """
    if identity not in {"header", "jwt"}:
        raise ValueError(f"identity must be 'header' or 'jwt', got {identity!r}")

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

            if identity == "jwt":
                user_id, override_user_id = _jwt_rate_limit_identity()
            else:
                user_id = _header_rate_limit_user_id(user_id_header)
                override_user_id = None

            allowed, retry_ms = limiter.check(
                user_id,
                endpoint,
                override_user_id=override_user_id,
            )
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
