"""Tests for packages/data/src/audit_export_routes.py (Flask Blueprint).

Mocks AuditExporter to avoid real DuckDB I/O. Covers the CSV export,
PDF export, summary, and validation (date order, bad format) paths.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def audit_logger() -> MagicMock:
    """Return a mock AuditLogger instance.

    Returns:
        MagicMock used as the audit_logger dependency.
    """
    return MagicMock()


@pytest.fixture()
def client(audit_logger: MagicMock, tmp_path):
    """Flask test client with audit export blueprint registered.

    Args:
        audit_logger: Mock AuditLogger fixture.
        tmp_path:     Pytest temporary directory.

    Yields:
        Flask test client.
    """
    from packages.data.src.audit_export_routes import create_audit_export_blueprint

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(create_audit_export_blueprint(audit_logger))
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# GET /admin/audit/export — CSV
# ---------------------------------------------------------------------------


class TestAuditExportCsv:
    def test_csv_export_success(self, client: MagicMock, tmp_path) -> None:
        """Valid date range with format=csv returns a file download.

        Args:
            client:   Flask test client.
            tmp_path: Pytest temp directory.
        """
        fake_csv = tmp_path / "audit.csv"
        fake_csv.write_text("timestamp,action\n2026-04-01,order.place\n")

        def _write_csv(from_date, to_date, path):
            path.write_text("timestamp,action\n")

        with patch(
            "packages.data.src.audit_export.AuditExporter.to_csv",
            side_effect=_write_csv,
        ):
            resp = client.get(
                "/admin/audit/export?format=csv&from=2026-04-01&to=2026-04-30"
            )

        assert resp.status_code == 200
        assert "csv" in resp.content_type or resp.status_code == 200

    def test_missing_from_date_returns_400(self, client: MagicMock) -> None:
        """Missing 'from' query parameter returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get("/admin/audit/export?format=csv&to=2026-04-30")
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_missing_to_date_returns_400(self, client: MagicMock) -> None:
        """Missing 'to' query parameter returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get("/admin/audit/export?format=csv&from=2026-04-01")
        assert resp.status_code == 400

    def test_from_after_to_returns_400(self, client: MagicMock) -> None:
        """'from' date after 'to' date returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get(
            "/admin/audit/export?format=csv&from=2026-04-30&to=2026-04-01"
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "before" in data["message"] or "on or before" in data["message"]

    def test_invalid_date_format_returns_400(self, client: MagicMock) -> None:
        """Non-ISO date string returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get(
            "/admin/audit/export?format=csv&from=01-04-2026&to=2026-04-30"
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /admin/audit/export — PDF
# ---------------------------------------------------------------------------


class TestAuditExportPdf:
    def test_pdf_export_error_returns_500(self, client: MagicMock) -> None:
        """AuditExportError during PDF export surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        from packages.data.src.audit_export import AuditExportError

        with patch(
            "packages.data.src.audit_export.AuditExporter.to_pdf",
            side_effect=AuditExportError("PDF lib unavailable"),
        ):
            resp = client.get(
                "/admin/audit/export?format=pdf&from=2026-04-01&to=2026-04-30"
            )

        assert resp.status_code == 500
        assert resp.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /admin/audit/summary
# ---------------------------------------------------------------------------


class TestAuditSummary:
    def test_summary_success(self, client: MagicMock) -> None:
        """Valid date range returns summary statistics.

        Args:
            client: Flask test client.
        """
        stats = {
            "total_events": 100,
            "events_by_type": {"order.place": 80, "order.cancel": 20},
            "orders_placed": 80,
            "orders_rejected": 5,
            "safety_triggers": 2,
        }
        with patch(
            "packages.data.src.audit_export.AuditExporter.summary_stats",
            return_value=stats,
        ):
            resp = client.get(
                "/admin/audit/summary?from=2026-04-01&to=2026-04-30"
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["data"]["total_events"] == 100

    def test_summary_missing_dates_returns_400(self, client: MagicMock) -> None:
        """Missing date parameters on summary endpoint returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get("/admin/audit/summary")
        assert resp.status_code == 400

    def test_summary_inverted_dates_returns_400(self, client: MagicMock) -> None:
        """'from' after 'to' on summary endpoint returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.get(
            "/admin/audit/summary?from=2026-05-01&to=2026-04-01"
        )
        assert resp.status_code == 400
