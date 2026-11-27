"""An old nominal command ingress cannot act for a versioned producer."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_native_financial_owner import RUN
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan, _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_legacy_command_route_refuses_v2_before_any_broker_read(mounted_desk: MountedDesk) -> None:
    """Reject versioned commands at the legacy route before broker reads.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    source, registration = _registered(desk, interval_ms=5000)
    _plan(source, registration, mark="5")
    view = _granted(desk)
    started = desk.client.post(RUN + "/autonomy-v2/start", headers=desk.headers, json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"], "grant_ref": view["grant"]["grant_ref"]})
    assert started.status_code == 200
    try:
        rejected = desk.client.post(RUN + "/autonomy/commands", headers=desk.headers, json={
            "command_id": "foreign-legacy-entry", "grant_id": view["grant"]["grant_ref"]["id"],
            "expected_revision": view["scope"]["binding_revision"],
            "order": {"symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY",
                      "quantity": 1, "price": 4, "order_type": "LIMIT"}})
        assert rejected.status_code == 409, rejected.get_json()
        assert desk.calls == []
    finally:
        row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
        stopped = desk.client.post(RUN + "/stop", headers=desk.headers, json={
            "account": row["account"], "environment": row["environment"], "expected_generation": row["generation"]})
        assert stopped.status_code == 200
        assert desk.app.config["EXECUTION_SESSIONS"].owners["mounted-native"].completed.wait(5)
