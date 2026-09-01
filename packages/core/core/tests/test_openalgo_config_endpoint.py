"""Tests for UI-driven OpenAlgo configuration persistence."""

from __future__ import annotations

import json
import logging
import os
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_openalgo_config_requires_auth_after_operator_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].is_setup = MagicMock(return_value=True)
    Workspace().set("openalgo.api_key", "operator-bridge-secret")

    response = app.test_client().get(
        "/v1/config/openalgo",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 401
    assert "operator-bridge-secret" not in response.get_data(as_text=True)


def test_openalgo_config_pre_setup_status_never_returns_raw_key(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].is_setup = MagicMock(return_value=False)
    Workspace().set("openalgo.api_key", "pre-setup-bridge-secret")

    response = app.test_client().get(
        "/v1/config/openalgo",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert "api_key" not in response.get_json()["data"]
    assert "pre-setup-bridge-secret" not in response.get_data(as_text=True)


def test_openalgo_config_operator_session_can_rehydrate_raw_key(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core import auth_routes
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].is_setup = MagicMock(return_value=True)
    Workspace().set("openalgo.api_key", "operator-session-secret")
    monkeypatch.setattr(auth_routes, "decode_token", lambda _token: {"type": "session"})

    response = app.test_client().get(
        "/v1/config/openalgo",
        headers={"Authorization": "Bearer signed-operator-session"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["api_key"] == "operator-session-secret"


def test_openalgo_config_endpoint_persists_telegram_username(monkeypatch, tmp_path):
    """The UI config surface can provide the username required by /telegram/notify."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"telegram_username": "linked-trader"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    workspace = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace["openalgo"]["telegram_username"] == "linked-trader"
    assert app.config["CLIENT"].settings.openalgo_telegram_username == "linked-trader"

    get_response = app.test_client().get(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert get_response.status_code == 200
    assert get_response.get_json()["data"]["telegram_username"] == "linked-trader"


def test_openalgo_config_telegram_save_keeps_env_bridge_endpoint(monkeypatch, tmp_path):
    """A Telegram-only save must not redirect OpenAlgo traffic onto localhost defaults."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.setenv("OPENALGO_HOST", "http://bridge.example:5000")
    monkeypatch.setenv("OPENALGO_PORT", "5000")
    monkeypatch.setenv("OPENALGO_WS_PORT", "8765")
    monkeypatch.setenv("OPENALGO_API_KEY", "env-bridge-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"telegram_username": "linked-trader"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert app.config["CLIENT"].settings.openalgo_telegram_username == "linked-trader"
    assert app.config["CLIENT"].settings.openalgo_host == "http://bridge.example:5000"
    assert app.config["CLIENT"].settings.openalgo_api_key == "env-bridge-key"
    assert app.config["CLIENT"]._base == "http://bridge.example:5000/api/v1"


def test_openalgo_config_endpoint_initialises_fresh_workspace(monkeypatch, tmp_path):
    """A native first run can save OpenAlgo settings without a pre-existing workspace.json."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_HOST", raising=False)
    monkeypatch.delenv("OPENALGO_PORT", raising=False)
    monkeypatch.delenv("OPENALGO_WS_PORT", raising=False)
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={
            "api_key": "openalgo-ui-key",
            "host": "http://127.0.0.1",
            "port": "5001",
            "ws_port": "8766",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    workspace = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace["openalgo"] == {
        "api_key": "openalgo-ui-key",
        "host": "http://127.0.0.1",
        "port": 5001,
        "ws_port": 8766,
    }
    assert app.config["CLIENT"].settings.openalgo_host == "http://127.0.0.1"
    assert app.config["CLIENT"].settings.openalgo_port == 5001
    assert app.config["CLIENT"]._base == "http://127.0.0.1:5001/api/v1"
    assert app.config["CLIENT"].settings.openalgo_api_key == "openalgo-ui-key"
    assert os.environ.get("OPENALGO_API_KEY") != "openalgo-ui-key"

    get_response = app.test_client().get(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert get_response.status_code == 200
    # An authenticated loopback GET returns the raw api_key so the memory-only
    # frontend store can rehydrate it after a reload; status fields remain too.
    assert get_response.get_json()["data"] == {
        "api_key": "openalgo-ui-key",
        "api_key_configured": True,
        "api_key_last4": "-key",
        "host": "http://127.0.0.1",
        "telegram_username": "",
        "port": 5001,
        "ws_port": 8766,
    }

    clear_response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={
            "api_key": "",
            "host": "",
            "port": "5000",
            "ws_port": "8765",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert clear_response.status_code == 200
    workspace = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace["openalgo"] == {
        "api_key": "",
        "host": "",
        "port": 5000,
        "ws_port": 8765,
    }


def test_openalgo_config_hot_reload_reconfigures_the_shared_client_in_place(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient

    shared_client = OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="old-openalgo-key")
    )
    app = create_flask_app(client=shared_client)
    app.config["TESTING"] = True
    shared_router_client = app.config["OPENALGO_CLIENT"]

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={
            "api_key": "rotated-openalgo-key",
            "host": "https://openalgo.example",
            "port": 5443,
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert app.config["CLIENT"] is shared_client
    assert app.config["OPENALGO_CLIENT"] is shared_router_client is shared_client
    assert shared_client.settings.openalgo_api_key == "rotated-openalgo-key"
    assert shared_client._base == "https://openalgo.example:5443/api/v1"


def test_openalgo_config_unauthenticated_remote_get_rejected_without_leaking_key(monkeypatch, tmp_path):
    """A non-loopback GET without credentials is refused before reading secrets."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": "secret-bridge-key", "host": "http://127.0.0.1"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    response = app.test_client().get(
        "/v1/config/openalgo",
        environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
    )

    assert response.status_code == 403
    assert "secret-bridge-key" not in response.get_data(as_text=True)


def test_openalgo_config_authenticated_remote_get_rehydrates_key(monkeypatch, tmp_path):
    """A remote web terminal with a session JWT may rehydrate its OpenAlgo connection."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core import auth_routes
    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["AUTH_SERVICE"].is_setup = MagicMock(return_value=True)
    Workspace().set("openalgo.api_key", "tailnet-session-secret")
    monkeypatch.setattr(auth_routes, "decode_token", lambda _token: {"type": "session"})

    response = app.test_client().get(
        "/v1/config/openalgo",
        headers={"Authorization": "Bearer signed-operator-session"},
        environ_overrides={"REMOTE_ADDR": "100.64.0.5"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["api_key"] == "tailnet-session-secret"


def test_openalgo_config_authenticated_remote_post_still_rejected(monkeypatch, tmp_path):
    """Writes stay loopback-only even for an authenticated remote caller."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": "remote-write-attempt", "host": "http://127.0.0.1"},
        environ_overrides={"REMOTE_ADDR": "100.64.0.5"},
    )

    assert response.status_code == 403
    assert Workspace().get("openalgo.api_key", "") != "remote-write-attempt"


def test_openalgo_config_endpoint_rejects_invalid_ports(monkeypatch, tmp_path):
    """OpenAlgo config saves fail before invalid ports enter workspace.json."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": "must-not-persist", "host": "https://invalid.local", "port": "70000"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 400
    assert "between 1 and 65535" in response.get_json()["message"]
    assert Workspace().get("openalgo.api_key", "") != "must-not-persist"
    assert Workspace().get("openalgo.host", "") != "https://invalid.local"


def test_openalgo_config_endpoint_rejects_non_object_json(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json=[{"api_key": "must-not-be-accepted"}],
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "status": "error",
        "message": "Request body must be a JSON object",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"host": "not-a-url"},
        {"host": "http://"},
        {"api_key": "your_openalgo_api_key_here"},
    ],
)
def test_openalgo_config_endpoint_validates_candidate_before_persisting(monkeypatch, tmp_path, payload):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    before = Workspace().as_dict()

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json=payload,
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "OpenAlgo settings are invalid"
    assert Workspace().as_dict() == before


def test_openalgo_config_endpoint_reconfigures_active_capture_and_desktop_redaction_key(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    recorder = MagicMock()
    runtime = MagicMock()
    app.config["TICK_RECORDER"] = recorder
    app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={
            "api_key": "rotated-openalgo-key",
            "host": "https://openalgo.local",
            "port": 5001,
            "ws_port": 9876,
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    recorder.reconfigure_connection.assert_called_once_with(
        ws_url="wss://openalgo.local:9876",
        api_key="rotated-openalgo-key",
    )
    runtime.update_api_key.assert_called_once_with("rotated-openalgo-key")
    assert app.config["TICK_CAPTURE_ERROR"] == ""


def test_openalgo_config_endpoint_reports_redacted_partial_capture_reconfiguration(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    old_api_key = "previous-openalgo-key"
    api_key = "rotated-openalgo-key"
    app = create_flask_app()
    app.config["TESTING"] = True
    old_client = MagicMock()
    old_client.settings.openalgo_api_key = old_api_key
    old_client.close = AsyncMock()
    app.config["CLIENT"] = old_client
    recorder = MagicMock()
    recorder.reconfigure_connection.side_effect = RuntimeError(
        f"capture rejected old={old_api_key} new={api_key}"
    )
    runtime = MagicMock()
    app.config["TICK_RECORDER"] = recorder
    app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    caplog.set_level(logging.WARNING, logger="flinttrade")

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": api_key, "host": "http://127.0.0.1", "ws_port": 9876},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    body = response.get_json()
    assert response.status_code == 200
    assert body["status"] == "partial"
    assert body["data"]["client_reloaded"] is True
    assert body["data"]["tick_capture_reconfigured"] is False
    assert "tick_capture_diagnostic" not in body["data"]
    assert app.config["CLIENT"].settings.openalgo_api_key == api_key
    assert app.config["TICK_CAPTURE_ERROR"] == "capture rejected old=[redacted] new=[redacted]"
    runtime.update_api_key.assert_called_once_with(api_key)
    assert api_key not in response.get_data(as_text=True)
    assert old_api_key not in response.get_data(as_text=True)
    assert api_key not in caplog.text
    assert old_api_key not in caplog.text


def test_openalgo_config_endpoint_leaves_disabled_capture_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    runtime = MagicMock()
    app.config["TICK_CAPTURE_ENABLED"] = False
    app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": "new-key", "ws_port": 9876},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"
    runtime.update_api_key.assert_not_called()


def test_openalgo_config_endpoint_preserves_unexpected_capture_death(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    old_api_key = "old-capture-key"
    new_api_key = "new-capture-key"
    app = create_flask_app()
    app.config["TESTING"] = True
    old_client = MagicMock()
    old_client.settings.openalgo_api_key = old_api_key
    old_client.close = AsyncMock()
    app.config["CLIENT"] = old_client
    recorder = MagicMock()
    runtime = MagicMock()
    app.config["TICK_RECORDER"] = recorder
    app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    def die_during_reload(**_kwargs) -> None:
        app.config.pop("TICK_RECORDER", None)
        app.config["TICK_CAPTURE_ERROR"] = f"recorder died using {old_api_key} and {new_api_key}"

    recorder.reconfigure_connection.side_effect = die_during_reload
    caplog.set_level(logging.WARNING, logger="flinttrade")

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": new_api_key, "ws_port": 9876},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "partial"
    assert response.get_json()["data"]["tick_capture_reconfigured"] is False
    assert app.config["TICK_CAPTURE_ERROR"] == "recorder died using [redacted] and [redacted]"
    runtime.update_api_key.assert_called_once_with(new_api_key)
    assert old_api_key not in caplog.text
    assert new_api_key not in caplog.text
    assert new_api_key not in response.get_data(as_text=True)


def test_openalgo_config_endpoint_reports_enabled_failed_capture_requires_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config.update(TESTING=True, TICK_CAPTURE_ENABLED=True, TICK_CAPTURE_ERROR="recorder stopped")

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"api_key": "new-key", "ws_port": 9876},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "partial"
    assert response.get_json()["data"]["tick_capture_reconfigured"] is False
    assert app.config["TICK_CAPTURE_ERROR"] == "recorder stopped"


def test_openalgo_config_endpoint_serialises_concurrent_persist_and_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.workspace import Workspace

    app = create_flask_app()
    app.config["TESTING"] = True
    recorder = MagicMock()
    app.config["TICK_RECORDER"] = recorder
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    original_update = Workspace.update

    def controlled_update(self, updater):
        def observe(config):
            result = updater(config)
            openalgo = config.get("openalgo", {})
            api_key = openalgo.get("api_key") if isinstance(openalgo, dict) else None
            if api_key == "first-key":
                first_entered.set()
                # Generous: the releasing main thread can be slow on a loaded
                # CI runner; only the SHORT non-entry window below carries the
                # serialisation claim.
                assert release_first.wait(10)
            elif api_key == "second-key":
                second_entered.set()
            return result

        return original_update(self, observe)

    monkeypatch.setattr(Workspace, "update", controlled_update)
    responses: dict[str, object] = {}

    def post(name: str) -> None:
        responses[name] = app.test_client().post(
            "/v1/config/openalgo",
            headers={"X-API-Key": "unit-backend-key"},
            json={"api_key": f"{name}-key"},
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )

    first = threading.Thread(target=post, args=("first",))
    second = threading.Thread(target=post, args=("second",))
    first.start()
    # Generous entry window — request dispatch under a loaded runner can take
    # well over a second; this wait is liveness, not the invariant.
    assert first_entered.wait(10)
    second.start()
    # THE invariant: while first holds the workspace transaction, second must
    # not enter its update. Short window by design.
    assert not second_entered.wait(0.25)
    release_first.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive()
    assert not second.is_alive()
    assert second_entered.is_set()
    assert responses["first"].status_code == 200
    assert responses["second"].status_code == 200
    assert Workspace().get("openalgo.api_key") == "second-key"
    assert app.config["CLIENT"].settings.openalgo_api_key == "second-key"
    assert recorder.reconfigure_connection.call_args_list[-1].kwargs["api_key"] == "second-key"
