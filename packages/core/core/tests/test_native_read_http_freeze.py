"""The composed HTTP boundary refuses reads before any broker authority lookup."""

from __future__ import annotations

from flask import Config
import pytest

from flinttrade_core.app import create_flask_app


class AuthorityPoison(Config):
    """Record dependency access even if a handler catches the raised exception."""

    def __init__(self, current: Config) -> None:
        super().__init__(current.root_path)
        self.update(current)
        self.calls: list[str] = []

    def get(self, key: str, default: object = None) -> object:
        if key in {"REGISTRY", "NATIVE_ADAPTERS", "BROKER_ROUTER", "BROKER_CLIENT", "CREDENTIAL_STORE"}:
            self.calls.append(key)
            raise AssertionError("Frozen HTTP reads cannot access broker authority")
        return super().get(key, default)


@pytest.fixture
def composed_app(monkeypatch):
    monkeypatch.setenv("FLINTTRADE_API_KEY", "synthetic-read-freeze-key")
    app = create_flask_app()
    app.config["TESTING"] = True
    poisoned = AuthorityPoison(app.config)
    app.config = poisoned
    return app, poisoned


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("kind", ["positions", "funds", "profile", "ltp", "option_chain", "instruments", "unsupported"])
def test_authenticated_http_reads_are_frozen_without_broker_dependencies(composed_app, method: str, kind: str) -> None:
    app, poison = composed_app
    response = app.test_client().open(
        f"/api/v1/native/accounts/dhan/synthetic/{kind}",
        method=method,
        headers={"X-API-Key": "synthetic-read-freeze-key"},
    )
    assert response.status_code == 409
    assert response.headers["Cache-Control"] == "no-store"
    if method == "GET":
        assert response.json == {
            "status": "error",
            "message": "Native broker HTTP reads are unavailable until the read cutover",
        }
    else:
        assert response.data == b""
    assert poison.calls == []


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_authentication_precedes_native_read_freeze(composed_app, method: str) -> None:
    app, poison = composed_app
    response = app.test_client().open("/api/v1/native/accounts/dhan/synthetic/positions", method=method)
    assert response.status_code == 401
    assert poison.calls == []
