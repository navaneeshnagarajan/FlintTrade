"""Reconciliation observability routes (contract §14.2) — HTTP surface.

``GET /api/v1/reconciliation/reports`` and ``/status`` read the engine
runner's JSONL history under ``<workspace>/reconciliation/``;
``POST /api/v1/reconciliation/run`` triggers the app-config runner's
``run_once()``. Mirrors the minimal-app fixture idiom of
``test_gated_verb_routes.py`` (operations blueprint on a bare Flask app),
with the workspace homed at ``tmp_path`` via ``FLINTTRADE_WORKSPACE_DIR`` so
each test reads only its own files.

Run with:
    uv run pytest packages/core/core/tests/test_reconciliation_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from flinttrade_core.operations_routes import operations_bp

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class _StubRunner:
    """Duck-typed stand-in for the engine ReconciliationRunner."""

    def __init__(self, payloads: list[dict[str, Any]] | None = None, *, running: bool = False) -> None:
        self._payloads = payloads or []
        self.is_running = running
        self.run_once_calls = 0

    async def run_once(self) -> list[dict[str, Any]]:
        self.run_once_calls += 1
        return list(self._payloads)


def _app(runner: object | None = None) -> Flask:
    app = Flask(__name__)
    if runner is not None:
        app.config["RECONCILIATION_RUNNER"] = runner
    app.register_blueprint(operations_bp)
    return app


def _report(
    broker: str = "dhan",
    account: str = "ACC1",
    *,
    clean: bool = True,
    severity: str = "",
    critical: int = 0,
    warning: int = 0,
    generated_at: str = "2026-06-12T09:15:00+00:00",
    error: str = "",
) -> dict[str, Any]:
    """One JSONL payload in the runner's ``ReconciliationReport.as_dict`` shape."""
    return {
        "adapter_id": broker,
        "account_id": account,
        "generated_at": generated_at,
        "orders_diff": [],
        "positions_diff": [],
        "holdings_diff": [],
        "error": error,
        "clean": clean,
        "severity": severity,
        "severity_counts": {"info": 0, "warning": warning, "critical": critical},
    }


def _write_history(home: Path, broker: str, account: str, reports: list[dict[str, Any]]) -> Path:
    path = home / "reconciliation" / broker / f"{account}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in reports) + "\n", encoding="utf-8")
    return path


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Home the workspace (and so the reconciliation tree) at tmp_path."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# GET /api/v1/reconciliation/reports
# ---------------------------------------------------------------------------


def test_reports_happy_path_newest_first(home: Path) -> None:
    """Reports come back parsed, newest (last-appended) line first."""
    _write_history(home, "dhan", "ACC1", [
        _report(generated_at="2026-06-12T09:00:00+00:00"),
        _report(generated_at="2026-06-12T09:05:00+00:00", clean=False, severity="critical", critical=2),
    ])
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["broker"] == "dhan"
    assert data["account_id"] == "ACC1"
    reports = data["reports"]
    assert len(reports) == 2
    assert reports[0]["generated_at"] == "2026-06-12T09:05:00+00:00"
    assert reports[0]["clean"] is False
    assert reports[0]["severity_counts"]["critical"] == 2
    assert reports[1]["generated_at"] == "2026-06-12T09:00:00+00:00"


def test_reports_respects_limit(home: Path) -> None:
    _write_history(home, "dhan", "ACC1", [
        _report(generated_at=f"2026-06-12T09:0{i}:00+00:00") for i in range(7)
    ])
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1&limit=2")
    assert resp.status_code == 200
    reports = resp.get_json()["data"]["reports"]
    assert [r["generated_at"] for r in reports] == [
        "2026-06-12T09:06:00+00:00",
        "2026-06-12T09:05:00+00:00",
    ]


def test_reports_default_limit_is_five(home: Path) -> None:
    _write_history(home, "dhan", "ACC1", [
        _report(generated_at=f"2026-06-12T09:0{i}:00+00:00") for i in range(7)
    ])
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1")
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]["reports"]) == 5


def test_reports_empty_when_no_file(home: Path) -> None:
    """No history yet — an honest empty list, not an error."""
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["reports"] == []


def test_reports_skips_malformed_lines(home: Path) -> None:
    """A torn/garbage line must not break the read side."""
    path = _write_history(home, "dhan", "ACC1", [_report()])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1")
    assert resp.status_code == 200
    reports = resp.get_json()["data"]["reports"]
    assert len(reports) == 1
    assert reports[0]["adapter_id"] == "dhan"


def test_reports_requires_broker_and_account(home: Path) -> None:
    client = _app().test_client()
    for query in ("", "?broker=dhan", "?account_id=ACC1"):
        resp = client.get(f"/api/v1/reconciliation/reports{query}")
        assert resp.status_code == 400
        assert "required" in resp.get_json()["message"]


def test_reports_rejects_bad_limit(home: Path) -> None:
    client = _app().test_client()
    for bad in ("abc", "0", "-3"):
        resp = client.get(f"/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1&limit={bad}")
        assert resp.status_code == 400
        assert "limit" in resp.get_json()["message"]


def test_reports_path_traversal_refused(home: Path) -> None:
    """Hostile ids can never read outside the reconciliation tree."""
    # A sentinel JSONL OUTSIDE the reconciliation root: naive joining of
    # broker=".." + account_id="outside" would resolve straight to it.
    sentinel = home / "outside.jsonl"
    sentinel.write_text(json.dumps({"secret": "LEAKED"}) + "\n", encoding="utf-8")
    client = _app().test_client()
    for broker, account in (
        ("..", "outside"),
        ("../..", "outside"),
        ("dhan", "../outside"),
        ("dhan", "..\\outside"),
        (".", ".."),
    ):
        resp = client.get(
            "/api/v1/reconciliation/reports",
            query_string={"broker": broker, "account_id": account},
        )
        assert resp.status_code in (200, 400)
        body = resp.get_json()
        if resp.status_code == 200:
            assert body["data"]["reports"] == []
        assert "LEAKED" not in json.dumps(body)


def test_reports_invalid_bearer_token_rejected(home: Path) -> None:
    """The observability scope guard rejects a garbage session token."""
    client = _app().test_client()
    resp = client.get(
        "/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/reconciliation/status
# ---------------------------------------------------------------------------


def test_status_summarises_latest_line_per_target(home: Path) -> None:
    _write_history(home, "dhan", "ACC1", [
        _report(clean=True, generated_at="2026-06-12T08:00:00+00:00"),
        _report(
            clean=False, severity="critical", critical=1, warning=2,
            generated_at="2026-06-12T09:00:00+00:00",
        ),
    ])
    _write_history(home, "upstox", "U99", [
        _report(broker="upstox", account="U99", clean=True, generated_at="2026-06-12T09:10:00+00:00"),
    ])
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["runner_active"] is False
    targets = {(t["broker"], t["account_id"]): t for t in data["targets"]}
    assert set(targets) == {("dhan", "ACC1"), ("upstox", "U99")}
    dhan = targets[("dhan", "ACC1")]
    assert dhan["clean"] is False
    assert dhan["severity"] == "critical"
    assert dhan["severity_counts"] == {"info": 0, "warning": 2, "critical": 1}
    assert dhan["last_report_at"] == "2026-06-12T09:00:00+00:00"
    assert targets[("upstox", "U99")]["clean"] is True


def test_status_empty_when_no_history(home: Path) -> None:
    client = _app().test_client()
    resp = client.get("/api/v1/reconciliation/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["targets"] == []
    assert data["runner_active"] is False


def test_status_reports_runner_active(home: Path) -> None:
    runner = _StubRunner(running=True)
    client = _app(runner=runner).test_client()
    resp = client.get("/api/v1/reconciliation/status")
    assert resp.status_code == 200
    assert resp.get_json()["data"]["runner_active"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/reconciliation/run
# ---------------------------------------------------------------------------


def test_run_returns_503_when_no_runner(home: Path) -> None:
    """Dormant natives — no runner on app.config — must fail honestly."""
    client = _app().test_client()
    resp = client.post("/api/v1/reconciliation/run", json={})
    assert resp.status_code == 503
    assert "not active" in resp.get_json()["message"]


def test_run_happy_path_invokes_run_once(home: Path) -> None:
    runner = _StubRunner(payloads=[_report(clean=False, severity="warning", warning=1)])
    client = _app(runner=runner).test_client()
    resp = client.post("/api/v1/reconciliation/run", json={})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert runner.run_once_calls == 1
    assert data["count"] == 1
    assert data["reports"][0]["severity"] == "warning"


def test_run_can_produce_zero_reports(home: Path) -> None:
    """Cadence-skipped cycles honestly report count 0 (not an error)."""
    runner = _StubRunner(payloads=[])
    client = _app(runner=runner).test_client()
    resp = client.post("/api/v1/reconciliation/run", json={})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["count"] == 0
    assert data["reports"] == []


def test_run_invalid_bearer_token_rejected(home: Path) -> None:
    runner = _StubRunner()
    client = _app(runner=runner).test_client()
    resp = client.post(
        "/api/v1/reconciliation/run", json={},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401
    assert runner.run_once_calls == 0
