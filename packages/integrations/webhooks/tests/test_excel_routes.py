"""Tests for packages/integrations/webhooks/src/excel_routes.py — Excel export/import endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_webhooks.excel_routes as mod
from flinttrade_webhooks.excel_bridge import ExcelBridgeError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mock_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.export_to_excel.return_value = "/tmp/export.xlsx"
    bridge.create_portfolio_report.return_value = "/tmp/portfolio.xlsx"
    bridge.import_from_excel.return_value = [{"symbol": "NIFTY", "qty": 50}]
    bridge.export_to_bytes.return_value = b"PK\x03\x04fake-xlsx-bytes"
    return bridge


@pytest.fixture()
def app(tmp_path):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["EXCEL_OUTPUT_DIR"] = str(tmp_path)
    mod.init_excel_routes(_mock_bridge())
    flask_app.register_blueprint(mod.excel_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /api/v1/integration/excel/export
# ---------------------------------------------------------------------------


def test_export_ok(client):
    """200 with file_path and row count."""
    rows = [{"symbol": "NIFTY", "qty": 50}, {"symbol": "TCS", "qty": 10}]
    resp = client.post(
        "/api/v1/integration/excel/export",
        json={"data": rows, "sheet_name": "Positions"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["rows"] == 2


def test_export_data_not_list(client):
    """400 when data is not a list."""
    resp = client.post(
        "/api/v1/integration/excel/export",
        json={"data": "bad"},
    )
    assert resp.status_code == 400


def test_export_bridge_error(app):
    """500 on ExcelBridgeError."""
    bridge = _mock_bridge()
    bridge.export_to_excel.side_effect = ExcelBridgeError("openpyxl not installed")
    mod.init_excel_routes(bridge)
    with app.test_client() as c:
        resp = c.post(
            "/api/v1/integration/excel/export",
            json={"data": [{"a": 1}]},
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/integration/excel/export/download
# ---------------------------------------------------------------------------


def test_export_download_streams_attachment(client):
    """Streams the .xlsx bytes with an attachment Content-Disposition header."""
    rows = [{"symbol": "NIFTY", "qty": 50}]
    resp = client.post(
        "/api/v1/integration/excel/export/download",
        json={"data": rows, "sheet_name": "Positions", "filename": "positions.xlsx"},
    )
    assert resp.status_code == 200
    assert resp.mimetype == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["Content-Disposition"]
    assert "positions.xlsx" in resp.headers["Content-Disposition"]
    assert resp.data == b"PK\x03\x04fake-xlsx-bytes"


def test_export_download_appends_xlsx_and_strips_traversal(client):
    """A filename without extension gets .xlsx; path traversal is stripped."""
    resp = client.post(
        "/api/v1/integration/excel/export/download",
        json={"data": [{"a": 1}], "filename": "../../etc/passwd"},
    )
    assert resp.status_code == 200
    disp = resp.headers["Content-Disposition"]
    assert "passwd.xlsx" in disp
    assert ".." not in disp and "/" not in disp.split("filename=")[1]


def test_export_download_data_not_list(client):
    """400 when data is not a list."""
    resp = client.post(
        "/api/v1/integration/excel/export/download",
        json={"data": "bad"},
    )
    assert resp.status_code == 400


def test_export_download_bridge_error(app):
    """500 on ExcelBridgeError (e.g. openpyxl missing)."""
    bridge = _mock_bridge()
    bridge.export_to_bytes.side_effect = ExcelBridgeError("openpyxl not installed")
    mod.init_excel_routes(bridge)
    with app.test_client() as c:
        resp = c.post(
            "/api/v1/integration/excel/export/download",
            json={"data": [{"a": 1}]},
        )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/v1/integration/excel/portfolio/report
# ---------------------------------------------------------------------------


def test_portfolio_report_ok(client):
    """200 with file_path."""
    resp = client.post(
        "/api/v1/integration/excel/portfolio/report",
        json={
            "positions": [{"symbol": "NIFTY", "qty": 50}],
            "holdings": [{"symbol": "TCS", "qty": 10}],
        },
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["positions"] == 1
    assert body["data"]["holdings"] == 1


def test_portfolio_report_empty(client):
    """200 with empty positions and holdings (uses defaults)."""
    resp = client.post("/api/v1/integration/excel/portfolio/report", json={})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/integration/excel/import
# ---------------------------------------------------------------------------


def test_import_ok(client):
    """200 with imported rows."""
    resp = client.post(
        "/api/v1/integration/excel/import",
        json={"file_path": "export.xlsx", "sheet_name": "Positions"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"]["count"] == 1


def test_import_missing_file_path(client):
    """400 when file_path absent."""
    resp = client.post("/api/v1/integration/excel/import", json={})
    assert resp.status_code == 400


def test_import_bridge_error(app):
    """400 on ExcelBridgeError during import."""
    bridge = _mock_bridge()
    bridge.import_from_excel.side_effect = ExcelBridgeError("File not found")
    mod.init_excel_routes(bridge)
    with app.test_client() as c:
        resp = c.post(
            "/api/v1/integration/excel/import",
            json={"file_path": "missing.xlsx"},
        )
    assert resp.status_code == 400
