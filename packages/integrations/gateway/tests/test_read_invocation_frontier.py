"""Bound read frontiers with installed SDK resources and inert held transports.

All identities, account enrolment and returned rows are synthetic. No provider
qualification, credential access, order or model action is exercised here.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from flinttrade_core.broker_client import BrokerClient
from flinttrade_core.broker_read_port import BrokerReadFailure, BrokerReadSuccess, LedgerRequest, TradeHistoryRequest
from flinttrade_engine.local_state_provider import OrderLifecycleLedger
from packages.integrations.gateway.tests.test_canonical_broker_observations import bound as bound
from packages.integrations.gateway.tests.test_canonical_observation_custody import (
    _factory_bound,
    _native_trade,
    _synthetic_auth_state as _synthetic_auth_state,
)

pytestmark = pytest.mark.unit


def test_async_only_reader_keeps_its_callers_loop(
    bound: Callable[..., SimpleNamespace],
) -> None:
    """Keep loop-affine async readers on their existing caller loop.

    Args:
        bound: Real read owner with an explicitly async-only synthetic provider.
    """
    loops = []

    class AsyncReader:
        async def trade_book(self, session: object) -> list:
            loops.append(asyncio.get_running_loop())
            return []

    handle = bound(AsyncReader())

    async def read() -> None:
        caller = asyncio.get_running_loop()
        result = await handle.owner.capture_observations(handle.port)
        assert result.coverage[0].availability == "available"
        assert loops == [caller]

    asyncio.run(read())


def _sdk(monkeypatch: pytest.MonkeyPatch, held: bool) -> SimpleNamespace:
    """Create a real SDK and record its exact resource transport calls.

    Args:
        monkeypatch: Scoped inert HTTP transport injection.
        held: Hold history page one until the test's controlled release.

    Returns:
        SDK, adapter, call ledger and event-held worker observations.
    """
    from dhanhq import DhanContext, dhanhq
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    sdk = dhanhq(DhanContext("NativeCase", "synthetic-token"))
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls: list[str] = []
    times: list[float] = []
    profiles: list[str] = []

    def transport(method: str, url: str, **kwargs: object) -> SimpleNamespace:
        assert method == "GET"
        if url.endswith("/profile"):
            profiles.append(url)
            expiry = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)
            rows = {"dhanClientId": "NativeCase", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M")}
        else:
            calls.append(url)
            times.append(time.monotonic())
            if url.endswith("/1"):
                entered.set()
                try:
                    if held:
                        assert release.wait(5), "controlled worker release was not reached"
                finally:
                    finished.set()
            rows = [_native_trade()] if url.endswith("/0") else []
        return SimpleNamespace(status_code=200, content=json.dumps(rows).encode())

    monkeypatch.setattr(sdk.dhan_http.session, "request", transport)
    return SimpleNamespace(sdk=sdk, adapter=DhanAdapter(client_factory=lambda _: sdk), entered=entered,
                           release=release, finished=finished, calls=calls, profiles=profiles, times=times)


def _queued_workers(adapter: object) -> None:
    """Witness two real SDK workers, one blocked at the actual adapter lock.

    Args:
        adapter: The exact adapter serving both bound reads.
    """
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
    raise AssertionError("second actual SDK task never reached the transport-lock queue")


def _capture(ledger: OrderLifecycleLedger, handle: SimpleNamespace):
    """Use the original half-second capture, including its real page prefix."""
    return ledger.refresh_observations(
        handle.owner, handle.port, history=TradeHistoryRequest("2026-10-23", "2026-10-24", 3),
        ledger=LedgerRequest("2026-10-23", "2026-10-24"), timeout_seconds=0.5,
    )


@pytest.mark.parametrize("change", ["unchanged", "port", "principal", "account", "generation"])
def test_queued_read_checks_current_authority_after_transport_wait(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    """Retired queued reads never invoke; an unchanged queued read really does.

    Args:
        bound: Real registry, credential and read-owner fixture.
        tmp_path: Disposable synthetic state.
        monkeypatch: Scoped external transport injection.
        change: The independent authority dimension changed while queued.
    """
    s = _sdk(monkeypatch, True)
    h = bound(s.adapter)
    pool = ThreadPoolExecutor(max_workers=2)
    first = pool.submit(asyncio.run, h.port.trade_history(TradeHistoryRequest("2026-10-23", "2026-10-24", 3)))
    second = None
    try:
        assert s.entered.wait(2)
        second = pool.submit(asyncio.run, h.port.trades())
        _queued_workers(s.adapter)
        assert not s.finished.is_set()
        if change == "port":
            assert h.owner.revoke(h.port)
        elif change == "principal":
            h.context[0] = replace(h.context[0], actor_id="different-actor")
        elif change in {"account", "generation"}:
            from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot
            from flinttrade_gateway.brokers._base import Session
            from flinttrade_gateway.registry import ManagedSessionAuthority

            workspace = read_workspace_snapshot(h.workspace_path)
            authority = ManagedSessionAuthority(h.store.selector_state(h.selector).version, workspace.version,
                                                broker_workspace_version(workspace))
            session = Session("synthetic-successor", time.time() + 3600,
                              "nativecase" if change == "account" else "NativeCase", "dhan")
            receipt = h.publisher.prepare_session_candidate(
                h.selector, session, expected_registry=h.registry.snapshot_selector(h.selector),
                authority=authority, broker="dhan", label="Synthetic successor", client=object(),
            )
            h.publisher.publish_prepared_candidate(receipt, current_authority=authority)
        before = tuple(s.calls)
        s.release.set()
        first.result(timeout=0.75)
        outcome = second.result(timeout=0.75)
        if change == "unchanged":
            assert isinstance(outcome, BrokerReadSuccess)
            assert s.calls == [*before, "https://api.dhan.co/v2/trades/"]
        else:
            assert isinstance(outcome, BrokerReadFailure)
            assert tuple(s.calls) == before
        assert h.owner.close(timeout=1)
    finally:
        s.release.set()
        pool.shutdown(wait=True)
        assert h.owner.close(timeout=2)
        s.sdk.dhan_http.session.close()


@pytest.mark.parametrize("executor_queue", [False, True])
def test_expired_queued_read_refuses_without_owner_retirement(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, executor_queue: bool,
) -> None:
    """Prove the original deadline alone stops the queued invocation.

    Args:
        bound: Real registry-bound read owner.
        tmp_path: Disposable ledger directory.
        monkeypatch: Scoped inert installed-SDK transport.
        executor_queue: Queue in the real executor rather than at the transport lock.
    """
    executor = None
    if executor_queue:
        from flinttrade_gateway.read_frontier import ReadContinuation

        original = ReadContinuation.__init__
        executor = ThreadPoolExecutor(max_workers=1)

        def initialise(continuation: ReadContinuation) -> None:
            original(continuation)
            # Installed before the first actual task is scheduled. The ordinary
            # loop owner, not the observer, still shuts down this executor.
            continuation.loop.call_soon_threadsafe(continuation.loop.set_default_executor, executor)

        monkeypatch.setattr(ReadContinuation, "__init__", initialise)
    s = _sdk(monkeypatch, True)
    h = bound(s.adapter)
    ledgers = [OrderLifecycleLedger(ledger_path=tmp_path / f"{index}.db") for index in range(2)]
    pool = ThreadPoolExecutor(max_workers=2)
    futures = [pool.submit(asyncio.run, _capture(ledgers[0], h))]
    try:
        assert s.entered.wait(2)
        futures.append(pool.submit(asyncio.run, _capture(ledgers[1], h)))
        if executor_queue:
            assert executor is not None
            deadline = time.monotonic() + 0.25
            while executor._work_queue.qsize() != 1 and time.monotonic() < deadline:
                time.sleep(0.001)
            assert executor._work_queue.qsize() == 1
            assert len(h.owner._observation_tasks) == 2
        else:
            _queued_workers(s.adapter)
        done, _ = wait(futures, timeout=0.75)
        assert len(done) == 2 and not s.finished.is_set()
        results = [future.result() for future in futures]
        assert not isinstance(h.owner.observation_binding(h.port), BrokerReadFailure)
        before = tuple(s.calls)
        assert len(h.owner._observation_tasks) == 2
        s.release.set()
        deadline = time.monotonic() + 0.75
        # Observe actual completion before any close/revoke; no owner pre-drain
        # is used in the separate normal-factory cleanup control below.
        while h.owner._observation_tasks and time.monotonic() < deadline:
            time.sleep(0.001)
        assert not h.owner._observation_tasks and h.owner._active == 0
        assert not isinstance(h.owner.observation_binding(h.port), BrokerReadFailure)
        assert tuple(s.calls) == before
        assert [ledger.observation_snapshot(h.selector) for ledger in ledgers] == results
    finally:
        s.release.set()
        pool.shutdown(wait=True)
        assert h.owner.close(timeout=2)
        s.sdk.dhan_http.session.close()


@pytest.mark.parametrize("held", [False, True])
def test_normal_factory_default_callers_return_and_retry_original_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_lease_factory: Callable[..., object], held: bool,
) -> None:
    """Bound ordinary callers, queued SDK invocation and same-owner cleanup.

    Args:
        tmp_path: Fresh synthetic factory workspace and ledgers.
        monkeypatch: Scoped inert transport and SDK construction injection.
        backend_lease_factory: Ordinary owned disposable backend proof.
        held: Independent genuine unheld positive versus retained transport.
    """
    from flinttrade_core.desktop import DesktopBackendShutdownIncomplete

    s = _sdk(monkeypatch, held)
    client = BrokerClient()
    h = _factory_bound(s.sdk, client, tmp_path / "factory", monkeypatch, backend_lease_factory)
    assert len(s.profiles) == 1
    adapter = h.app.extensions["flinttrade.account_setup"].drivers["dhan"].adapter
    ledgers = [OrderLifecycleLedger(ledger_path=tmp_path / f"{index}.db") for index in range(2)]
    pool = ThreadPoolExecutor(max_workers=2)
    futures = [pool.submit(asyncio.run, _capture(ledgers[0], h))]
    try:
        assert s.entered.wait(2)
        # The second operation is an ordinary daily capture. Keep the factory's
        # real data quota; no budget override is needed to queue this resource.
        futures.append(pool.submit(asyncio.run, ledgers[1].refresh_observations(
            h.owner, h.port, timeout_seconds=0.5,
        )))
        if held:
            _queued_workers(adapter)
        done, _ = wait(futures, timeout=0.75)
        assert len(done) == 2, "ordinary asyncio.run callers still depend on a held SDK worker"
        results = [future.result() for future in futures]
        continuation = h.owner._continuation
        assert continuation is not None
        if held:
            assert not s.finished.is_set()
            assert len(h.owner._observation_tasks) == 2
            before = tuple(s.calls)
            with pytest.raises(DesktopBackendShutdownIncomplete):
                h.cleanup.release(deadline=time.monotonic() + 0.1)
            assert h.app.extensions["flinttrade_broker_dependencies_draining"] is h.dependencies
            assert continuation._thread.is_alive() and not continuation.loop.is_closed()
            assert not client._closed and client._thread is None
            s.release.set()
            # Do not pre-drain the read owner or replace the factory continuation.
            h.cleanup.release(deadline=time.monotonic() + 10)
            assert tuple(s.calls) == before
        else:
            expected = ["https://api.dhan.co/v2/trades/",
                        "https://api.dhan.co/v2/trades/2026-10-23/2026-10-24/0",
                        "https://api.dhan.co/v2/trades/2026-10-23/2026-10-24/1",
                        "https://api.dhan.co/v2/ledger?from-date=2026-10-23&to-date=2026-10-24"]
            assert Counter(s.calls) == Counter([*expected, "https://api.dhan.co/v2/trades/"]), (
                s.times, [[(c.resource, c.availability, c.issues) for c in result.coverage] for result in results]
            )
            h.cleanup.release(deadline=time.monotonic() + 10)
        assert [ledger.observation_snapshot(h.selector) for ledger in ledgers] == results
        assert h.owner._active == 0 and not h.owner._observation_tasks
        assert h.owner._continuation is continuation
        assert continuation.loop.is_closed() and not continuation._thread.is_alive()
        assert client._closed and client._loop is None and client._thread is None
    finally:
        s.release.set()
        pool.shutdown(wait=True)
        h.cleanup.release(deadline=time.monotonic() + 10)
        s.sdk.dhan_http.session.close()
