"""Nominal ingress observations through the unchanged normal-factory owners."""
from __future__ import annotations

from typing import Any

import pytest
import requests

from packages.core.core.tests.test_native_financial_owner import RUN
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan, _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.test_native_workflow_v2 import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


def test_versioned_legacy_ingress_is_proved_unsent_before_every_book_or_transport(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse versioned input at legacy ingress before book reads or transport invocation.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        monkeypatch: Scoped replacements restored after this test.
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
    registry = desk.app.config["EXECUTION_SESSIONS"]
    native = registry.autonomy
    events: list[tuple[str, Any]] = []
    original_send, original_books = requests.Session.send, native._books

    def send(session: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        events.append(("http", (request.method, request.url)))
        return original_send(session, request, **kwargs)

    def books(row: dict[str, Any]) -> Any:
        events.append(("books", row["binding"]["run_id"]))
        return original_books(row)

    monkeypatch.setattr(requests.Session, "send", send)
    monkeypatch.setattr(native, "_books", books)
    original_financial = native.v2.financial_status(desk.headers["Authorization"].removeprefix("Bearer "),
        "mounted-native")
    try:
        for operation in ("order", "cancel"):
            command = {"command_id": "legacy-" + operation, "grant_id": view["grant"]["grant_ref"]["id"],
                       "expected_revision": view["scope"]["binding_revision"]}
            command[operation] = ({"symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY",
                                   "quantity": 1, "price": 4, "order_type": "LIMIT"}
                                  if operation == "order" else {"placement_command_id": "absent"})
            rejected = desk.client.post(RUN + "/autonomy/commands", headers=desk.headers, json=command)
            # Inspect the causal ledger before status, including exceptions in
            # the inert transport that a route could otherwise hide as 503.
            assert events == [] and desk.calls == []
            assert rejected.status_code == 409, rejected.get_json()
        assert native.v2.financial_status(desk.headers["Authorization"].removeprefix("Bearer "),
            "mounted-native") == original_financial
        assert native._tickets == {}
    finally:
        row = desk.client.get(RUN, headers=desk.headers).get_json()["data"]
        stopped = desk.client.post(RUN + "/stop", headers=desk.headers, json={
            "account": row["account"], "environment": row["environment"], "expected_generation": row["generation"],
        })
        assert stopped.status_code == 200
        assert registry.owners["mounted-native"].completed.wait(5)


def test_legacy_configuration_status_and_command_reach_the_original_authority_owner(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep genuine legacy requests routed to their existing authority owner.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        monkeypatch: Scoped replacements restored after this test.
    """
    desk = mounted_desk
    body = {"run_id": "mounted-native", "broker": "dhan", "account_id": "Mounted",
            "strategy_revision": "strategy-1", "config_revision": "config-1",
            "policy_revision": "policy-1", "provider_revision": "provider-1"}
    configured = desk.client.post("/api/v1/execution-sessions/native", headers=desk.headers, json=body)
    assert configured.status_code == 201, configured.get_json()
    view = configured.get_json()["data"]
    assert desk.client.get(RUN + "/autonomy", headers=desk.headers).get_json()["data"] == view
    native = desk.app.config["EXECUTION_SESSIONS"].autonomy
    original = native._entry_authority
    admitted: list[str] = []

    def observe(row: dict[str, Any]) -> None:
        admitted.append(row["binding"]["run_id"])
        return original(row)

    monkeypatch.setattr(native, "_entry_authority", observe)
    result = desk.client.post(RUN + "/autonomy/commands", headers=desk.headers, json={
        "command_id": "ordinary-legacy", "grant_id": "not-issued", "expected_revision": view["revision"],
        "order": {"symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY",
                  "quantity": 1, "price": 4, "order_type": "LIMIT"},
    })
    assert admitted == ["mounted-native"]
    assert result.status_code == 409 and desk.calls == []
    assert native.status(desk.headers["Authorization"].removeprefix("Bearer "), "mounted-native") == view
    # This is positive nominal admission and read compatibility, not a broker
    # write positive: the unchanged real qualification owner still refuses.
