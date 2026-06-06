"""Route tests for the overnight-optimiser report endpoints (through a Flask app)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def client_with_store(tmp_path):
    from flask import Flask

    from flinttrade_ai.ai_routes import ai_bp
    from flinttrade_ai.optimiser_report_store import OptimiserReportStore

    app = Flask(__name__)
    store = OptimiserReportStore(tmp_path)
    app.config["OPTIMISER_REPORT_STORE"] = store
    app.register_blueprint(ai_bp)  # carries its own /api/v1 prefix
    with app.test_client() as client:
        yield client, store


def _report(ts: str, optimised: int = 1) -> dict:
    return {
        "timestamp": ts,
        "strategies_seen": optimised,
        "strategies_optimised": optimised,
        "suggestions": [{"strategy_name": "ema"}],
        "errors": [],
    }


def test_reports_route_empty(client_with_store):
    client, _ = client_with_store
    resp = client.get("/api/v1/ai/optimiser/reports")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["reports"] == []


def test_reports_route_lists_written_reports(client_with_store):
    client, store = client_with_store
    store.write(_report("2026-06-06T02:00:00+00:00", optimised=2))

    resp = client.get("/api/v1/ai/optimiser/reports")
    assert resp.status_code == 200
    reports = resp.get_json()["data"]["reports"]
    assert len(reports) == 1
    assert reports[0]["timestamp"] == "2026-06-06T02:00:00+00:00"
    assert reports[0]["strategies_optimised"] == 2


def test_latest_route_returns_the_report(client_with_store):
    client, store = client_with_store
    store.write(_report("2026-06-06T02:00:00+00:00"))

    resp = client.get("/api/v1/ai/optimiser/reports/latest")
    assert resp.status_code == 200
    report = resp.get_json()["data"]["report"]
    assert report["timestamp"] == "2026-06-06T02:00:00+00:00"
    assert report["suggestions"][0]["strategy_name"] == "ema"


def test_latest_route_is_null_when_no_store_configured():
    from flask import Flask

    from flinttrade_ai.ai_routes import ai_bp

    app = Flask(__name__)
    app.register_blueprint(ai_bp)  # no OPTIMISER_REPORT_STORE
    with app.test_client() as client:
        resp = client.get("/api/v1/ai/optimiser/reports/latest")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["report"] is None
