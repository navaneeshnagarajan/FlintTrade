"""Native inspect adopts the supplied finite plan at the existing canonical owner."""
from __future__ import annotations

import time

import pytest

from flinttrade_core.broker_identity import BrokerSelector
from packages.core.core.tests.test_native_financial_owner import BASE, RUN
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, _configuration
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_all_requested_surfaces_are_retained_under_one_actual_read_ceiling(mounted_desk: MountedDesk) -> None:
    """Retain every requested canonical surface under the same owned read ceiling.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    created = desk.client.post(BASE + "/native-v2", headers=desk.headers, json=_configuration())
    assert created.status_code == 201
    scope = created.get_json()["data"]["scope"]
    surfaces = ["trades", "orders", "positions", "holdings", "fees", "broker_protection", "quotes"]
    plan = {"surfaces": surfaces, "max_reads": 1, "max_pages": 1, "deadline_ms": int(time.time() * 1000) + 10000}
    result = desk.client.post(RUN + "/autonomy-v2/inspect", headers=desk.headers, json={
        "schema_version": "2", "run_id": scope["run_id"], "expected_binding_revision": scope["binding_revision"],
        "read_plan": plan,
    })
    assert result.status_code == 200, result.get_json()
    assert desk.calls == ["trades"]
    snapshot = desk.app.config["ORDER_LIFECYCLE_LEDGER"].observation_snapshot(BrokerSelector("dhan", "Mounted"))
    assert [(row.surface, row.family) for row in snapshot.surfaces] == [
        ("trades", "daily"), ("orders", "regular"), ("positions", None), ("holdings", None),
        ("fees", "account_postings"), ("broker_protection", "forever"), ("broker_protection", "super"), (
            "quotes", None),
    ]
    assert snapshot.surfaces[0].coverage.availability == "available"
    assert all(row.value_json is None and row.coverage.availability != "available" for row in snapshot.surfaces[1:])
    assert not snapshot.admission_available
    view = result.get_json()["data"]
    assert view["report"]["status"] == "blocked" and view["effective_authority"] == "none" and view["grant"] is None
    native = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers)
    generic = desk.client.get(RUN, headers=desk.headers)
    assert native.status_code == generic.status_code == 200
    assert native.get_json()["data"]["report"] == generic.get_json()["data"]["autonomy_v2"]["report"]
    # The manifest is the existing canonical owner's, not a second local ledger.
    assert desk.calls == ["trades"]


def test_missing_quote_and_fee_selections_are_unavailable_without_guessed_reads(mounted_desk: MountedDesk) -> None:
    """Refuse missing quote and fee selections without guessing provider requests.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
    """
    desk = mounted_desk
    configured = desk.client.post(BASE + "/native-v2", headers=desk.headers, json=_configuration()).get_json()["data"]
    response = desk.client.post(RUN + "/autonomy-v2/inspect", headers=desk.headers, json={
        "schema_version": "2", "run_id": "mounted-native", "expected_binding_revision": configured["scope"][
            "binding_revision"],
        "read_plan": {"surfaces": ["fees", "quotes"], "max_reads": 2, "max_pages": 1,
                      "deadline_ms": int(time.time() * 1000) + 10000},
    })
    assert response.status_code == 200, response.get_json()
    snapshot = desk.app.config["ORDER_LIFECYCLE_LEDGER"].observation_snapshot(BrokerSelector("dhan", "Mounted"))
    assert [(row.surface, row.value_json) for row in snapshot.surfaces] == [("fees", None), ("quotes", None)]
    assert all(row.coverage.availability == "unsupported" for row in snapshot.surfaces)
    assert desk.calls == [] and response.get_json()["data"]["grant"] is None
