"""Tests for the gateway rate-limit routes — GET/PUT /v1/rate-limits."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from flask import Flask

from flinttrade_gateway.auth import gateway_bp
from flinttrade_gateway.rate_limiter import BrokerRateLimiter

pytestmark = pytest.mark.unit


class _FakeRouter:
    """Exposes a live rate limiter the way BrokerRouter does."""

    def __init__(self, limiter: BrokerRateLimiter):
        self._limiter = limiter

    @property
    def rate_limiter(self) -> BrokerRateLimiter:
        return self._limiter


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Workspace persistence must write to a throwaway home, not ~/.flinttrade.
    monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    limiter = BrokerRateLimiter({"openalgo": {"order": 10.0, "data": 5.0}})
    flask_app.config["BROKER_ROUTER"] = _FakeRouter(limiter)
    flask_app.register_blueprint(gateway_bp)
    flask_app.config["_TEST_LIMITER"] = limiter
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_get_returns_live_limits(client):
    resp = client.get("/v1/rate-limits")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["limits"]["openalgo"] == {"order": 10.0, "data": 5.0}


def test_get_is_empty_when_no_limiter():
    flask_app = Flask(__name__)
    flask_app.register_blueprint(gateway_bp)
    resp = flask_app.test_client().get("/v1/rate-limits")
    assert resp.status_code == 200
    assert resp.get_json()["limits"] == {}


def test_put_applies_live_and_keeps_untouched_kind(app, client):
    resp = client.put("/v1/rate-limits", json={"broker_id": "openalgo", "order": 3})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["limits"]["openalgo"]["order"] == 3.0
    assert body["limits"]["openalgo"]["data"] == 5.0  # untouched
    # The change reached the live limiter.
    assert app.config["_TEST_LIMITER"]._rate("openalgo", "order") == 3.0


def test_put_persists_to_workspace(client, tmp_path):
    client.put("/v1/rate-limits", json={"broker_id": "dhan", "order": 8, "data": 4})
    ws_file = tmp_path / "workspace.json"
    assert ws_file.exists()
    saved = json.loads(ws_file.read_text())
    assert saved["brokers"]["rate_limits"]["dhan"] == {"order": 8.0, "data": 4.0}


def test_put_does_not_follow_atomic_set_with_stale_full_save(client, monkeypatch):
    from flinttrade_core.workspace import Workspace

    redundant_save = Mock()
    monkeypatch.setattr(Workspace, "save", redundant_save)

    response = client.put("/v1/rate-limits", json={"broker_id": "dhan", "order": 8})

    assert response.status_code == 200
    redundant_save.assert_not_called()


def test_concurrent_broker_updates_do_not_overwrite_each_other(app, tmp_path, monkeypatch):
    from flinttrade_core.workspace import Workspace

    original_set = Workspace.set
    stale_writers_ready = threading.Barrier(2)

    def synchronised_legacy_set(self, key, value):
        stale_writers_ready.wait(timeout=2.0)
        return original_set(self, key, value)

    monkeypatch.setattr(Workspace, "set", synchronised_legacy_set)

    def update(broker_id: str) -> int:
        with app.test_client() as thread_client:
            response = thread_client.put(
                "/v1/rate-limits",
                json={"broker_id": broker_id, "order": 8},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(update, ("dhan", "upstox")))

    assert statuses == [200, 200]
    saved = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert saved["brokers"]["rate_limits"] == {
        "dhan": {"order": 8.0},
        "upstox": {"order": 8.0},
    }


def test_put_requires_broker_id(client):
    resp = client.put("/v1/rate-limits", json={"order": 5})
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_put_rejects_negative_rate(client):
    resp = client.put("/v1/rate-limits", json={"broker_id": "openalgo", "order": -1})
    assert resp.status_code == 400


def test_put_requires_at_least_one_field(client):
    resp = client.put("/v1/rate-limits", json={"broker_id": "openalgo"})
    assert resp.status_code == 400
