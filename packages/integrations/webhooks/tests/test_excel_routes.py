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
    bridge.import_from_excel_named.return_value = ([{"symbol": "NIFTY", "qty": 50}], "Data")
    bridge.export_to_bytes.return_value = b"PK\x03\x04fake-xlsx-bytes"
    bridge.create_portfolio_report_bytes.return_value = b"PK\x03\x04fake-portfolio-bytes"
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


def test_portfolio_report_download_streams_attachment(client):
    """Streams the multi-sheet .xlsx bytes with an attachment header."""
    resp = client.post(
        "/api/v1/integration/excel/portfolio/report/download",
        json={
            "positions": [{"symbol": "NIFTY", "pnl": 1200}],
            "holdings": [{"symbol": "TCS", "pnl": -300}],
            "filename": "my-portfolio",
        },
    )
    assert resp.status_code == 200
    assert resp.mimetype == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "attachment" in resp.headers["Content-Disposition"]
    # filename without extension gets .xlsx appended
    assert "my-portfolio.xlsx" in resp.headers["Content-Disposition"]
    assert resp.data == b"PK\x03\x04fake-portfolio-bytes"


def test_portfolio_report_download_bridge_error(app):
    """500 on ExcelBridgeError (e.g. openpyxl missing)."""
    bridge = _mock_bridge()
    bridge.create_portfolio_report_bytes.side_effect = ExcelBridgeError("openpyxl not installed")
    mod.init_excel_routes(bridge)
    with app.test_client() as c:
        resp = c.post(
            "/api/v1/integration/excel/portfolio/report/download",
            json={"positions": [], "holdings": []},
        )
    assert resp.status_code == 500


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


# ---------------------------------------------------------------------------
# POST /api/v1/integration/excel/import/upload
# ---------------------------------------------------------------------------


def test_import_upload_ok(client, app):
    """200 with rows parsed from the uploaded workbook via a temp file."""
    import io

    # The named import echoes the sheet it actually read.
    mod._bridge.import_from_excel_named.return_value = ([{"symbol": "NIFTY", "qty": 50}], "Symbols")  # noqa: SLF001
    resp = client.post(
        "/api/v1/integration/excel/import/upload",
        data={
            "file": (io.BytesIO(b"PK\x03\x04fake-xlsx"), "watchlist.xlsx"),
            "sheet_name": "Symbols",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 1
    assert body["data"]["sheet_name"] == "Symbols"
    # The bridge was handed a real temp path that is removed afterwards.
    called_path = mod._bridge.import_from_excel_named.call_args[0][0]  # noqa: SLF001
    import os

    assert called_path.endswith(".xlsx")
    assert not os.path.exists(called_path)


def test_import_upload_reports_the_sheet_actually_read(client):
    """Omitting sheet_name reads the FIRST sheet, and the response echoes that
    sheet's real name (not the request's null) — most workbooks are not
    literally named 'Sheet1'."""
    import io

    mod._bridge.import_from_excel_named.return_value = ([{"a": 1}], "Data")  # noqa: SLF001
    resp = client.post(
        "/api/v1/integration/excel/import/upload",
        data={"file": (io.BytesIO(b"PK\x03\x04fake-xlsx"), "export.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    # None was passed to the bridge (→ first sheet), and the resolved name
    # "Data" is reported back, not null.
    assert mod._bridge.import_from_excel_named.call_args[0][1] is None  # noqa: SLF001
    assert resp.get_json()["data"]["sheet_name"] == "Data"


def test_import_upload_missing_file(client):
    """400 when no file part is sent."""
    resp = client.post(
        "/api/v1/integration/excel/import/upload",
        data={},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "file is required" in resp.get_json()["message"]


def test_import_upload_bridge_error(app):
    """400 on ExcelBridgeError (e.g. not a real workbook) — temp file still removed."""
    import io

    bridge = _mock_bridge()
    bridge.import_from_excel_named.side_effect = ExcelBridgeError("Invalid workbook")
    mod.init_excel_routes(bridge)
    with app.test_client() as c:
        resp = c.post(
            "/api/v1/integration/excel/import/upload",
            data={"file": (io.BytesIO(b"not-xlsx"), "bad.xlsx")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    assert "Invalid workbook" in resp.get_json()["message"]
