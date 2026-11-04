"""Normal-factory continuation after a committed operation's local disposal fails."""
from __future__ import annotations
from typing import Any
from uuid import uuid4
import pytest
from flinttrade_core.broker_identity import BrokerSelector
from packages.core.core.tests.test_account_setup_production import connect, production_app as production_app

pytestmark = pytest.mark.integration


def test_committed_cleanup_pending_retries_exact_owner_without_reauthentication(
    production_app: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain pending custody; terminal durable proof permits cleanup only after real release."""
    app, token, _path, calls = production_app
    assert connect(app, token).get_json()["runtimeStatus"] == "session_present"
    setup = app.extensions["flinttrade.account_setup"]
    selector = BrokerSelector("dhan", "Synthetic")
    authority = setup.runtime._provider.current_authority_for(selector)
    handle = setup.registry.get_connected_session_for(selector, current_authority=authority)
    sdk_session = handle.extra["client"].dhan_http.session
    original_close = sdk_session.close
    released = False
    attempts: list[bool] = []

    def close() -> None:
        """Hold only the actual external HTTP pool disposal, never a lifecycle verdict."""
        attempts.append(released)
        if not released:
            raise OSError("synthetic owned pool remains held")
        original_close()

    monkeypatch.setattr(sdk_session, "close", close)
    key = str(uuid4())
    try:
        response = app.test_client().post("/api/v1/native/accounts/dhan/Synthetic/login", json={},
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": key})
        body = response.get_json()
        assert response.status_code == 200 and body["receipt"]["state"] == "committed", body
        assert body["runtimeStatus"] == "cleanup_pending" and attempts
        assert setup.lifecycle.snapshot().cleanup_pending
        assert len(calls) == 2
    finally:
        released = True
    assert setup.lifecycle.close_and_drain(2)
    assert attempts[-1] is True
    assert setup.lifecycle.snapshot().cleanup_pending == 0
    assert setup.store.active_operation(setup.store.owner_capability(setup.proof)) is None
    assert len(calls) == 2
