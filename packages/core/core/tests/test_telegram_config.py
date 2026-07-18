"""Tests for the UI-persisted Telegram bot settings (telegram_config + route).

Covers the llm_config-mirroring secret discipline: token in a hardened
owner-only secrets file, workspace.json carrying only a ``secret://``
reference, redacted reads, blank-keeps-existing saves, fail-closed enabling,
and the from_env resolution fix (a bare reference string must never be used
as a bot token).
"""

from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

pytestmark = pytest.mark.unit


def _make_app(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "unit-backend-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("unit-test-master-password", encoding="utf-8")
    master_password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


def _headers() -> dict[str, str]:
    return {"X-API-Key": "unit-backend-key", "Content-Type": "application/json"}


VALID_TOKEN = "123456789:AAf1qwertzuiopasdfghjklyxcvbnm12345"


# ---------------------------------------------------------------------------
# telegram_config module
# ---------------------------------------------------------------------------


def test_persist_stores_token_in_secret_file_not_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.telegram_config import (
        TELEGRAM_BOT_TOKEN_REF,
        persist_telegram_config,
        read_telegram_config,
        resolve_telegram_bot_token,
    )

    state = persist_telegram_config(
        {"enabled": True, "chat_id": "-100123456", "bot_token": VALID_TOKEN}
    )
    assert state == {"enabled": True, "chat_id": "-100123456", "bot_token_set": True}

    secret_path = tmp_path / "secrets" / "telegram_bot_token"
    assert secret_path.read_text(encoding="utf-8").strip() == VALID_TOKEN
    assert resolve_telegram_bot_token() == VALID_TOKEN

    workspace_json = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    raw = json.dumps(workspace_json)
    assert VALID_TOKEN not in raw
    assert workspace_json["notifications"]["telegram_bot_token_ref"] == TELEGRAM_BOT_TOKEN_REF

    assert read_telegram_config() == state


def test_blank_token_preserves_existing_and_clear_token_removes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.telegram_config import (
        persist_telegram_config,
        resolve_telegram_bot_token,
    )

    persist_telegram_config({"enabled": True, "chat_id": "42", "bot_token": VALID_TOKEN})
    # Blank token on a later save keeps the stored secret.
    state = persist_telegram_config({"enabled": True, "chat_id": "42", "bot_token": ""})
    assert state["bot_token_set"] is True
    assert resolve_telegram_bot_token() == VALID_TOKEN

    # Explicit clear removes it (and therefore cannot stay enabled).
    state = persist_telegram_config({"enabled": False, "chat_id": "42", "clear_token": True})
    assert state["bot_token_set"] is False
    assert resolve_telegram_bot_token() == ""


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"enabled": True, "chat_id": "42"}, "requires both"),
        ({"enabled": True, "chat_id": "", "bot_token": VALID_TOKEN}, "requires both"),
        ({"enabled": False, "chat_id": "not-a-number"}, "numeric"),
        ({"enabled": False, "bot_token": "secret://telegram/bot_token"}, "does not look like"),
        ({"enabled": False, "bot_token": "https://api.telegram.org/bot123"}, "does not look like"),
        ({"enabled": "yes"}, "boolean"),
        (
            {"enabled": False, "bot_token": VALID_TOKEN, "clear_token": True},
            "mutually exclusive",
        ),
    ],
)
def test_persist_rejects_malformed_payloads(monkeypatch, tmp_path: Path, payload, match) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_core.telegram_config import persist_telegram_config

    with pytest.raises(ValueError, match=match):
        persist_telegram_config(payload)
    # Nothing was written.
    assert not (tmp_path / "secrets" / "telegram_bot_token").exists()


def test_from_env_resolves_stored_secret_and_never_uses_the_ref_literal(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)

    from flinttrade_automation.telegram_bot import BotConfig
    from flinttrade_core.telegram_config import persist_telegram_config

    persist_telegram_config({"enabled": True, "chat_id": "77", "bot_token": VALID_TOKEN})
    config = BotConfig.from_env()
    assert config.token == VALID_TOKEN
    assert config.chat_id == "77"
    assert config.enabled is True


def test_from_env_fails_closed_on_a_legacy_ref_with_no_secret_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)

    from flinttrade_automation.telegram_bot import BotConfig
    from flinttrade_core.workspace import Workspace

    ws = Workspace()
    ws.set("notifications.telegram_bot_token_ref", "secret://telegram/bot_token")
    ws.set("notifications.telegram_chat_id", "77")
    ws.set("notifications.telegram_enabled", True)
    ws.save()

    config = BotConfig.from_env()
    # The pre-fix behaviour used the literal reference string as the token.
    assert config.token == ""


# ---------------------------------------------------------------------------
# /v1/config/telegram route
# ---------------------------------------------------------------------------


def test_route_roundtrip_persists_and_redacts(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with app.test_client() as client:
        resp = client.post(
            "/v1/config/telegram",
            json={"enabled": True, "chat_id": "-100555", "bot_token": VALID_TOKEN},
            headers=_headers(),
        )
        assert resp.status_code == 200, resp.get_json()

        get_resp = client.get("/v1/config/telegram", headers=_headers())
        assert get_resp.status_code == 200
        data = get_resp.get_json()["data"]
        assert data == {"enabled": True, "chat_id": "-100555", "bot_token_set": True}
        assert VALID_TOKEN not in get_resp.get_data(as_text=True)


def test_route_rejects_malformed_payload_with_400(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with app.test_client() as client:
        resp = client.post(
            "/v1/config/telegram",
            json={"enabled": True, "chat_id": ""},
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "requires both" in resp.get_json()["message"]


def test_route_requires_control_auth(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)
    with app.test_client() as client:
        resp = client.get("/v1/config/telegram")
        assert resp.status_code in (401, 403)


def test_route_applies_saved_config_to_the_running_bot(monkeypatch, tmp_path: Path) -> None:
    app = _make_app(monkeypatch, tmp_path)

    class StubBot:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.config = None

        def stop(self) -> None:
            self.calls.append("stop")

        def start_background(self) -> bool:
            self.calls.append("start")
            return True

    bot = StubBot()
    app.config["TELEGRAM_BOT"] = bot

    with app.test_client() as client:
        resp = client.post(
            "/v1/config/telegram",
            json={"enabled": True, "chat_id": "88", "bot_token": VALID_TOKEN},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert "applying" in resp.get_json()["message"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and bot.calls != ["stop", "start"]:
        time.sleep(0.02)
    assert bot.calls == ["stop", "start"]
    assert bot.config is not None
    assert bot.config.token == VALID_TOKEN
    assert bot.config.chat_id == "88"
    assert bot.config.enabled is True
