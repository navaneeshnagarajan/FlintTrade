"""Actual diagnostic producers through the existing health/log blueprints."""
from __future__ import annotations

import logging

import pytest
from flask import Flask

from flinttrade_core.health_routes import health_bp
from flinttrade_core.log_stream import install_log_capture, log_stream_bp
from flinttrade_core.monitoring import HealthAggregator

pytestmark = pytest.mark.integration


def test_mounted_diagnostics_reads_real_request_events_and_missing_collection(monkeypatch):
    from flinttrade_core import monitoring
    monkeypatch.setattr(monitoring, "_load_psutil", lambda: None)
    monkeypatch.setattr(monitoring.shutil, "which", lambda name: None)
    app = Flask(__name__)
    app.register_blueprint(health_bp)
    app.register_blueprint(log_stream_bp)

    @app.get("/synthetic-failure")
    def failed():
        return {"code": "synthetic_failure"}, 503

    monkeypatch.setenv("FLINTTRADE_API_KEY", "r4-synthetic-key")
    client = app.test_client()
    client.environ_base["HTTP_X_API_KEY"] = "r4-synthetic-key"
    response = client.get("/synthetic-failure?token=NEVER-LOG-THIS")
    assert response.status_code == 503
    diagnostics = client.get("/api/v1/system/diagnostics")
    assert diagnostics.status_code == 200, "System must have a mounted diagnostic reader"
    data = diagnostics.json["data"]
    for key in ("cpu", "gpu", "network"):
        assert data["resources"][key]["status"] == "unavailable"
        assert "used_pct" not in data["resources"][key]
    assert data["resources"]["duckdb"]["status"] == "unavailable"
    assert data["models"]["capacity"] is None
    assert data["jobs"]["active"] is None
    assert data["acquisition"]["status"] == "unavailable"
    events = client.get("/v1/logs/recent?n=100").json["data"]["entries"]
    failures = [event for event in events if event.get("operation") == "failed"]
    assert len(failures) == 1
    event = failures[0]
    assert event["status_code"] == 503
    assert event["measurement"] == "core_http_request_duration"
    assert event["duration_ms"] >= 0
    assert event["request_id"] == response.headers["X-Diagnostic-Request-ID"]
    assert event["scope"] == "core_process"
    assert "NEVER-LOG-THIS" not in str(events)


def test_log_capture_installs_once_and_retains_safe_correlations():
    buf = install_log_capture()
    install_log_capture()
    logger = logging.getLogger("flinttrade.r4-producer")
    logger.setLevel(logging.INFO)
    cursor = buf.latest_seq
    logger.info("bounded observation token=SECRET-TEST", extra={"request_id": "test-request", "operation": "synthetic"})
    _, records = buf.since(cursor)
    matching = [row for row in records if "bounded observation" in row["message"]]
    assert len(matching) == 1
    assert matching[0]["request_id"] == "test-request"
    assert "SECRET-TEST" not in matching[0]["message"]


def test_unperformed_health_checks_are_never_healthy(monkeypatch):
    monkeypatch.setattr(HealthAggregator, "check_disk_space", lambda self, path=None: {"status": "ok", "scope": "host"})
    monkeypatch.setattr(HealthAggregator, "check_memory", lambda self: {"status": "unavailable"})
    monkeypatch.setattr(HealthAggregator, "check_cpu", lambda self: None)
    monkeypatch.setattr(HealthAggregator, "check_gpu", lambda self: None)
    monkeypatch.setattr(HealthAggregator, "check_network", lambda self: None)
    health = HealthAggregator().get_health()
    assert health["broker"]["status"] == "unavailable"
    assert health["duckdb"]["status"] == "unavailable"
    assert health["status"] != "ok"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 101.0, -1.0])
def test_invalid_cpu_observation_is_unavailable(monkeypatch, value):
    from types import SimpleNamespace
    from flinttrade_core import monitoring
    monkeypatch.setattr(monitoring, "_load_psutil", lambda: SimpleNamespace(cpu_percent=lambda **kw: value,
                                                                          cpu_count=lambda **kw: 4))
    assert HealthAggregator().check_cpu() is None


def test_missing_memory_fields_do_not_fabricate_free_memory_or_zero_utilisation(monkeypatch):
    from types import SimpleNamespace
    from flinttrade_core import monitoring
    class PartialCollector:
        def virtual_memory(self):
            return SimpleNamespace(total=1024)
        def Process(self):
            raise RuntimeError("no process observation")
    monkeypatch.setattr(monitoring, "_load_psutil", lambda: PartialCollector())
    result = HealthAggregator().check_memory()
    assert result["status"] == "unavailable"
    assert "used_pct" not in result
