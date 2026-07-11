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

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

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
    def test_reconfigure_preserves_identity_and_updates_one_connection_snapshot(self):
        client = _client()
        original_http = client._http
        replacement = Settings(
            openalgo_host="https://openalgo.example",
            openalgo_port=5443,
            openalgo_api_key="rotated-key",
        )

        result = client.reconfigure(replacement)

        assert result is client
        assert client._http is original_http
        assert client.settings is replacement
        assert client._base == "https://openalgo.example:5443/api/v1"
        assert client._api_key == "rotated-key"

    def test_many_sequential_calls_one_owner_loop(self):
        client = _client()

        async def _loop_id() -> int:
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
            await asyncio.sleep(30)

        with pytest.raises(TimeoutError):
            client.run_sync(_hang(), timeout=0.2)
        client.close_sync()

    @pytest.mark.asyncio
    async def test_async_and_sync_requests_share_one_http_owner_loop(self):
        class LoopRecordingHttp:
            def __init__(self) -> None:
                self.request_loops: list[int] = []
                self.close_loops: list[int] = []

            async def get(self, url, **_kwargs):
                self.request_loops.append(id(asyncio.get_running_loop()))
                return httpx.Response(200, json={"status": "success", "url": url})

            async def post(self, url, **_kwargs):
                self.request_loops.append(id(asyncio.get_running_loop()))
                return httpx.Response(200, json={"status": "success", "url": url})

            async def aclose(self) -> None:
                self.close_loops.append(id(asyncio.get_running_loop()))

        client = _client()
        http = LoopRecordingHttp()
        client._http = http

        await client.ping()
        await asyncio.to_thread(client.run_sync, client.ping())
        await client.shutdown()

        assert len(http.request_loops) == 2
        assert len(set(http.request_loops + http.close_loops)) == 1

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_inflight_owner_task_result(self):
        client = _client()
        started = threading.Event()
        release = threading.Event()
        result: list[str] = []
        errors: list[BaseException] = []

        async def in_flight() -> str:
            started.set()
            await asyncio.to_thread(release.wait)
            return "completed"

        def caller() -> None:
            try:
                result.append(client.run_sync(in_flight(), timeout=2.0))
            except BaseException as exc:  # noqa: BLE001 - assertion captures cross-thread failure
                errors.append(exc)

        thread = threading.Thread(target=caller)
        thread.start()
        assert await asyncio.to_thread(started.wait, 1.0)

        shutdown = asyncio.create_task(client.shutdown())
        await asyncio.sleep(0.05)
        assert shutdown.done() is False
        release.set()
        await shutdown
        thread.join(timeout=1)

        assert thread.is_alive() is False
        assert errors == []
        assert result == ["completed"]

    @pytest.mark.asyncio
    async def test_shutdown_cannot_overtake_admitted_owner_submission(self):
        client = _client()
        admitted = threading.Event()
        release_submission = threading.Event()
        result: list[str] = []
        errors: list[BaseException] = []
        original_ensure = client._ensure_owner_loop

        def paused_ensure():
            loop = original_ensure()
            admitted.set()
            release_submission.wait(timeout=1)
            return loop

        client._ensure_owner_loop = paused_ensure  # type: ignore[method-assign]

        async def admitted_call() -> str:
            return "submitted"

        def caller() -> None:
            try:
                result.append(client.run_sync(admitted_call(), timeout=2))
            except BaseException as exc:  # noqa: BLE001 - assertion captures cross-thread failure
                errors.append(exc)

        thread = threading.Thread(target=caller)
        thread.start()
        assert await asyncio.to_thread(admitted.wait, 1.0)

        shutdown = asyncio.create_task(client.shutdown())
        await asyncio.sleep(0.05)
        shutdown_overtook_submission = shutdown.done()
        release_submission.set()
        shutdown_result = await asyncio.gather(shutdown, return_exceptions=True)
        thread.join(timeout=1)

        assert shutdown_overtook_submission is False
        assert shutdown_result == [None]
        assert thread.is_alive() is False
        assert errors == []
        assert result == ["submitted"]

    @pytest.mark.asyncio
    async def test_owner_close_failure_preserves_loop_for_retry(self):
        class FlakyHttp:
            def __init__(self) -> None:
                self.fail = True

            async def aclose(self) -> None:
                if self.fail:
                    raise RuntimeError("close failed")

        client = _client()
        http = FlakyHttp()
        client._http = http

        async def _noop() -> None:
            return None

        client.run_sync(_noop())
        owner_loop = client._owner_loop
        owner_thread = client._owner_thread

        with pytest.raises(RuntimeError, match="close failed"):
            await client.shutdown()

        assert client._owner_loop is owner_loop
        assert client._owner_thread is owner_thread
        assert owner_loop is not None and owner_loop.is_running()
        assert owner_thread is not None and owner_thread.is_alive()

        http.fail = False
        await client.shutdown()
        assert client._owner_loop is None


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


@pytest.mark.asyncio
async def test_application_shutdown_tears_down_client_owner_loop() -> None:
    from flinttrade_core.app import FlintTradeApp

    client = _client()

    async def _noop() -> bool:
        return True

    assert client.run_sync(_noop()) is True
    owner_thread = client._owner_thread
    assert owner_thread is not None and owner_thread.is_alive()

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = client
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    assert client._owner_loop is None
    assert client._owner_thread is None
    assert not owner_thread.is_alive()


@pytest.mark.asyncio
async def test_application_shutdown_closes_async_only_client_on_current_loop() -> None:
    from flinttrade_core.app import FlintTradeApp

    expected_loop = asyncio.get_running_loop()

    class LoopBoundClient(OpenAlgoClient):
        async def close(self) -> None:
            if asyncio.get_running_loop() is not expected_loop:
                raise RuntimeError("client closed on the wrong loop")
            await super().close()

    client = LoopBoundClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test")
    )
    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = client
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    assert client._http.is_closed
