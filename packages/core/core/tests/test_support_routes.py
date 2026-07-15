"""Tests for the operator-controlled support diagnostics surface."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from flask import Flask

from flinttrade_core.support_routes import support_bp, support_diagnostics


class _FakeErrorLog:
    def __init__(self, rows: list[dict[str, Any]], *, total: int | None = None) -> None:
        self.rows = rows
        self.total = len(rows) if total is None else total
        self.metadata_limits: list[int] = []

    def recent_metadata(self, limit: int = 100) -> list[dict[str, Any]]:
        self.metadata_limits.append(limit)
        return self.rows[:limit]

    def count(self) -> int:
        return self.total


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(support_bp)

    @app.get("/v1/accounts/<account_id>/orders/<order_id>")
    def _dynamic_order(account_id: str, order_id: str) -> dict[str, str]:
        return {"account_id": account_id, "order_id": order_id}

    return app


def test_diagnostics_aggregate_safe_error_metadata_without_raw_payloads(app: Flask) -> None:
    now = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
    secret = "credential-value-that-must-never-leave"
    app.config["ERROR_LOG"] = _FakeErrorLog(
        [
            {
                "timestamp": now.isoformat(),
                "route": f"https://127.0.0.1:5173/trade?token={secret}",
                "method": "CLIENT",
                "status_code": 0,
                "request_body": {"api_key": secret},
                "error_class": "TypeError",
                "error_message": secret,
                "traceback": f"trace {secret}",
                "user_id": "personal-account-id",
                "entry_id": "raw-entry-id",
            },
            {
                "timestamp": (now - timedelta(minutes=3)).isoformat(),
                "route": "/trade/private-route-id?account_id=private",
                "method": "client",
                "status_code": 0,
                "error_class": "TypeError",
            },
        ],
        total=8,
    )

    response = app.test_client().get("/v1/support/diagnostics")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()["data"]
    assert body["schema_version"] == 1
    assert body["errors"]["available"] is True
    assert body["errors"]["total"] == 8
    assert body["errors"]["sampled"] == 2
    assert body["errors"]["groups"] == [
        {
            "route": "/trade",
            "method": "CLIENT",
            "status_code": 0,
            "error_class": "TypeError",
            "occurrences": 2,
            "first_seen": (now - timedelta(minutes=3)).isoformat(),
            "last_seen": now.isoformat(),
        }
    ]
    encoded = json.dumps(body)
    assert secret not in encoded
    assert "private" not in encoded
    assert "personal-account-id" not in encoded
    assert "raw-entry-id" not in encoded
    for excluded in ("request_body", "error_message", "traceback", "user_id", "entry_id"):
        assert excluded not in encoded


def test_diagnostics_degrade_honestly_when_error_log_is_unavailable(app: Flask) -> None:
    response = app.test_client().get("/v1/support/diagnostics")

    assert response.status_code == 200
    errors = response.get_json()["data"]["errors"]
    assert errors == {"available": False, "total": 0, "sampled": 0, "groups": []}


def test_diagnostics_degrade_honestly_when_error_log_read_fails(app: Flask) -> None:
    class _BrokenErrorLog:
        def recent_metadata(self, limit: int = 100) -> list[dict[str, Any]]:
            del limit
            raise RuntimeError("database path must stay private")

    app.config["ERROR_LOG"] = _BrokenErrorLog()

    response = app.test_client().get("/v1/support/diagnostics")

    assert response.status_code == 200
    encoded = json.dumps(response.get_json())
    assert "database path must stay private" not in encoded
    assert response.get_json()["data"]["errors"] == {
        "available": False,
        "total": 0,
        "sampled": 0,
        "groups": [],
    }


def test_diagnostics_replace_dynamic_backend_identifiers_with_route_template(app: Flask) -> None:
    account_id = "private-account-123"
    order_id = "private-order-456"
    app.config["ERROR_LOG"] = _FakeErrorLog(
        [
            {
                "timestamp": "2026-07-14T09:30:00+00:00",
                "route": f"/v1/accounts/{account_id}/orders/{order_id}",
                "method": "GET",
                "status_code": 500,
                "error_class": "RuntimeError",
            }
        ]
    )

    response = app.test_client().get("/v1/support/diagnostics")

    encoded = json.dumps(response.get_json())
    group = response.get_json()["data"]["errors"]["groups"][0]
    assert group["route"] == "/v1/accounts/<account_id>/orders/<order_id>"
    assert account_id not in encoded
    assert order_id not in encoded


def test_diagnostics_bound_recent_rows_and_aggregate_groups(app: Flask) -> None:
    rows = [
        {
            "timestamp": f"2026-07-14T09:{index % 60:02d}:00+00:00",
            "route": f"/v1/route/{index}",
            "method": "GET",
            "status_code": 500,
            "error_class": f"RuntimeError{index}",
        }
        for index in range(140)
    ]
    error_log = _FakeErrorLog(rows, total=140)
    app.config["ERROR_LOG"] = error_log

    response = app.test_client().get("/v1/support/diagnostics")

    errors = response.get_json()["data"]["errors"]
    assert error_log.metadata_limits == [100]
    assert errors["sampled"] == 100
    assert len(errors["groups"]) == 50


def test_diagnostics_require_the_error_read_scope() -> None:
    assert getattr(support_diagnostics, "__required_scope__", None) == "admin.errors.read"
