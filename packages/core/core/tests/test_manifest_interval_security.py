"""Interval grammar and untrusted numeric work through the real backtest route."""
from __future__ import annotations

import re
from copy import deepcopy

import pytest
from flask import Flask

pytestmark = pytest.mark.integration


@pytest.fixture
def request_manifest():
    from flinttrade_backtest.data_connector import DataResult
    from flinttrade_core.backtest_routes import backtest_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(backtest_bp)
    scope = {"principal_id": "synthetic-operator", "environment": "research", "account_id": None,
             "run_id": "synthetic-run", "generation": 1}
    bars = [{"timestamp": f"2026-01-05T14:{30 + index}:00+00:00", "open": 100,
             "high": 103, "low": 99, "close": 100 + index, "volume": 1, "oi": None} for index in range(3)]
    manifest = {"snapshot_id": "a" * 64, "scope": scope, "bars": bars,
                "identity": {"instrument_id": "TEST", "venue": "XNAS", "interval_seconds": 60}}
    calls = []

    class Connector:
        def load_manifest(self, identity, *, scope):
            calls.append(identity)
            assert identity == manifest["snapshot_id"] and scope == manifest["scope"]
            return DataResult(bars=deepcopy(bars), source="synthetic", manifest=deepcopy(manifest))

        def load(self, *args):
            raise AssertionError("explicit manifest cannot fall back")

    app.config.update(DATA_SCOPE_RESOLVER=lambda: deepcopy(scope), BACKTEST_DATA_CONNECTOR_FACTORY=Connector)
    client = app.test_client()

    def send(interval, seconds=60):
        manifest["identity"]["interval_seconds"] = seconds
        return client.post("/api/v1/backtest/run", json={"data_manifest_id": manifest["snapshot_id"],
            "symbol": "TEST", "exchange": "XNAS", "interval": interval, "strategy": "EMACrossover"})

    return send, calls


@pytest.mark.parametrize("suffix", ["m", "", "x"])
def test_long_numeric_input_never_reaches_unbounded_regex(request_manifest, monkeypatch, suffix):
    send, calls = request_manifest
    untrusted = "1" * 100_000 + suffix
    observed = []
    original = re.fullmatch

    def observe(pattern, value, *args, **kwargs):
        if value is untrusted or isinstance(value, str) and value == untrusted:
            observed.append(len(value))
        return original(pattern, value, *args, **kwargs)

    monkeypatch.setattr(re, "fullmatch", observe)
    response = send(untrusted)
    assert response.status_code == 400
    assert response.json == {"status": "error", "message": "Manifest does not match the requested input"}
    assert calls == ["a" * 64]
    assert observed == [], "unbounded numeric request was sent to the regex engine"


@pytest.mark.parametrize(("interval", "seconds"), [
    ("1s", 1), ("60s", 60), ("1m", 60), ("3600s", 3600), ("60m", 3600), ("1h", 3600),
    ("86400s", 86400), ("1440m", 86400), ("24h", 86400), ("1d", 86400),
    ("1000000000000000000000000000000s", 10**30),
])
def test_accepted_interval_syntax_and_ranges_reach_real_engine(request_manifest, interval, seconds):
    send, calls = request_manifest
    response = send(interval, seconds)
    assert response.status_code == 200, response.json
    assert response.json["data"]["total_bars"] == 3
    assert calls == ["a" * 64]


@pytest.mark.parametrize("interval", ["0m", "+1m", "01m", "1.0m", "1e0m", "١m", "１m", "1M", "1w", "1 m",
                                      "1mTAIL", "-1m", "1_0m", "2m", "1s", "1d"])
def test_invalid_interval_keeps_exact_refusal(request_manifest, interval):
    send, calls = request_manifest
    response = send(interval)
    assert response.status_code == 400
    assert response.json == {"status": "error", "message": "Manifest does not match the requested input"}
    assert calls == ["a" * 64]


@pytest.mark.parametrize("interval", ["", " 1m", "1m\n", None, True, 1])
def test_noncanonical_selector_refuses_before_history(request_manifest, interval):
    send, calls = request_manifest
    response = send(interval)
    assert response.status_code == 400
    assert response.json == {"status": "error", "message": "Explicit canonical manifest selectors required"}
    assert calls == []
