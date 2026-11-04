"""Real SDK deadline and retained-worker custody with inert HTTP transport."""

from __future__ import annotations


import importlib.util
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from flinttrade_core.broker_client import BrokerClient
from flinttrade_core.broker_read_port import BrokerReadFailure, ExactReadTarget, LedgerRequest, TradeHistoryRequest
from flinttrade_engine.local_state_provider import OrderLifecycleLedger

_spec = importlib.util.spec_from_file_location(
    "_canonical_custody_fixture", Path(__file__).with_name("test_canonical_broker_observations.py")
)
assert _spec is not None and _spec.loader is not None
_fixture = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _fixture
_spec.loader.exec_module(_fixture)
bound = _fixture.bound
pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _synthetic_auth_state(tmp_path: Path) -> Iterator[None]:
    """Keep normal factory authentication in a fresh synthetic store.

    Args:
        tmp_path: Disposable test directory.

    Yields:
        No policy override; only the ordinary auth store's test binding.
    """
    from flinttrade_core import auth_state

    auth_state.reset_singleton_for_tests()
    auth_state.get_auth_state(db_path=tmp_path / "auth-state.sqlite")
    try:
        yield
    finally:
        auth_state.reset_singleton_for_tests()


def _native_trade() -> dict[str, str]:
    return {
        "dhanClientId": "NativeCase", "orderId": "OrderAa", "exchangeTradeId": "FillAa",
        "exchangeOrderId": "ExchangeAa", "tradingSymbol": "SYNTHETIC-OPTION", "securityId": "TokenAa",
        "exchangeSegment": "NSE_FNO", "productType": "MARGIN", "transactionType": "BUY",
        "tradedQuantity": "1", "tradedPrice": "12.50", "exchangeTime": "2026-10-23 10:00:00",
    }


def _factory_bound(
    sdk: Any, client: BrokerClient, path: Path, monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory: Callable[..., object],
) -> SimpleNamespace:
    """Bind through ordinary factory enrolment with only inert SDK transport.

    Args:
        sdk: Installed SDK whose actual HTTP transport is test-owned.
        client: The application's real persistent client component.
        path: Fresh synthetic workspace, never an operator account.
        monkeypatch: Scoped injection of the SDK constructor only.
        backend_lease_factory: Normal disposable backend proof issuer.

    Returns:
        The factory's original cleanup/read owners and their bound port.
    """
    from flinttrade_core import app as app_api, auth_routes
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
    from flinttrade_core.workspace_migrations import compare_and_swap_workspace
    from flinttrade_engine.request_context import RequestContext
    from flinttrade_gateway.brokers import dhan as dhan_api

    import requests

    path.mkdir(mode=0o700)

    def profile_transport(session: object, request: requests.PreparedRequest, **kwargs: object) -> requests.Response:
        assert (request.method, request.url) == ("GET", "https://api.dhan.co/v2/profile")
        observed = sdk.dhan_http.session.request(request.method, request.url)
        response = requests.Response()
        response.status_code = observed.status_code
        response._content = observed.content
        return response

    monkeypatch.setattr(requests.Session, "send", profile_transport)

    def configure(config: dict) -> None:
        config["brokers"]["account_acls"] = {"dhan": {"NativeCase": ["actor"]}}

    compare_and_swap_workspace(path, None, configure)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(path))
    monkeypatch.setattr(app_api, "_get_master_password", lambda: "synthetic-password")
    monkeypatch.setattr(dhan_api, "_build_dhan_client", lambda *_: sdk)
    app = app_api.create_flask_app(client=client, backend_lease_proof=backend_lease_factory())
    cleanup = _DesktopShutdownRecoveryOwner(app, borrowed_keys=frozenset())
    try:
        app.config["AUTH_SERVICE"].setup_account("actor", "actor@example.test", "synthetic-password")
        with app.app_context():
            token = auth_routes._create_token("actor", mode="explore")
        response = app.test_client().post(
            "/api/v1/native/accounts",
            json={"adapter_id": "dhan", "account_id": "NativeCase",
                  "credentials": {"client_id": "NativeCase", "access_token": "synthetic-token"}},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200, response.json
        assert response.json["receipt"]["state"] == "committed"
        assert response.json["runtimeStatus"] == "session_present"
        dependencies = app.extensions["flinttrade_broker_dependencies"]
        owner = dependencies.read_owner
        assert owner is app.extensions["flinttrade.account_setup"].runtime.read_owner
        selector = BrokerSelector("dhan", "NativeCase")
        context = [RequestContext("jti", "human", "actor", "practice", selector="dhan:NativeCase")]
        port = owner.bind(target=ExactReadTarget(selector), verify_current_authority=lambda: context[0])
        assert not isinstance(port, BrokerReadFailure)
        return SimpleNamespace(app=app, cleanup=cleanup, dependencies=dependencies, owner=owner, port=port,
                               selector=selector, context=context, workspace_path=path)
    except BaseException:
        cleanup.release(deadline=time.monotonic() + 10)
        raise


@pytest.mark.parametrize("factory", [False, True])
@pytest.mark.parametrize("held", [False, True])
def test_sdk_capture_bounds_wait_without_releasing_worker_custody(
    bound: Callable[..., SimpleNamespace], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    backend_lease_factory: Callable[..., object], factory: bool, held: bool
) -> None:
    """Return a bounded prefix while the actual worker remains owned until retry.

    Args:
        bound: Real registry/read-owner fixture with inert synthetic accounts.
        tmp_path: Disposable ledger directory.
        monkeypatch: Scoped external-transport and factory adapter injection.
        backend_lease_factory: Existing disposable backend ownership proof.
        factory: Exercise normal application construction and cleanup if true.
        held: Hold the actual SDK transport after its accepted first page.
    """
    from dhanhq import DhanContext, dhanhq
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    sdk = dhanhq(DhanContext("NativeCase", "synthetic-token"))
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls: list[str] = []
    profile_calls: list[str] = []

    def transport(method: str, url: str, **kwargs: object) -> SimpleNamespace:
        if url.endswith("/profile"):
            assert method == "GET"
            profile_calls.append(url)
            expiry = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)
            return SimpleNamespace(status_code=200, content=json.dumps({
                "dhanClientId": "NativeCase", "tokenValidity": expiry.strftime("%d/%m/%Y %H:%M"),
            }).encode())
        calls.append(url)
        if url.endswith("/1"):
            entered.set()
            try:
                if held:
                    assert release.wait(5)
            finally:
                finished.set()
        rows = [_native_trade()] if url.endswith("/0") else []
        return SimpleNamespace(status_code=200, content=json.dumps(rows).encode())

    monkeypatch.setattr(sdk.dhan_http.session, "request", transport)
    adapter = DhanAdapter(client_factory=lambda _: sdk)
    client = BrokerClient()
    cleanup = None
    app = None
    executor = ThreadPoolExecutor(max_workers=1)
    pending = None
    try:
        if factory:
            handle = _factory_bound(
                sdk, client, tmp_path / "factory", monkeypatch, backend_lease_factory,
            )
            app, cleanup, dependencies = handle.app, handle.cleanup, handle.dependencies
            assert len(profile_calls) == 1
        else:
            handle = bound(adapter)
            assert profile_calls == []
        owner, port = handle.owner, handle.port
        ledger = OrderLifecycleLedger(ledger_path=tmp_path / "ledger.db")
        attempt = ledger.prepare_dispatch(
            adapter_id="dhan", account_id=handle.selector.account_id,
            operation="place_order", request_context=handle.context[0],
            payload={"symbol": "SYNTHETIC", "exchange": "NFO", "product": "NRML", "action": "BUY", "quantity": 1},
        )
        ledger.mark_invoked(attempt)
        ledger.mark_outcome_unknown(attempt, error_kind="synthetic_unknown")
        pending = executor.submit(
            client.run_sync,
            ledger.refresh_observations(
                owner, port, history=TradeHistoryRequest("2026-10-23", "2026-10-24", 3),
                ledger=LedgerRequest("2026-10-23", "2026-10-24"), timeout_seconds=0.5,
            ),
            2.0,
        )
        assert entered.wait(2)
        # This does not cancel, drain or rescue the worker before measurement.
        result = pending.result(timeout=0.75)
        assert len(result.unallocated_trades) == 1 and not result.fills
        history = next(row for row in result.coverage if row.resource == "trades.history")
        assert not result.admission_available
        assert ledger.list_unresolved_outcomes()[0]["attempt_id"] == attempt
        if held:
            assert not finished.is_set()
            assert len(calls) == 3
            assert next(row for row in result.coverage if row.resource == "ledger.account_postings").availability == (
                "provider_failure"
            )
            assert history.pages == (0,) and history.availability == "provider_failure"
            assert "read_deadline_exceeded" in history.issues
            before_calls = list(calls)
            if cleanup is not None:
                from flinttrade_core.desktop import DesktopBackendShutdownIncomplete

                assert app is not None
                with pytest.raises(DesktopBackendShutdownIncomplete):
                    cleanup.release(deadline=time.monotonic() + 0.1)
                assert app.extensions["flinttrade_broker_dependencies_draining"] is dependencies
                assert not client._closed and client._thread.is_alive()
            else:
                assert not owner.close(timeout=0.1)
            assert not finished.is_set() and calls == before_calls
            release.set()
            assert finished.wait(2)
            if cleanup is not None:
                # Retry the original factory owner directly; an observer must
                # not pre-drain the read owner and repair cleanup on its behalf.
                cleanup.release(deadline=time.monotonic() + 10)
                assert client._loop.is_closed() and not client._thread.is_alive()
            else:
                assert owner.close(timeout=1)
            assert ledger.observation_snapshot(handle.selector) == result
            assert calls == before_calls  # No page two, retry or late publication.
        else:
            assert finished.is_set()
            assert len(calls) == 4
            assert history.pages == (0, 1) and history.availability == "available"
        assert ledger.list_unresolved_outcomes()[0]["attempt_id"] == attempt
    finally:
        release.set()
        if pending is not None:
            try:
                pending.result(timeout=3)
            except Exception:
                pass  # Preserve the body failure; the exact owned worker is rescued below.
        executor.shutdown(wait=True)
        if cleanup is not None:
            cleanup.release(deadline=time.monotonic() + 10)
        client.close_sync()
        sdk.dhan_http.session.close()
    assert client._loop is None or client._loop.is_closed()
    assert client._thread is None or not client._thread.is_alive()
