"""Tests for packages/core/src/http_pool.py.

Covers: client creation, URL base extraction, retry on status codes,
        retry on transport errors, close_all, stats, async context manager.
All httpx I/O is mocked — no live network calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from packages.core.src.http_pool import HTTPClientPool, _RETRYABLE_STATUSES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    return httpx.Response(status_code, json=body or {})


# ---------------------------------------------------------------------------
# _extract_base_url
# ---------------------------------------------------------------------------


def test_extract_base_url_http() -> None:
    """_extract_base_url strips path from http URL."""
    pool = HTTPClientPool()
    assert pool._extract_base_url("http://127.0.0.1:5000/api/v1/funds") == "http://127.0.0.1:5000"


def test_extract_base_url_https() -> None:
    """_extract_base_url handles https scheme."""
    pool = HTTPClientPool()
    assert pool._extract_base_url("https://api.example.com/v1/orders") == "https://api.example.com"


def test_extract_base_url_no_path() -> None:
    """_extract_base_url returns the URL unchanged when no path present."""
    pool = HTTPClientPool()
    assert pool._extract_base_url("http://localhost:5000") == "http://localhost:5000"


# ---------------------------------------------------------------------------
# get_client()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_client_creates_new_client() -> None:
    """get_client() creates an httpx.AsyncClient on first call."""
    pool = HTTPClientPool()
    client = await pool.get_client("http://localhost:5000")
    assert isinstance(client, httpx.AsyncClient)
    await pool.close_all()


@pytest.mark.asyncio
async def test_get_client_reuses_existing_client() -> None:
    """get_client() returns the same client for the same base URL."""
    pool = HTTPClientPool()
    c1 = await pool.get_client("http://localhost:5000")
    c2 = await pool.get_client("http://localhost:5000")
    assert c1 is c2
    await pool.close_all()


@pytest.mark.asyncio
async def test_get_client_separate_for_different_hosts() -> None:
    """get_client() creates separate clients for different base URLs."""
    pool = HTTPClientPool()
    c1 = await pool.get_client("http://localhost:5000")
    c2 = await pool.get_client("http://localhost:5001")
    assert c1 is not c2
    await pool.close_all()


# ---------------------------------------------------------------------------
# request() — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_success_no_retry() -> None:
    """request() returns the response on first attempt (200 OK)."""
    pool = HTTPClientPool()
    mock_response = _make_response(200, {"status": "ok"})

    with patch.object(httpx.AsyncClient, "request", new=AsyncMock(return_value=mock_response)):
        resp = await pool.request("GET", "http://localhost:5000/ping")

    assert resp.status_code == 200
    assert pool.stats()["total_retries"] == 0
    await pool.close_all()


# ---------------------------------------------------------------------------
# request() — retry on retryable status codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_retries_on_500() -> None:
    """request() retries on HTTP 500 and succeeds on the third attempt."""
    pool = HTTPClientPool()
    responses = [
        _make_response(500),
        _make_response(500),
        _make_response(200, {"ok": True}),
    ]
    call_count = 0

    async def _mock_request(*args, **kwargs):
        nonlocal call_count
        r = responses[min(call_count, len(responses) - 1)]
        call_count += 1
        return r

    with patch.object(httpx.AsyncClient, "request", new=_mock_request):
        with patch("packages.core.src.http_pool.asyncio.sleep", new=AsyncMock()):
            resp = await pool.request("POST", "http://localhost:5000/api")

    assert resp.status_code == 200
    assert pool.stats()["total_retries"] == 2
    await pool.close_all()


@pytest.mark.asyncio
async def test_request_retries_on_429() -> None:
    """request() retries on HTTP 429 (rate limit)."""
    pool = HTTPClientPool()
    responses = [_make_response(429), _make_response(200)]
    idx = 0

    async def _mock_request(*args, **kwargs):
        nonlocal idx
        r = responses[idx]
        idx += 1
        return r

    with patch.object(httpx.AsyncClient, "request", new=_mock_request):
        with patch("packages.core.src.http_pool.asyncio.sleep", new=AsyncMock()):
            resp = await pool.request("GET", "http://localhost:5000/data")

    assert resp.status_code == 200
    await pool.close_all()


# ---------------------------------------------------------------------------
# request() — retry on transport errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_retries_on_transport_error() -> None:
    """request() retries on TransportError and succeeds after recovery."""
    pool = HTTPClientPool()
    call_count = 0

    async def _mock_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("connection refused")
        return _make_response(200)

    with patch.object(httpx.AsyncClient, "request", new=_mock_request):
        with patch("packages.core.src.http_pool.asyncio.sleep", new=AsyncMock()):
            resp = await pool.request("GET", "http://localhost:5000/")

    assert resp.status_code == 200
    await pool.close_all()


@pytest.mark.asyncio
async def test_request_raises_after_all_retries_exhausted() -> None:
    """request() raises TransportError when all retries are exhausted."""
    pool = HTTPClientPool()

    async def _always_fail(*args, **kwargs):
        raise httpx.ConnectError("always down")

    with patch.object(httpx.AsyncClient, "request", new=_always_fail):
        with patch("packages.core.src.http_pool.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(httpx.TransportError):
                await pool.request("GET", "http://down.example.com/")

    await pool.close_all()


# ---------------------------------------------------------------------------
# close_all() / stats()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all_clears_pool() -> None:
    """close_all() closes clients and empties the pool."""
    pool = HTTPClientPool()
    await pool.get_client("http://localhost:5000")
    await pool.get_client("http://localhost:5001")
    assert pool.stats()["pool_size"] == 2
    await pool.close_all()
    assert pool.stats()["pool_size"] == 0


@pytest.mark.asyncio
async def test_stats_structure() -> None:
    """stats() returns dict with expected keys."""
    pool = HTTPClientPool()
    s = pool.stats()
    assert "pool_size" in s
    assert "hosts" in s
    assert "total_requests" in s
    assert "total_retries" in s
    await pool.close_all()


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_context_manager_closes_on_exit() -> None:
    """The pool closes all clients when used as an async context manager."""
    async with HTTPClientPool() as pool:
        await pool.get_client("http://localhost:9999")
        assert pool.stats()["pool_size"] == 1
    assert pool.stats()["pool_size"] == 0
