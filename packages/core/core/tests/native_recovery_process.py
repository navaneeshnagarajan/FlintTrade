"""Disposable process-loss controls for retained recovery refusals.

Only synthetic workspace/account bytes are used. A child explicitly proves
failed duty drainage before process loss; its exit is never reported as normal
factory cleanup. The parent waits for actual exit before reacquiring any lease.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo


def exercise(case: str, root: Path) -> None:
    """Run a genuine factory/account path and retain its real HTTP/custody results."""
    import requests
    import pytest
    from flinttrade_core import app as app_module, auth_state
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_core.backend_instance import acquire_backend_instance_lease
    from flinttrade_core.workspace_migrations import compare_and_swap_workspace
    from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
    from packages.core.core.tests.test_native_financial_owner import (
        _source, _configure, _facts, _cash_filled, _qualify, _financial, RUN,
    )
    from packages.core.core.tests.test_native_read_only_recovery import _recover

    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(root)
    app_module._MASTER_PASSWORD = "pytest-master-password"
    auth_state.reset_singleton_for_tests()
    auth_state.get_auth_state(db_path=root / "synthetic-auth-state.sqlite")

    def configure(value: dict[str, Any]) -> None:
        """Install explicit synthetic human and bounded read ACLs before account enrolment."""
        value["brokers"]["account_acls"] = {"dhan": {"Mounted": ["mounted-operator", "bounded:mounted-native"]}}

    compare_and_swap_workspace(root, None, configure)
    calls: list[str] = []
    faults = {"profile": False, "candidate": False, "race": False}
    desk: MountedDesk | None = None
    expiry = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(hours=2)).strftime("%d/%m/%Y %H:%M")

    class Transport:
        """Actual installed Dhan SDK's external profile endpoint only."""
        authentication_calls: list[str] = calls

        def send(self, request: requests.PreparedRequest) -> requests.Response:
            """Serve only the exact synthetic profile endpoint, retaining refused/racing responses."""
            assert request.method == "GET" and request.url == "https://api.dhan.co/v2/profile"
            calls.append(request.url)
            if faults["race"]:
                faults["race"] = False
                assert desk is not None
                row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
                stop = desk.client.post(RUN + "/stop", headers=desk.headers, json={
                    "account": row["account"], "environment": row["environment"],
                    "expected_generation": row["generation"]})
                assert stop.status_code == 200
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps({"dhanClientId": "Foreign" if faults["profile"] else "Mounted",
                                            "tokenValidity": expiry}).encode()
            return response

    transport = Transport()
    patcher = pytest.MonkeyPatch()

    def send(_session: requests.Session, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
        """Forward the installed SDK request to this owned inert transport."""
        return transport.send(request)

    patcher.setattr(requests.Session, "send", send)
    lease = acquire_backend_instance_lease()
    app = app_module.create_flask_app(backend_lease_proof=lease.proof)
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].setup_account("mounted-operator", "operator@example.test", "synthetic-password")
    with app.app_context():
        token = _create_token("mounted-operator", mode="live", live_mode_unlocked=True)
    desk = MountedDesk(app, app.test_client(), {"Authorization": "Bearer " + token}, [], transport)
    first = desk.client.post(
        "/api/v1/native/accounts", headers={**desk.headers, "Idempotency-Key": str(uuid4())}, json={
            "adapter_id": "dhan", "account_id": "Mounted",
            "credentials": {"client_id": "Mounted", "access_token": "synthetic"}})
    assert first.status_code == 200 and first.get_json()["receipt"]["state"] == "committed"
    source = _source(desk)
    _configure(desk)
    facts = _facts()
    _cash_filled(facts)
    source.publish("mounted-native", facts)
    _qualify(desk)
    before = _financial(desk)
    if case == "R01":
        faults["profile"] = True
    elif case == "R02":
        from flinttrade_core.account_setup import _OwnedDriver
        original = _OwnedDriver.authenticate

        def substitute(owner: Any, *args: Any, **kwargs: Any) -> Any:
            """Negative-only proof substitution after genuine installed authentication."""
            candidate = original(owner, *args, **kwargs)
            candidate.session.extra["provider_verified"] = True
            candidate.identity_evidence = object()
            return candidate

        patcher.setattr(_OwnedDriver, "authenticate", substitute)
    elif case == "R06":
        faults["race"] = True
    else:
        assert case == "R09"
    key = str(uuid4())
    result = _recover(desk, key=key)
    body = result.get_json()
    if case == "R09":
        assert result.status_code == 200 and body["runtimeStatus"] == "read_only_recovery", body
    else:
        assert body.get("runtimeStatus") != "read_only_recovery", body
        assert body.get("receipt", {}).get("state") != "committed", body
    assert _financial(desk) == before
    assert len(calls) == 2
    assert not app.config["EXECUTION_SESSIONS"].shutdown(0)
    if case != "R09":
        setup = app.extensions["flinttrade.account_setup"]
        assert not setup.lifecycle.close_and_drain(2)
        assert setup.lifecycle.snapshot().cleanup_pending == 0
        assert setup.store.active_operation(setup.store.owner_capability(setup.proof)) is not None
    from flinttrade_core.backend_instance import require_backend_lease_proof
    assert require_backend_lease_proof(lease.proof) is lease.proof
    # Actual results, not a fabricated success DTO; the synthetic token remains
    # inside this disposable private workspace for the separate restart control.
    (root / "process-result.json").write_text(json.dumps({"case": case, "http": body, "status": result.status_code,
        "financial": before, "facts": facts, "key": key, "token": token,
        "retained_shutdown": False, "authentication_calls": len(calls)}))
    # No release/close after a false drain. The real child exits, modelling
    # process loss; the parent independently observes exit and lease exclusion.
