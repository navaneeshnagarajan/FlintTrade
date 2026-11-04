"""No legacy read or producer port may adopt a nominal versioned run."""
from __future__ import annotations

from typing import Any

import pytest

from packages.core.core.tests.test_native_financial_owner import RUN
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan, _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("operation", ["reconcile", "qualify", "revoke", "port"])
def test_nominal_run_refuses_other_legacy_owners_before_reads(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    """Reject nominal versioned runs at other legacy owners before any reads.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        monkeypatch: Scoped replacements restored after this test.
        operation: Public lifecycle or command operation exercised by this control.
    """
    desk = mounted_desk
    source, registration = _registered(desk, interval_ms=5000)
    _plan(source, registration, mark="5")
    view = _granted(desk)
    started = desk.client.post(RUN + "/autonomy-v2/start", headers=desk.headers, json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"], "grant_ref": view["grant"]["grant_ref"],
    })
    assert started.status_code == 200
    native = desk.app.config["EXECUTION_SESSIONS"].autonomy
    calls: list[str] = []
    original = native._books

    def observe(row: dict[str, Any]) -> Any:
        calls.append(row["binding"]["run_id"])
        return original(row)

    monkeypatch.setattr(native, "_books", observe)
    try:
        if operation == "port":
            with pytest.raises(ValueError, match="versioned"):
                native.port(desk.headers["Authorization"].removeprefix("Bearer "), "mounted-native")
        else:
            body = {"grant_id": view["grant"]["grant_ref"]["id"]} if operation == "revoke" else {}
            result = desk.client.post(RUN + "/autonomy/" + operation, json=body, headers=desk.headers)
            assert calls == [] and desk.calls == []
            assert result.status_code == 409, result.get_json()
        assert calls == [] and desk.calls == []
    finally:
        row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
        stop = desk.client.post(RUN + "/stop", headers=desk.headers, json={
            "account": row["account"], "environment": row["environment"], "expected_generation": row["generation"],
        })
        assert stop.status_code == 200
        assert native.registry.owners["mounted-native"].completed.wait(5)
