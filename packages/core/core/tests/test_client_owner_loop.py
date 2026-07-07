"""Regression tests for the OpenAlgo client owner-loop (cross-event-loop bug).

A shared httpx.AsyncClient pools keep-alive connections that are AFFINE to
the event loop they were created on. Driving one shared client with a fresh
``asyncio.run()`` per request reused poisoned connections and failed with
"Event loop is closed" on alternating requests across six route surfaces.

These tests prove: (a) run_sync serves many sequential calls from sync code
over ONE loop, (b) calls from multiple threads work, (c) close_sync tears the
owner loop down, and (d) client_call_sync/client_close_sync fall back for
duck-typed fakes.
"""

from __future__ import annotations

import threading

import pytest

from flinttrade_core.config import Settings
from flinttrade_core.openalgo_client import (
    OpenAlgoClient,
    client_call_sync,
    client_close_sync,
)

pytestmark = pytest.mark.unit


def _client() -> OpenAlgoClient:
    return OpenAlgoClient(Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test"))


class TestRunSync:
    def test_many_sequential_calls_one_owner_loop(self):
        client = _client()

        async def _loop_id() -> int:
            import asyncio  # noqa: PLC0415

            return id(asyncio.get_running_loop())

        ids = {client.run_sync(_loop_id()) for _ in range(5)}
        # Every call ran on the SAME persistent loop — no per-call loops.
        assert len(ids) == 1
        client.close_sync()

    def test_calls_from_multiple_threads_share_the_loop(self):
        client = _client()
        results: list[int] = []
        lock = threading.Lock()

        async def _loop_id() -> int:
            import asyncio  # noqa: PLC0415

            return id(asyncio.get_running_loop())

        def worker() -> None:
            value = client.run_sync(_loop_id())
            with lock:
                results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(set(results)) == 1
        client.close_sync()

    def test_close_sync_tears_down_owner_loop(self):
        client = _client()

        async def _noop() -> bool:
            return True

        assert client.run_sync(_noop()) is True
        assert client._owner_loop is not None
        client.close_sync()
        assert client._owner_loop is None

    def test_timeout_raises_and_cancels(self):
        client = _client()

        async def _hang() -> None:
            import asyncio  # noqa: PLC0415

            await asyncio.sleep(30)

        with pytest.raises(TimeoutError):
            client.run_sync(_hang(), timeout=0.2)
        client.close_sync()


class TestModuleHelpers:
    def test_client_call_sync_uses_owner_loop(self):
        client = _client()

        async def _ok() -> str:
            return "ok"

        assert client_call_sync(client, _ok()) == "ok"
        assert client._owner_loop is not None
        client_close_sync(client)
        assert client._owner_loop is None

    def test_helpers_fall_back_for_duck_typed_fakes(self):
        class _Fake:
            async def do(self) -> str:
                return "fake-ok"

            async def close(self) -> None:
                self.closed = True

        fake = _Fake()
        assert client_call_sync(fake, fake.do()) == "fake-ok"
        client_close_sync(fake)
        assert fake.closed is True
