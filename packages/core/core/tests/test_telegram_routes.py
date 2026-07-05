"""Tests for the FlintTrade Telegram route."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core.telegram_routes import telegram_bp


@pytest.fixture()
def client() -> Iterator[FlaskClient]:
    app = Flask(__name__)
    app.register_blueprint(telegram_bp)
    yield app.test_client()


def test_send_telegram_uses_explicit_in_memory_credentials(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str, bool]] = []

    class FakeBot:
        def __init__(self, config: Any) -> None:
            self.config = config

        def send_message(self, text: str) -> bool:
            calls.append((text, self.config.token, self.config.chat_id, self.config.enabled))
            return True

    monkeypatch.setattr("flinttrade_core.telegram_routes.TelegramBot", FakeBot)

    response = client.post(
        "/api/v1/telegram",
        json={"message": "hello", "bot_token": "tok-test", "chat_id": "123"},
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert response.get_json() == {"status": "success", "data": {"message": "sent"}}
    assert "tok-test" not in body
    assert calls == [("hello", "tok-test", "123", True)]


def test_send_telegram_requires_explicit_credentials_together(client: FlaskClient) -> None:
    response = client.post("/api/v1/telegram", json={"message": "hello", "bot_token": "tok-test"})

    assert response.status_code == 400
    assert response.get_json()["message"] == "bot_token and chat_id are required together"


def test_send_telegram_rejects_disabled_workspace_config(
    client: FlaskClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_automation.telegram_bot import BotConfig

    monkeypatch.setattr(
        "flinttrade_core.telegram_routes.BotConfig.from_env",
        classmethod(lambda cls: BotConfig(token="tok", chat_id="123", enabled=False)),
    )

    response = client.post("/api/v1/telegram", json={"message": "hello"})

    assert response.status_code == 400
    assert response.get_json()["message"] == "Telegram notifications are disabled"


def test_send_telegram_reports_send_failure(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeBot:
        def __init__(self, config: Any) -> None:
            self.config = config

        def send_message(self, text: str) -> bool:
            return False

    monkeypatch.setattr("flinttrade_core.telegram_routes.TelegramBot", FakeBot)

    response = client.post(
        "/api/v1/telegram",
        json={"message": "hello", "bot_token": "tok-test", "chat_id": "123"},
    )

    assert response.status_code == 502
    assert response.get_json()["message"] == "Telegram message could not be sent"
