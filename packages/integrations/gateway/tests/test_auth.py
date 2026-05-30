"""Tests for the Flask auth blueprint (gateway_bp).

All broker registry and credential store interactions are replaced with
lightweight mock classes so the tests never touch real adapters, databases,
or the network.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from flinttrade_gateway.auth import gateway_bp
from flinttrade_gateway.models import BrokerAccountInfo, AccountStatus
from flinttrade_gateway.exceptions import BrokerNotFoundError, CredentialError


# ---------------------------------------------------------------------------
# Mock registry and credential store
# ---------------------------------------------------------------------------


class MockRegistry:
    """Minimal registry stand-in for unit tests."""

    def __init__(self) -> None:
        self._accounts: dict[str, BrokerAccountInfo] = {}
        self._primary: str | None = None

    def list_accounts(self) -> list[BrokerAccountInfo]:
        return list(self._accounts.values())

    def add_account(
        self,
        account_id: str,
        broker: str,
        label: str,
        credentials: dict[str, Any],
    ) -> BrokerAccountInfo:
        from flinttrade_gateway.adapter import BROKER_CATALOG
        if broker not in BROKER_CATALOG:
            raise BrokerNotFoundError(f"Broker '{broker}' not found in catalog.")
        info = BrokerAccountInfo(
            account_id=account_id,
            broker=broker,
            label=label,
            status=AccountStatus.connected,
        )
        self._accounts[account_id] = info
        return info

    def remove_account(self, account_id: str) -> None:
        if account_id not in self._accounts:
            raise BrokerNotFoundError(f"Account '{account_id}' not found in registry.")
        del self._accounts[account_id]
        if self._primary == account_id:
            self._primary = None

    def reconnect_account(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
        credential_store: Any | None = None,
    ) -> BrokerAccountInfo:
        if account_id not in self._accounts:
            raise BrokerNotFoundError(f"Account '{account_id}' not found in registry.")
        # Simulate fetching from store when no inline credentials
        if credentials is None and credential_store is not None:
            credentials = credential_store.retrieve(account_id)
        info = self._accounts[account_id]
        return info.model_copy(update={"status": AccountStatus.connected})

    def set_primary(self, account_id: str) -> None:
        if account_id not in self._accounts:
            raise BrokerNotFoundError(f"Account '{account_id}' not found in registry.")
        self._primary = account_id


class MockCredentialStore:
    """Minimal credential store stand-in for unit tests."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def store(
        self,
        account_id: str,
        broker: str,
        label: str,
        credentials: dict[str, Any],
        is_primary: bool = False,
    ) -> None:
        self._data[account_id] = credentials

    def retrieve(self, account_id: str) -> dict[str, Any]:
        if account_id not in self._data:
            raise CredentialError(f"Account not found: {account_id!r}")
        return self._data[account_id]

    def remove(self, account_id: str) -> None:
        self._data.pop(account_id, None)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Flask test app wired with mock registry and credential store."""
    from flask import Flask

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["REGISTRY"] = MockRegistry()
    flask_app.config["CREDENTIAL_STORE"] = MockCredentialStore()
    flask_app.config["OAUTH_STATES"] = {}
    flask_app.register_blueprint(gateway_bp)
    return flask_app


@pytest.fixture
def client(app):
    """Flask test client bound to the test app."""
    return app.test_client()


# ---------------------------------------------------------------------------
# 1. test_list_brokers
# ---------------------------------------------------------------------------


def test_list_brokers(client) -> None:
    """GET /v1/brokers returns every non-sandbox broker."""
    from adapter import BROKER_CATALOG

    response = client.get("/v1/brokers")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    brokers = data["brokers"]
    expected_live_brokers = [info for info in BROKER_CATALOG.values() if not info.is_sandbox]
    assert len(brokers) == len(expected_live_brokers)
    # All returned brokers must not be sandboxes
    assert all(not b["is_sandbox"] for b in brokers)


# ---------------------------------------------------------------------------
# 2. test_list_accounts_empty
# ---------------------------------------------------------------------------


def test_list_accounts_empty(client) -> None:
    """GET /v1/accounts returns an empty list on a fresh registry."""
    response = client.get("/v1/accounts")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["accounts"] == []


# ---------------------------------------------------------------------------
# 3. test_add_account_success
# ---------------------------------------------------------------------------


def test_add_account_success(client) -> None:
    """POST /v1/accounts creates an account and returns 201."""
    payload = {
        "broker": "zerodha",
        "label": "Primary Zerodha",
        "account_id": "ZD001",
        "credentials": {"api_key": "k", "totp": "123456"},
    }
    response = client.post("/v1/accounts", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"
    account = data["account"]
    assert account["account_id"] == "ZD001"
    assert account["broker"] == "zerodha"
    assert account["status"] == "connected"


# ---------------------------------------------------------------------------
# 4. test_add_account_unknown_broker
# ---------------------------------------------------------------------------


def test_add_account_unknown_broker(client) -> None:
    """POST /v1/accounts with unknown broker returns 404."""
    payload = {
        "broker": "nonexistent_broker_xyz",
        "label": "Test",
        "credentials": {},
    }
    response = client.post("/v1/accounts", json=payload)
    assert response.status_code == 404
    data = response.get_json()
    assert data["status"] == "error"
    assert "not found" in data["message"].lower()


# ---------------------------------------------------------------------------
# 5. test_remove_account
# ---------------------------------------------------------------------------


def test_remove_account(client) -> None:
    """DELETE /v1/accounts/<id> removes an account successfully."""
    # First add an account
    client.post(
        "/v1/accounts",
        json={
            "broker": "fyers",
            "label": "Fyers Test",
            "account_id": "FY001",
            "credentials": {"api_key": "k"},
        },
    )
    # Verify it exists
    get_resp = client.get("/v1/accounts")
    assert len(get_resp.get_json()["accounts"]) == 1

    # Remove it
    del_resp = client.delete("/v1/accounts/FY001")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["status"] == "success"

    # Verify gone
    get_resp2 = client.get("/v1/accounts")
    assert get_resp2.get_json()["accounts"] == []


def test_remove_account_not_found(client) -> None:
    """DELETE /v1/accounts/<id> with unknown id returns 404."""
    response = client.delete("/v1/accounts/GHOST99")
    assert response.status_code == 404
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# 6. test_set_primary
# ---------------------------------------------------------------------------


def test_set_primary(client) -> None:
    """POST /v1/accounts/<id>/set-primary promotes the account."""
    # Add account first
    client.post(
        "/v1/accounts",
        json={
            "broker": "angel",
            "label": "Angel One",
            "account_id": "AN001",
            "credentials": {"client_id": "c", "password": "p", "totp": "123456"},
        },
    )
    response = client.post("/v1/accounts/AN001/set-primary")
    assert response.status_code == 200
    assert response.get_json()["status"] == "success"


def test_set_primary_not_found(client) -> None:
    """POST /v1/accounts/<id>/set-primary for unknown account → 404."""
    response = client.post("/v1/accounts/GHOST99/set-primary")
    assert response.status_code == 404
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# 7. test_oauth_start_returns_url_and_state
# ---------------------------------------------------------------------------


def test_oauth_start_returns_url_and_state(client) -> None:
    """POST /v1/auth/oauth/start returns redirect_url and state."""
    response = client.post(
        "/v1/auth/oauth/start",
        json={"broker": "zerodha", "label": "My Zerodha"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert "state" in data
    assert isinstance(data["state"], str)
    assert len(data["state"]) > 20  # token_urlsafe(32) → 43 chars
    assert "redirect_url" in data


# ---------------------------------------------------------------------------
# 8. test_oauth_start_stores_csrf_state
# ---------------------------------------------------------------------------


def test_oauth_start_stores_csrf_state(app, client) -> None:
    """OAuth start stores state in app.config['OAUTH_STATES']."""
    with app.app_context():
        initial_count = len(app.config["OAUTH_STATES"])

    response = client.post(
        "/v1/auth/oauth/start",
        json={"broker": "upstox", "label": "Upstox"},
    )
    assert response.status_code == 200
    state_token = response.get_json()["state"]

    with app.app_context():
        states = app.config["OAUTH_STATES"]
        assert state_token in states
        entry = states[state_token]
        assert entry["broker"] == "upstox"
        assert entry["label"] == "Upstox"
        assert "timestamp" in entry
        assert len(states) == initial_count + 1


# ---------------------------------------------------------------------------
# 9. test_oauth_callback_validates_state
# ---------------------------------------------------------------------------


def test_oauth_callback_validates_state(client) -> None:
    """OAuth callback with an invalid state redirects to /setup?auth=error."""
    response = client.get(
        "/v1/auth/oauth/callback",
        query_string={"state": "completely_invalid_state", "code": "fake_code"},
    )
    # Should redirect
    assert response.status_code in (301, 302)
    location = response.headers.get("Location", "")
    assert "auth=error" in location


def test_oauth_callback_missing_state(client) -> None:
    """OAuth callback with no state parameter redirects to error."""
    response = client.get(
        "/v1/auth/oauth/callback",
        query_string={"code": "some_code"},
    )
    assert response.status_code in (301, 302)
    assert "auth=error" in response.headers.get("Location", "")


def test_oauth_callback_success(app, client) -> None:
    """OAuth callback with a valid state authenticates and redirects to success."""
    # Start OAuth to get a valid state
    start_resp = client.post(
        "/v1/auth/oauth/start",
        json={"broker": "zerodha", "label": "Zerodha OAuth", "account_id": "ZD_OAUTH"},
    )
    assert start_resp.status_code == 200
    state_token = start_resp.get_json()["state"]

    # Hit the callback with the valid state
    callback_resp = client.get(
        "/v1/auth/oauth/callback",
        query_string={"state": state_token, "code": "valid_auth_code"},
    )
    assert callback_resp.status_code in (301, 302)
    location = callback_resp.headers.get("Location", "")
    assert "auth=success" in location

    # State must be consumed (prevent replay)
    with app.app_context():
        assert state_token not in app.config["OAUTH_STATES"]


# ---------------------------------------------------------------------------
# 10. test_credentials_submit_success
# ---------------------------------------------------------------------------


def test_credentials_submit_success(client) -> None:
    """POST /v1/auth/credentials stores credentials and returns account."""
    payload = {
        "broker": "angel",
        "label": "Angel TOTP",
        "account_id": "AN_CRED",
        "credentials": {
            "client_id": "A123456",
            "password": "secret",
            "totp": "654321",
        },
    }
    response = client.post("/v1/auth/credentials", json=payload)
    assert response.status_code == 201
    data = response.get_json()
    assert data["status"] == "success"
    account = data["account"]
    assert account["account_id"] == "AN_CRED"
    assert account["broker"] == "angel"


# ---------------------------------------------------------------------------
# 11. test_credentials_unknown_broker
# ---------------------------------------------------------------------------


def test_credentials_unknown_broker(client) -> None:
    """POST /v1/auth/credentials with unknown broker returns 404."""
    payload = {
        "broker": "ghost_broker",
        "label": "Ghost",
        "credentials": {"api_key": "k"},
    }
    response = client.post("/v1/auth/credentials", json=payload)
    assert response.status_code == 404
    data = response.get_json()
    assert data["status"] == "error"
    assert "not found" in data["message"].lower()


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------


def test_oauth_start_non_oauth_broker(client) -> None:
    """OAuth start for a non-OAuth broker returns 400."""
    response = client.post(
        "/v1/auth/oauth/start",
        json={"broker": "angel"},  # angel uses totp_form, not oauth_redirect
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["status"] == "error"
    assert "OAuth" in data["message"] or "oauth" in data["message"].lower()


def test_oauth_start_unknown_broker(client) -> None:
    """OAuth start with unknown broker returns 404."""
    response = client.post(
        "/v1/auth/oauth/start",
        json={"broker": "totally_unknown"},
    )
    assert response.status_code == 404


def test_add_account_missing_broker_field(client) -> None:
    """POST /v1/accounts without broker field returns 400."""
    response = client.post("/v1/accounts", json={"label": "Test"})
    assert response.status_code == 400


def test_oauth_start_expires_old_states(app, client) -> None:
    """OAuth start purges states older than 10 minutes."""
    with app.app_context():
        # Inject a stale state (timestamp 11 minutes ago)
        stale_token = "stale_token_abc123"
        app.config["OAUTH_STATES"][stale_token] = {
            "broker": "fyers",
            "label": "Old",
            "account_id": "",
            "timestamp": time.time() - 660,  # 11 minutes ago
        }
        len(app.config["OAUTH_STATES"])

    # A new OAuth start should purge the expired entry
    client.post(
        "/v1/auth/oauth/start",
        json={"broker": "dhan", "label": "Dhan"},
    )

    with app.app_context():
        assert stale_token not in app.config["OAUTH_STATES"]
