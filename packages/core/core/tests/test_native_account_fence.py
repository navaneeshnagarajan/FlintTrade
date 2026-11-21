"""Native empty-census account cutover through the actual normal factory."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, _configuration
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_configured_empty_native_run_allows_exact_account_cutover_and_retry(mounted_desk: MountedDesk) -> None:
    """An inspected empty native owner is not absent storage or live authority."""
    desk = mounted_desk
    created = desk.client.post("/api/v1/execution-sessions/native-v2", json=_configuration(), headers=desk.headers)
    assert created.status_code == 201, created.get_json()
    body: dict[str, Any] = {"credentials": {"client_id": "Mounted", "access_token": "synthetic-successor"}}
    headers = {**desk.headers, "Idempotency-Key": str(uuid4())}
    path = "/api/v1/native/accounts/dhan/Mounted/login"
    response = desk.client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["receipt"]["state"] == "committed"
    replay = desk.client.post(path, json=body, headers=headers)
    assert replay.status_code == 200, replay.get_json()
    assert replay.get_json()["receipt"] == response.get_json()["receipt"]
    assert len(desk.transport.authentication_calls) == 2
    native = desk.app.config["EXECUTION_SESSIONS"].autonomy
    assert native.storage_present(native.registry.path)
    assert desk.calls == []
