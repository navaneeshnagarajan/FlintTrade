"""Tests for packages/engine/src/freeze_routes.py (Flask Blueprint).

Covers GET/POST /v1/admin/freeze and GET /v1/admin/freeze/blocks — both the
happy path (manager wired up) and the 503 path (manager absent).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def manager() -> MagicMock:
    """Return a mock QuantityFreezeManager.

    Returns:
        MagicMock with all_limits, set_limit, recent_blocks methods.
    """
    m = MagicMock()
    m.all_limits.return_value = []
    m.recent_blocks.return_value = []
    return m


@pytest.fixture()
def client(manager: MagicMock):
    """Flask test client with freeze_manager set on the app object.

    Args:
        manager: Mock freeze manager fixture.

    Yields:
        Flask test client.
    """
    from packages.engine.src.freeze_routes import freeze_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.freeze_manager = manager  # type: ignore[attr-defined]
    flask_app.register_blueprint(freeze_bp)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def client_no_manager():
    """Flask test client without freeze_manager set (simulates unconfigured state).

    Yields:
        Flask test client.
    """
    from packages.engine.src.freeze_routes import freeze_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(freeze_bp)
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# GET /v1/admin/freeze  — list limits
# ---------------------------------------------------------------------------


class TestListLimits:
    def test_empty_limits(self, client: MagicMock) -> None:
        """Empty limits list is returned correctly.

        Args:
            client: Flask test client.
        """
        resp = client.get("/v1/admin/freeze")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["limits"] == []
        assert data["data"]["count"] == 0

    def test_populated_limits(self, client: MagicMock, manager: MagicMock) -> None:
        """Populated limits from manager are surfaced in the response.

        Args:
            client:  Flask test client.
            manager: Mock freeze manager.
        """
        manager.all_limits.return_value = [
            {"symbol": "NIFTY", "exchange": "NFO", "max_qty": 1800}
        ]
        resp = client.get("/v1/admin/freeze")
        data = resp.get_json()
        assert data["data"]["count"] == 1
        assert data["data"]["limits"][0]["symbol"] == "NIFTY"

    def test_no_manager_returns_503(self, client_no_manager) -> None:
        """Missing freeze manager returns HTTP 503.

        Args:
            client_no_manager: Flask test client without freeze_manager.
        """
        resp = client_no_manager.get("/v1/admin/freeze")
        assert resp.status_code == 503
        assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /v1/admin/freeze  — set limit
# ---------------------------------------------------------------------------


class TestSetLimit:
    def test_set_limit_success(self, client: MagicMock, manager: MagicMock) -> None:
        """Valid payload calls manager.set_limit and returns success.

        Args:
            client:  Flask test client.
            manager: Mock freeze manager.
        """
        resp = client.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "exchange": "NFO", "max_qty": 1800},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["symbol"] == "NIFTY"
        assert data["data"]["max_qty"] == 1800
        manager.set_limit.assert_called_once_with("NIFTY", "NFO", 1800)

    def test_missing_symbol_returns_400(self, client: MagicMock) -> None:
        """Missing symbol field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/admin/freeze",
            json={"exchange": "NFO", "max_qty": 1800},
        )
        assert resp.status_code == 400
        assert "symbol" in resp.get_json()["message"]

    def test_missing_exchange_returns_400(self, client: MagicMock) -> None:
        """Missing exchange field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "max_qty": 1800},
        )
        assert resp.status_code == 400
        assert "exchange" in resp.get_json()["message"]

    def test_missing_max_qty_returns_400(self, client: MagicMock) -> None:
        """Missing max_qty field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "exchange": "NFO"},
        )
        assert resp.status_code == 400
        assert "max_qty" in resp.get_json()["message"]

    def test_invalid_max_qty_returns_400(self, client: MagicMock) -> None:
        """Non-integer max_qty returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "exchange": "NFO", "max_qty": "lots"},
        )
        assert resp.status_code == 400

    def test_value_error_from_manager_returns_400(self, client: MagicMock, manager: MagicMock) -> None:
        """ValueError from manager.set_limit surfaces as HTTP 400.

        Args:
            client:  Flask test client.
            manager: Mock that raises ValueError.
        """
        manager.set_limit.side_effect = ValueError("max_qty must be positive")
        resp = client.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "exchange": "NFO", "max_qty": -1},
        )
        assert resp.status_code == 400

    def test_no_manager_returns_503(self, client_no_manager) -> None:
        """Missing freeze manager on POST returns HTTP 503.

        Args:
            client_no_manager: Flask test client without freeze_manager.
        """
        resp = client_no_manager.post(
            "/v1/admin/freeze",
            json={"symbol": "NIFTY", "exchange": "NFO", "max_qty": 1800},
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /v1/admin/freeze/blocks
# ---------------------------------------------------------------------------


class TestRecentBlocks:
    def test_returns_empty_blocks(self, client: MagicMock) -> None:
        """Empty blocks list is returned when no orders have been blocked.

        Args:
            client: Flask test client.
        """
        resp = client.get("/v1/admin/freeze/blocks")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["blocks"] == []
        assert data["data"]["count"] == 0

    def test_returns_block_entries(self, client: MagicMock, manager: MagicMock) -> None:
        """Blocked orders from manager are surfaced in the response.

        Args:
            client:  Flask test client.
            manager: Mock freeze manager with populated blocks.
        """
        manager.recent_blocks.return_value = [
            {"symbol": "BANKNIFTY", "exchange": "NFO", "qty_attempted": 3600}
        ]
        resp = client.get("/v1/admin/freeze/blocks")
        data = resp.get_json()
        assert data["data"]["count"] == 1

    def test_no_manager_returns_503(self, client_no_manager) -> None:
        """Missing freeze manager returns HTTP 503 for blocks endpoint.

        Args:
            client_no_manager: Flask test client without freeze_manager.
        """
        resp = client_no_manager.get("/v1/admin/freeze/blocks")
        assert resp.status_code == 503
