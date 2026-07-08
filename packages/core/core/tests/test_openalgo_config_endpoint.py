"""Tests for UI-driven OpenAlgo configuration persistence."""

from __future__ import annotations

import json
import os


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
    # The loopback GET returns the RAW api_key so the memory-only frontend store
    # can rehydrate it after a reload (the browser already holds it in memory for
    # every OpenAlgo request); status fields are retained alongside it.
    assert get_response.get_json()["data"] == {
        "api_key": "openalgo-ui-key",
        "api_key_configured": True,
        "api_key_last4": "-key",
        "host": "http://127.0.0.1",
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


def test_openalgo_config_get_rejects_non_loopback_and_never_leaks_key(monkeypatch, tmp_path):
    """The GET returns the raw api_key, so a non-loopback caller must be refused."""
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
        headers={"X-API-Key": "unit-backend-key"},
        environ_overrides={"REMOTE_ADDR": "203.0.113.5"},
    )

    assert response.status_code == 403
    assert "secret-bridge-key" not in response.get_data(as_text=True)


def test_openalgo_config_endpoint_rejects_invalid_ports(monkeypatch, tmp_path):
    """OpenAlgo config saves fail before invalid ports enter workspace.json."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    (tmp_path / "master_password").write_text("pytest-master-password", encoding="utf-8")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True

    response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={"port": "70000"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 400
    assert "between 1 and 65535" in response.get_json()["message"]
