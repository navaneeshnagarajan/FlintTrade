"""Installed diagnostic readback stays private on real early refusals."""
from __future__ import annotations

import json

import pytest

from flinttrade_core.request_observability import current_safe_request_summary
from packages.core.core.tests.test_service_tasks import mounted as mounted

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode,path,template,status", [
    ("normal", "/api/v1/backtest/run", "/api/v1/backtest/run/{resource}", 401),
    ("model-auth", "/v1/model-runs/synthetic-private-run/configuration/confirm", "/v1/model-runs/{resource}", 403),
    ("shutdown", "/api/v1/backtest/run", "/api/v1/backtest/run/{resource}", 503),
    ("shutdown", "/api/v1/execution-sessions/synthetic-private-run", "/api/v1/execution-sessions/{resource}", 503),
    ("shutdown", "/api/v1/protection/synthetic-private-run", "/api/v1/protection/{resource}", 503),
])
def test_real_refusal_diagnostics_never_retain_private_envelope(monkeypatch, request, mode, path, template, status):
    monkeypatch.setenv("ENABLE_ANALYZER", "true")
    app, client, _store, _calls = request.getfixturevalue("mounted")
    try:
        if mode == "shutdown":
            app.config["RUNTIME_REQUEST_TRACKER"].stop_admitting()
        response = client.post(path, json={"note": "SYNTHETIC-PRIVATE-CONTEXT"},
                               headers={"User-Agent": "SYNTHETIC-PRIVATE-AGENT"})
        assert response.status_code == status, response.json
        rows = app.config["API_ANALYZER"].recent(limit=20)
        assert len(rows) == 1, "Inspect the actual persisted request, not only its classifier"
        encoded = json.dumps(rows, default=str)
        assert "SYNTHETIC-PRIVATE-CONTEXT" not in encoded
        assert "SYNTHETIC-PRIVATE-AGENT" not in encoded
        assert "synthetic-private-run" not in encoded
        assert rows[0]["route"] == template
        assert rows[0]["response_body"] is None
        summary = rows[0]["request_body"]
        assert set(summary) == {"route_template", "method", "content_length", "has_credentials"}
        assert summary["route_template"] == template
        assert summary["method"] == "POST"
        assert summary["has_credentials"] is True
        assert current_safe_request_summary() is None, "Teardown must restore the preceding context"
    finally:
        # These requests never acquire execution workers. Keep the normal
        # factory's data owner from outliving the synthetic fixture.
        app.config["DATA_RUNTIME"].close()
