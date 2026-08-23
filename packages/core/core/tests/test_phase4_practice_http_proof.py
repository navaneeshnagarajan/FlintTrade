"""Phase 4 Practice HTTP proof — real SandboxEngine, not a mock.

Ports the salvageable Claim A from the 2026-08-10 Phase 4 practice-proof
archive (`archive-wip/.../phase4-practice-proof-v3-real`) onto current main.

The archive expected a forged ``X-FlintTrade-Mode: live`` header to lose to a
Practice JWT (HTTP 200). After ``77deb79b`` a contradictory mode header is
rejected 403 before sandbox or router dispatch. This suite pins that
fail-closed behaviour and the frozen-clock 10/11 burst against a real
``SandboxEngine``.

This is not the Phase 4 exit. The market-day Practice run remains a separate
operator gate. Live broker adapters, OpenAlgo and ``BrokerRouter`` stay
unreachable sentinels here.

Run with:
    uv run pytest packages/core/core/tests/test_phase4_practice_http_proof.py -v --import-mode=importlib
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.order_routes import orders_bp
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine

_PRACTICE_BODY = {
    "symbol": "NIFTY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "price": 100.0,
    "product": "MIS",
    "order_type": "MARKET",
}


class _LivePathSentinel:
    """Fail-fast stand-in for live broker / OpenAlgo handles.

    Practice dispatch must never read these config keys. Attribute access is
    counted so a later assertion can prove the live path stayed dark.
    """

    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str) -> object:
        self.accesses.append(name)
        raise RuntimeError(f"live-path sentinel accessed: {name}")


def _practice_token() -> str:
    """Mint a Practice JWT against the module scratch-workspace secret."""
    return _create_token("phase4-proof", mode="practice", live_mode_unlocked=False)


def _practice_headers(**extra: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_practice_token()}",
        "Content-Type": "application/json",
        "X-User-ID": "phase4-proof-user",
    }
    headers.update(extra)
    return headers


def _minimal_practice_app(db_path: Path) -> Flask:
    """Minimal Flask app: real sandbox + limiter, live handles as sentinels."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["DATA_SANDBOX_ENGINE"] = SandboxEngine(
        db_path=str(db_path),
        initial_capital=100_000.0,
    )
    app.config["RATE_LIMITER"] = RateLimiter(global_rate=100, per_user_rate=10)
    app.config["BROKER_ROUTER"] = _LivePathSentinel()
    app.config["CLIENT"] = _LivePathSentinel()
    app.config["OPENALGO_CLIENT"] = _LivePathSentinel()
    app.config["TICK_RECORDER"] = None
    app.register_blueprint(orders_bp)
    return app


@pytest.fixture
def practice_app(tmp_path: Path) -> Flask:
    """Isolated Practice app with its own sandbox database."""
    return _minimal_practice_app(tmp_path / "sandbox.sqlite3")


@pytest.mark.unit
def test_practice_jwt_fills_real_sandbox_without_live_sentinels(practice_app: Flask) -> None:
    """A Practice JWT reaches the real sandbox and never the live handles."""
    client = practice_app.test_client()
    sandbox = practice_app.config["DATA_SANDBOX_ENGINE"]

    resp = client.post(
        "/api/v1/orders/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(),
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "COMPLETE"
    assert body["order_id"]
    orders = sandbox.get_orders()
    assert len(orders) == 1
    assert orders[0]["symbol"] == "NIFTY"
    assert orders[0]["action"] == "BUY"
    assert practice_app.config["BROKER_ROUTER"].accesses == []
    assert practice_app.config["CLIENT"].accesses == []
    assert practice_app.config["OPENALGO_CLIENT"].accesses == []


@pytest.mark.unit
def test_practice_jwt_with_forged_live_header_rejected_before_sandbox(
    practice_app: Flask,
) -> None:
    """A contradictory Live header cannot retarget a Practice JWT."""
    client = practice_app.test_client()
    sandbox = practice_app.config["DATA_SANDBOX_ENGINE"]

    resp = client.post(
        "/api/v1/orders/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(**{"X-FlintTrade-Mode": "live"}),
    )

    assert resp.status_code == 403
    assert "mode" in resp.get_json()["message"].lower()
    assert sandbox.get_orders() == []
    assert practice_app.config["BROKER_ROUTER"].accesses == []
    assert practice_app.config["CLIENT"].accesses == []
    assert practice_app.config["OPENALGO_CLIENT"].accesses == []


@pytest.mark.unit
def test_invalid_jwt_does_not_write_sandbox_rows(practice_app: Flask) -> None:
    """An invalid bearer token is rejected and leaves the sandbox empty."""
    client = practice_app.test_client()
    sandbox = practice_app.config["DATA_SANDBOX_ENGINE"]

    resp = client.post(
        "/api/v1/orders/place",
        json=_PRACTICE_BODY,
        headers={
            "Authorization": "Bearer invalid",
            "Content-Type": "application/json",
        },
    )

    assert resp.status_code in (401, 403)
    assert sandbox.get_orders() == []
    assert practice_app.config["BROKER_ROUTER"].accesses == []


@pytest.mark.unit
def test_routed_live_path_rejects_practice_jwt_before_router(practice_app: Flask) -> None:
    """Selector-bound ``/<broker>/place`` stays live-only and never hits the sentinel."""
    client = practice_app.test_client()

    resp = client.post(
        "/api/v1/orders/dhan/place",
        json=_PRACTICE_BODY,
        headers=_practice_headers(),
    )

    assert resp.status_code in (400, 403)
    assert practice_app.config["BROKER_ROUTER"].accesses == []
    assert practice_app.config["DATA_SANDBOX_ENGINE"].get_orders() == []


@pytest.mark.unit
def test_frozen_clock_21_call_http_burst_uses_real_sandbox(tmp_path: Path) -> None:
    """Twenty-one Practice posts under a frozen clock: ten fills, eleven 429s.

    The limiter is constructed after ``time.monotonic`` is frozen so the
    initial burst is exactly the configured 10/s per-user capacity. Accepted
    rows are persisted by a real ``SandboxEngine``, not a mock.
    """
    frozen = time.monotonic() + 1.0
    with patch("flinttrade_core.rate_limiter.time.monotonic", return_value=frozen):
        app = _minimal_practice_app(tmp_path / "sandbox.sqlite3")
        app.config["RATE_LIMITER"].reset()
        client = app.test_client()
        sandbox = app.config["DATA_SANDBOX_ENGINE"]
        headers = _practice_headers()

        accepted = 0
        rate_limited = 0
        for index in range(21):
            payload = {
                **_PRACTICE_BODY,
                "price": 100.0 + index,
            }
            resp = client.post("/api/v1/orders/place", json=payload, headers=headers)
            if resp.status_code == 200:
                accepted += 1
            elif resp.status_code == 429:
                rate_limited += 1
            else:
                pytest.fail(f"unexpected status {resp.status_code}: {resp.get_json()}")

        assert accepted == 10
        assert rate_limited == 11
        assert len(sandbox.get_orders()) == 10
        assert app.config["BROKER_ROUTER"].accesses == []
        assert app.config["CLIENT"].accesses == []
        assert app.config["OPENALGO_CLIENT"].accesses == []
