"""Tests for packages/engine/src/bracket_routes.py (Flask Blueprint).

Covers POST /api/v1/orders/bracket (place), GET /api/v1/orders/brackets (list),
and DELETE /api/v1/orders/bracket/<id> (cancel) — both happy and error paths.

Note: require_non_explore is bypassed when app.config["TESTING"] = True,
so no JWT minting is required in tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY = {
    "symbol": "NIFTY25APRFUT",
    "exchange": "NFO",
    "action": "BUY",
    "quantity": 50,
    "price": 0,
    "strategy": "Flint",
    "product": "MIS",
}

_BRACKET_BODY = {
    "entry": _ENTRY,
    "stoploss": 22000.0,
    "target": 22500.0,
}


def _make_service(success: bool = True, bracket_id: str = "br-001") -> MagicMock:
    """Build a mock BracketOrderService.

    Args:
        success:    Whether place_bracket should return success.
        bracket_id: UUID to attach to mock bracket objects.

    Returns:
        Configured MagicMock.
    """
    svc = MagicMock()
    bracket = MagicMock()
    bracket.bracket_id = bracket_id
    bracket.to_dict.return_value = {"bracket_id": bracket_id, "status": "active"}

    result = MagicMock()
    result.success = success
    result.message = "OK" if success else "Rejected"
    result.error = None if success else "validation_error"
    result.bracket = bracket if success else None
    svc.place_bracket.return_value = result

    svc.get_active_brackets.return_value = [bracket] if success else []
    svc.get_bracket.return_value = bracket if success else None
    svc.cancel_bracket.return_value = success
    return svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Flask test client with a mock BracketOrderService configured.

    Yields:
        Flask test client.
    """
    from packages.engine.src.bracket_routes import bracket_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["BRACKET_SERVICE"] = _make_service()
    flask_app.register_blueprint(bracket_bp)
    with flask_app.test_client() as c:
        yield c


@pytest.fixture()
def client_no_service():
    """Flask test client without BRACKET_SERVICE (simulates unconfigured state).

    Yields:
        Flask test client.
    """
    from packages.engine.src.bracket_routes import bracket_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(bracket_bp)
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/v1/orders/bracket
# ---------------------------------------------------------------------------


class TestPlaceBracket:
    def test_place_success_returns_201(self, client) -> None:
        """Valid bracket payload returns 201 with bracket details.

        Args:
            client: Flask test client.
        """
        resp = client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert "bracket_id" in data["data"]

    def test_place_missing_entry_returns_400(self, client) -> None:
        """Missing entry field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/api/v1/orders/bracket",
            json={"stoploss": 22000.0, "target": 22500.0},
        )
        assert resp.status_code == 400
        assert "entry" in resp.get_json()["message"]

    def test_place_missing_stoploss_returns_400(self, client) -> None:
        """Missing stoploss field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/api/v1/orders/bracket",
            json={"entry": _ENTRY, "target": 22500.0},
        )
        assert resp.status_code == 400

    def test_place_service_rejection_returns_422(self) -> None:
        """Service-level rejection surfaces as HTTP 422.

        Uses a fresh client with a failure-mode service.
        """
        from packages.engine.src.bracket_routes import bracket_bp

        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        flask_app.config["BRACKET_SERVICE"] = _make_service(success=False)
        flask_app.register_blueprint(bracket_bp)
        with flask_app.test_client() as c:
            resp = c.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 422
        assert resp.get_json()["status"] == "error"

    def test_no_service_returns_503(self, client_no_service) -> None:
        """Missing BRACKET_SERVICE returns HTTP 503.

        Args:
            client_no_service: Flask test client without service config.
        """
        resp = client_no_service.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/v1/orders/brackets
# ---------------------------------------------------------------------------


class TestListBrackets:
    def test_list_active_brackets(self, client) -> None:
        """Active brackets are returned in a list with count.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/orders/brackets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 1
        assert len(data["data"]["brackets"]) == 1

    def test_no_service_returns_503(self, client_no_service) -> None:
        """Missing BRACKET_SERVICE returns HTTP 503 on list.

        Args:
            client_no_service: Flask test client without service config.
        """
        resp = client_no_service.get("/api/v1/orders/brackets")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# DELETE /api/v1/orders/bracket/<id>
# ---------------------------------------------------------------------------


class TestCancelBracket:
    def test_cancel_existing_bracket(self, client) -> None:
        """Cancelling an existing bracket returns 200 with success.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/api/v1/orders/bracket/br-001")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_cancel_nonexistent_bracket_returns_404(self) -> None:
        """Cancel of a non-existent bracket returns HTTP 404.

        Uses a client where get_bracket returns None.
        """
        from packages.engine.src.bracket_routes import bracket_bp

        svc = MagicMock()
        svc.get_bracket.return_value = None
        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        flask_app.config["BRACKET_SERVICE"] = svc
        flask_app.register_blueprint(bracket_bp)
        with flask_app.test_client() as c:
            resp = c.delete("/api/v1/orders/bracket/ghost-id")
        assert resp.status_code == 404

    def test_cancel_already_done_returns_409(self) -> None:
        """Cancel of a completed bracket returns HTTP 409.

        Uses a client where cancel_bracket returns False.
        """
        from packages.engine.src.bracket_routes import bracket_bp

        svc = MagicMock()
        bracket = MagicMock()
        bracket.to_dict.return_value = {"bracket_id": "br-x"}
        svc.get_bracket.return_value = bracket
        svc.cancel_bracket.return_value = False

        flask_app = Flask(__name__)
        flask_app.config["TESTING"] = True
        flask_app.config["BRACKET_SERVICE"] = svc
        flask_app.register_blueprint(bracket_bp)
        with flask_app.test_client() as c:
            resp = c.delete("/api/v1/orders/bracket/br-x")
        assert resp.status_code == 409
