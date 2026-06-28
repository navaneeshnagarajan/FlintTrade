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
            "host": "http://127.0.0.1:5001",
            "ws_port": "8766",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert response.status_code == 200
    workspace = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace["openalgo"] == {
        "api_key": "openalgo-ui-key",
        "host": "http://127.0.0.1:5001",
        "ws_port": 8766,
    }
    assert app.config["CLIENT"].settings.openalgo_host == "http://127.0.0.1:5001"
    assert app.config["CLIENT"].settings.openalgo_api_key == "openalgo-ui-key"
    assert os.environ.get("OPENALGO_API_KEY") != "openalgo-ui-key"

    get_response = app.test_client().get(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert get_response.status_code == 200
    assert get_response.get_json()["data"] == {
        "api_key_configured": True,
        "api_key_last4": "-key",
        "host": "http://127.0.0.1:5001",
        "ws_port": 8766,
    }

    clear_response = app.test_client().post(
        "/v1/config/openalgo",
        headers={"X-API-Key": "unit-backend-key"},
        json={
            "api_key": "",
            "host": "",
            "ws_port": "8765",
        },
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )

    assert clear_response.status_code == 200
    workspace = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace["openalgo"] == {
        "api_key": "",
        "host": "",
        "ws_port": 8765,
    }
