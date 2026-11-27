"""Literal HTTP journey for a server-registered, inert native strategy."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_native_custody_owner import _preview, _selection
from packages.core.core.tests.test_native_financial_owner import RUN, _qualify
from packages.core.core.tests.test_native_producer_v2 import _plan, _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_explicit_preview_accept_grant_start_stop_and_exact_reads(mounted_desk: MountedDesk) -> None:
    """Exercise explicit custody, grant, Start, Stop and exact-account read transitions.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    source, registration = _registered(desk, interval_ms=5000)
    _plan(source, registration, mark="5")

    def read() -> dict:
        native = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
        generic = desk.client.get(RUN, headers=desk.headers)
        assert native.status_code == generic.status_code == 200
        assert native.get_json()["data"]["scope"] == generic.get_json()["data"]["autonomy_v2"]["scope"]
        return generic.get_json()["data"]

    view = _qualify(desk)
    read()
    selection = _selection(view)
    preview = _preview(desk, selection)
    read()
    accepted = desk.client.post(RUN + "/autonomy-v2/transfer-accept", json={
        "schema_version": "2", "preview_ref": preview["preview_ref"],
        "expected_duty_revision": preview["duty"]["duty_ref"]["revision"],
    }, headers=desk.headers)
    assert accepted.status_code == 200
    read()
    granted = desk.client.post(RUN + "/autonomy-v2/grant", json=selection, headers=desk.headers)
    assert granted.status_code == 200, granted.get_json()
    view = granted.get_json()["data"]
    assert desk.app.config["EXECUTION_SESSIONS"].owners == {} and desk.calls == []
    read()
    started = desk.client.post(RUN + "/autonomy-v2/start", json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"], "grant_ref": view["grant"]["grant_ref"],
    }, headers=desk.headers)
    assert started.status_code == 200, started.get_json()
    row = read()
    stop = desk.client.post(RUN + "/stop", headers=desk.headers, json={
        "account": row["account"], "environment": row["environment"], "expected_generation": row["generation"],
    })
    assert stop.status_code == 200, stop.get_json()
    owner = desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"]
    assert owner.completed.wait(5) and owner.shutdown(0)
    retired = read()["autonomy_v2"]
    assert retired["entry_state"] == "retired" and retired["effective_authority"] == "none"
    assert desk.calls == []
