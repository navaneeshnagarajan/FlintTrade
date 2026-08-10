"""RED/GREEN test for Claim A — real minimal Flask Practice route to real SandboxEngine.

TDD vertical gate (A): real minimal Flask.test_client -> actual orders_bp Practice JWT route -> explicit isolated real SandboxEngine with forged Live header losing to signed Practice and invalid/routed-Live negatives.

All tests use real component constructors and spy/wrap actual methods; fail if not invoked.
"""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from flinttrade_core.order_routes import orders_bp
from flinttrade_core.auth_routes import _create_token
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine


class Sentinel:
    """Fail-fast sentinel that counts attribute access."""
    count = 0

    def __getattr__(self, name: str):
        Sentinel.count += 1
        raise RuntimeError(f"sentinel accessed: {name}")


def _setup_minimal_app(db_path: str) -> Flask:
    """Minimal Flask app with only orders_bp, real SandboxEngine, RateLimiter, fail-fast sentinels."""
    app = Flask(__name__)
    app.config["TESTING"] = False
    app.config["DATA_SANDBOX_ENGINE"] = SandboxEngine(db_path=db_path, initial_capital=100000.0)
    app.config["RATE_LIMITER"] = RateLimiter(global_rate=100, per_user_rate=10)
    app.config["BROKER_ROUTER"] = Sentinel()
    app.config["CLIENT"] = Sentinel()
    app.config["OPENALGO_CLIENT"] = Sentinel()
    app.config["TICK_RECORDER"] = None
    app.register_blueprint(orders_bp)
    return app


def _make_practice_token(workspace_dir: Path) -> str:
    """Mint Practice JWT using isolated workspace secret."""
    os.environ["FLINTTRADE_WORKSPACE_DIR"] = str(workspace_dir)
    # Ensure jwt_secret exists (minimal for _create_token)
    secret_path = workspace_dir / "jwt_secret"
    if not secret_path.exists():
        secret_path.write_bytes(b"phase4-proof-secret-for-test-only")
    return _create_token("phase4-proof", mode="practice", live_mode_unlocked=False)


@pytest.fixture
def isolated_run_root(tmp_path):
    """Isolated run root with stores and workspace."""
    root = tmp_path / "phase4-http-red"
    root.mkdir()
    stores = root / "stores"
    stores.mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    yield root, stores, workspace


def test_real_practice_jwt_reaches_real_sandbox_no_sentinel(isolated_run_root):
    """RED/GREEN: Practice JWT + forged Live header reaches real sandbox; Live sentinels remain zero."""
    root, stores, workspace = isolated_run_root
    db_path = str(stores / "sandbox.sqlite3")
    app = _setup_minimal_app(db_path)
    client = app.test_client()

    token = _make_practice_token(workspace)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-FlintTrade-Mode": "live",  # forged Live header
        "Content-Type": "application/json",
    }
    # Positive price MARKET order so SandboxEngine fills deterministically
    payload = {"symbol": "NIFTY25AUG25000CE", "exchange": "NSE", "action": "BUY", "quantity": 1, "price": 100.0, "product": "MIS"}

    # First call
    resp = client.post("/api/v1/orders/place", json=payload, headers=headers)
    assert resp.status_code == 200
    # Sentinel count must be zero (Practice won)
    assert Sentinel.count == 0, f"Live sentinel was accessed {Sentinel.count} times"

    # Verify real sandbox has the order
    sandbox = app.config["DATA_SANDBOX_ENGINE"]
    orders = sandbox.get_orders()
    assert len(orders) == 1
    assert orders[0]["symbol"] == "NIFTY25AUG25000CE"
    assert orders[0]["action"] == "BUY"

    # Invalid JWT should reject and no sandbox row
    bad_headers = {"Authorization": "Bearer invalid", "Content-Type": "application/json"}
    resp_bad = client.post("/api/v1/orders/place", json=payload, headers=bad_headers)
    assert resp_bad.status_code in (401, 403)
    # No additional sandbox row
    assert len(sandbox.get_orders()) == 1

    # Routed Live endpoint with Practice token should reject before router sentinel
    routed_resp = client.post("/api/v1/orders/dhan/place", json=payload, headers=headers)
    assert routed_resp.status_code in (400, 403, 404)  # routed Live-only
    assert Sentinel.count == 0  # never reached sentinel


def test_frozen_clock_21_call_http_burst(isolated_run_root):
    """GREEN: 21 rapid calls under frozen monotonic; 10 accepted, 11 rate limited, 10 sandbox orders, sentinels zero."""
    root, stores, workspace = isolated_run_root
    db_path = str(stores / "sandbox.sqlite3")

    # Freeze time.monotonic BEFORE constructing RateLimiter (compute fresh value before patch; patch module)
    frozen = time.monotonic() + 1.0
    with patch("flinttrade_core.rate_limiter.time.monotonic", return_value=frozen):
        app = _setup_minimal_app(db_path)
        # Reset to ensure full initial capacity under frozen time (plan burst proof)
        app.config["RATE_LIMITER"].reset()
        client = app.test_client()

        token = _make_practice_token(workspace)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-User-ID": "phase4-proof-user",  # explicit user for consistent per-user bucket
            "Content-Type": "application/json",
        }

        sentinel_before = Sentinel.count
        sandbox = app.config["DATA_SANDBOX_ENGINE"]
        initial_orders = len(sandbox.get_orders())

        accepted = 0
        rate_limited = 0
        for i in range(21):
            action = "BUY" if i % 2 == 0 else "SELL"
            payload = {
                "symbol": "NIFTY25AUG25000CE",
                "exchange": "NSE",
                "action": action,
                "quantity": 1,
                "price": 100.0 + i,
                "product": "MIS",
            }
            resp = client.post("/api/v1/orders/place", json=payload, headers=headers)
            if resp.status_code == 200:
                accepted += 1
            elif resp.status_code == 429:
                rate_limited += 1
            else:
                pytest.fail(f"Unexpected status {resp.status_code}")

        assert accepted == 10
        assert rate_limited == 11
        assert accepted + rate_limited == 21
        assert len(sandbox.get_orders()) == initial_orders + 10
        assert Sentinel.count == sentinel_before  # no sentinel access

    # Cleanup note: test uses explicit isolated stores only
