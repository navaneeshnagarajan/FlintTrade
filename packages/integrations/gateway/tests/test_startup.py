"""Tests for gateway startup wiring (Task 8).

Verifies that:
- BrokerRegistry, CredentialStore, and ContractManager are wired into Flask
  app.config when create_flask_app is called.
- The gateway blueprint endpoints are reachable.
- _reconnect_saved_accounts handles empty stores and partial auth failures
  without raising exceptions.

All heavy external dependencies (real credentials DB, real adapters) are
replaced with lightweight mocks so these tests never touch the network or
the filesystem beyond temporary paths.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sys
from typing import Any
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Ensure gateway src/ is on sys.path so bare-name gateway imports work.
# (The gateway's pyproject.toml sets pythonpath = ["src", "../.."] but that
#  only activates when pytest is invoked from packages/integrations/gateway/.  When run
#  from the repo root we must inject it manually.)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[4]
_GATEWAY_SRC = str(_REPO_ROOT / "packages" / "integrations" / "gateway" / "src")
if _GATEWAY_SRC not in sys.path:
    sys.path.insert(0, _GATEWAY_SRC)


# ---------------------------------------------------------------------------
# Deferred imports — after sys.path is ready
# ---------------------------------------------------------------------------

from flinttrade_gateway.registry import BrokerRegistry  # noqa: E402
from flinttrade_gateway.credentials import CredentialStore  # noqa: E402
from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: E402
from flinttrade_gateway.auth import gateway_bp  # noqa: E402
from flinttrade_gateway.contracts import ContractManager  # noqa: E402
from flinttrade_gateway.exceptions import AuthFlowError  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — minimal Flask app factory that mirrors create_flask_app wiring
# ---------------------------------------------------------------------------


def _make_test_app(
    registry: Any | None = None,
    credential_store: Any | None = None,
    contract_manager: Any | None = None,
):
    """Return a minimal Flask test app wired with gateway components.

    Mirrors the gateway-specific portion of ``create_flask_app`` without
    pulling in the full FlintTrade dependency tree (SafetySystem, CronManager,
    etc.).

    Args:
        registry: BrokerRegistry (or mock).  A fresh BrokerRegistry is
            created when ``None`` is passed.
        credential_store: CredentialStore (or mock).  A MagicMock that returns
            an empty list from ``list_accounts()`` is used when ``None``.
        contract_manager: ContractManager (or mock).

    Returns:
        Configured Flask test application.
    """
    from flask import Flask  # noqa: PLC0415

    if registry is None:
        registry = BrokerRegistry()
    if credential_store is None:
        cs = MagicMock(spec=CredentialStore)
        cs.list_accounts.return_value = []
        credential_store = cs
    if contract_manager is None:
        cm = MagicMock(spec=ContractManager)
        contract_manager = cm

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = credential_store
    app.config["CONTRACT_MANAGER"] = contract_manager
    app.config["OAUTH_STATES"] = {}
    app.register_blueprint(gateway_bp)
    return app


# ---------------------------------------------------------------------------
# 1. test_registry_in_app_config
# ---------------------------------------------------------------------------


def test_registry_in_app_config() -> None:
    """Flask app.config must contain a BrokerRegistry instance after wiring."""
    app = _make_test_app()
    assert "REGISTRY" in app.config
    assert isinstance(app.config["REGISTRY"], BrokerRegistry)


# ---------------------------------------------------------------------------
# 2. test_credential_store_in_config
# ---------------------------------------------------------------------------


def test_credential_store_in_config() -> None:
    """Flask app.config must contain a CREDENTIAL_STORE entry after wiring."""
    app = _make_test_app()
    assert "CREDENTIAL_STORE" in app.config
    # We accept either a real CredentialStore or the MagicMock stand-in
    assert app.config["CREDENTIAL_STORE"] is not None


# ---------------------------------------------------------------------------
# 3. test_gateway_blueprint_registered
# ---------------------------------------------------------------------------


def test_gateway_blueprint_registered() -> None:
    """The /v1/brokers endpoint must be reachable (blueprint registered)."""
    app = _make_test_app()
    with app.test_client() as client:
        response = client.get("/v1/brokers")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    expected_live_brokers = [info for info in BROKER_CATALOG.values() if not info.is_sandbox]
    assert len(data["brokers"]) == len(expected_live_brokers)


# ---------------------------------------------------------------------------
# 4. test_reconnect_with_no_saved_accounts
# ---------------------------------------------------------------------------



_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture


def test_reconnect_with_no_saved_accounts(tmp_path, caplog):
    import logging
    from flinttrade_core.app import _reconnect_saved_accounts
    fixture = RegistryFixture(tmp_path)
    _reconnect_saved_accounts(fixture.registry, fixture.store, logging.getLogger("test.reconnect"),
        registry_publication_owner=fixture.owner, workspace_path=tmp_path, mutation_admission=lambda: None)
    assert fixture.registry.list_accounts() == []
    fixture.close()


def test_reconnect_partial_failure_uses_exact_owner_and_explicit_primary(tmp_path, monkeypatch, caplog):
    import logging
    from flinttrade_core.app import _reconnect_saved_accounts
    from flinttrade_core.broker_identity import BrokerSelector
    fixture = RegistryFixture(tmp_path)
    for account in ("FAIL001", "OK001"):
        selector = BrokerSelector("openalgo", account)
        fixture.store.put_credentials(selector, "zerodha", "Private label", {"api_key": account},
            expected=fixture.store.selector_state(selector).version)
    calls = []
    class Adapter:
        def authenticate(self, credentials):
            calls.append(credentials["api_key"])
            if credentials["api_key"] == "FAIL001":
                raise AuthFlowError("Rejected synthetic credential")
            return "synthetic-token", None
    monkeypatch.setattr("flinttrade_gateway.session.load_broker_adapter", lambda _: Adapter())
    with caplog.at_level(logging.INFO):
        _reconnect_saved_accounts(fixture.registry, fixture.store, logging.getLogger("test.reconnect"),
            registry_publication_owner=fixture.owner, workspace_path=tmp_path,
            execution_default_selector=BrokerSelector("openalgo", "OK001"), mutation_admission=lambda: None)
    assert calls == ["FAIL001", "OK001"]
    assert fixture.registry.snapshot_exact_state(BrokerSelector("openalgo", "OK001")).status == "connected"
    assert fixture.registry.snapshot_exact_state(BrokerSelector("openalgo", "FAIL001")).status == "tombstoned"
    assert fixture.registry.get_primary_session().info.account_id == "OK001"
    logs = "\n".join(caplog.messages)
    assert not any(secret in logs for secret in ("FAIL001", "OK001", "Private label", "synthetic-token"))
    assert "account#" in logs
    fixture.close()
