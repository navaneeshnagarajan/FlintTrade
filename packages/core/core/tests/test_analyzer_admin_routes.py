"""Tests for packages/core/core/src/analyzer_admin_routes.py (Flask Blueprint).

Covers the four admin analyzer endpoints — enable, disable, status, clear —
using a MagicMock as the analyzer dependency.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def analyzer() -> MagicMock:
    """Return a mock APIAnalyzer with all required interface methods.

    Returns:
        MagicMock pre-configured for enable/disable/is_enabled/count/clear_logs.
    """
    m = MagicMock()
    m.is_enabled.return_value = False
    m.count.return_value = 0
    m.clear_logs.return_value = 0
    return m


@pytest.fixture()
def client(analyzer: MagicMock):
    """Flask test client with the analyzer admin blueprint registered.

    Args:
        analyzer: Mock APIAnalyzer instance.

    Yields:
        Flask test client wired up to the analyzer blueprint.
    """
    from flinttrade_core.analyzer_admin_routes import create_analyzer_admin_blueprint

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_analyzer_admin_blueprint(analyzer))
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /admin/analyzer/enable
# ---------------------------------------------------------------------------


class TestAnalyzerEnable:
    def test_enable_returns_ok(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Enable endpoint calls analyzer.enable() and returns enabled=True.

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        resp = client.post("/admin/analyzer/enable")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["enabled"] is True
        analyzer.enable.assert_called_once()

    def test_enable_message_present(self, client: MagicMock) -> None:
        """Enable response body includes a human-readable message field.

        Args:
            client: Flask test client.
        """
        resp = client.post("/admin/analyzer/enable")
        assert "message" in resp.get_json()


# ---------------------------------------------------------------------------
# POST /admin/analyzer/disable
# ---------------------------------------------------------------------------


class TestAnalyzerDisable:
    def test_disable_returns_ok(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Disable endpoint calls analyzer.disable() and returns enabled=False.

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        resp = client.post("/admin/analyzer/disable")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["enabled"] is False
        analyzer.disable.assert_called_once()


# ---------------------------------------------------------------------------
# GET /admin/analyzer/status
# ---------------------------------------------------------------------------


class TestAnalyzerStatus:
    def test_status_disabled(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Status endpoint reflects analyzer.is_enabled() and count().

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        analyzer.is_enabled.return_value = False
        analyzer.count.return_value = 42
        resp = client.get("/admin/analyzer/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["enabled"] is False
        assert data["total_calls"] == 42

    def test_status_enabled(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Status reflects enabled state when analyzer is on.

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        analyzer.is_enabled.return_value = True
        analyzer.count.return_value = 7
        resp = client.get("/admin/analyzer/status")
        data = resp.get_json()
        assert data["enabled"] is True
        assert data["total_calls"] == 7


# ---------------------------------------------------------------------------
# DELETE /admin/analyzer/clear
# ---------------------------------------------------------------------------


class TestAnalyzerClear:
    def test_clear_all_logs(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Clear without query param deletes all rows.

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        analyzer.clear_logs.return_value = 99
        resp = client.delete("/admin/analyzer/clear")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["rows_deleted"] == 99
        analyzer.clear_logs.assert_called_once_with(older_than_days=None)

    def test_clear_with_older_than_days(self, client: MagicMock, analyzer: MagicMock) -> None:
        """Clear with older_than_days passes the value to analyzer.

        Args:
            client:   Flask test client.
            analyzer: Mock analyzer fixture.
        """
        analyzer.clear_logs.return_value = 5
        resp = client.delete("/admin/analyzer/clear?older_than_days=30")
        assert resp.status_code == 200
        analyzer.clear_logs.assert_called_once_with(older_than_days=30)

    def test_clear_invalid_days_returns_400(self, client: MagicMock) -> None:
        """Non-integer older_than_days returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/admin/analyzer/clear?older_than_days=abc")
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_clear_negative_days_returns_400(self, client: MagicMock) -> None:
        """Negative older_than_days returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/admin/analyzer/clear?older_than_days=-1")
        assert resp.status_code == 400
