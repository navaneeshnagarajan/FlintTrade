"""Tests for the UI-persisted n8n bridge settings (n8n_config + route).

Mirrors test_whatsapp_config: secret-file API key with a secret:// reference
in workspace.json, plain non-secret host, redacted reads, preserve-on-absent
semantics, and the bridge's workspace fallback with env precedence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


VALID_HOST = "http://127.0.0.1:5678"
VALID_KEY = "n8n_api_0123456789abcdef"


def _make_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("N8N_HOST", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


def _headers() -> dict[str, str]:
    return {"X-API-Key": "unit-backend-key", "Content-Type": "application/json"}


def test_persist_stores_key_in_secret_file_not_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.n8n_config import (
        N8N_API_KEY_REF,
        persist_n8n_config,
        read_n8n_config,
        resolve_n8n_api_key,
    )

    state = persist_n8n_config({"host": VALID_HOST, "api_key": VALID_KEY})
    assert state == {"host": VALID_HOST, "api_key_set": True}

    secret_path = tmp_path / "secrets" / "n8n_api_key"
    assert secret_path.read_text(encoding="utf-8").strip() == VALID_KEY
    assert resolve_n8n_api_key() == VALID_KEY

    workspace_json = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert VALID_KEY not in json.dumps(workspace_json)
    assert workspace_json["n8n"]["api_key_ref"] == N8N_API_KEY_REF
    assert workspace_json["n8n"]["host"] == VALID_HOST

    assert read_n8n_config() == state


def test_absent_fields_preserve_and_clear_removes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.n8n_config import persist_n8n_config, resolve_n8n_api_key

    persist_n8n_config({"host": VALID_HOST, "api_key": VALID_KEY})

    state = persist_n8n_config({})
    assert state == {"host": VALID_HOST, "api_key_set": True}
    assert resolve_n8n_api_key() == VALID_KEY

    state = persist_n8n_config({"clear_api_key": True})
    assert state == {"host": VALID_HOST, "api_key_set": False}
    assert resolve_n8n_api_key() == ""


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"host": "not-a-url"}, "http"),
        ({"host": "ftp://x/y"}, "http"),
        ({"api_key": "secret://n8n/api_key"}, "reference"),
        ({"api_key": VALID_KEY, "clear_api_key": True}, "mutually exclusive"),
        ({"clear_api_key": "yes"}, "boolean"),
    ],
)
def test_persist_rejects_malformed_payloads(monkeypatch, tmp_path: Path, payload, match) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.n8n_config import persist_n8n_config

    with pytest.raises(ValueError, match=match):
        persist_n8n_config(payload)
    assert not (tmp_path / "secrets" / "n8n_api_key").exists()


def test_bridge_resolves_workspace_settings_with_env_precedence(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("N8N_HOST", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)

    from flinttrade_automation.n8n_bridge import N8nBridge
    from flinttrade_core.n8n_config import persist_n8n_config

    persist_n8n_config({"host": "http://10.0.0.5:5678", "api_key": VALID_KEY})

    bridge = N8nBridge()
    try:
        assert bridge.host == "http://10.0.0.5:5678"
        assert bridge.api_key == VALID_KEY
    finally:
        bridge.close()

    # Environment variables override the workspace values.
    monkeypatch.setenv("N8N_HOST", "http://env-host:5678")
    monkeypatch.setenv("N8N_API_KEY", "env-key")
    bridge = N8nBridge()
    try:
        assert bridge.host == "http://env-host:5678"
        assert bridge.api_key == "env-key"
    finally:
        bridge.close()


def test_route_roundtrip_persists_redacts_and_resets_the_bridge(
    monkeypatch, tmp_path: Path
) -> None:
    app = _make_app(monkeypatch, tmp_path)

    import flinttrade_automation.n8n_routes as n8n_routes

    reset_calls: list[bool] = []
    monkeypatch.setattr(n8n_routes, "reset_n8n_bridge", lambda: reset_calls.append(True))

    with app.test_client() as client:
        resp = client.post(
            "/v1/config/n8n",
            json={"host": VALID_HOST, "api_key": VALID_KEY},
            headers=_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        assert reset_calls == [True]

        get_resp = client.get("/v1/config/n8n", headers=_headers())
        assert get_resp.status_code == 200
        assert get_resp.get_json()["data"] == {"host": VALID_HOST, "api_key_set": True}
        assert VALID_KEY not in get_resp.get_data(as_text=True)

        unauth = client.get("/v1/config/n8n")
        assert unauth.status_code in (401, 403)
