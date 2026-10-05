"""Native reader loop ownership and fail-closed resolution."""

import asyncio
import threading
from concurrent.futures import CancelledError, ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from flinttrade_core.broker_client import BrokerClient, client_call_sync, client_close_sync, resolve_broker_client
from flinttrade_core.exceptions import APIError


def test_native_reader_shares_one_loop_across_request_threads():
    client = BrokerClient()

    async def identity():
        return asyncio.get_running_loop(), threading.current_thread()

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            identities = list(pool.map(lambda _: client.run_sync(identity()), range(8)))
        assert all(loop is identities[0][0] and thread is identities[0][1] for loop, thread in identities)
        assert identities[0][1] is not threading.current_thread()
    finally:
        client_close_sync(client)
    assert not identities[0][1].is_alive()
    assert identities[0][0].is_closed()


def test_native_reader_does_not_create_a_fallback_session():
    with pytest.raises(APIError, match="Native broker reader is unavailable"):
        resolve_broker_client(SimpleNamespace(config={}))


def test_native_reader_without_app_fails_explicitly():
    client = BrokerClient()
    try:
        with pytest.raises(APIError, match="no authorised native broker read integration"):
            client_call_sync(client, client.positionbook())
        with pytest.raises(AttributeError):
            getattr(client, "place_order")
    finally:
        client_close_sync(client)


def test_native_reader_rejects_work_after_shutdown():
    client = BrokerClient()
    client.close_sync()

    async def read():
        return True

    with pytest.raises(RuntimeError, match="closed"):
        client.run_sync(read())


@pytest.mark.asyncio
async def test_async_close_disposes_the_owned_loop_and_preserves_registry_sessions():
    client = BrokerClient()
    registry = MagicMock()
    client.bind(SimpleNamespace(config={"REGISTRY": registry}))

    async def identity():
        return asyncio.get_running_loop(), threading.current_thread()

    loop, thread = await asyncio.to_thread(client.run_sync, identity())
    try:
        await client.close()
        assert loop.is_closed()
        assert not thread.is_alive()
        assert client._closed
        registry.assert_not_called()
        assert not registry.mock_calls
        await client.close()
        await client.shutdown()
        client.close_sync()
        rejected = identity()
        with pytest.raises(RuntimeError, match="closed"):
            client.run_sync(rejected)
        assert rejected.cr_frame is None
    finally:
        client.close_sync()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["close", "shutdown"])
async def test_async_close_cancels_inflight_work_without_blocking_the_caller_loop(method):
    client = BrokerClient()
    started = threading.Event()
    cleaning = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()

    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            while not release.is_set():
                await asyncio.sleep(0.001)
            cleaned.set()

    caller = asyncio.create_task(asyncio.to_thread(client.run_sync, pending()))
    assert await asyncio.to_thread(started.wait, 1)
    closing = asyncio.create_task(getattr(client, method)())
    try:
        assert await asyncio.to_thread(cleaning.wait, 1)
        assert not closing.done()
        release.set()
        await asyncio.wait_for(closing, 1)
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert cleaned.is_set()
        assert client._loop.is_closed()
        assert not client._thread.is_alive()
    finally:
        release.set()
        await asyncio.to_thread(client.close_sync)


@pytest.mark.asyncio
async def test_cancelled_async_close_still_finishes_cleanup():
    client = BrokerClient()
    started = threading.Event()
    cleaning = threading.Event()
    release = threading.Event()

    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            while not release.is_set():
                await asyncio.sleep(0.001)

    caller = asyncio.create_task(asyncio.to_thread(client.run_sync, pending()))
    assert await asyncio.to_thread(started.wait, 1)
    closing = asyncio.create_task(client.close())
    try:
        assert await asyncio.to_thread(cleaning.wait, 1)
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        release.set()
        await asyncio.to_thread(client._thread.join, 1)
        assert not client._thread.is_alive()
        assert client._loop.is_closed()
        with pytest.raises(asyncio.CancelledError):
            await caller
        await client.shutdown()
    finally:
        release.set()
        await asyncio.to_thread(client.close_sync)


def test_run_sync_timeout_cancels_the_submitted_work():
    client = BrokerClient()
    cleaned = threading.Event()

    async def pending():
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    try:
        with pytest.raises(TimeoutError):
            client.run_sync(pending(), timeout=0.02)
        assert cleaned.wait(1)
    finally:
        client.close_sync()


def test_close_from_the_owned_loop_returns_and_retires_it():
    client = BrokerClient()

    async def close_here():
        await client.close()
        return "closed"

    try:
        assert client.run_sync(close_here(), timeout=1) == "closed"
        client._thread.join(1)
        assert not client._thread.is_alive()
        assert client._loop.is_closed()
    finally:
        client.close_sync()


def test_close_racing_a_submission_never_strands_the_accepted_coroutine(monkeypatch):
    client = BrokerClient()
    submitting = threading.Event()
    release = threading.Event()
    closing = threading.Event()
    submit = asyncio.run_coroutine_threadsafe

    def held_submission(coro, loop):
        submitting.set()
        assert release.wait(1)
        return submit(coro, loop)

    def close():
        closing.set()
        client.close_sync()

    async def read():
        return "finished"

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", held_submission)
    coro = read()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(client.run_sync, coro, 1)
            assert submitting.wait(1)
            cleanup = pool.submit(close)
            assert closing.wait(1)
            release.set()
            cleanup.result(1)
            try:
                assert work.result(1) == "finished"
            except CancelledError:
                pass  # Accepted work may be cancelled by retirement, never stranded.
        assert coro.cr_frame is None
        assert client._loop.is_closed()
        assert not client._thread.is_alive()
    finally:
        release.set()
        client.close_sync()


def test_http_native_reads_remain_frozen_without_provider_calls():
    from flask import Flask
    from unittest.mock import MagicMock

    app = Flask(__name__)
    owner = MagicMock()
    app.extensions["flinttrade_broker_dependencies"] = SimpleNamespace(read_owner=owner)
    client = BrokerClient()
    client.bind(app)
    try:
        with app.test_request_context("/api/v1/quotes"):
            with pytest.raises(APIError) as refusal:
                client_call_sync(client, client.quotes("RELIANCE", "NSE"))
            assert refusal.value.status_code == 409
        owner.bind.assert_not_called()
    finally:
        client_close_sync(client)
