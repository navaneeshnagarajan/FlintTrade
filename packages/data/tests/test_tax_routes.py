"""Tests for Tax Report Flask endpoints.

Run with:
    python -m pytest packages/data/tests/test_tax_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

import json

import pytest


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
    from packages.core.src.app import create_flask_app

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
        assert data["status"] == "ok"

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
        resp = _get(app_client, "/v1/tax/summary")
        data = json.loads(resp.data)["data"]
        assert data["fy"] == "2025-26"

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
        assert data["status"] == "ok"

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
