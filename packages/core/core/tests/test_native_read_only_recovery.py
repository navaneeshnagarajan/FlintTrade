"""Verified same-account recovery through the real normal-factory account lane.

Only external installed-SDK transport and explicitly labelled primitive source
facts are inert. Old pins and complete financial/model histories are retained.
"""
from __future__ import annotations
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4
import pytest
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, mounted_desk as mounted_desk
from packages.core.core.tests.test_native_financial_owner import (
    _source, _configure, _facts, _cash_filled, _qualify, _financial, RUN,
)

pytestmark = pytest.mark.integration


def test_P01_verified_same_account_recovery_preserves_cash_custody(mounted_desk: MountedDesk) -> None:
    """Provider identity permits reads, not new grants, pin rewrites or settlement."""
    desk = mounted_desk
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    _cash_filled(facts)
    source.publish("mounted-native", facts)
    before = _qualify(desk)
    financial = _financial(desk)
    key = str(uuid4())
    url = "/api/v1/native/accounts/dhan/Mounted/login"
    try:
        result = desk.client.post(url, json={}, headers={**desk.headers, "Idempotency-Key": key})
        assert result.status_code == 200, result.get_json()
        body = result.get_json()
        assert body["receipt"]["state"] == "committed", body
        assert body["runtimeStatus"] == "read_only_recovery", body
        assert body["recovery"]["readOnly"] and body["recovery"]["writeAuthority"] == "none"
        assert body["recovery"]["grantAuthority"] == "none" and body["recovery"]["reconciliationRequired"]
        assert body["recovery"]["census"]["complete"] is True
        assert body["recovery"]["census"]["runIds"] == ["mounted-native"]
        current = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert current["scope"] == before["scope"] and current["config"] == before["config"]
        assert current["effective_authority"] == "none" and current["entry_state"] == "retired"
        assert _financial(desk) == financial
        assert desk.client.post(url, json={}, headers={**desk.headers, "Idempotency-Key": key}).get_json() == body
        assert len(desk.transport.authentication_calls) == 2
        assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
    finally:
        # Restore only through an owner-issued read correspondence and genuine
        # synthetic lifetime settlement; recovery itself never releases duties.
        if len(desk.transport.authentication_calls) == 2:
            source.rebind_read_only_recovery("mounted-native")
        from packages.core.core.tests.test_native_financial_owner import _settle_cash
        _settle_cash(desk, source, facts)



@contextmanager
def _cash_duty(desk: MountedDesk) -> Iterator[tuple[Any, dict[str, Any], dict[str, Any]]]:
    """Acquire real synthetic duties and settle only through their retained owner."""
    from packages.core.core.tests.test_native_financial_owner import _settle_cash
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    _cash_filled(facts)
    source.publish("mounted-native", facts)
    before = _qualify(desk)
    try:
        yield source, facts, before
    finally:
        if desk.app.extensions["flinttrade_broker_dependencies"] is not source.dependencies:
            source.rebind_read_only_recovery("mounted-native")
        _settle_cash(desk, source, facts)


def _recover(desk: MountedDesk, *, key: str | None = None, account: str = "Mounted", body: Any = None) -> Any:
    """Invoke only the approved public RECONNECT route with an explicit operation ID."""
    return desk.client.post("/api/v1/native/accounts/dhan/" + account + "/login", json={} if body is None else body,
                            headers={**desk.headers, "Idempotency-Key": key or str(uuid4())})


def test_P02_options_unknown_model_cost_survives_read_only_recovery(mounted_desk: MountedDesk) -> None:
    """A completed producer is distinct from retained UNKNOWN service-account cost."""
    import httpx
    from flinttrade_core.service_usage_contracts import UsageAmounts
    from packages.core.core.tests.test_native_model_producer_v2 import model_desk
    from packages.core.core.tests.test_native_model_safety_v2 import _option_plan, _grant_model, _start, _status
    desk = mounted_desk
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        """Record the real task request then return an explicit external uncertainty."""
        calls.append(request)
        raise httpx.ReadError("synthetic unknown model receipt", request=request)

    source, registration = model_desk(desk, send, options=True)
    _option_plan(source, registration, mark="5")
    owner = _start(desk, _grant_model(desk, registration))
    assert owner.completed.wait(5) and owner.shutdown(0)
    before = _status(desk)
    attempt = before["model_calls"][0]["receipt"]["attempts"][0]
    assert attempt["state"] == "UNKNOWN"
    try:
        result = _recover(desk)
        assert (result.status_code == 200
                and result.get_json()["runtimeStatus"] == "read_only_recovery"), result.get_json()
        assert _status(desk)["model_calls"] == before["model_calls"]
        view = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert view["schema_version"] == "2-options-1" and view["duty"]["model_obligations"]
        assert len(calls) == 1 and not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
    finally:
        dispatcher = desk.app.config["MODEL_RUN_SERVICES"].dispatcher()
        dispatcher.ledger.reconcile(attempt["attempt_id"], UsageAmounts(
            requests=1, input_tokens=12, output_tokens=5, currency_micros=1),
            evidence="synthetic-complete-provider-usage-receipt")
        desk.app.config["EXECUTION_SESSIONS"].autonomy.v2.reconcile_model_calls(
            desk.headers["Authorization"][7:], "mounted-native")
    assert len(_status(desk)["model_calls"]) == 1
    assert desk.app.config["EXECUTION_SESSIONS"].shutdown(0)


def test_R03_incomplete_and_corrupt_custody_refuses_before_authentication(mounted_desk: MountedDesk) -> None:
    """Missing either member and a corrupt seal are not an empty native account."""
    desk = mounted_desk
    with _cash_duty(desk):
        root = desk.app.config["EXECUTION_SESSIONS"].path
        for name in ("autonomy.sqlite", "autonomy.sqlite.authority.json"):
            path, held = root / name, root / (name + ".held-for-negative-control")
            path.rename(held)
            try:
                result = _recover(desk)
                assert result.status_code == 503
                assert len(desk.transport.authentication_calls) == 1
            finally:
                held.rename(path)
        marker = root / "autonomy.sqlite.authority.json"
        original = marker.read_bytes()
        try:
            marker.write_bytes(b"corrupt-synthetic-authority")
            assert _recover(desk).status_code == 503
            assert len(desk.transport.authentication_calls) == 1
        finally:
            marker.write_bytes(original)


def test_R04_active_model_owner_prevents_replacement_until_same_owner_drains(mounted_desk: MountedDesk) -> None:
    """Retirement revokes future work but cannot replace an event-held actual model worker."""
    import threading
    import httpx
    from packages.core.core.tests.test_native_model_producer_v2 import model_desk, response
    from packages.core.core.tests.test_native_model_safety_v2 import _grant_model, _start, _status
    from packages.core.core.tests.test_native_producer_v2 import _plan
    desk = mounted_desk
    entered, release = threading.Event(), threading.Event()
    calls: list[httpx.Request] = []

    def send(request: httpx.Request) -> httpx.Response:
        """Hold the real external model request until the existing owner may complete."""
        calls.append(request)
        entered.set()
        assert release.wait(10)
        return response(request)

    source, registration = model_desk(desk, send)
    _plan(source, registration, mark="5")
    owner = _start(desk, _grant_model(desk, registration))
    try:
        assert entered.wait(5)
        count = len(desk.transport.authentication_calls)
        result = _recover(desk)
        assert result.status_code == 503, result.get_json()
        assert len(desk.transport.authentication_calls) == count
        assert desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"] is owner
        assert owner.snapshot()["alive"] and not owner.shutdown(0)
    finally:
        release.set()
        assert owner.completed.wait(5) and owner.shutdown(0)
    history = _status(desk)["model_calls"]
    result = _recover(desk)
    assert result.status_code == 200 and result.get_json()["runtimeStatus"] == "read_only_recovery", result.get_json()
    assert _status(desk)["model_calls"] == history and len(calls) == 1


def test_R05_foreign_execution_owner_never_substitutes_for_the_factory_custody(
    mounted_desk: MountedDesk, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, backend_lease_factory: Any,
) -> None:
    """A genuine second workspace's owner cannot substitute for this factory's custody."""
    from flinttrade_core.app import create_flask_app
    desk = mounted_desk
    with _cash_duty(desk):
        owner = desk.app.config["EXECUTION_SESSIONS"]
        original_workspace = desk.app.extensions["flinttrade.account_setup"].path
        foreign_path = tmp_path / "foreign-workspace"
        foreign_path.mkdir(mode=0o700)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(foreign_path))
        foreign = create_flask_app(backend_lease_proof=backend_lease_factory())
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(original_workspace))
        try:
            desk.app.config["EXECUTION_SESSIONS"] = foreign.config["EXECUTION_SESSIONS"]
            assert _recover(desk).status_code == 503
            assert len(desk.transport.authentication_calls) == 1
        finally:
            desk.app.config["EXECUTION_SESSIONS"] = owner
        assert _recover(desk).get_json()["runtimeStatus"] == "read_only_recovery"


def test_R07_recovery_replay_and_conflicting_key_do_not_authenticate(mounted_desk: MountedDesk) -> None:
    """Replay preserves the durable receipt; conflict is never fresh login authority."""
    desk = mounted_desk
    with _cash_duty(desk):
        key = str(uuid4())
        body = _recover(desk, key=key).get_json()
        assert body["runtimeStatus"] == "read_only_recovery"
        assert _recover(desk, key=key).get_json() == body
        conflicting = _recover(desk, key=key, body={"credentials": {"client_id": "Mounted", "access_token": "changed"}})
        assert conflicting.status_code == 409
        assert len(desk.transport.authentication_calls) == 2


def test_R08_recovered_session_never_grants_or_rearms_old_or_new_runs(mounted_desk: MountedDesk) -> None:
    """Read-only restriction is lifetime-scoped, not a timer that restores writes."""
    from flinttrade_core.broker_identity import BrokerSelector
    desk = mounted_desk
    with _cash_duty(desk) as (_source_owner, _facts_owner, before):
        assert _recover(desk).get_json()["runtimeStatus"] == "read_only_recovery"
        setup = desk.app.extensions["flinttrade.account_setup"]
        target = BrokerSelector("dhan", "Mounted")
        authority = setup.runtime._provider.current_authority_for(target)
        handle = setup.registry.get_connected_session_for(target, current_authority=authority)
        assert handle.is_read_only
        for action, body in (("start", {"schema_version": "2", "run_id": "mounted-native",
                "expected_binding_revision": before["scope"]["binding_revision"],
                "grant_ref": {"id": "old", "revision": "0" * 64}}),
                ("grant", {}), ("transfer-accept", {})):
            assert desk.client.post(RUN + "/autonomy-v2/" + action, json=body, headers=desk.headers).status_code == 409
        assert desk.client.post("/api/v1/placeorder", headers=desk.headers, json={
            "broker": "dhan", "account_id": "Mounted",
            "symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY", "quantity": "1",
            "price": "4", "pricetype": "LIMIT"}).status_code != 200
        assert len(desk.transport.authentication_calls) == 2 and desk.calls == []
        from datetime import datetime, UTC
        # The sealed publication keeps the lifetime restriction independent of
        # this legacy timestamp; no expiry/refresh input can turn it into writes.
        assert handle._record.read_only_lifetime
        assert handle.expires_at > datetime.now(UTC).timestamp()
    # Only after legitimate financial settlement: expiry is unavailable, never writable.
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
    setup.registry_owner.shorten_session_expiry(handle, 0.0, current_authority=authority)
    assert handle.is_read_only
    with pytest.raises(RegistrySessionUnavailable):
        setup.registry.get_connected_session_for(target, current_authority=authority)


def test_R10_foreign_and_case_only_targets_remain_strict(mounted_desk: MountedDesk) -> None:
    """A matching local alias is not interchangeable with any other native account."""
    desk = mounted_desk
    with _cash_duty(desk):
        for account in ("Foreign", "mounted"):
            result = _recover(desk, account=account, body={
                "credentials": {"client_id": account, "access_token": "synthetic"}})
            assert result.status_code == 503
            assert len(desk.transport.authentication_calls) == 1
        assert _recover(desk).get_json()["runtimeStatus"] == "read_only_recovery"


def test_R11_recovery_preserves_human_read_acl_and_unavailable_books(mounted_desk: MountedDesk) -> None:
    """Recovery does not repair malformed books or make unknown data empty."""
    desk = mounted_desk
    with _cash_duty(desk):
        setup = desk.app.extensions["flinttrade.account_setup"]
        acls = setup.workspace.assert_coherent().as_dict()["brokers"]["account_acls"]
        result = _recover(desk)
        assert result.get_json()["runtimeStatus"] == "read_only_recovery"
        assert setup.workspace.assert_coherent().as_dict()["brokers"]["account_acls"] == acls
        response = desk.client.get("/api/v1/native/accounts/dhan/Mounted/trades", headers=desk.headers)
        assert response.status_code == 200, response.get_json()
        assert desk.calls == ["trades"]
        unauthenticated = desk.client.get("/api/v1/native/accounts/dhan/Mounted/trades")
        assert unauthenticated.status_code == 401
        assert desk.calls == ["trades"]


def test_P04_ordinary_connect_remove_remain_excluded_by_retained_duties(mounted_desk: MountedDesk) -> None:
    """The exception belongs only to exact RECONNECT, never CONNECT or REMOVE."""
    desk = mounted_desk
    with _cash_duty(desk):
        result = desk.client.post("/api/v1/native/accounts", json={"adapter_id": "dhan", "account_id": "Mounted",
            "credentials": {"client_id": "Mounted", "access_token": "synthetic"}},
            headers={**desk.headers, "Idempotency-Key": str(uuid4())})
        assert result.status_code == 503
        removed = desk.client.delete("/api/v1/native/accounts/dhan/Mounted", json={},
            headers={**desk.headers, "Idempotency-Key": str(uuid4())})
        assert removed.status_code == 503
        assert len(desk.transport.authentication_calls) == 1


def test_U01_public_recovery_envelope_is_not_session_or_trading_readiness(mounted_desk: MountedDesk) -> None:
    """Capture the actual typed HTTP contract; frontend rendering is a separate owner."""
    desk = mounted_desk
    with _cash_duty(desk):
        result = _recover(desk)
        body = result.get_json()
        assert set(body) == {"receipt", "runtimeStatus", "recovery"}
        assert body["runtimeStatus"] == "read_only_recovery"
        assert body["recovery"]["broker"] == "dhan" and body["recovery"]["accountId"] == "Mounted"
        assert body["recovery"]["reconciliationRequired"] is True
        assert result.headers["Cache-Control"] == "no-store"


def _process_case(tmp_path: Any, case: str) -> dict[str, Any]:
    """Wait for real disposable process exit; never confuse it with owner cleanup."""
    import json
    import subprocess
    import sys
    command = [
        sys.executable, "-B", "-c",
        "from pathlib import Path\n"
        "from packages.core.core.tests.native_recovery_process import exercise\n"
        "exercise(" + repr(case) + ", Path(" + repr(str(tmp_path)) + "))",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((tmp_path / "process-result.json").read_text())


def test_R01_foreign_provider_identity_never_recovers_retained_custody(tmp_path: Any) -> None:
    """Matching caller labels cannot override the real profile's foreign identity."""
    result = _process_case(tmp_path, "R01")
    assert result["authentication_calls"] == 2 and result["retained_shutdown"] is False


def test_R02_fake_candidate_flags_never_replace_producer_identity(tmp_path: Any) -> None:
    """A DTO/flag after real auth is not this candidate's bound provider receipt."""
    result = _process_case(tmp_path, "R02")
    assert result["authentication_calls"] == 2 and result["retained_shutdown"] is False


def test_R06_post_auth_custody_generation_change_refuses_publication(tmp_path: Any) -> None:
    """A real public Stop during auth invalidates the original owner census CAS."""
    result = _process_case(tmp_path, "R06")
    assert result["authentication_calls"] == 2 and result["retained_shutdown"] is False


def test_R09_restart_keeps_duties_and_replay_does_not_reconstruct_a_session(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch, backend_lease_factory: Any, owned_flask_apps: Any,
) -> None:
    """Process loss preserves semantic duties; fresh explicit auth alone restores reads."""
    import json
    import requests
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from flinttrade_core import auth_state
    from flinttrade_core.app import create_flask_app
    from packages.core.core.tests.test_native_financial_owner import _settle_cash
    result = _process_case(tmp_path, "R09")
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    auth_state.reset_singleton_for_tests()
    auth_state.get_auth_state(db_path=tmp_path / "synthetic-auth-state.sqlite")
    from flinttrade_core import auth_routes
    # Match a genuinely cold restart: load this child's persisted synthetic
    # signing key, not a previous test workspace's process-global cache.
    monkeypatch.setattr(auth_routes, "_JWT_SECRET_KEY", "")
    calls: list[str] = []
    expiry = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).strftime("%d/%m/%Y %H:%M")

    class Transport:
        """Fresh explicit auth through the same installed SDK after observed child exit."""
        authentication_calls: list[str] = calls

        def send(self, request: requests.PreparedRequest) -> requests.Response:
            """Forward only the exact installed SDK request to the owned synthetic profile transport."""
            assert request.method == "GET" and request.url == "https://api.dhan.co/v2/profile"
            calls.append(request.url)
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps({"dhanClientId": "Mounted", "tokenValidity": expiry}).encode()
            return response

    transport = Transport()

    def send(_session: requests.Session, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        """Forward only the exact installed SDK request to the owned synthetic profile transport."""
        return transport.send(request)

    monkeypatch.setattr(requests.Session, "send", send)
    app = create_flask_app(backend_lease_proof=backend_lease_factory())
    desk = MountedDesk(app, app.test_client(), {"Authorization": "Bearer " + result["token"]}, [], transport)
    assert calls == []
    before = _financial(desk)
    assert before == result["financial"]
    replay = _recover(desk, key=result["key"])
    assert replay.status_code == 200 and replay.get_json()["receipt"] == result["http"]["receipt"]
    assert replay.get_json()["runtimeStatus"] == "session_unavailable" and calls == []
    recovered = _recover(desk)
    assert recovered.get_json()["runtimeStatus"] == "read_only_recovery", recovered.get_json()
    assert _financial(desk) == before and len(calls) == 1
    source = _source(desk)
    _settle_cash(desk, source, result["facts"])
    assert app.config["EXECUTION_SESSIONS"].shutdown(0)
    owned_flask_apps.close()


@pytest.mark.parametrize("mounted_desk", ["kotak_acl"], indirect=True)
def test_P03_kotak_installed_auth_identity_and_supported_option_allocation(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain real View/Trade UCC; validate exact options without lifting read-only policy."""
    import copy
    import json
    from pathlib import Path
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from types import SimpleNamespace
    import httpx
    from neo_api_client.utils.neo_utility import CONFIG_SERVICE_URL_PROD
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.models import Order
    from flinttrade_core.native_autonomy import NativeDispatchAuthority, _digest
    from packages.core.core.tests.test_exact_contract_http_preflight import _resolver
    from packages.core.core.tests.test_native_financial_owner import BASE, _fees, _ref

    desk = mounted_desk
    setup = desk.app.extensions["flinttrade.account_setup"]
    calls: list[str] = []

    class Wire:
        """Installed SDK v3 auth steps and liveness; every trade endpoint is forbidden."""

        def send(self, request: httpx.Request) -> httpx.Response:
            """Serve only installed View/Trade/config/liveness requests; reject every trade endpoint."""
            calls.append(str(request.url))
            if request.url.path.endswith("tradeApiLogin"):
                assert json.loads(request.content)["ucc"] == "KotakMounted"
                data = {"token": "synthetic-view", "sid": "synthetic-sid", "ucc": "KotakMounted",
                        "kType": "View", "status": "success"}
            elif request.url.path.endswith("tradeApiValidate"):
                data = {"token": "synthetic-trade", "sid": "synthetic-sid", "ucc": "KotakMounted", "kType": "Trade",
                        "status": "success", "baseUrl": "https://example.invalid", "dataCenter": "synthetic"}
            elif str(request.url).split("?", 1)[0] == CONFIG_SERVICE_URL_PROD:
                data = {"configs": {}}
            else:
                assert request.method == "GET" and request.url.path.endswith("get-client-ip")
                return httpx.Response(200, request=request, json={"status": "success", "stCode": 1000,
                                                                   "data": [{"ip": "192.0.2.1"}]})
            return httpx.Response(200, request=request, json={"data": data})

    wire = Wire()

    def send(_client: httpx.Client, request: httpx.Request, **_kwargs: Any) -> httpx.Response:
        """Serve only installed View/Trade/config/liveness requests; reject every trade endpoint."""
        return wire.send(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    credentials = {"consumer_key": "synthetic-key", "mobile_number": "+910****0000", "ucc": "KotakMounted",
                   "totp": "000000", "mpin": "000000"}
    connected = desk.client.post("/api/v1/native/accounts", headers={**desk.headers, "Idempotency-Key": str(uuid4())},
        json={"adapter_id": "kotakneo", "account_id": "KotakMounted", "credentials": credentials})
    assert (connected.status_code == 200
            and connected.get_json()["receipt"]["state"] == "committed"), connected.get_json()
    target = BrokerSelector("kotakneo", "KotakMounted")
    handle = setup.registry.get_connected_session_for(
        target, current_authority=setup.runtime._provider.current_authority_for(target)
    )
    assert handle.verified_native_account == "KotakMounted" and handle.is_read_only
    native = desk.app.config["EXECUTION_SESSIONS"].autonomy
    source = native.v2.install_primitive_fixture_source(transport=wire, transport_binding=httpx.Client.send,
                                                       current_transport_binding=lambda: httpx.Client.send)
    resolver, symbol = _resolver("kotakneo", "NFO")
    adapter = desk.app.config["ACTIVE_BROKER_ADAPTERS"]["kotakneo"]
    adapter.replace_contract_resolver(resolver, expected_revision=None)
    order = Order(
        symbol=symbol, exchange="NFO", product="NRML", action="BUY", quantity="3", price="4", pricetype="LIMIT"
    )
    preparation = adapter.prepare_order(order, session=handle)
    evidence = preparation.contract_evidence()
    assert evidence["instrument_id"] == "71472" and evidence["lot_size"] == 3
    assert evidence["tick_scale_verified"] is False
    corpus = json.loads((Path(__file__).parent / "fixtures/native-options-v2.json").read_text())
    request = next(row["value"] for row in corpus["cases"] if row["id"] == "options-ConfigureRequestV2-positive")
    request["config"].update(
        run_id="mounted-native", broker="kotakneo", account_id="KotakMounted", environment="synthetic"
    )
    request["config"]["risk"]["max_mark_age_ms"] = 60000
    created = desk.client.post(BASE + "/native-v2", json=request, headers=desk.headers)
    assert created.status_code == 201, created.get_json()
    facts = _facts()
    now = facts["observed_at_ms"]
    contract = {"contract_ref": _ref("option-contract"),
                "listing_ref": {"id": "native-listing", "revision": _digest(evidence)},
                "token": "71472", "underlying_ref": _ref("index"), "underlying": "NIFTY",
                "exchange": "NFO", "product": "NRML",
                "expiry_at_ms": int(datetime(2099, 6, 23, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp() * 1000),
                "right": "CE", "strike": "22250", "units_per_lot": 3,
                "quantity_unit": "underlying_units", "currency": "INR"}
    entry = {"entry_ref": _ref("option-entry"), "contract": contract, "current_contract": contract,
             "listing_observed_at_ms": now, "side": "long", "fills": [],
             "writes": [{"write_ref": _ref("option-write"), "contract_ref": contract["contract_ref"],
                         "purpose": "entry",
                         "side": "buy", "original_quantity": 3, "remaining_quantity": 3, "released_quantity": 0,
                         "resolution_ref": None, "premium_upper_bound": "4"}],
             "mark": {"contract_ref": contract["contract_ref"], "underlying_ref": contract["underlying_ref"],
                      "source_ref": _ref("mark"),
                      "underlying_price": "10", "underlying_at_ms": now,
                      "option_price": "4", "option_at_ms": now}, "margin": None}
    facts["entries"], facts["fees"] = [entry], _fees(entry, now, ("entry_possible", "close_possible"), options=True)
    source.publish("mounted-native", facts)
    before = _qualify(desk)
    assert _financial(desk)["assessment"]["status"] == "within_bounds"
    # Exercise the exact pure binding used by canonical entry. This unregistered
    # object cannot invoke: it is not a grant/ticket and is never installed in custody.
    with native.db.transaction() as db:
        row = native.v2._get(db, "mounted-native", before["scope"]["operator"])
    binding = NativeDispatchAuthority(native, row, {"financial_contract": contract})
    binding.bind_preparation(SimpleNamespace(preparation=preparation), order)
    for field, changed in (("token", "wrong"), ("listing_ref", _ref("wrong-listing")), ("units_per_lot", 4)):
        invalid = copy.deepcopy(contract)
        invalid[field] = changed
        with pytest.raises(ValueError, match="allocation"):
            NativeDispatchAuthority(native, row, {"financial_contract": invalid}).bind_preparation(
                SimpleNamespace(preparation=preparation), order)
    count = len(calls)
    try:
        result = desk.client.post("/api/v1/native/accounts/kotakneo/KotakMounted/login",
                                  json={"credentials": credentials},
                                  headers={**desk.headers, "Idempotency-Key": str(uuid4())})
        assert (result.status_code == 200
                and result.get_json()["runtimeStatus"] == "read_only_recovery"), result.get_json()
        current = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
        assert current["scope"] == before["scope"] and current["duty"]["possible_entry_quantity"] == 3
        assert current["duty"]["obligations"] and current["effective_authority"] == "none"
        assert len(calls) == count + 4
    finally:
        source.rebind_read_only_recovery("mounted-native")
        entry["writes"][0].update(
            remaining_quantity=0, released_quantity=3, resolution_ref=_ref("synthetic-terminal-resource")
        )
        # No execution or incurred charge was observed in this synthetic lifecycle;
        # pending-only allocations cease with the evidenced released units.
        facts["fees"] = []
        source.publish("mounted-native", facts)
        _qualify(desk)
    assert native.retire_all(), _financial(desk)

