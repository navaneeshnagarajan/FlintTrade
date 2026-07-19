"""Tests for the UI-persisted WhatsApp alert settings (whatsapp_config + route).

Mirrors test_telegram_config: secret-file storage with a secret:// reference
in workspace.json, redacted reads, preserve-on-absent semantics, fail-closed
enabling, legacy plaintext-key migration, and the from_env resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


VALID_URL = "https://hooks.example.net/wa/send?token=abc123"


def _make_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("WHATSAPP_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


def _headers() -> dict[str, str]:
    return {"X-API-Key": "unit-backend-key", "Content-Type": "application/json"}


def test_persist_stores_url_in_secret_file_not_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.whatsapp_config import (
        WHATSAPP_WEBHOOK_URL_REF,
        persist_whatsapp_config,
        read_whatsapp_config,
        resolve_whatsapp_webhook_url,
    )

    state = persist_whatsapp_config({"enabled": True, "webhook_url": VALID_URL})
    assert state == {"enabled": True, "webhook_url_set": True}

    secret_path = tmp_path / "secrets" / "whatsapp_webhook_url"
    assert secret_path.read_text(encoding="utf-8").strip() == VALID_URL
    assert resolve_whatsapp_webhook_url() == VALID_URL

    workspace_json = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert VALID_URL not in json.dumps(workspace_json)
    assert workspace_json["whatsapp"]["webhook_url_ref"] == WHATSAPP_WEBHOOK_URL_REF

    assert read_whatsapp_config() == state


def test_absent_fields_preserve_and_clear_removes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.whatsapp_config import (
        persist_whatsapp_config,
        resolve_whatsapp_webhook_url,
    )

    persist_whatsapp_config({"enabled": True, "webhook_url": VALID_URL})

    # {} → complete no-op.
    state = persist_whatsapp_config({})
    assert state == {"enabled": True, "webhook_url_set": True}
    assert resolve_whatsapp_webhook_url() == VALID_URL

    # Explicit clear (cannot stay enabled without a URL).
    state = persist_whatsapp_config({"enabled": False, "clear_webhook_url": True})
    assert state == {"enabled": False, "webhook_url_set": False}
    assert resolve_whatsapp_webhook_url() == ""


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"enabled": True}, "requires a webhook URL"),
        ({"enabled": False, "webhook_url": "not-a-url"}, "http"),
        ({"enabled": False, "webhook_url": "ftp://host/x"}, "http"),
        ({"enabled": "yes"}, "boolean"),
        (
            {"enabled": False, "webhook_url": VALID_URL, "clear_webhook_url": True},
            "mutually exclusive",
        ),
    ],
)
def test_persist_rejects_malformed_payloads(monkeypatch, tmp_path: Path, payload, match) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.whatsapp_config import persist_whatsapp_config

    with pytest.raises(ValueError, match=match):
        persist_whatsapp_config(payload)
    assert not (tmp_path / "secrets" / "whatsapp_webhook_url").exists()


def test_legacy_plaintext_key_migrates_into_the_secret_file(monkeypatch, tmp_path: Path) -> None:
    """A pre-UI workspace with a plaintext whatsapp.webhook_url keeps working,
    and the first save migrates the URL into the secret file and clears the
    plaintext key from workspace.json."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.whatsapp_config import (
        persist_whatsapp_config,
        read_whatsapp_config,
        resolve_whatsapp_webhook_url,
    )
    from flinttrade_core.workspace import Workspace

    ws = Workspace()
    ws.set("whatsapp.webhook_url", VALID_URL)
    ws.set("whatsapp.enabled", True)

    # Read fallback works before any save.
    assert resolve_whatsapp_webhook_url() == VALID_URL
    assert read_whatsapp_config() == {"enabled": True, "webhook_url_set": True}

    # A preserve-save (no new URL supplied) must NOT lose the legacy URL.
    state = persist_whatsapp_config({"enabled": True})
    assert state == {"enabled": True, "webhook_url_set": True}
    assert resolve_whatsapp_webhook_url() == VALID_URL

    workspace_json = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert workspace_json["whatsapp"]["webhook_url"] == ""
    assert VALID_URL not in json.dumps(workspace_json)


def test_from_env_resolves_secret_and_never_uses_a_ref_literal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("WHATSAPP_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)

    from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
    from flinttrade_core.whatsapp_config import persist_whatsapp_config

    persist_whatsapp_config({"enabled": True, "webhook_url": VALID_URL})
    config = WhatsAppConfig.from_env()
    assert config.webhook_url == VALID_URL
    assert config.enabled is True


def test_from_env_fails_closed_on_a_ref_with_no_secret_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("WHATSAPP_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WHATSAPP_ENABLED", raising=False)

    from flinttrade_automation.whatsapp_alerts import WhatsAppConfig
    from flinttrade_core.workspace import Workspace

    ws = Workspace()
    ws.set("whatsapp.webhook_url", "secret://whatsapp/webhook_url")
    ws.set("whatsapp.enabled", True)

    config = WhatsAppConfig.from_env()
    assert config.webhook_url == ""


def test_route_roundtrip_persists_redacts_and_resets_the_alerter(
    monkeypatch, tmp_path: Path
) -> None:
    app = _make_app(monkeypatch, tmp_path)

    import flinttrade_automation.whatsapp_routes as wa_routes

    reset_calls: list[bool] = []
    monkeypatch.setattr(wa_routes, "reset_whatsapp_alerter", lambda: reset_calls.append(True))

    with app.test_client() as client:
        resp = client.post(
            "/v1/config/whatsapp",
            json={"enabled": True, "webhook_url": VALID_URL},
            headers=_headers(),
        )
        assert resp.status_code == 200, resp.get_json()
        assert reset_calls == [True]

        get_resp = client.get("/v1/config/whatsapp", headers=_headers())
        assert get_resp.status_code == 200
        assert get_resp.get_json()["data"] == {"enabled": True, "webhook_url_set": True}
        assert VALID_URL not in get_resp.get_data(as_text=True)


def test_route_rejects_malformed_payload_and_requires_auth(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with app.test_client() as client:
        resp = client.post(
            "/v1/config/whatsapp",
            json={"enabled": True},
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "requires a webhook URL" in resp.get_json()["message"]

        unauth = client.get("/v1/config/whatsapp")
        assert unauth.status_code in (401, 403)
