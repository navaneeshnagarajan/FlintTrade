"""Practice restore stores fills as records and does not admit them."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from flinttrade_data.sandbox_engine import RESTORED_FROM_BACKUP, SandboxEngine
from flinttrade_engine.laya import reset_process_laya_for_tests


pytestmark = pytest.mark.unit


@pytest.fixture()
def restore_app(tmp_path, monkeypatch):
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    with patch("flinttrade_core.auth_routes._get_auth_service") as mock:
        from flinttrade_core.app import create_flask_app
        from flinttrade_core.auth_service import AuthService

        svc = AuthService(db_path=tmp_path / "auth.db")
        mock.return_value = svc
        app = create_flask_app()
        app.config["TESTING"] = True
        app.config["RATELIMIT_ENABLED"] = False
        limiter = app.config.get("LIMITER")
        if limiter is not None:
            limiter.enabled = False
        engine = SandboxEngine(db_path=":memory:")
        app.config["DATA_SANDBOX_ENGINE"] = engine
        with app.test_client() as client:
            yield client, svc, engine
        engine.close()


def _setup(client) -> None:
    created = client.post(
        "/v1/auth/setup",
        json={
            "username": "nav",
            "email": "nav@example.com",
            "password": "StrongP@ss123!",
            "pin": "123456",
        },
        headers={"Content-Type": "application/json"},
    )
    assert created.status_code == 201


def _practice_headers() -> dict[str, str]:
    from flinttrade_core.auth_routes import _create_token

    return {
        "Authorization": f"Bearer {_create_token('nav', mode='practice')}",
        "Content-Type": "application/json",
    }


def _backup() -> str:
    return json.dumps(
        {
            "schema_version": 2,
            "capital": {"initial": 100_000.0, "current": 100_000.0},
            "positions": [
                {
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "product": "MIS",
                    "net_qty": 1,
                    "avg_price": 1500.0,
                }
            ],
            "orders": [
                {
                    "order_id": "o1",
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 1500.0,
                    "product": "MIS",
                    "status": "COMPLETE",
                    "strategy": "original",
                }
            ],
            "trades": [
                {
                    "trade_id": "t1",
                    "order_id": "o1",
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 1500.0,
                    "product": "MIS",
                    "strategy": "original",
                    "traded_at": 1_700_000_000,
                }
            ],
            "pnl_history": [],
        }
    )


def test_practice_restore_marks_fills_and_does_not_admit(restore_app) -> None:
    from flinttrade_engine.laya import process_laya

    client, _svc, engine = restore_app
    _setup(client)
    reset_process_laya_for_tests()
    placed = {"count": 0}
    original_place = engine.place_order

    def _place(*args, **kwargs):
        placed["count"] += 1
        return original_place(*args, **kwargs)

    engine.place_order = _place
    resp = client.post(
        "/v1/sandbox/import",
        json={"data": _backup()},
        headers=_practice_headers(),
    )
    assert resp.status_code == 200, resp.get_json()
    trades = engine.get_trades()
    assert len(trades) == 1
    assert trades[0]["strategy"] == RESTORED_FROM_BACKUP
    assert trades[0]["symbol"] == "INFY"
    positions = engine.get_positions()
    assert len(positions) == 1
    assert positions[0]["restored"] is True
    assert placed["count"] == 0
    assert process_laya().decision_log() == ()


def test_restore_outside_practice_is_refused(restore_app, monkeypatch) -> None:
    from flinttrade_core.auth_routes import _create_token

    client, _svc, engine = restore_app
    _setup(client)
    explore = {
        "Authorization": f"Bearer {_create_token('nav', mode='explore')}",
        "Content-Type": "application/json",
    }
    refused = client.post("/v1/sandbox/import", json={"data": _backup()}, headers=explore)
    assert refused.status_code == 403
    assert refused.get_json()["message"] == "Restore is available in Practice Mode only."
    assert engine.get_trades() == []

    monkeypatch.setenv("FLINTTRADE_API_KEY", "tester-api-key")
    keyed = client.post(
        "/v1/sandbox/import",
        json={"data": _backup()},
        headers={"Content-Type": "application/json", "X-API-Key": "tester-api-key"},
    )
    assert keyed.status_code == 403
    assert keyed.get_json()["message"] == "Restore is available in Practice Mode only."
    assert engine.get_trades() == []

    signed_out = client.post(
        "/v1/sandbox/import",
        json={"data": _backup()},
        headers={"Content-Type": "application/json"},
    )
    assert signed_out.status_code == 401
    assert engine.get_trades() == []


def test_reset_backup_imports_and_pending_orders_do_not_fill(restore_app) -> None:
    """A reset snapshot is a valid restore, and its resting orders stay resting."""
    client, _svc, engine = restore_app
    _setup(client)
    limit_order = engine.place_order(
        "INFY",
        "NSE",
        "BUY",
        1,
        100.0,
        order_type="LIMIT",
        strategy="limit-desk",
    )
    stop_order = engine.place_order(
        "INFY",
        "NSE",
        "BUY",
        1,
        100.0,
        order_type="SL",
        trigger_price=90.0,
        strategy="stop-desk",
    )
    stop_market = engine.place_order(
        "INFY",
        "NSE",
        "BUY",
        1,
        100.0,
        order_type="SL-M",
        trigger_price=90.0,
        strategy="stop-market-desk",
    )
    assert limit_order["status"] == "PENDING"
    assert stop_order["status"] == "PENDING"
    assert stop_market["status"] == "PENDING"
    backup = engine.reset()
    assert "reset_at" in backup
    resp = client.post(
        "/v1/sandbox/import",
        json={"data": json.dumps(backup)},
        headers=_practice_headers(),
    )
    assert resp.status_code == 200, resp.get_json()
    orders = engine.get_orders()
    assert len(orders) == 3
    assert {row["strategy"] for row in orders} == {RESTORED_FROM_BACKUP}
    assert {row["status"] for row in orders} == {"PENDING"}
    # 95 is through the limit and both stop triggers. None of them may fill.
    assert engine.check_pending_fills({"NSE:INFY": 95.0}) == []
    assert {row["status"] for row in engine.get_orders()} == {"PENDING"}


def test_restore_still_rejects_fields_outside_the_schema(restore_app) -> None:
    client, _svc, engine = restore_app
    _setup(client)
    resp = client.post(
        "/v1/sandbox/import",
        json={"data": json.dumps({"schema_version": 2, "reset_at": "2026-01-01T00:00:00+00:00", "note": "no"})},
        headers=_practice_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "The backup does not match the Practice schema."
    assert engine.get_trades() == []


def test_restore_rejects_a_backup_outside_the_schema(restore_app) -> None:
    client, _svc, engine = restore_app
    _setup(client)
    resp = client.post(
        "/v1/sandbox/import",
        json={"data": json.dumps({"schema_version": 9, "note": "no"})},
        headers=_practice_headers(),
    )
    assert resp.status_code == 400
    assert resp.get_json()["message"] == "The backup does not match the Practice schema."
    assert engine.get_trades() == []
