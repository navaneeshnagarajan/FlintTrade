"""Normal full-factory boot on real loopback, with no broker/session enablement.

The authorised seams are FlintTradeApp.start/stop, the kernel backend lease and
HTTP responses from the installed Waitress listener. Only external transports
are stubbed; factory, safety, schedulers, registry and shutdown remain real.
Removing PYTEST_CURRENT_TEST also exercises the ordinary instrument-master
worker, which fixture-only lifecycle tests deliberately do not start.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, closing
import errno
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import re
import select
import socket
import sys
import threading
from typing import Any
import urllib.error
import urllib.request

import httpx
import pytest
import requests.adapters

pytestmark = pytest.mark.integration


@pytest.fixture
def offline_startup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Any]]:
    """Seed private state and fail closed on any unregistered external call."""
    from flinttrade_core.secure_file import write_secret_text

    root = Path(__file__).resolve().parents[4]
    assert not (root / ".env").exists(), "Normal startup must not load an operator .env"
    source_paths = [
        Path(__file__).resolve(),
        *(root / "packages/core/core/src/flinttrade_core" / name for name in ("app.py", "instrument_lot_master.py")),
    ]

    def source_identity() -> dict[str, str]:
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}

    before = source_identity()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_secret_text(workspace / "master_password", "pytest-master-password")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FLINTTRADE_INSTALLATION_STATE_DIR", str(tmp_path / "installation"))
    monkeypatch.setenv("DUCKDB_PATH", str(workspace / "data/flint.duckdb"))
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # No API key, broker secrets, downloaded inference runtime or operator home
    # is supplied. The namespace launcher owns the outer security boundary.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    monkeypatch.setenv("FLINTTRADE_BACKEND_PORT", str(port))
    monkeypatch.setenv("FLINTTRADE_BACKEND_HOST", "127.0.0.1")
    ledger: dict[str, Any] = {
        "workspace": str(workspace),
        "port": port,
        "public_master_calls": [],
        "unexpected": [],
        "route_inventory": str(tmp_path / "route-inventory.json"),
    }

    def refuse(kind: str, target: object) -> None:
        ledger["unexpected"].append({"transport": kind, "target": str(target)})
        raise AssertionError(f"Unregistered external transport: {kind} {target}")

    def urlopen(request: Any, *_args: Any, **_kwargs: Any) -> Any:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if url == "https://images.dhan.co/api-data/api-scrip-master.csv" or re.fullmatch(
            r"https://lapi\.kotaksecurities\.com/wso2-scripmaster/v1/prod/\d{4}-\d{2}-\d{2}/transformed/nse_fo\.csv",
            url,
        ):
            # Exercise the real offline fallback, never supply made-up contracts.
            ledger["public_master_calls"].append(url)
            raise urllib.error.URLError("synthetic offline public-master transport")
        refuse("urllib", url)

    def sync_http(_transport: Any, request: Any) -> Any:
        refuse("httpx", request.url)

    async def async_http(_transport: Any, request: Any) -> Any:
        refuse("httpx-async", request.url)

    def requests_send(_adapter: Any, request: Any, **_kwargs: Any) -> Any:
        refuse("requests", request.url)

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def allowed(address: Any) -> bool:
        return not isinstance(address, tuple) or address[0] in {"127.0.0.1", "::1", "localhost"}

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if not allowed(address):
            refuse("socket", address)
        return connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> Any:
        if not allowed(address):
            refuse("socket-connect-ex", address)
        return connect_ex(sock, address)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_http)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_http)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", requests_send)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    try:
        yield ledger
    finally:
        after = source_identity()
        _emit("owned-source", before=before, after=after, source_changed=before != after)
        assert before == after, "The exercised smoke/lifecycle sources changed during this test"


def _emit(stage: str, **values: Any) -> None:
    print("NORMAL_RUNTIME_SMOKE " + json.dumps({"stage": stage, **values}, sort_keys=True), flush=True)


def _request(port: int, method: str, path: str, *, token: str = "", body: Any = None) -> dict[str, Any]:
    """Reach the real listener; neither Flask.test_client nor a fixture handler."""
    headers = {"Connection": "close"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        return {"method": method, "path": path, "status": response.status, "body": payload}


async def _wait_started(start: asyncio.Task[None], reached: asyncio.Event) -> None:
    waiter = asyncio.create_task(reached.wait())
    try:
        done, _ = await asyncio.wait({start, waiter}, timeout=30, return_when=asyncio.FIRST_COMPLETED)
        if start in done:
            await start
            pytest.fail("Normal runtime returned before readiness")
        assert waiter in done, "Normal startup did not reach its real shutdown-wait boundary"
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


def _owned_threads(baseline: set[threading.Thread]) -> list[threading.Thread]:
    # asyncio.to_thread workers belong to pytest's event loop, not the runtime;
    # they are disposed by that loop after the test. All product threads count.
    return [
        thread for thread in threading.enumerate() if thread not in baseline and not thread.name.startswith("asyncio_")
    ]


async def _assert_released(runtime: Any, listener: Any, lease: Any, threads: list[threading.Thread], port: int) -> None:
    from flinttrade_core.backend_instance import (
        BackendLeaseUnavailable,
        acquire_backend_instance_lease,
        require_backend_lease_proof,
    )

    assert runtime._stop_completed is True
    assert runtime._startup_recovery_pending is False
    assert runtime._shutdown_sync_workers == {}
    assert runtime._shutdown_async_tasks == {}
    assert runtime._holiday_refresh_task is None
    assert runtime._reconciliation_task is None
    assert runtime._flask_server_owner is None
    assert not listener.thread.is_alive()
    assert listener._dispatcher.threads == set()
    # A closed TCP acceptor is stronger evidence than a stopped-thread flag.
    with socket.socket() as probe:
        probe.settimeout(1)
        assert probe.connect_ex(("127.0.0.1", port)) == errno.ECONNREFUSED
    proof = lease.proof
    lease.release()
    with pytest.raises(BackendLeaseUnavailable):
        require_backend_lease_proof(proof)
    replacement = acquire_backend_instance_lease()
    try:
        assert replacement.proof.incarnation != proof.incarnation
    finally:
        replacement.release()
    for thread in threads:
        await asyncio.to_thread(thread.join, 1)
    alive = [thread.name for thread in threads if thread.is_alive()]
    _emit(
        "released",
        listener_alive=listener.thread.is_alive(),
        owned_threads_alive=alive,
        backend_lease_reacquired=True,
        waiters_remaining=False,
    )
    assert alive == [], f"Normal stop leaked owned workers: {alive}"


@pytest.mark.asyncio
async def test_normal_factory_runtime_readiness_refusal_and_clean_stop(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """An ordinary no-account process serves recovery UI without trading authority."""
    import flinttrade_core.app as app_module
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease
    from flinttrade_core.health_routes import reset_health_singletons_for_tests

    baseline = set(threading.enumerate())
    # Pytest re-publishes this variable when the fixture enters its call phase.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    reset_health_singletons_for_tests()
    runtime = app_module.FlintTradeApp()
    reached = asyncio.Event()
    real_wait = runtime._wait_for_shutdown_result

    async def observe_startup() -> None:
        reached.set()
        await real_wait()

    monkeypatch.setattr(runtime, "_wait_for_shutdown_result", observe_startup)
    lease = acquire_backend_instance_lease()
    runtime._backend_lease_proof = lease.proof
    start = asyncio.create_task(runtime.start())
    listener = None
    try:
        await _wait_started(start, reached)
        flask_app = runtime._flask_app
        listener = runtime._flask_server_owner
        assert flask_app is not None and listener is not None
        assert listener.thread.is_alive() and listener.thread.daemon is False
        assert type(listener._server).__module__.startswith("waitress.")
        assert listener._server.socket.getsockname() == ("127.0.0.1", offline_startup["port"])
        assert listener._server.socket.fileno() >= offline_startup.get("minimum_listener_fd", 0)
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        assert runtime.registry.list_accounts() == []
        assert runtime.registry.list_sessions() == []
        assert flask_app.config["NATIVE_ADAPTERS"] == {}
        assert flask_app.config["BROKER_ROUTER"] is None
        assert flask_app.config["SAFETY"] is runtime.safety
        assert runtime.safety.order_reservations_durable is True
        for name in (
            "BACKEND_LEASE_READY",
            "SAFETY_CONFIG_READY",
            "EMERGENCY_INTENT_JOURNAL_READY",
            "DAILY_PNL_STATE_READY",
        ):
            assert flask_app.config[name] is True
        assert runtime.safety.runtime_loop_ready is True
        assert runtime._calendar_loaded is False
        assert runtime._calendar_schedulers_started is True
        routes = sorted(
            [
                {"path": rule.rule, "methods": sorted(rule.methods), "endpoint": rule.endpoint}
                for rule in flask_app.url_map.iter_rules()
            ],
            key=lambda rule: (rule["path"], rule["endpoint"]),
        )
        by_path = {rule["path"]: rule for rule in routes}
        for path in ("/api/v1/ping", "/healthz", "/readyz", "/api/v1/orders/place", "/api/v1/orders/forever"):
            assert path in by_path
        await asyncio.to_thread(
            Path(offline_startup["route_inventory"]).write_text,
            json.dumps(routes, indent=2) + "\n",
            encoding="utf-8",
        )
        _emit(
            "started",
            python=sys.version,
            executable=sys.executable,
            app_source=app_module.__file__,
            waitress=importlib.metadata.version("waitress"),
            listener_fd=listener._server.socket.fileno(),
            route_count=len(routes),
            route_inventory=offline_startup["route_inventory"],
            owned_threads=[thread.name for thread in _owned_threads(baseline)],
            registry_accounts=0,
            native_adapters=[],
            broker_router_published=False,
            durable_safety=True,
            live_loop_bound=True,
            calendar_authoritative=False,
        )
        port = offline_startup["port"]
        with flask_app.app_context():
            locked_live = _create_token("startup-smoke", mode="live")
            explore = _create_token("startup-smoke", mode="explore")
        replies = []
        for path in ("/api/v1/ping", "/healthz", "/readyz"):
            replies.append(await asyncio.to_thread(_request, port, "GET", path))
        for path in ("/health", "/health/detail"):
            replies.append(await asyncio.to_thread(_request, port, "GET", path, token=locked_live))
        assert [reply["status"] for reply in replies] == [200, 200, 200, 200, 200], replies
        assert replies[0]["body"]["laya"] == "down"
        assert replies[0]["body"]["laya_live_qualified"] is False
        assert replies[2]["body"] == {"status": "ready"}
        assert replies[3]["body"]["status"] == "healthy"
        unauthenticated = await asyncio.to_thread(_request, port, "GET", "/api/v1/orders/forever")
        assert unauthenticated["status"] == 401
        replies.append(unauthenticated)
        gtt = await asyncio.to_thread(
            _request,
            port,
            "POST",
            "/api/v1/orders/place",
            token=locked_live,
            body={"variety": "gtt", "symbol": "SYNTHETIC", "quantity": 1},
        )
        assert gtt["status"] == 422 and gtt["body"]["code"] == "gtt_unsupported", gtt
        replies.append(gtt)
        for suffix in ("forever", "super", "triggers"):
            frozen = await asyncio.to_thread(_request, port, "GET", f"/api/v1/orders/{suffix}", token=locked_live)
            assert frozen["status"] == 409, frozen
            assert frozen["body"]["message"] == "Native broker HTTP reads are unavailable until the read cutover"
            replies.append(frozen)
        locked = await asyncio.to_thread(
            _request,
            port,
            "POST",
            "/api/v1/orders/place",
            token=locked_live,
            body={"symbol": "SYNTHETIC", "quantity": 1},
        )
        assert locked["status"] == 403 and "verify PIN" in locked["body"]["message"], locked
        replies.append(locked)
        mode_blocked = await asyncio.to_thread(_request, port, "GET", "/api/v1/orders/forever", token=explore)
        assert mode_blocked["status"] == 403 and "live mode only" in mode_blocked["body"]["message"], mode_blocked
        replies.append(mode_blocked)
        _emit("http", replies=replies)
        threads = _owned_threads(baseline)
        assert any(thread.name == "instrument-master-refresh" for thread in threads)
        await runtime.stop(timeout=30)
        await asyncio.wait_for(start, timeout=5)
        rejected = flask_app.test_client().get("/api/v1/ping")
        assert rejected.status_code == 503 and rejected.json["message"] == "Application is shutting down"
        await _assert_released(runtime, listener, lease, threads, port)
        assert offline_startup["public_master_calls"]
        assert offline_startup["unexpected"] == []
        _emit("transport", **offline_startup)
    finally:
        if not runtime._stop_completed:
            await runtime.stop(timeout=30)
        if not start.done():
            await asyncio.wait_for(start, timeout=5)
        lease.release()
        reset_health_singletons_for_tests()


@pytest.mark.asyncio
async def test_normal_factory_runtime_with_an_existing_descriptor_owner(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """Another resource owner's descriptors cannot kill or be stolen by startup.

    Reuse the complete normal start/HTTP/refusal/stop control above, not a fake
    listener. On poll-capable platforms the prior owner fills the descriptor
    range used by select(); other platforms still exercise resource ownership
    and the complete listener lifecycle without imposing POSIX descriptor limits.
    """
    import flinttrade_core.app as app_module

    high_descriptors = hasattr(select, "poll")
    normal_factory = app_module.create_flask_app
    descriptors = []
    owned_fds: list[int] = []
    with ExitStack() as prior_owner:

        def hold_descriptor() -> Any:
            descriptor = prior_owner.enter_context(open(os.devnull, "rb"))
            descriptors.append(descriptor)
            return descriptor

        hold_descriptor()

        def observe_factory(*args: Any, **kwargs: Any) -> Any:
            flask_app = normal_factory(*args, **kwargs)
            # Real factory construction can collect earlier apps and free low
            # descriptor slots. Fill them at this public return boundary so the
            # forthcoming real listener must actually use a high descriptor.
            descriptor = hold_descriptor()
            if high_descriptors:
                while descriptor.fileno() < 1024:
                    descriptor = hold_descriptor()
                assert descriptor.fileno() >= 1024
                offline_startup["minimum_listener_fd"] = 1024
            owned_fds[:] = [item.fileno() for item in descriptors]
            _emit(
                "prior-descriptor-owner",
                high_descriptors=high_descriptors,
                highest_owned_fd=descriptor.fileno(),
                descriptor_count=len(descriptors),
            )
            return flask_app

        monkeypatch.setattr(app_module, "create_flask_app", observe_factory)
        await test_normal_factory_runtime_readiness_refusal_and_clean_stop(monkeypatch, offline_startup)
        assert [item.fileno() for item in descriptors] == owned_fds
        assert all(item.read(1) == b"" for item in descriptors)
    assert all(item.closed for item in descriptors)


@pytest.mark.asyncio
async def test_normal_factory_startup_failure_rolls_back_listener_and_workers(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """A failure after the real listener/schedulers cannot orphan their owners."""
    from flinttrade_core.app import FlintTradeApp
    from flinttrade_core.backend_instance import acquire_backend_instance_lease

    baseline = set(threading.enumerate())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    runtime = FlintTradeApp()
    reached = asyncio.Event()
    fail = asyncio.Event()

    async def inject_after_startup() -> None:
        reached.set()
        await fail.wait()
        raise RuntimeError("injected after normal factory/listener/schedulers")

    monkeypatch.setattr(runtime, "_wait_for_shutdown_result", inject_after_startup)
    lease = acquire_backend_instance_lease()
    runtime._backend_lease_proof = lease.proof
    start = asyncio.create_task(runtime.start())
    try:
        await _wait_started(start, reached)
        listener = runtime._flask_server_owner
        flask_app = runtime._flask_app
        assert listener is not None and flask_app is not None
        port = offline_startup["port"]
        ping = await asyncio.to_thread(_request, port, "GET", "/api/v1/ping")
        assert ping["status"] == 200 and ping["body"]["laya_live_qualified"] is False
        threads = _owned_threads(baseline)
        assert any(thread.name == "instrument-master-refresh" for thread in threads)
        _emit("rollback-control-started", ping=ping, owned_threads=[thread.name for thread in threads])
        fail.set()
        with pytest.raises(RuntimeError, match="injected after normal factory/listener/schedulers"):
            await asyncio.wait_for(start, timeout=30)
        assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        assert runtime._flask_app is None
        assert runtime._startup_owner_ledger is None
        assert runtime._stop_event.is_set()
        await _assert_released(runtime, listener, lease, threads, port)
        assert offline_startup["public_master_calls"]
        assert offline_startup["unexpected"] == []
        _emit("rollback-control-complete", **offline_startup)
    finally:
        fail.set()
        await asyncio.gather(start, return_exceptions=True)
        if not runtime._stop_completed:
            await runtime.stop(timeout=30)
        lease.release()


@pytest.mark.asyncio
async def test_normal_stop_retains_a_blocked_public_master_owner_until_retry(
    monkeypatch: pytest.MonkeyPatch,
    offline_startup: dict[str, Any],
) -> None:
    """A real blocked transport cannot turn a shutdown timeout into release."""
    from flinttrade_core.app import FlintTradeApp
    from flinttrade_core.backend_instance import BackendInstanceAlreadyRunning, acquire_backend_instance_lease

    baseline = set(threading.enumerate())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    entered = threading.Event()
    release = threading.Event()
    urlopen = urllib.request.urlopen

    def held_download(request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.full_url == "https://images.dhan.co/api-data/api-scrip-master.csv":
            entered.set()
            if not release.wait(timeout=30):
                offline_startup["unexpected"].append({"transport": "held-download", "target": "release timed out"})
                raise AssertionError("The test did not release its owned transport")
        return urlopen(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", held_download)
    runtime = FlintTradeApp()
    reached = asyncio.Event()
    real_wait = runtime._wait_for_shutdown_result

    async def observe_startup() -> None:
        reached.set()
        await real_wait()

    monkeypatch.setattr(runtime, "_wait_for_shutdown_result", observe_startup)
    lease = acquire_backend_instance_lease()
    runtime._backend_lease_proof = lease.proof
    start = asyncio.create_task(runtime.start())
    try:
        await _wait_started(start, reached)
        assert await asyncio.to_thread(entered.wait, 5)
        flask_app = runtime._flask_app
        listener = runtime._flask_server_owner
        assert flask_app is not None and listener is not None
        owner = flask_app.config["INSTRUMENT_MASTER_REFRESH_OWNER"]
        threads = _owned_threads(baseline)
        with pytest.raises(RuntimeError, match="shutdown encountered errors"):
            await runtime.stop(timeout=0.05)
        with pytest.raises(RuntimeError, match="shutdown encountered errors"):
            await asyncio.wait_for(start, timeout=5)
        assert runtime._stop_completed is False
        assert owner.thread.is_alive()
        assert flask_app.config["INSTRUMENT_MASTER_REFRESH_OWNER"] is owner
        assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        with pytest.raises(BackendInstanceAlreadyRunning):
            acquire_backend_instance_lease()
        _emit(
            "timeout-retained",
            master_alive=owner.thread.is_alive(),
            stop_completed=runtime._stop_completed,
            backend_lease_contended=True,
            shutdown_workers=sorted(runtime._shutdown_sync_workers),
        )
        release.set()
        await runtime.stop(timeout=30)
        assert "INSTRUMENT_MASTER_REFRESH_OWNER" not in flask_app.config
        await _assert_released(runtime, listener, lease, threads, offline_startup["port"])
        assert offline_startup["unexpected"] == []
        _emit("timeout-retry-complete", **offline_startup)
    finally:
        release.set()
        if not runtime._stop_completed:
            await runtime.stop(timeout=30)
        await asyncio.gather(start, return_exceptions=True)
        lease.release()
