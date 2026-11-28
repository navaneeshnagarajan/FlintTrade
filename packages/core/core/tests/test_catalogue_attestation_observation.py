"""Read-only catalogues share one fresh SDK observation per response.

These public blueprint controls delegate to the real installed SDK attester.
They do not qualify broker accounts or replace an execution-authority check.
"""
from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from flinttrade_core import broker_sdk_attest
from flinttrade_core.native_account_routes import native_accounts_bp
from flinttrade_gateway.capabilities_routes import capabilities_bp


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    ["/api/v1/native/brokers", "/api/v1/broker/capabilities", "/api/v1/broker/mcp"],
)
def test_catalogue_response_uses_one_fresh_sdk_observation(
    monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    """A catalogue is one observation, not a full SDK rescan for every row."""
    observed: list[dict[str, dict[str, Any]]] = []
    actual = broker_sdk_attest.attestations_by_pin

    def record() -> dict[str, dict[str, Any]]:
        rows = actual()
        observed.append(rows)
        return rows

    monkeypatch.setattr(broker_sdk_attest, "attestations_by_pin", record)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(native_accounts_bp)
    app.register_blueprint(capabilities_bp)
    response = app.test_client().get(path)
    assert response.status_code == 200
    body = response.get_json()
    brokers = body["data"]["brokers"] if path == "/api/v1/native/brokers" else body["brokers"]
    pinned = [row for row in brokers if row.get("sdk_pin") is not None]
    assert len(pinned) > 1
    assert len(observed) == 1
    for row in pinned:
        assert row["sdk_attestation"] == observed[0][row["sdk_pin"]]


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    ["/api/v1/native/brokers", "/api/v1/broker/capabilities", "/api/v1/broker/mcp"],
)
def test_catalogue_next_request_gets_a_fresh_observation(
    monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    """Even a retained application context cannot lend the previous response's SDK state."""
    observed: list[dict[str, dict[str, Any]]] = []
    actual = broker_sdk_attest.attestations_by_pin

    def record() -> dict[str, dict[str, Any]]:
        rows = actual()
        observed.append(rows)
        return rows

    monkeypatch.setattr(broker_sdk_attest, "attestations_by_pin", record)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(native_accounts_bp)
    app.register_blueprint(capabilities_bp)
    with app.app_context(), app.test_client() as client:
        first = client.get(path)
        assert first.status_code == 200
        assert len(observed) == 1
        second = client.get(path)
        assert second.status_code == 200
        assert len(observed) == 2
    assert observed[0] is not observed[1]
    assert first.get_json() == second.get_json()


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    ["/api/v1/native/brokers", "/api/v1/broker/capabilities", "/api/v1/broker/mcp"],
)
def test_catalogue_unavailable_observation_is_not_reused_after_recovery(
    monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    """An unavailable response stays honest and the next request re-observes the SDKs."""
    failed = True
    attempts = 0
    observed: list[dict[str, dict[str, Any]]] = []
    actual = broker_sdk_attest.attestations_by_pin

    def observe() -> dict[str, dict[str, Any]]:
        nonlocal attempts
        attempts += 1
        if failed:
            raise OSError("Synthetic SDK-observation failure")
        rows = actual()
        observed.append(rows)
        return rows

    monkeypatch.setattr(broker_sdk_attest, "attestations_by_pin", observe)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(native_accounts_bp)
    app.register_blueprint(capabilities_bp)
    with app.app_context(), app.test_client() as client:
        unavailable = client.get(path)
        assert unavailable.status_code == 200
        body = unavailable.get_json()
        brokers = body["data"]["brokers"] if path == "/api/v1/native/brokers" else body["brokers"]
        pinned = [row for row in brokers if row.get("sdk_pin") is not None]
        assert len(pinned) > 1
        assert all(row["sdk_attestation"]["status"] == "unknown" for row in pinned)
        assert attempts == 1
        failed = False
        recovered = client.get(path)
        assert recovered.status_code == 200
        assert attempts == 2
        body = recovered.get_json()
        brokers = body["data"]["brokers"] if path == "/api/v1/native/brokers" else body["brokers"]
        for row in brokers:
            if row.get("sdk_pin") is not None:
                assert row["sdk_attestation"] == observed[0][row["sdk_pin"]]
