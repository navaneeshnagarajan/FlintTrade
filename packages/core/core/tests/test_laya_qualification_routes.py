"""Supported operator configuration for real managed qualification checks."""
from __future__ import annotations
from typing import Any
import pytest
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk, mounted_desk as mounted_desk
from packages.core.core.tests.test_laya_qualification_owner import sidecar as sidecar

pytestmark = pytest.mark.integration


def test_public_qualification_requires_explicit_suite_and_lifetime(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]],
) -> None:
    """Configure, measure and retire without caller-supplied readiness evidence."""
    desk = mounted_desk
    url = "/api/v1/laya/qualification"
    assert desk.client.post(url, json={}, headers=desk.headers).status_code == 409
    assert sidecar[1] == []
    configured = desk.client.put(url + "/configuration", headers=desk.headers, json={
        "schema_version": "1", "cases": [["positive", "BUY", "Reviewed limit", "allow"],
                                         ["negative", "BUY", "revenge", "deny"]],
        "max_age_seconds": 10,
    })
    assert configured.status_code == 200, configured.get_json()
    assert configured.get_json()["qualified"] is False
    assert sidecar[1] == []
    refused = desk.client.post(url, json={"qualified": True}, headers=desk.headers)
    assert refused.status_code == 400 and sidecar[1] == []
    measured = desk.client.post(url, json={}, headers=desk.headers)
    assert measured.status_code == 200, measured.get_json()
    assert measured.get_json()["qualified"] is True
    assert measured.get_json()["observed_effects"] == ["allow", "deny"]
    assert desk.client.delete(url, headers=desk.headers).status_code == 200
    assert not desk.app.config["LAYA_QUALIFICATION_OWNER"].qualifies()
    assert desk.client.post(url, json={}).status_code == 401


@pytest.mark.parametrize("body", [
    {}, {"schema_version": "1", "cases": [], "max_age_seconds": 10},
    {"schema_version": "1", "cases": [["positive", "BUY", "Reviewed limit", "allow"]], "max_age_seconds": 10},
    {"schema_version": "1", "cases": [["p", "BUY", "x", "allow"], ["n", "BUY", "y", "deny"]], "max_age_seconds": True},
])
def test_public_qualification_configuration_fails_closed(mounted_desk: MountedDesk, body: dict[str, Any]) -> None:
    """Incomplete suites, missing lifetimes and booleans never become defaults."""
    result = mounted_desk.client.put("/api/v1/laya/qualification/configuration", json=body,
                                     headers=mounted_desk.headers)
    assert result.status_code == 400
    assert not mounted_desk.app.config["LAYA_QUALIFICATION_OWNER"].qualifies()
