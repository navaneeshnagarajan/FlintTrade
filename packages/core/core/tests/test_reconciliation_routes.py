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
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from flask.testing import FlaskClient

from flinttrade_core.operations_routes import operations_bp
from flinttrade_engine.reconciliation_runner import ReconciliationRunBusyError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class _StubRunner:
    """Duck-typed stand-in for the engine ReconciliationRunner."""

    def __init__(self, payloads: list[dict[str, Any]] | None = None, *, running: bool = False) -> None:
        self._payloads = payloads or []
        self.is_running = running
        self.trigger_calls = 0
        self.trigger_requests: list[tuple[frozenset[str] | None, bool]] = []

    def trigger(
        self,
        *,
        selectors: set[str] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        self.trigger_calls += 1
        self.trigger_requests.append(
            (frozenset(selectors) if selectors is not None else None, force)
        )
        return list(self._payloads)


class _LedgerEvidenceRunner(_StubRunner):
    """Route-contract fake that returns the ledger's already-adopted test snapshot."""

    def __init__(self, ledger: object) -> None:
        super().__init__()
        self._ledger = ledger

    def trigger(
        self,
        *,
        selectors: set[str] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        self.trigger_calls += 1
        self.trigger_requests.append(
            (frozenset(selectors) if selectors is not None else None, force)
        )
        payloads: list[dict[str, Any]] = []
        for selector in sorted(selectors or ()):
            broker, account_id = selector.split(":", 1)
            generation = self._ledger.latest_snapshot_generation(
                adapter_id=broker,
                account_id=account_id,
            )
            if generation is not None:
                payloads.append(
                    {
                        "adapter_id": broker,
                        "account_id": account_id,
                        "snapshot_generation": generation,
                    }
                )
        return payloads


class _AuthenticatedClient(FlaskClient):
    """Inject one normal operator session unless a test supplies its own token."""

    def open(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Authorization", _live_headers()["Authorization"])
        return super().open(*args, headers=headers, **kwargs)


def _app(runner: object | None = None, **config: object) -> Flask:
    app = Flask(__name__)
    app.test_client_class = _AuthenticatedClient
    app.config.update(config)
    if runner is not None:
        app.config["RECONCILIATION_RUNNER"] = runner
    app.config.setdefault(
        "BROKER_ROUTER",
        _ResolutionRouter(selectors=("dhan:ACC1", "upstox:U99", "dhan:personal")),
    )
    ledger = app.config.get("ORDER_LIFECYCLE_LEDGER")
    if runner is None and ledger is not None:
        app.config.setdefault("RECONCILIATION_RUNNER", _LedgerEvidenceRunner(ledger))
    audit = app.config.get("AUDIT")
    bind_verifier = getattr(ledger, "set_audit_receipt_verifier", None)
    verify_receipt = getattr(audit, "verify_event_receipt", None)
    if callable(bind_verifier) and callable(verify_receipt):
        bind_verifier(verify_receipt)
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


def test_reports_skip_identityless_and_malformed_evidence(home: Path) -> None:
    _write_history(
        home,
        "dhan",
        "ACC1",
        [
            _report(),
            {},
            {
                **_report(generated_at="2026-06-12T09:20:00+00:00"),
                "orders_diff": None,
                "positions_diff": "invalid",
                "holdings_diff": ["invalid", {"symbol": "TCS"}],
                "severity_counts": {"warning": "not-a-number"},
            },
            {
                **_report(generated_at="2026-06-12T09:21:00+00:00"),
                "clean": True,
                "severity": "info",
                "severity_counts": {"info": 1, "warning": 0, "critical": 0},
            },
        ],
    )

    response = _app().test_client().get(
        "/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1"
    )

    assert response.status_code == 200
    reports = response.get_json()["data"]["reports"]
    assert len(reports) == 1
    assert reports[0]["generated_at"] == "2026-06-12T09:15:00+00:00"


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
        assert resp.status_code in (200, 400, 403)
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


def test_reports_rejects_an_account_outside_the_current_router_acl(home: Path) -> None:
    _write_history(home, "dhan", "ACC1", [_report()])
    response = _app(
        BROKER_ROUTER=_ResolutionRouter(selectors=()),
    ).test_client().get(
        "/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1"
    )

    assert response.status_code == 403
    assert "authorised" in response.get_json()["message"]


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


def test_status_filters_targets_by_current_router_acl(home: Path) -> None:
    _write_history(home, "dhan", "ACC1", [_report()])
    _write_history(home, "upstox", "U99", [_report(broker="upstox", account="U99")])

    response = _app(
        BROKER_ROUTER=_ResolutionRouter(selectors=("dhan:ACC1",)),
    ).test_client().get("/api/v1/reconciliation/status")

    assert response.status_code == 200
    assert response.get_json()["data"]["targets"] == [
        {
            "broker": "dhan",
            "account_id": "ACC1",
            "last_report_at": "2026-06-12T09:15:00+00:00",
            "clean": True,
            "severity": "",
            "severity_counts": {"info": 0, "warning": 0, "critical": 0},
            "error": "",
        }
    ]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform lacks symlink support")
def test_status_ignores_symbolic_link_history(home: Path) -> None:
    sentinel = home / "outside.jsonl"
    sentinel.write_text(
        json.dumps(_report(account="LEAKED")) + "\n",
        encoding="utf-8",
    )
    broker_dir = home / "reconciliation" / "dhan"
    broker_dir.mkdir(parents=True)
    (broker_dir / "ACC1.jsonl").symlink_to(sentinel)

    response = _app().test_client().get("/api/v1/reconciliation/status")

    assert response.status_code == 200
    assert response.get_json()["data"]["targets"] == []


# ---------------------------------------------------------------------------
# POST /api/v1/reconciliation/run
# ---------------------------------------------------------------------------


def test_run_returns_503_when_no_runner(home: Path) -> None:
    """Dormant natives — no runner on app.config — must fail honestly."""
    client = _app().test_client()
    resp = client.post("/api/v1/reconciliation/run", json={})
    assert resp.status_code == 503
    assert "not active" in resp.get_json()["message"]


def test_run_happy_path_uses_runner_owned_loop_trigger(home: Path) -> None:
    runner = _StubRunner(payloads=[_report(clean=False, severity="warning", warning=1)])
    client = _app(runner=runner).test_client()
    resp = client.post("/api/v1/reconciliation/run", json={})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert runner.trigger_calls == 1
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


def test_run_filters_returned_reports_by_current_router_acl(home: Path) -> None:
    runner = _StubRunner(payloads=[
        _report(),
        _report(broker="upstox", account="U99"),
    ])

    response = _app(
        runner=runner,
        BROKER_ROUTER=_ResolutionRouter(selectors=("dhan:ACC1",)),
    ).test_client().post("/api/v1/reconciliation/run", json={})

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["count"] == 1
    assert [(row["adapter_id"], row["account_id"]) for row in data["reports"]] == [
        ("dhan", "ACC1")
    ]
    assert runner.trigger_requests == [(frozenset({"dhan:ACC1"}), False)]


def test_run_invalid_bearer_token_rejected(home: Path) -> None:
    runner = _StubRunner()
    client = _app(runner=runner).test_client()
    resp = client.post(
        "/api/v1/reconciliation/run", json={},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401
    assert runner.trigger_calls == 0


def test_run_returns_conflict_when_cycle_is_already_active(home: Path) -> None:
    class _BusyRunner(_StubRunner):
        def trigger(
            self,
            *,
            selectors: set[str] | None = None,
            force: bool = False,
        ) -> list[dict[str, Any]]:
            self.trigger_calls += 1
            raise ReconciliationRunBusyError("already running")

    runner = _BusyRunner()
    response = _app(runner=runner).test_client().post(
        "/api/v1/reconciliation/run",
        json={},
    )

    assert response.status_code == 409
    assert "already" in response.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Explicit OUTCOME_UNKNOWN recovery
# ---------------------------------------------------------------------------


def _live_headers(*, unlocked: bool = True) -> dict[str, str]:
    from flinttrade_core.auth_routes import _create_token

    token = _create_token("operator-1", mode="live", live_mode_unlocked=unlocked)
    return {"Authorization": f"Bearer {token}"}


def _unknown_ledger(home: Path):
    from datetime import datetime, timezone

    from flinttrade_engine.local_state_provider import OrderLifecycleLedger
    from flinttrade_engine.request_context import RequestContext

    observed = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    ledger = OrderLifecycleLedger(
        ledger_path=home / "order-lifecycle.sqlite3",
        clock=lambda: observed,
    )
    attempt_id = ledger.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=RequestContext(
            jti="sensitive-jti",
            actor_type="human",
            actor_id="operator-1",
            mode="live",
            intent_source="manual",
            selector="dhan:personal",
        ),
        payload={
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
            "price": 2500,
        },
        observed_at=observed,
    )
    ledger.mark_invoked(attempt_id, observed_at=observed)
    ledger.mark_outcome_unknown(attempt_id, "TimeoutError", observed_at=observed)
    ledger.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[],
        positions=[],
        holdings=[],
        observed_at="2026-07-15T09:31:00+00:00",
    )
    return ledger, attempt_id


class _ResolutionRouter:
    def __init__(
        self,
        *,
        clear_result: bool = True,
        selectors: tuple[str, ...] = ("dhan:personal",),
    ) -> None:
        self.cleared: list[str] = []
        self.clear_result = clear_result
        self.selectors = selectors

    def authorised_selectors(self, actor_id: str) -> tuple[str, ...]:
        return self.selectors if actor_id == "operator-1" else ()

    def clear_lifecycle_fault(
        self,
        attempt_id: str,
        *,
        resolution_id: str,
        selector: str,
    ) -> dict[str, str] | None:
        self.cleared.append(attempt_id)
        if not self.clear_result:
            return None
        return {
            "receipt_id": f"clear:{resolution_id}",
            "resolution_id": resolution_id,
            "attempt_id": attempt_id,
            "selector": selector,
            "router_generation": "test-router-generation",
        }

    @staticmethod
    def verify_lifecycle_fault_clear(
        receipt: object,
        *,
        resolution_id: str,
        attempt_id: str,
        selector: str,
    ) -> bool:
        return bool(
            isinstance(receipt, dict)
            and receipt.get("receipt_id") == f"clear:{resolution_id}"
            and receipt.get("resolution_id") == resolution_id
            and receipt.get("attempt_id") == attempt_id
            and receipt.get("selector") == selector
            and receipt.get("router_generation") == "test-router-generation"
        )


def test_unknown_outcome_listing_returns_operator_safe_attempt_details(home: Path) -> None:
    ledger, attempt_id = _unknown_ledger(home)
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
    ).test_client().get(
        "/api/v1/reconciliation/outcomes",
        headers=_live_headers(),
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["count"] == 1
    assert payload["outcomes"][0]["attempt_id"] == attempt_id
    assert payload["outcomes"][0]["symbol"] == "RELIANCE"
    assert "request_jti_hash" not in payload["outcomes"][0]
    assert "sensitive-jti" not in response.get_data(as_text=True)


def test_unknown_outcome_listing_filters_accounts_by_current_router_acl(home: Path) -> None:
    from datetime import datetime, timezone

    from flinttrade_engine.request_context import RequestContext

    ledger, visible_attempt = _unknown_ledger(home)
    observed = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    hidden_attempt = ledger.prepare_dispatch(
        adapter_id="dhan",
        account_id="family",
        operation="place_order",
        request_context=RequestContext(
            jti="hidden-jti",
            actor_type="human",
            actor_id="operator-1",
            mode="live",
            intent_source="manual",
            selector="dhan:family",
        ),
        payload={
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
            "price": 3500,
        },
        observed_at=observed,
    )
    ledger.mark_invoked(hidden_attempt, observed_at=observed)
    ledger.mark_outcome_unknown(hidden_attempt, "TimeoutError", observed_at=observed)

    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
    ).test_client().get(
        "/api/v1/reconciliation/outcomes",
        headers=_live_headers(),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["count"] == 1
    assert [outcome["attempt_id"] for outcome in data["outcomes"]] == [visible_attempt]
    assert hidden_attempt not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("body_override", "expected_status"),
    [
        ({"confirmation": "CONFIRM APPLIED dhan:personal:wrong-attempt"}, 400),
        ({"account_id": "someone-else"}, 403),
        ({"business_date": "2026-07-14"}, 409),
        ({"broker_order_ids": []}, 400),
    ],
)
def test_unknown_outcome_resolution_rejects_inexact_or_incomplete_evidence(
    home: Path,
    body_override: dict[str, object],
    expected_status: int,
) -> None:
    ledger, attempt_id = _unknown_ledger(home)
    audit = MagicMock()
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    )
    body = {
        "broker": "dhan",
        "account_id": "personal",
        "business_date": "2026-07-15",
        "outcome": "confirmed_applied",
        "broker_order_ids": ["RECOVERED-1"],
        "confirmation": f"CONFIRM APPLIED dhan:personal:{attempt_id}",
        **body_override,
    }
    if "account_id" in body_override and "confirmation" not in body_override:
        body["confirmation"] = (
            f"CONFIRM APPLIED dhan:{body['account_id']}:{attempt_id}"
        )

    response = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )

    assert response.status_code == expected_status
    assert ledger.list_unresolved_outcomes()[0]["resolution"] is None
    audit.log_event.assert_not_called()


def test_unknown_outcome_resolution_requires_pin_audit_and_exact_selector(home: Path) -> None:
    from datetime import datetime

    from flinttrade_data.audit_logger import IST, AuditLogger

    ledger, attempt_id = _unknown_ledger(home)
    ledger.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{
            "orderid": "RECOVERED-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "OPEN",
            "quantity": 1,
            "filled_quantity": 0,
            "price": 2500,
        }],
        positions=[],
        holdings=[],
        observed_at="2026-07-15T09:32:00+00:00",
    )
    router = _ResolutionRouter()
    audit = AuditLogger(str(home / "audit"))
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    )
    evidence_runner = app.config["RECONCILIATION_RUNNER"]
    client = app.test_client()
    body = {
        "broker": "dhan",
        "account_id": "personal",
        "business_date": "2026-07-15",
        "outcome": "confirmed_applied",
        "broker_order_ids": ["RECOVERED-1"],
        "confirmation": f"CONFIRM APPLIED dhan:personal:{attempt_id}",
        "note": "Verified in the broker order book",
    }

    locked = client.post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(unlocked=False),
    )
    assert locked.status_code == 403
    assert ledger.list_unresolved_outcomes()[0]["resolution"] is None

    response = client.post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["attempt_id"] == attempt_id
    assert payload["outcome"] == "confirmed_applied"
    assert payload["status"] == "COMMITTED"
    assert payload["writes_unblocked"] is True
    assert payload["remaining_outcomes"] == 0
    assert evidence_runner.trigger_requests == [(frozenset({"dhan:personal"}), True)]
    assert router.cleared == [attempt_id]
    assert ledger.is_outcome_resolved(attempt_id) is True
    ledger.assert_write_ready()
    records = audit.read_day(datetime.now(IST).strftime("%Y-%m-%d"))
    assert records[-1]["event_type"] == "ORDER_OUTCOME_RESOLUTION_AUTHORISED"
    assert records[-1]["attempt_id"] == attempt_id
    assert records[-1]["evidence_digest"] == payload["evidence_digest"]
    assert "sensitive-jti" not in json.dumps(records)
    audit.close()


def test_unknown_outcome_resolution_rejects_a_refresh_marker_not_adopted_by_ledger(
    home: Path,
) -> None:
    from flinttrade_data.audit_logger import AuditLogger

    ledger, attempt_id = _unknown_ledger(home)
    runner = _StubRunner(payloads=[{
        "adapter_id": "dhan",
        "account_id": "personal",
        "snapshot_generation": 999,
    }])
    app = _app(
        runner=runner,
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=AuditLogger(str(home / "audit")),
    )

    response = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
    )

    assert response.status_code == 409
    assert runner.trigger_requests == [(frozenset({"dhan:personal"}), True)]
    assert ledger.list_unresolved_outcomes()[0]["resolution"] is None


def test_unknown_multi_order_resolution_accepts_an_explicit_partial_partition(home: Path) -> None:
    from datetime import datetime, timezone

    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger
    from flinttrade_engine.request_context import RequestContext

    observed = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    ledger = OrderLifecycleLedger(
        ledger_path=home / "order-lifecycle.sqlite3",
        clock=lambda: observed,
    )
    attempt_id = ledger.prepare_dispatch(
        adapter_id="upstox",
        account_id="personal",
        operation="place_multi_order",
        request_context=RequestContext(
            jti="multi-jti",
            actor_type="human",
            actor_id="operator-1",
            mode="live",
            intent_source="manual",
            selector="upstox:personal",
        ),
        payload={
            "_op": "place_multi_order",
            "orders": [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 2500,
                },
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "SELL",
                    "quantity": 2,
                    "price": 3500,
                },
            ],
        },
        observed_at=observed,
    )
    ledger.mark_invoked(attempt_id, observed_at=observed)
    ledger.mark_outcome_unknown(attempt_id, "TimeoutError", observed_at=observed)
    ledger.record_broker_snapshot(
        adapter_id="upstox",
        account_id="personal",
        orders=[{
            "orderid": "PARTIAL-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "OPEN",
            "quantity": 1,
            "filled_quantity": 0,
            "price": 2500,
        }],
        positions=[],
        holdings=[],
        observed_at="2026-07-15T09:31:00+00:00",
    )
    audit = AuditLogger(str(home / "audit"))
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(selectors=("upstox:personal",)),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    ).test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "upstox",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_partial",
            "broker_order_ids": ["PARTIAL-1"],
            "broker_order_item_indexes": [0],
            "not_applied_item_indexes": [1],
            "confirmation": f"CONFIRM PARTIAL upstox:personal:{attempt_id}",
            "note": "Fresh broker order book contains only the first child",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["outcome"] == "confirmed_partial"
    assert ledger.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_PARTIAL"
    audit.close()


def test_unknown_outcome_audit_failure_requires_fresh_evidence_before_retry(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    class _FailingAudit:
        @staticmethod
        def log_event(_event_type: str, **_fields: object) -> None:
            raise OSError("audit disk unavailable")

    ledger, attempt_id = _unknown_ledger(home)
    router = _ResolutionRouter()
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=_FailingAudit(),
    )
    body = {
        "broker": "dhan",
        "account_id": "personal",
        "business_date": "2026-07-15",
        "outcome": "confirmed_not_applied",
        "broker_order_ids": [],
        "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
        "note": "Fresh broker order book contains no matching order",
    }

    failed = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )

    assert failed.status_code == 503
    failed_data = failed.get_json()["data"]
    assert failed_data["attempt_id"] == attempt_id
    assert failed_data["status"] == "PENDING_AUDIT"
    assert failed_data["resolution"]["status"] == "PENDING_AUDIT"
    unresolved = ledger.list_unresolved_outcomes()
    assert unresolved[0]["resolution"]["status"] == "PENDING_AUDIT"
    resolution_id = unresolved[0]["resolution"]["resolution_id"]
    with pytest.raises(LifecycleStateError, match="requires reconciliation"):
        ledger.assert_write_ready()
    assert router.cleared == []

    audit = AuditLogger(str(home / "audit"))
    app.config["AUDIT"] = audit
    ledger.set_audit_receipt_verifier(audit.verify_event_receipt)
    stale_retry = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )
    assert stale_retry.status_code == 503
    assert stale_retry.get_json()["data"]["resolution_id"] == resolution_id

    ledger.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[],
        positions=[],
        holdings=[],
        observed_at="2026-07-15T09:32:00+00:00",
    )
    retried = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )

    assert retried.status_code == 200
    assert retried.get_json()["data"]["resolution_id"] != resolution_id
    assert router.cleared == [attempt_id]
    ledger.assert_write_ready()
    audit.close()


def test_fresh_evidence_conflict_returns_pending_resolution_metadata(home: Path) -> None:
    class _FailingAudit:
        @staticmethod
        def log_event(_event_type: str, **_fields: object) -> None:
            raise OSError("audit disk unavailable")

    ledger, attempt_id = _unknown_ledger(home)
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=_FailingAudit(),
    )
    body = {
        "broker": "dhan",
        "account_id": "personal",
        "business_date": "2026-07-15",
        "outcome": "confirmed_not_applied",
        "broker_order_ids": [],
        "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
        "note": "Initial order book was empty",
    }
    initial = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )
    pending = initial.get_json()["data"]
    ledger.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{
            "orderid": "LATE-MATCH-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "OPEN",
            "quantity": 1,
            "filled_quantity": 0,
            "price": 2500,
        }],
        positions=[],
        holdings=[],
        observed_at="2026-07-15T09:32:00+00:00",
    )

    conflicted = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
        headers=_live_headers(),
    )

    assert conflicted.status_code == 409
    assert "conflicts" in conflicted.get_json()["message"]
    assert conflicted.get_json()["data"]["resolution_id"] == pending["resolution_id"]
    assert conflicted.get_json()["data"]["status"] == "PENDING_AUDIT"


def test_unknown_outcome_resolution_rechecks_selector_acl_under_router_lease(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    ledger, attempt_id = _unknown_ledger(home)
    authorised_router = _ResolutionRouter()
    replacement_router = _ResolutionRouter(selectors=())
    audit = AuditLogger(str(home / "audit"))
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=authorised_router,
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    )
    durable_log_event = audit.log_event

    def log_then_replace_router(event_type: str, **fields: object) -> str:
        receipt = durable_log_event(event_type, **fields)
        app.config["BROKER_ROUTER"] = replacement_router
        return receipt

    audit.log_event = log_then_replace_router  # type: ignore[method-assign]

    response = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
        headers=_live_headers(),
    )

    assert response.status_code == 403
    assert replacement_router.cleared == []
    assert ledger.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"
    with pytest.raises(LifecycleStateError, match="requires reconciliation"):
        ledger.assert_write_ready()
    audit.close()


def test_resolved_attempt_stays_blocked_when_current_router_had_no_matching_memory_fault(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    ledger, attempt_id = _unknown_ledger(home)
    router = _ResolutionRouter(clear_result=False)
    audit = AuditLogger(str(home / "audit"))
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    ).test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
        headers=_live_headers(),
    )

    assert response.status_code == 503
    assert "pending exact router clear" in response.get_json()["message"]
    assert response.get_json()["data"]["status"] == "PENDING_ROUTER_CLEAR"
    with pytest.raises(LifecycleStateError, match="requires reconciliation"):
        ledger.assert_write_ready()
    audit.close()


def test_legacy_boolean_router_clear_result_cannot_complete_resolution(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    class _LegacyBooleanClearRouter(_ResolutionRouter):
        def clear_lifecycle_fault(
            self,
            attempt_id: str,
            *,
            resolution_id: str,
            selector: str,
        ) -> bool:
            del resolution_id, selector
            self.cleared.append(attempt_id)
            return True

    ledger, attempt_id = _unknown_ledger(home)
    audit = AuditLogger(str(home / "audit"))
    router = _LegacyBooleanClearRouter()
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=router,
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    ).test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
        headers=_live_headers(),
    )

    assert response.status_code == 503
    assert ledger.list_unresolved_outcomes()[0]["resolution"]["status"] == "PENDING_ROUTER_CLEAR"
    with pytest.raises(LifecycleStateError, match="requires reconciliation"):
        ledger.assert_write_ready()
    audit.close()


def test_router_clear_failure_stays_durable_and_retryable(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    class _FailingClearRouter(_ResolutionRouter):
        def clear_lifecycle_fault(
            self,
            attempt_id: str,
            *,
            resolution_id: str,
            selector: str,
        ) -> dict[str, str] | None:
            self.cleared.append(attempt_id)
            raise RuntimeError("router clear unavailable")

    ledger, attempt_id = _unknown_ledger(home)
    audit = AuditLogger(str(home / "audit"))
    app = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_FailingClearRouter(),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    )
    body = {
        "broker": "dhan",
        "account_id": "personal",
        "business_date": "2026-07-15",
        "outcome": "confirmed_not_applied",
        "broker_order_ids": [],
        "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
        "note": "Fresh broker order book contains no matching order",
    }

    failed = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
    )

    assert failed.status_code == 503
    assert failed.get_json()["data"]["status"] == "PENDING_ROUTER_CLEAR"
    unresolved = ledger.list_unresolved_outcomes()
    resolution_id = unresolved[0]["resolution"]["resolution_id"]
    assert unresolved[0]["resolution"]["status"] == "PENDING_ROUTER_CLEAR"
    with pytest.raises(LifecycleStateError, match="requires reconciliation"):
        ledger.assert_write_ready()

    succeeding_router = _ResolutionRouter()
    app.config["BROKER_ROUTER"] = succeeding_router
    retried = app.test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json=body,
    )

    assert retried.status_code == 200
    assert retried.get_json()["data"]["resolution_id"] == resolution_id
    assert succeeding_router.cleared == [attempt_id]
    ledger.assert_write_ready()
    audit.close()


def test_resolving_outcome_does_not_hide_unrelated_critical_ledger_health(home: Path) -> None:
    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.local_state_provider import LifecycleStateError

    ledger, attempt_id = _unknown_ledger(home)
    ledger.mark_health_critical("independent ledger integrity fault")
    audit = AuditLogger(str(home / "audit"))
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    ).test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
        headers=_live_headers(),
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["remaining_outcomes"] == 0
    assert data["writes_unblocked"] is False
    with pytest.raises(LifecycleStateError, match="independent ledger integrity fault"):
        ledger.assert_write_ready()
    audit.close()


def test_resolution_count_excludes_unknown_outcomes_outside_operator_acl(home: Path) -> None:
    from datetime import datetime, timezone

    from flinttrade_data.audit_logger import AuditLogger
    from flinttrade_engine.request_context import RequestContext

    ledger, attempt_id = _unknown_ledger(home)
    observed = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    hidden_attempt = ledger.prepare_dispatch(
        adapter_id="upstox",
        account_id="hidden",
        operation="place_order",
        request_context=RequestContext(
            jti="hidden-jti",
            actor_type="human",
            actor_id="other-operator",
            mode="live",
            intent_source="manual",
            selector="upstox:hidden",
        ),
        payload={
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
            "price": 3000,
        },
        observed_at=observed,
    )
    ledger.mark_invoked(hidden_attempt, observed_at=observed)
    ledger.mark_outcome_unknown(hidden_attempt, "TimeoutError", observed_at=observed)
    audit = AuditLogger(str(home / "audit"))
    response = _app(
        ORDER_LIFECYCLE_LEDGER=ledger,
        BROKER_ROUTER=_ResolutionRouter(selectors=("dhan:personal",)),
        BROKER_ROUTER_REBUILD_LOCK=__import__("threading").RLock(),
        AUDIT=audit,
    ).test_client().post(
        f"/api/v1/reconciliation/outcomes/{attempt_id}/resolve",
        json={
            "broker": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "outcome": "confirmed_not_applied",
            "broker_order_ids": [],
            "confirmation": f"CONFIRM NOT_APPLIED dhan:personal:{attempt_id}",
            "note": "Fresh broker order book contains no matching order",
        },
        headers=_live_headers(),
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["remaining_outcomes"] == 0
    assert response.get_json()["data"]["writes_unblocked"] is False
    assert [row["attempt_id"] for row in ledger.list_unresolved_outcomes()] == [hidden_attempt]
    audit.close()
