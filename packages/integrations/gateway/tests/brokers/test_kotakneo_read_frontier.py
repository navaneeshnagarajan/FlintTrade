"""Kotak final read waits and retained worker custody with the actual SDK."""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from flinttrade_core.broker_read_port import BrokerReadFailure, BrokerReadSuccess
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class
from packages.integrations.gateway.tests.test_canonical_broker_observations import bound as bound

pytestmark = pytest.mark.unit


def _sdk(held: bool = True) -> SimpleNamespace:
    """Build the actual pinned resource with a finite event-held inert transport."""
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.url.path == "/quick/user/trades"
        calls.append(request.url.path)
        if len(calls) == 1:
            entered.set()
            try:
                if held:
                    assert release.wait(5), "controlled transport release was not reached"
            finally:
                finished.set()
        return httpx.Response(200, json={"stat": "Ok", "data": []})

    neo = _sdk_class()(consumer_key="synthetic", transport=httpx.MockTransport(transport))
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    neo.configuration.base_url = "https://example.invalid"
    facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    facade._neo, facade._closed = neo, False
    return SimpleNamespace(facade=facade, calls=calls, entered=entered, release=release, finished=finished,
                           adapter=KotakNeoAdapter(client_factory=lambda _: facade))


def _queued_workers(adapter: KotakNeoAdapter) -> None:
    """Witness real workers at the transport boundary, never a fabricated queue."""
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        workers = 0
        for frame in sys._current_frames().values():
            while frame:
                if frame.f_code.co_name == "locked_call" and frame.f_locals.get("self") is adapter:
                    workers += 1
                    break
                frame = frame.f_back
        if workers == 2:
            return
        time.sleep(0.001)
    raise AssertionError("second real Kotak SDK worker never reached the transport-lock queue")


@pytest.mark.parametrize("change", ["unchanged", "port", "principal", "account", "generation"])
def test_queued_read_rechecks_real_owner_after_transport_wait(bound: Any, change: str) -> None:
    """A retired queued read never invokes, alongside the unchanged real positive."""
    s = _sdk()
    h = bound(s.adapter, broker="kotakneo")
    pool = ThreadPoolExecutor(max_workers=2)
    first = pool.submit(asyncio.run, h.port.trades())
    second = None
    try:
        assert s.entered.wait(2)
        second = pool.submit(asyncio.run, h.port.trades())
        _queued_workers(s.adapter)
        assert not s.finished.is_set() and s.calls == ["/quick/user/trades"]
        if change == "port":
            assert h.owner.revoke(h.port)
        elif change == "principal":
            h.context[0] = replace(h.context[0], actor_id="foreign")
        elif change in {"account", "generation"}:
            from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot
            from flinttrade_gateway.brokers._base import Session
            from flinttrade_gateway.registry import ManagedSessionAuthority

            snapshot = read_workspace_snapshot(h.workspace_path)
            authority = ManagedSessionAuthority(h.store.selector_state(h.selector).version, snapshot.version,
                                                broker_workspace_version(snapshot))
            session = Session("synthetic-successor", time.time() + 3600,
                              "nativecase" if change == "account" else "NativeCase", "kotakneo")
            receipt = h.publisher.prepare_session_candidate(h.selector, session,
                expected_registry=h.registry.snapshot_selector(h.selector), authority=authority,
                broker="kotakneo", label="Synthetic", client=object())
            h.publisher.publish_prepared_candidate(receipt, current_authority=authority)
        before = tuple(s.calls)
        s.release.set()
        first.result(timeout=0.75)
        outcome = second.result(timeout=0.75)
        if change == "unchanged":
            assert isinstance(outcome, BrokerReadSuccess)
            assert s.calls == [*before, "/quick/user/trades"]
        else:
            assert isinstance(outcome, BrokerReadFailure)
            assert tuple(s.calls) == before
        assert h.owner.close(timeout=1)
    finally:
        s.release.set()
        pool.shutdown(wait=True)
        assert h.owner.close(timeout=2)
        s.facade.close()
