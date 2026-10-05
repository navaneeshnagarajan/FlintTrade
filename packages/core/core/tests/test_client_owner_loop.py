"""Native reader loop ownership and fail-closed resolution."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

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
