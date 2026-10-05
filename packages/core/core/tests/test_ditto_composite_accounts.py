"""Ditto metadata mutations preserve exact native account identity and freezes."""

from __future__ import annotations

import pytest

from flinttrade_ditto.account_manager import AccountManager, BrokerAccount


@pytest.fixture()
def accounts_app(tmp_path, monkeypatch, backend_lease_factory):
    from flinttrade_core import operations_routes
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_routes import _create_token

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "ditto-composite-test-key")
    monkeypatch.setenv("FLINTTRADE_DEV", "1")
    app = create_flask_app(backend_lease_proof=backend_lease_factory())
    app.config["TESTING"] = True
    with AccountManager(str(tmp_path / "copy-accounts.sqlite")) as manager:
        for adapter in ("dhan", "upstox"):
            manager.add_account(BrokerAccount("primary", adapter, name=adapter))
        monkeypatch.setattr(operations_routes, "_ditto_manager", lambda: manager)
        with app.app_context():
            token = _create_token("ditto-test-operator", mode="explore")
        headers = {"X-API-Key": "ditto-composite-test-key", "Authorization": f"Bearer {token}"}
        yield app, manager, headers


def test_list_exposes_complete_selectors_for_duplicate_account_ids(accounts_app):
    app, _manager, headers = accounts_app
    response = app.test_client().get("/api/v1/ditto/accounts", headers=headers)
    assert response.status_code == 200
    rows = response.get_json()["data"]["accounts"]
    assert [(row["adapter_id"], row["account_id"]) for row in rows] == [
        ("dhan", "primary"),
        ("upstox", "primary"),
    ]
    assert all(row["broker"] == row["adapter_id"] and row["id"] == row["account_id"] for row in rows)


def test_composite_enable_disable_changes_only_the_selected_broker(accounts_app):
    app, manager, headers = accounts_app
    client = app.test_client()
    for adapter in ("dhan", "upstox"):
        response = client.post(f"/api/v1/ditto/accounts/{adapter}/primary/disable", headers=headers)
        assert response.status_code == 200
        assert response.get_json()["data"]["account"]["adapter_id"] == adapter
    response = client.post("/api/v1/ditto/accounts/upstox/primary/enable", headers=headers)
    assert response.status_code == 200
    assert manager.get_account("primary", adapter_id="dhan").enabled is False
    assert manager.get_account("primary", adapter_id="upstox").enabled is True
    assert app.config["DITTO_RUNTIME"] is None


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_ambiguous_legacy_mutation_returns_client_error_and_changes_neither_row(accounts_app, action):
    app, manager, headers = accounts_app
    before = manager.list_accounts()
    response = app.test_client().post(f"/api/v1/ditto/accounts/primary/{action}", headers=headers)
    assert response.status_code == 400
    assert response.get_json()["code"] == "account_selector_required"
    assert manager.list_accounts() == before


@pytest.mark.parametrize(
    "adapter,account,status",
    [("groww", "primary", 404), ("unknown", "primary", 404), ("DHAN", "primary", 400), ("dhan", "bad%20id", 400)],
)
def test_explicit_unknown_or_malformed_selector_never_mutates_another_account(accounts_app, adapter, account, status):
    app, manager, headers = accounts_app
    before = manager.list_accounts()
    response = app.test_client().post(f"/api/v1/ditto/accounts/{adapter}/{account}/disable", headers=headers)
    assert response.status_code == status
    assert manager.list_accounts() == before


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/ditto/accounts/dhan/primary/disable"),
        ("post", "/api/v1/ditto/accounts/upstox/primary/enable"),
        ("delete", "/api/v1/ditto/accounts/dhan/primary"),
    ],
)
def test_composite_mutation_requires_session_auth_before_account_lookup(accounts_app, monkeypatch, method, path):
    from flinttrade_core import operations_routes

    app, manager, _headers = accounts_app
    before = manager.list_accounts()

    def poison_manager():
        pytest.fail("Unauthenticated request looked up copy-account metadata")

    monkeypatch.setattr(operations_routes, "_ditto_manager", poison_manager)
    response = getattr(app.test_client(), method)(path, headers={"X-API-Key": "ditto-composite-test-key"})
    assert response.status_code == 401
    assert manager.list_accounts() == before


def test_composite_delete_preserves_production_freeze_before_store_access(accounts_app, monkeypatch):
    from flinttrade_core import operations_routes

    app, manager, headers = accounts_app
    before = manager.list_accounts()

    def poison_manager():
        pytest.fail("Frozen delete reached account metadata")

    monkeypatch.setattr(operations_routes, "_ditto_manager", poison_manager)
    response = app.test_client().delete("/api/v1/ditto/accounts/dhan/primary", headers=headers)
    assert response.status_code == 503
    assert response.get_json()["error"] == "broker_account_cutover_unavailable"
    assert response.headers["Cache-Control"] == "no-store"
    assert manager.list_accounts() == before


def test_retained_delete_uses_exact_pair_only_when_test_composition_admits_it(accounts_app):
    app, manager, headers = accounts_app
    app.config["BROKER_ACCOUNT_MUTATION_ADMISSION"] = lambda: None
    response = app.test_client().delete("/api/v1/ditto/accounts/dhan/primary", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"]["adapter_id"] == "dhan"
    assert manager.get_account("primary", adapter_id="dhan") is None
    assert manager.get_account("primary", adapter_id="upstox").name == "upstox"


def test_unambiguous_legacy_mutation_resolves_and_publishes_the_exact_pair(accounts_app):
    app, manager, headers = accounts_app
    manager.remove_account("primary", adapter_id="upstox")
    response = app.test_client().post("/api/v1/ditto/accounts/primary/disable", headers=headers)
    assert response.status_code == 200
    row = response.get_json()["data"]["account"]
    assert (row["adapter_id"], row["account_id"]) == ("dhan", "primary")
    assert manager.get_account("primary", adapter_id="dhan").enabled is False


def test_composite_delete_keeps_secret_envelope_observability_bounded():
    from flinttrade_core.request_observability import classify_secret_envelope

    assert classify_secret_envelope("DELETE", "/ft-api/api/v1/ditto/accounts/dhan/primary") == (
        "/api/v1/ditto/accounts/{adapter_id}/{account_id}"
    )


def test_retained_ambiguous_delete_refuses_without_changing_either_row(accounts_app):
    app, manager, headers = accounts_app
    app.config["BROKER_ACCOUNT_MUTATION_ADMISSION"] = lambda: None
    before = manager.list_accounts()
    response = app.test_client().delete("/api/v1/ditto/accounts/primary", headers=headers)
    assert response.status_code == 400
    assert response.get_json()["code"] == "account_selector_required"
    assert manager.list_accounts() == before


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/ditto/accounts/dhan/primary/disable"),
        ("delete", "/api/v1/ditto/accounts/dhan/primary"),
    ],
)
def test_legacy_runtime_with_duplicate_id_refuses_without_stopping_a_sibling(accounts_app, method, path):
    from unittest.mock import MagicMock

    app, manager, headers = accounts_app
    app.config["BROKER_ACCOUNT_MUTATION_ADMISSION"] = lambda: None
    runtime = MagicMock()
    runtime.status.return_value = {
        "active": True,
        "lifecycle": "active",
        "source_account": "primary",
        "target_accounts": [],
    }
    app.config["DITTO_RUNTIME"] = runtime
    before = manager.list_accounts()
    response = getattr(app.test_client(), method)(path, headers=headers)
    assert response.status_code == 503
    runtime.stop.assert_not_called()
    assert manager.list_accounts() == before
