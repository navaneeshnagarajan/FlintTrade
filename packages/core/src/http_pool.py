"""Shared async httpx client pool for FlintTrade broker REST calls.

Each base URL (e.g. ``http://127.0.0.1:5000``) maps to a single
:class:`httpx.AsyncClient` with connection limits and timeout configured
at construction time.  Callers share the client for all requests to the
same host, eliminating per-call TCP handshake overhead.

Retry policy: up to 2 retries with exponential back-off (0.5 s, 1.0 s) on
network errors and HTTP 429/500/502/503/504 responses.

Usage::

    pool = HTTPClientPool(max_connections_per_host=20, timeout=30.0)
    resp = await pool.request("POST", "http://127.0.0.1:5000/api/v1/funds",
                               json={"apikey": "..."})
    print(resp.json())
    await pool.close_all()

The module exposes a module-level singleton :data:`pool` for convenience.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger("flinttrade.core.http_pool")

# HTTP status codes that trigger a retry
_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_MAX_RETRIES = 2
_BACKOFF_BASE = 0.5  # seconds


# ---------------------------------------------------------------------------
# HTTPClientPool
# ---------------------------------------------------------------------------


class HTTPClientPool:
    """Shared :class:`httpx.AsyncClient` pool keyed by base URL.

    A single :class:`httpx.AsyncClient` is created per base URL and cached
    for the lifetime of the pool.  The client uses ``httpx.Limits`` to cap
    connections per host and global total connections.

    Automatic retry
    ---------------
    :meth:`request` retries up to ``_MAX_RETRIES`` times on:

    * :class:`httpx.TransportError` (connection reset, timeout, etc.)
    * HTTP responses with status in :data:`_RETRYABLE_STATUSES`

    Back-off is exponential: ``0.5 s``, ``1.0 s``.

    Args:
        max_connections_per_host: Per-host connection limit (default 20).
        timeout: Request timeout in seconds (default 30.0).

    Example::

        async with HTTPClientPool() as pool:
            resp = await pool.request("GET", "http://host/ping")
    """

    def __init__(
        self,
        max_connections_per_host: int = 20,
        timeout: float = 30.0,
    ) -> None:
        self._max_connections_per_host = max(1, max_connections_per_host)
        self._timeout = timeout
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()
        # Stats
        self._total_requests: int = 0
        self._total_retries: int = 0
        self._active_per_host: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Client access
    # ------------------------------------------------------------------

    async def get_client(self, base_url: str) -> httpx.AsyncClient:
        """Return the shared :class:`httpx.AsyncClient` for *base_url*.

        Creates a new client on first access.  The client is configured with
        connection limits and a unified timeout.

        Args:
            base_url: Scheme + host + optional port, e.g.
                ``"http://127.0.0.1:5000"``.

        Returns:
            A live :class:`httpx.AsyncClient` ready to send requests.
        """
        normalised = base_url.rstrip("/")
        async with self._lock:
            if normalised not in self._clients:
                limits = httpx.Limits(
                    max_connections=self._max_connections_per_host * 2,
                    max_keepalive_connections=self._max_connections_per_host,
                )
                client = httpx.AsyncClient(
                    base_url=normalised,
                    limits=limits,
                    timeout=httpx.Timeout(self._timeout),
                )
                self._clients[normalised] = client
                self._active_per_host[normalised] = 0
                logger.debug("HTTPClientPool: created client for %s", normalised)
        return self._clients[normalised]

    # ------------------------------------------------------------------
    # Unified request with retry
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with automatic retry on transient errors.

        The base URL is derived from the scheme + host + port of *url*.  The
        path and query string are forwarded to the underlying client.

        Args:
            method: HTTP method string (``"GET"``, ``"POST"``, etc.).
            url: Full URL.  The base URL portion is used to look up the
                pooled client; the path is sent as the request target.
            **kwargs: Forwarded verbatim to :meth:`httpx.AsyncClient.request`.

        Returns:
            :class:`httpx.Response` from the server.

        Raises:
            httpx.HTTPStatusError: When all retries are exhausted and the
                final response has a non-retryable error status.
            httpx.TransportError: When all retries are exhausted and the
                connection still fails.
        """
        base_url = self._extract_base_url(url)
        client = await self.get_client(base_url)
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                self._total_requests += 1
                response = await client.request(method, url, **kwargs)

                if response.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    self._total_retries += 1
                    logger.warning(
                        "HTTPClientPool: HTTP %d from %s, retry %d/%d in %.1fs",
                        response.status_code,
                        url,
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                return response

            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    self._total_retries += 1
                    logger.warning(
                        "HTTPClientPool: transport error for %s (%s), retry %d/%d in %.1fs",
                        url,
                        exc,
                        attempt + 1,
                        _MAX_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "HTTPClientPool: all retries exhausted for %s: %s", url, exc
                    )
                    raise

        # Should only be reached if retryable status persisted across retries
        if last_exc is not None:
            raise last_exc  # pragma: no cover
        # Return last response even if it had a retryable status
        return response  # type: ignore[return-value]  # noqa: F821

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """Close and evict all pooled clients.

        Should be called on application shutdown to release open sockets.
        """
        async with self._lock:
            for base_url, client in list(self._clients.items()):
                try:
                    await client.aclose()
                    logger.debug("HTTPClientPool: closed client for %s", base_url)
                except Exception:
                    logger.exception("HTTPClientPool: error closing client for %s", base_url)
            self._clients.clear()
            self._active_per_host.clear()

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "HTTPClientPool":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close_all()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return pool usage statistics.

        Returns:
            Dict with keys: ``pool_size`` (number of cached clients),
            ``hosts`` (list of base URLs with clients),
            ``total_requests``, ``total_retries``.
        """
        return {
            "pool_size": len(self._clients),
            "hosts": list(self._clients.keys()),
            "total_requests": self._total_requests,
            "total_retries": self._total_retries,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_base_url(url: str) -> str:
        """Extract scheme + host + port from *url*."""
        # Fast path: find the end of the authority component
        # e.g. "http://127.0.0.1:5000/api/v1/funds" → "http://127.0.0.1:5000"
        for scheme in ("https://", "http://"):
            if url.startswith(scheme):
                authority_start = len(scheme)
                slash_pos = url.find("/", authority_start)
                if slash_pos == -1:
                    return url
                return url[:slash_pos]
        return url


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Shared pool instance.  Import for normal use.
pool: HTTPClientPool = HTTPClientPool()
