"""Tests for Tax Report Flask endpoints.

Run with:
    python -m pytest packages/core/data/tests/test_tax_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import datetime
import json

import pytest


def _current_fy() -> str:
    """Return the current Indian fiscal-year string (e.g. ``"2025-26"``).

    Indian FY runs April → March. Before 1 April we are still in the
    previous-calendar-year FY; on or after 1 April we are in the
    current-calendar-year FY. Mirrors the server-side default so the
    `test_default_fy` assertion ages with the calendar.
    """
    today = datetime.date.today()
    if today.month < 4:
        start = today.year - 1
    else:
        start = today.year
    return f"{start}-{str(start + 1)[2:]}"


_TEST_API_KEY = "test-tax-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def app_client(monkeypatch_module):
    """Return a Flask test client with the tax blueprint registered."""
    from flinttrade_core.app import create_flask_app

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)

    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _get(client, url):
    return client.get(url, headers={"X-API-Key": _TEST_API_KEY})


class TestTaxSummaryEndpoint:
    """Test GET /v1/tax/summary."""

    def test_returns_ok(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/summary?fy=2025-26")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"

    def test_summary_has_required_fields(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/summary?fy=2025-26")
        data = json.loads(resp.data)["data"]
        required_fields = [
            "fy", "equity_ltcg", "equity_stcg", "intraday_pnl",
            "fno_pnl", "commodity_pnl", "stt_paid", "turnover",
            "tax_liability_estimated", "ltcg_exemption_used",
            "needs_audit", "trade_count",
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"

    def test_fy_matches_request(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/summary?fy=2024-25")
        data = json.loads(resp.data)["data"]
        assert data["fy"] == "2024-25"

    def test_default_fy(self, app_client) -> None:
        """The endpoint's default FY must track the wall-clock Indian fiscal
        year. Previously hardcoded as ``"2025-26"`` which would have started
        failing on 1 April 2026 when FY rolls to 2026-27. Now computed
        locally so the test ages with the calendar."""
        resp = _get(app_client, "/v1/tax/summary")
        data = json.loads(resp.data)["data"]
        assert data["fy"] == _current_fy()

    def test_trade_count_matches_sample(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/summary?fy=2025-26")
        data = json.loads(resp.data)["data"]
        assert data["trade_count"] == 50

    def test_numeric_fields_are_numbers(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/summary?fy=2025-26")
        data = json.loads(resp.data)["data"]
        numeric_fields = [
            "equity_ltcg", "equity_stcg", "intraday_pnl",
            "fno_pnl", "commodity_pnl", "stt_paid", "turnover",
            "tax_liability_estimated", "ltcg_exemption_used",
        ]
        for field in numeric_fields:
            assert isinstance(data[field], (int, float)), f"{field} is not numeric"


class TestTaxReportEndpoint:
    """Test GET /v1/tax/report."""

    def test_returns_ok(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/report?fy=2025-26")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"

    def test_report_has_summary_and_segments(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/report?fy=2025-26")
        data = json.loads(resp.data)["data"]
        assert "summary" in data
        assert "segments" in data

    def test_all_segments_present(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/report?fy=2025-26")
        segments = json.loads(resp.data)["data"]["segments"]
        expected = {"equity_ltcg", "equity_stcg", "equity_intraday", "futures", "options", "commodity"}
        assert set(segments.keys()) == expected

    def test_segment_has_trades(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/report?fy=2025-26")
        segments = json.loads(resp.data)["data"]["segments"]
        # At least one segment should have trades
        has_trades = any(seg["trade_count"] > 0 for seg in segments.values())
        assert has_trades

    def test_trade_details_have_required_fields(self, app_client) -> None:
        resp = _get(app_client, "/v1/tax/report?fy=2025-26")
        segments = json.loads(resp.data)["data"]["segments"]
        for seg_name, seg_data in segments.items():
            for trade in seg_data["trades"]:
                assert "date" in trade
                assert "symbol" in trade
                assert "exchange" in trade
                assert "action" in trade
                assert "quantity" in trade
                assert "price" in trade
                assert "pnl" in trade
