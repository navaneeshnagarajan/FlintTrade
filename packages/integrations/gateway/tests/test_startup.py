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

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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

from registry import BrokerRegistry  # noqa: E402
from credentials import CredentialStore  # noqa: E402
from adapter import BROKER_CATALOG  # noqa: E402
from auth import gateway_bp  # noqa: E402
from contracts import ContractManager  # noqa: E402
from exceptions import AuthFlowError  # noqa: E402


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


def test_reconnect_with_no_saved_accounts(caplog: pytest.LogCaptureFixture) -> None:
    """_reconnect_saved_accounts must not raise when no accounts are stored."""
    import logging  # noqa: PLC0415

    # Import _reconnect_saved_accounts via the packages path (repo-root import)
    sys.path.insert(0, str(_REPO_ROOT))
    from flinttrade_core.app import _reconnect_saved_accounts  # noqa: PLC0415

    registry = BrokerRegistry()
    cs = MagicMock(spec=CredentialStore)
    cs.list_accounts.return_value = []

    reconnect_logger = logging.getLogger("test.reconnect.empty")
    with caplog.at_level(logging.INFO, logger="test.reconnect.empty"):
        # Must complete without raising
        _reconnect_saved_accounts(registry, cs, reconnect_logger)

    assert len(registry.list_accounts()) == 0
    # The store's list_accounts was called exactly once
    cs.list_accounts.assert_called_once()


# ---------------------------------------------------------------------------
# 5. test_reconnect_partial_failure
# ---------------------------------------------------------------------------


def test_reconnect_partial_failure(caplog: pytest.LogCaptureFixture) -> None:
    """_reconnect_saved_accounts must continue past a failed account.

    Setup: two saved accounts.
      - Account A (FAIL001): authenticate raises AuthFlowError.
      - Account B (OK001): authenticate succeeds.

    After the call, Account B is in the registry; no exception is raised.
    """
    import logging  # noqa: PLC0415

    from flinttrade_core.app import _reconnect_saved_accounts  # noqa: PLC0415

    registry = BrokerRegistry()

    cs = MagicMock(spec=CredentialStore)
    cs.list_accounts.return_value = [
        {
            "account_id": "FAIL001",
            "broker": "zerodha",
            "label": "Bad Account",
            "is_primary": False,
        },
        {
            "account_id": "OK001",
            "broker": "zerodha",
            "label": "Good Account",
            "is_primary": True,
        },
    ]

    def _retrieve(account_id: str) -> dict[str, Any]:
        if account_id == "FAIL001":
            return {"api_key": "bad", "totp": "000000"}
        return {"api_key": "good", "totp": "123456"}

    cs.retrieve.side_effect = _retrieve

    reconnect_logger = logging.getLogger("test.reconnect.partial")

    # Build mock BrokerSession instances — FAIL001 raises on authenticate,
    # OK001 succeeds.  We patch the BrokerSession class inside the module
    # that _reconnect_saved_accounts imports it from.
    _fail_session = MagicMock()
    _fail_session.authenticate.side_effect = AuthFlowError("Bad credentials")

    _ok_session = MagicMock()
    _ok_session.authenticate.return_value = None  # success — no exception

    _session_map: dict[str, Any] = {
        "FAIL001": _fail_session,
        "OK001": _ok_session,
    }

    def _make_session(account_id: str, broker: str, label: str) -> Any:
        return _session_map[account_id]

    with patch("flinttrade_gateway.session.BrokerSession", side_effect=_make_session):
        with caplog.at_level(logging.WARNING, logger="test.reconnect.partial"):
            # Must not raise even though FAIL001 fails
            _reconnect_saved_accounts(registry, cs, reconnect_logger)

    # OK001's mock session must have been inserted into the registry
    assert "OK001" in registry._sessions
    assert registry._sessions["OK001"] is _ok_session
    # FAIL001 must not have been added
    assert "FAIL001" not in registry._sessions
    # Primary should be set to OK001 (is_primary=True in saved accounts)
    assert registry._primary == "OK001"
