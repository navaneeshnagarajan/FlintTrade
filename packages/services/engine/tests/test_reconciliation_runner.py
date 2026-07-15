"""ReconciliationRunner — cadence, JSONL persistence, audit, failure isolation.

All fakes are local: a fake adapter producing REAL ``ReconciliationReport``
objects via the gateway's pure ``build_report``, a controllable monotonic
clock, an in-memory audit sink, and an injected sleep so the ``run()`` loop is
exercised without wall-clock waits.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import flinttrade_engine.reconciliation_runner as reconciliation_runner_module
from flinttrade_engine.reconciliation_runner import (
    DEFAULT_INTERVAL_SECONDS,
    RECONCILIATION_MISMATCH_EVENT,
    ReconciliationRunner,
    _safe_component,
)
from flinttrade_engine.local_state_provider import JournalLocalStateProvider
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from flinttrade_gateway.reconciliation import (
    LocalStateSnapshot,
    ReconciliationReport,
    build_report,
    reconciliation_evidence_sha256,
)

pytestmark = pytest.mark.unit

ReconciliationRunBusyError = getattr(
    reconciliation_runner_module,
    "ReconciliationRunBusyError",
    RuntimeError,
)

_TS = datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc)

_VALID_ORDER_DIFF = {
    "order_id": "B1",
    "symbol": "RELIANCE",
    "discrepancy": "exists_only_on_broker",
    "severity": "warning",
    "flinttrade_status": "",
    "broker_status": "OPEN",
    "detail": "",
}
_VALID_POSITION_DIFF = {
    "symbol": "NIFTY",
    "exchange": "NFO",
    "product": "MIS",
    "flinttrade_qty": 0.0,
    "broker_qty": 50.0,
    "discrepancy": "exists_only_on_broker",
    "severity": "critical",
}
_VALID_HOLDING_DIFF = {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "flinttrade_qty": 0.0,
    "broker_qty": 1.0,
    "discrepancy": "exists_only_on_broker",
    "severity": "warning",
}
_ZERO_SEVERITY_COUNTS = {"info": 0, "warning": 0, "critical": 0}


def _broker_order(**updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "orderid": "B1",
        "status": "OPEN",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "action": "BUY",
        "quantity": "1",
        "filled_quantity": "0",
        "price": "2500",
        "trigger_price": "0",
        "price_type": "LIMIT",
        "variety": "regular",
        "validity": "DAY",
        "strategy": "Flint",
        "average_price": "0",
    }
    row.update(updates)
    return row


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeCapabilities:
    reconcile_recommended_seconds: int = 300


class _FakeSession:
    def __init__(self, account_id: str = "personal") -> None:
        self.account_id = account_id


class _FakeAdapter:
    """Adapter double: counts reconcile calls, returns real reports or raises."""

    def __init__(
        self,
        broker_id: str = "dhan",
        *,
        interval: int = 300,
        broker_orders: list[dict[str, Any]] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._broker_id = broker_id
        self.capabilities = _FakeCapabilities(reconcile_recommended_seconds=interval)
        self.calls = 0
        self._broker_orders = [_broker_order(**row) for row in (broker_orders or [])]
        self._raise_exc = raise_exc

    @property
    def broker_id(self) -> str:
        return self._broker_id

    async def reconcile(self, session: Any) -> Any:
        self.calls += 1
        if self._raise_exc is not None:
            raise self._raise_exc
        return build_report(
            adapter_id=self._broker_id,
            account_id=str(getattr(session, "account_id", "")),
            generated_at=_TS,
            broker_orders=self._broker_orders,
        )


class _PayloadOverrideReport:
    """Keep real private snapshots while overriding the public payload."""

    def __init__(self, report: Any, updates: dict[str, Any]) -> None:
        self._report = report
        self._updates = updates

    def __getattr__(self, name: str) -> Any:
        return getattr(self._report, name)

    def as_dict(self) -> dict[str, Any]:
        payload = self._report.as_dict()
        payload.update(self._updates)
        return payload


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def log_event(self, event_type: str, **fields: Any) -> None:
        self.events.append((event_type, fields))


def _runner(
    targets: list[tuple[Any, Any]],
    tmp_path: Path,
    *,
    audit: _FakeAudit | None = None,
    clock: _FakeClock | None = None,
    sleep: Any = None,
    poll_seconds: float = 30.0,
) -> ReconciliationRunner:
    return ReconciliationRunner(
        lambda: list(targets),
        audit_logger=audit,
        home_dir=tmp_path,
        poll_seconds=poll_seconds,
        clock=clock if clock is not None else _FakeClock(),
        sleep=sleep,
    )


def _jsonl_lines(tmp_path: Path, broker: str, account: str) -> list[dict[str, Any]]:
    path = tmp_path / "reconciliation" / broker / f"{account}.jsonl"
    assert path.exists(), f"expected JSONL at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# First pass + persistence
# ---------------------------------------------------------------------------


async def test_first_pass_reconciles_and_persists_jsonl(tmp_path: Path) -> None:
    adapter = _FakeAdapter("dhan")
    runner = _runner([(adapter, _FakeSession("personal"))], tmp_path)

    payloads = await runner.run_once()

    assert adapter.calls == 1
    assert len(payloads) == 1
    rows = _jsonl_lines(tmp_path, "dhan", "personal")
    assert len(rows) == 1
    assert rows[0]["adapter_id"] == "dhan"
    assert rows[0]["account_id"] == "personal"
    assert rows[0]["clean"] is True
    assert rows[0]["error"] == ""


@pytest.mark.parametrize("identity_source", ["report", "payload"])
async def test_cross_account_report_identity_fails_closed_for_selected_target(
    tmp_path: Path,
    identity_source: str,
) -> None:
    selected_adapter = "dhan"
    selected_account = "personal"
    foreign_adapter = "upstox"
    foreign_account = "other"
    audit = _FakeAudit()
    recorder = MagicMock()

    class _PayloadOverrideReport:
        def __init__(self, report: Any) -> None:
            self._report = report

        def __getattr__(self, name: str) -> Any:
            return getattr(self._report, name)

        def as_dict(self) -> dict[str, Any]:
            payload = self._report.as_dict()
            payload["adapter_id"] = foreign_adapter
            payload["account_id"] = foreign_account
            return payload

    class _CrossAccountAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            if identity_source == "report":
                return build_report(
                    adapter_id=foreign_adapter,
                    account_id=foreign_account,
                    generated_at=_TS,
                )
            report = build_report(
                adapter_id=selected_adapter,
                account_id=selected_account,
                generated_at=_TS,
            )
            return _PayloadOverrideReport(report)

    foreign_dir = tmp_path / "reconciliation" / foreign_adapter
    foreign_dir.mkdir(parents=True)
    foreign_mismatch = foreign_dir / f"{foreign_account}.mismatch.json"
    foreign_mismatch.write_text('{"fingerprint":"keep-me"}', encoding="utf-8")
    adapter = _CrossAccountAdapter(selected_adapter)
    runner = ReconciliationRunner(
        lambda: [(adapter, _FakeSession(selected_account))],
        audit_logger=audit,
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert len(payloads) == 1
    assert payloads[0]["adapter_id"] == selected_adapter
    assert payloads[0]["account_id"] == selected_account
    assert payloads[0]["error"]
    assert payloads[0]["clean"] is False
    selected_rows = _jsonl_lines(tmp_path, selected_adapter, selected_account)
    assert selected_rows == payloads
    assert not (foreign_dir / f"{foreign_account}.jsonl").exists()
    assert foreign_mismatch.read_text(encoding="utf-8") == '{"fingerprint":"keep-me"}'
    assert len(audit.events) == 1
    assert audit.events[0][1]["adapter_id"] == selected_adapter
    assert audit.events[0][1]["account_id"] == selected_account
    recorder.assert_not_called()


@pytest.mark.parametrize(
    "malformed_fields",
    [
        {"generated_at": None},
        {"orders_diff": None},
        {"positions_diff": ["not-a-row"]},
        {"severity_counts": {"info": 0, "warning": "1", "critical": 0}},
        {"clean": True},
        {"orders_diff": [{}]},
        {
            "orders_diff": [
                {key: value for key, value in _VALID_ORDER_DIFF.items() if key != "detail"}
            ]
        },
        {"orders_diff": [{**_VALID_ORDER_DIFF, "order_id": 1}]},
        {"orders_diff": [{**_VALID_ORDER_DIFF, "discrepancy": "unknown"}]},
        {
            "orders_diff": [{**_VALID_ORDER_DIFF, "severity": "critical"}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {
            "orders_diff": [],
            "positions_diff": [{}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {
            "orders_diff": [],
            "positions_diff": [{**_VALID_POSITION_DIFF, "flinttrade_qty": "0"}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {
            "orders_diff": [],
            "positions_diff": [{**_VALID_POSITION_DIFF, "broker_qty": float("inf")}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {
            "orders_diff": [],
            "positions_diff": [{**_VALID_POSITION_DIFF, "discrepancy": "status_mismatch"}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {
            "orders_diff": [],
            "positions_diff": [{**_VALID_POSITION_DIFF, "severity": "warning"}],
            "severity": "warning",
            "severity_counts": {"info": 0, "warning": 1, "critical": 0},
        },
        {
            "orders_diff": [],
            "holdings_diff": [{}],
            "severity_counts": {"info": 0, "warning": 1, "critical": 0},
        },
        {
            "orders_diff": [],
            "holdings_diff": [{**_VALID_HOLDING_DIFF, "broker_qty": True}],
            "severity_counts": {"info": 0, "warning": 1, "critical": 0},
        },
        {
            "orders_diff": [],
            "holdings_diff": [{**_VALID_HOLDING_DIFF, "discrepancy": "status_mismatch"}],
            "severity_counts": {"info": 0, "warning": 1, "critical": 0},
        },
        {
            "orders_diff": [],
            "holdings_diff": [{**_VALID_HOLDING_DIFF, "severity": "critical"}],
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 0, "critical": 1},
        },
        {"severity_counts": _ZERO_SEVERITY_COUNTS},
        {"severity": "critical"},
        {
            "orders_diff": [],
            "clean": False,
            "severity": "",
            "severity_counts": _ZERO_SEVERITY_COUNTS,
        },
        {"error": "broker fetch failed", "severity": "critical"},
        {
            "orders_diff": [],
            "error": "broker fetch failed",
            "severity": "warning",
            "severity_counts": _ZERO_SEVERITY_COUNTS,
        },
        {
            "orders_diff": [],
            "error": "broker fetch failed",
            "severity": "critical",
            "severity_counts": {"info": 0, "warning": 1, "critical": 0},
        },
    ],
    ids=[
        "missing-generated-at",
        "non-list-diffs",
        "non-mapping-diff-row",
        "non-integer-severity-count",
        "inconsistent-clean-flag",
        "empty-order-diff",
        "missing-order-field",
        "non-string-order-field",
        "unknown-order-discrepancy",
        "wrong-order-severity",
        "empty-position-diff",
        "non-numeric-position-quantity",
        "non-finite-position-quantity",
        "unknown-position-discrepancy",
        "wrong-position-severity",
        "empty-holding-diff",
        "boolean-holding-quantity",
        "unknown-holding-discrepancy",
        "wrong-holding-severity",
        "inexact-severity-counts",
        "wrong-highest-severity",
        "non-clean-report-without-error-or-diffs",
        "error-report-with-diffs",
        "non-critical-error-report",
        "error-report-with-diff-counts",
    ],
)
async def test_malformed_report_fails_closed_before_persistence_or_snapshot_adoption(
    tmp_path: Path,
    malformed_fields: dict[str, Any],
) -> None:
    broker_order = {
        "orderid": "B1",
        "symbol": "RELIANCE",
        "status": "OPEN",
        "quantity": "1",
        "filled_quantity": "0",
    }

    class _MalformedAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            report = await super().reconcile(session)
            return _PayloadOverrideReport(report, malformed_fields)

    recorder = MagicMock(return_value=91)
    audit = _FakeAudit()
    runner = ReconciliationRunner(
        lambda: [(_MalformedAdapter("dhan", broker_orders=[broker_order]), _FakeSession("personal"))],
        audit_logger=audit,
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert len(payloads) == 1
    assert payloads[0]["error"] == "TypeError"
    assert payloads[0]["clean"] is False
    assert "snapshot_generation" not in payloads[0]
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    assert [event for event, _fields in audit.events] == [RECONCILIATION_MISMATCH_EVENT]
    recorder.assert_not_called()


async def test_report_cannot_supply_its_own_snapshot_generation(tmp_path: Path) -> None:
    class _ForgedGenerationAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            report = await super().reconcile(session)
            return _PayloadOverrideReport(report, {"snapshot_generation": 999_999})

    recorder = MagicMock(return_value=None)
    runner = ReconciliationRunner(
        lambda: [(_ForgedGenerationAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert "snapshot_generation" not in payloads[0]
    assert "snapshot_generation" not in _jsonl_lines(tmp_path, "dhan", "personal")[0]
    assert payloads[0]["error"] == "TypeError"
    recorder.assert_not_called()


async def test_exact_but_unstamped_report_contract_fails_closed(tmp_path: Path) -> None:
    class _UnstampedAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            return ReconciliationReport(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
            )

    recorder = MagicMock(return_value=11)
    runner = ReconciliationRunner(
        lambda: [(_UnstampedAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] == "TypeError"
    assert "snapshot_generation" not in payloads[0]
    recorder.assert_not_called()


async def test_forged_report_cannot_persist_diff_then_adopt_empty_broker_snapshot(
    tmp_path: Path,
) -> None:
    broker_order = {
        "orderid": "B1",
        "symbol": "RELIANCE",
        "status": "OPEN",
        "quantity": "1",
        "filled_quantity": "0",
    }

    class _UnboundBrokerSnapshotReport:
        def __init__(self) -> None:
            self._public_report = build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[broker_order],
            )
            self.adapter_id = self._public_report.adapter_id
            self.account_id = self._public_report.account_id
            self.generated_at = self._public_report.generated_at
            self.error = self._public_report.error
            self.broker_orders: tuple[dict[str, Any], ...] = ()
            self.broker_positions: tuple[dict[str, Any], ...] = ()
            self.broker_holdings: tuple[dict[str, Any], ...] = ()
            self.local_state = LocalStateSnapshot()

        def as_dict(self) -> dict[str, Any]:
            return self._public_report.as_dict()

    class _ForgedAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            return _UnboundBrokerSnapshotReport()

    recorder = MagicMock(return_value=12)
    runner = ReconciliationRunner(
        lambda: [(_ForgedAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] == "TypeError"
    assert payloads[0]["orders_diff"] == []
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    recorder.assert_not_called()


async def test_forged_report_cannot_persist_clean_result_from_different_local_snapshot(
    tmp_path: Path,
) -> None:
    broker_order = {
        "orderid": "B1",
        "symbol": "RELIANCE",
        "status": "OPEN",
        "quantity": "1",
        "filled_quantity": "0",
    }
    validated_local = LocalStateSnapshot(orders=(broker_order,))

    class _UnboundLocalSnapshotReport:
        def __init__(self) -> None:
            self._public_report = build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[broker_order],
                local_state=validated_local,
            )
            self.adapter_id = self._public_report.adapter_id
            self.account_id = self._public_report.account_id
            self.generated_at = self._public_report.generated_at
            self.error = self._public_report.error
            self.broker_orders = self._public_report.broker_orders
            self.broker_positions = self._public_report.broker_positions
            self.broker_holdings = self._public_report.broker_holdings
            self.local_state = LocalStateSnapshot()

        def as_dict(self) -> dict[str, Any]:
            return self._public_report.as_dict()

    class _ForgedAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            return _UnboundLocalSnapshotReport()

    recorder = MagicMock(return_value=13)
    runner = ReconciliationRunner(
        lambda: [(_ForgedAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] == "TypeError"
    assert payloads[0]["orders_diff"] == []
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    recorder.assert_not_called()


async def test_private_price_mutation_after_report_build_fails_closed_before_adoption(
    tmp_path: Path,
) -> None:
    order = _broker_order()
    local = LocalStateSnapshot(orders=(order,))

    class _MutatedEvidenceAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            report = build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[order],
                local_state=local,
            )
            report.broker_orders[0]["price"] = "2600"  # type: ignore[index]
            return report

    recorder = MagicMock(return_value=15)
    runner = ReconciliationRunner(
        lambda: [(_MutatedEvidenceAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] in {"TypeError", "ValueError"}
    assert payloads[0]["orders_diff"] == []
    assert "snapshot_generation" not in payloads[0]
    recorder.assert_not_called()


async def test_replaced_private_price_evidence_fails_binding_before_adoption(
    tmp_path: Path,
) -> None:
    order = _broker_order()
    local = LocalStateSnapshot(orders=(order,))

    class _ReplacedEvidenceAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            report = build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[order],
                local_state=local,
            )
            object.__setattr__(
                report,
                "broker_orders",
                ({**order, "price": "2600"},),
            )
            return report

    recorder = MagicMock(return_value=16)
    runner = ReconciliationRunner(
        lambda: [(_ReplacedEvidenceAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] == "ValueError"
    assert "snapshot_generation" not in payloads[0]
    recorder.assert_not_called()


@pytest.mark.parametrize(
    ("field", "replacement", "refresh_binding"),
    [
        pytest.param("price", "2600", False, id="private-binding"),
        pytest.param("price", "2600", True, id="immutable-original-binding"),
        pytest.param("quantity", "2", True, id="public-contract"),
    ],
)
async def test_adoption_revalidates_evidence_after_scan(
    tmp_path: Path,
    field: str,
    replacement: str,
    refresh_binding: bool,
) -> None:
    order = _broker_order(price="2500", average_price="0")
    local = LocalStateSnapshot(orders=(order,))

    class _StableAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            return build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[order],
                local_state=local,
            )

    class _PostScanMutationRunner(ReconciliationRunner):
        async def _reconcile_one(
            self,
            adapter: Any,
            session: Any,
            broker_id: str,
            account_id: str,
        ) -> tuple[dict[str, Any], Any | None] | None:
            outcome = await super()._reconcile_one(adapter, session, broker_id, account_id)
            assert outcome is not None
            payload, report = outcome
            assert report is not None
            mutated_order = {**report.broker_orders[0], field: replacement}
            object.__setattr__(report, "broker_orders", (mutated_order,))
            if refresh_binding:
                object.__setattr__(
                    report,
                    "_evidence_sha256",
                    reconciliation_evidence_sha256(
                        adapter_id=report.adapter_id,
                        account_id=report.account_id,
                        generated_at=report.generated_at,
                        broker_orders=report.broker_orders,
                        broker_positions=report.broker_positions,
                        broker_holdings=report.broker_holdings,
                        local_state=report.local_state,
                    ),
                )
            return payload, report

    recorder = MagicMock(return_value=17)
    runner = _PostScanMutationRunner(
        lambda: [(_StableAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["clean"] is True
    assert payloads[0]["error"] == ""
    assert "snapshot_generation" not in payloads[0]
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    recorder.assert_not_called()


async def test_adoption_revalidates_public_report_after_scan(tmp_path: Path) -> None:
    order = _broker_order()

    class _PostScanPublicMutationRunner(ReconciliationRunner):
        async def _reconcile_one(
            self,
            adapter: Any,
            session: Any,
            broker_id: str,
            account_id: str,
        ) -> tuple[dict[str, Any], Any | None] | None:
            outcome = await super()._reconcile_one(adapter, session, broker_id, account_id)
            assert outcome is not None
            payload, report = outcome
            assert report is not None and report.orders_diff
            object.__setattr__(report, "orders_diff", ())
            return payload, report

    recorder = MagicMock(return_value=18)
    runner = _PostScanPublicMutationRunner(
        lambda: [(_FakeAdapter("dhan", broker_orders=[order]), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["orders_diff"]
    assert "snapshot_generation" not in payloads[0]
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    recorder.assert_not_called()


async def test_stable_evidence_is_revalidated_and_adopted(tmp_path: Path) -> None:
    order = _broker_order(price=0, trigger_price=0.0, average_price="0")
    local = LocalStateSnapshot(orders=(order,))

    class _StableAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            return build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                broker_orders=[order],
                local_state=local,
            )

    recorder = MagicMock(return_value=18)
    runner = ReconciliationRunner(
        lambda: [(_StableAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["snapshot_generation"] == 18
    recorded = recorder.call_args.kwargs["orders"][0]
    assert recorded["price"] == 0
    assert recorded["trigger_price"] == 0.0
    assert recorded["average_price"] == "0"


async def test_error_report_never_adopts_attached_private_snapshot(tmp_path: Path) -> None:
    class _ErrorAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            report = build_report(
                adapter_id="dhan",
                account_id="personal",
                generated_at=_TS,
                error="broker fetch failed",
            )
            object.__setattr__(report, "broker_orders", (_broker_order(),))
            return report

    recorder = MagicMock(return_value=14)
    runner = ReconciliationRunner(
        lambda: [(_ErrorAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert payloads[0]["error"] == "ValueError"
    assert payloads[0]["orders_diff"] == []
    assert _jsonl_lines(tmp_path, "dhan", "personal") == payloads
    recorder.assert_not_called()


async def test_jsonl_appends_one_line_per_run(tmp_path: Path) -> None:
    clock = _FakeClock()
    adapter = _FakeAdapter("dhan", interval=60)
    runner = _runner([(adapter, _FakeSession("personal"))], tmp_path, clock=clock)

    await runner.run_once()
    clock.advance(61)
    await runner.run_once()

    assert adapter.calls == 2
    assert len(_jsonl_lines(tmp_path, "dhan", "personal")) == 2


async def test_restart_repairs_only_torn_unterminated_tail_before_adoption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    path.parent.mkdir(parents=True)
    previous = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=_TS - timedelta(minutes=1),
    ).as_dict()
    prior_line = json.dumps(previous, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    torn_tail = b'{"account_id":"personal","adapter_id":"dhan"'
    path.write_bytes(prior_line + torn_tail)

    observed_rows: list[list[dict[str, Any]]] = []

    def _record_after_persistence(**_fields: Any) -> int:
        encoded = path.read_bytes()
        assert encoded.endswith(b"\n")
        rows = [json.loads(line) for line in encoded.splitlines()]
        observed_rows.append(rows)
        return 41

    adapter = _FakeAdapter(
        "dhan",
        broker_orders=[
            {
                "orderid": "B1",
                "symbol": "RELIANCE",
                "status": "OPEN",
                "quantity": "1",
                "filled_quantity": "0",
            }
        ],
    )
    restarted = ReconciliationRunner(
        lambda: [(adapter, _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=_record_after_persistence,
    )

    payloads = await restarted.run_once()

    assert payloads[0]["snapshot_generation"] == 41
    assert len(observed_rows) == 1
    assert observed_rows[0][0] == previous
    assert observed_rows[0][1]["adapter_id"] == "dhan"
    assert torn_tail not in path.read_bytes()


async def test_restart_preserves_complete_unterminated_report_before_append(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    path.parent.mkdir(parents=True)
    previous = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=_TS - timedelta(minutes=1),
    ).as_dict()
    path.write_text(
        json.dumps(previous, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    runner = _runner([(_FakeAdapter("dhan"), _FakeSession("personal"))], tmp_path)

    await runner.run_once()

    rows = _jsonl_lines(tmp_path, "dhan", "personal")
    assert len(rows) == 2
    assert rows[0] == previous
    assert rows[1]["generated_at"] == _TS.isoformat()


async def test_invalid_interior_history_blocks_append_and_snapshot_adoption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    path.parent.mkdir(parents=True)
    first = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=_TS - timedelta(minutes=2),
    ).as_dict()
    last = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=_TS - timedelta(minutes=1),
    ).as_dict()
    original = b"".join(
        (
            json.dumps(first, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n",
            b"{}\n",
            json.dumps(last, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n",
        )
    )
    path.write_bytes(original)
    recorder = MagicMock(return_value=42)
    runner = ReconciliationRunner(
        lambda: [(_FakeAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert "snapshot_generation" not in payloads[0]
    assert path.read_bytes() == original
    recorder.assert_not_called()


async def test_unterminated_complete_malformed_report_is_not_repaired(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    path.parent.mkdir(parents=True)
    original = b"{}"
    path.write_bytes(original)
    recorder = MagicMock(return_value=42)
    runner = ReconciliationRunner(
        lambda: [(_FakeAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert "snapshot_generation" not in payloads[0]
    assert path.read_bytes() == original
    recorder.assert_not_called()


async def test_newline_terminated_invalid_tail_blocks_append_and_adoption(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    path.parent.mkdir(parents=True)
    previous = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=_TS - timedelta(minutes=1),
    ).as_dict()
    original = (
        json.dumps(previous, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n{not-json}\n"
    )
    path.write_bytes(original)
    recorder = MagicMock(return_value=42)
    audit = _FakeAudit()
    adapter = _FakeAdapter(
        "dhan",
        broker_orders=[
            {
                "orderid": "B1",
                "symbol": "RELIANCE",
                "status": "OPEN",
                "quantity": "1",
                "filled_quantity": "0",
            }
        ],
    )
    runner = ReconciliationRunner(
        lambda: [(adapter, _FakeSession("personal"))],
        audit_logger=audit,
        home_dir=tmp_path,
        state_recorder=recorder,
    )

    payloads = await runner.run_once()

    assert "snapshot_generation" not in payloads[0]
    assert path.read_bytes() == original
    assert audit.events == []
    recorder.assert_not_called()


async def test_report_append_uses_shared_per_file_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = tmp_path / "reconciliation" / "dhan"
    report_dir.mkdir(parents=True)
    lock_path = report_dir / ".personal.jsonl.lock"
    recorder = MagicMock(return_value=43)
    runner = ReconciliationRunner(
        lambda: [(_FakeAdapter("dhan"), _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )
    monkeypatch.setattr(
        reconciliation_runner_module,
        "_PERSIST_LOCK_TIMEOUT_SECONDS",
        0.0,
    )

    with OwnerSafeFileLock(lock_path, timeout=0, mode=0o600, thread_local=False):
        payloads = await runner.run_once()

    assert "snapshot_generation" not in payloads[0]
    assert not (report_dir / "personal.jsonl").exists()
    recorder.assert_not_called()


async def test_broker_only_observation_stays_nonclean_but_unchanged_audit_deduplicates(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "order-lifecycle.sqlite3"
    order = {
        "orderid": "D1",
        "symbol": "NIFTY",
        "exchange": "NFO",
        "product": "MIS",
        "status": "OPEN",
        "quantity": "50",
        "filled_quantity": "0",
    }

    class _LifecycleSession(_FakeSession):
        adapter_id = "dhan"

    class _LifecycleAdapter(_FakeAdapter):
        def __init__(
            self,
            provider: JournalLocalStateProvider,
            row: dict[str, Any],
            generated_at: datetime,
        ) -> None:
            super().__init__("dhan", broker_orders=[row])
            self.provider = provider
            self.generated_at = generated_at

        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            return build_report(
                adapter_id="dhan",
                account_id=session.account_id,
                    generated_at=self.generated_at,
                broker_orders=self._broker_orders,
                local_state=self.provider(session),
            )

    cycle_index = 0

    async def _cycle(row: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, dict[str, Any]]]]:
        nonlocal cycle_index
        provider = JournalLocalStateProvider(ledger_path=ledger_path)
        generated_at = _TS + timedelta(seconds=cycle_index)
        cycle_index += 1
        adapter = _LifecycleAdapter(provider, row, generated_at)
        audit = _FakeAudit()
        runner = ReconciliationRunner(
            lambda: [(adapter, _LifecycleSession("personal"))],
            audit_logger=audit,
            home_dir=tmp_path,
            state_recorder=provider.record_broker_snapshot,
        )
        payloads = await runner.run_once()
        return payloads[0], audit.events

    first, first_events = await _cycle(order)
    unchanged, unchanged_events = await _cycle(order)
    partial = {**order, "status": "PARTIALLY_FILLED", "filled_quantity": "25"}
    changed, changed_events = await _cycle(partial)
    converged, converged_events = await _cycle(partial)

    assert first["clean"] is False
    assert first["snapshot_generation"] == 1
    assert [name for name, _ in first_events] == [RECONCILIATION_MISMATCH_EVENT]
    assert unchanged["clean"] is False
    assert unchanged_events == []
    assert changed["clean"] is False
    assert [name for name, _ in changed_events] == [RECONCILIATION_MISMATCH_EVENT]
    assert converged["clean"] is False
    assert converged_events == []

    restarted = JournalLocalStateProvider(ledger_path=ledger_path)
    assert restarted(_LifecycleSession("personal")).orders == ()
    assert [
        event["status"]
        for event in restarted.list_order_events(
            adapter_id="dhan", account_id="personal", order_id="D1"
        )
    ] == ["OPEN", "PARTIALLY_FILLED"]


async def test_snapshot_is_not_adopted_when_report_persistence_fails(tmp_path: Path) -> None:
    recorder = MagicMock()
    adapter = _FakeAdapter(
        "dhan",
        broker_orders=[{"orderid": "B1", "symbol": "RELIANCE", "status": "OPEN"}],
    )
    runner = ReconciliationRunner(
        lambda: [(adapter, _FakeSession("personal"))],
        home_dir=tmp_path,
        state_recorder=recorder,
    )
    runner._persist = MagicMock(return_value=False)  # type: ignore[method-assign]

    payloads = await runner.run_once()

    assert payloads[0]["clean"] is False
    recorder.assert_not_called()


async def test_local_only_dispatch_remains_critical_across_empty_snapshots_and_restart(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "order-lifecycle.sqlite3"
    provider = JournalLocalStateProvider(ledger_path=ledger_path)
    provider.record_dispatched_order(
        adapter_id="dhan",
        account_id="personal",
        order_id="LOCAL-ONLY",
        order={"symbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": 1},
    )

    class _SessionWithAdapter(_FakeSession):
        adapter_id = "dhan"

    class _EmptyBrokerAdapter(_FakeAdapter):
        def __init__(self, state: JournalLocalStateProvider) -> None:
            super().__init__("dhan")
            self.state = state

        async def reconcile(self, session: Any) -> Any:
            self.calls += 1
            return build_report(
                adapter_id="dhan",
                account_id=session.account_id,
                generated_at=_TS,
                broker_orders=[],
                local_state=self.state(session),
            )

    adapter = _EmptyBrokerAdapter(provider)
    first_audit = _FakeAudit()
    first = ReconciliationRunner(
        lambda: [(adapter, _SessionWithAdapter("personal"))],
        home_dir=tmp_path,
        audit_logger=first_audit,
        state_recorder=provider.record_broker_snapshot,
    )
    first_payload = (await first.run_once())[0]

    restarted_provider = JournalLocalStateProvider(ledger_path=ledger_path)
    second_adapter = _EmptyBrokerAdapter(restarted_provider)
    second_audit = _FakeAudit()
    second = ReconciliationRunner(
        lambda: [(second_adapter, _SessionWithAdapter("personal"))],
        home_dir=tmp_path,
        audit_logger=second_audit,
        state_recorder=restarted_provider.record_broker_snapshot,
    )
    second_payload = (await second.run_once())[0]

    assert first_payload["clean"] is False
    assert first_payload["orders_diff"][0]["discrepancy"] == "exists_only_in_flinttrade"
    assert second_payload["clean"] is False
    assert second_payload["orders_diff"][0]["discrepancy"] == "exists_only_in_flinttrade"
    assert restarted_provider(_SessionWithAdapter("personal")).orders[0]["orderid"] == "LOCAL-ONLY"
    assert [event for event, _fields in first_audit.events] == [RECONCILIATION_MISMATCH_EVENT]
    assert second_audit.events == []


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


async def test_cadence_respects_recommended_seconds(tmp_path: Path) -> None:
    clock = _FakeClock()
    adapter = _FakeAdapter("dhan", interval=300)
    runner = _runner([(adapter, _FakeSession())], tmp_path, clock=clock)

    await runner.run_once()
    assert adapter.calls == 1

    # Not yet due — repeated cycles must not re-reconcile.
    await runner.run_once()
    clock.advance(299)
    await runner.run_once()
    assert adapter.calls == 1

    # Past the interval — due again.
    clock.advance(2)
    await runner.run_once()
    assert adapter.calls == 2


async def test_selector_filter_limits_work_and_force_bypasses_cadence(tmp_path: Path) -> None:
    clock = _FakeClock()
    dhan = _FakeAdapter("dhan", interval=300)
    upstox = _FakeAdapter("upstox", interval=300)
    runner = _runner(
        [(dhan, _FakeSession("a")), (upstox, _FakeSession("b"))],
        tmp_path,
        clock=clock,
    )

    first = await runner.run_once(selectors={"dhan:a"})
    not_due = await runner.run_once(selectors={"dhan:a"})
    forced = await runner.run_once(selectors={"dhan:a"}, force=True)

    assert [(row["adapter_id"], row["account_id"]) for row in first] == [("dhan", "a")]
    assert not_due == []
    assert [(row["adapter_id"], row["account_id"]) for row in forced] == [("dhan", "a")]
    assert dhan.calls == 2
    assert upstox.calls == 0


async def test_selector_filter_rejects_non_exact_values(tmp_path: Path) -> None:
    runner = _runner([], tmp_path)

    with pytest.raises(ValueError, match="exact broker:account"):
        await runner.run_once(selectors={"dhan"})


async def test_per_broker_cadence_is_independent(tmp_path: Path) -> None:
    clock = _FakeClock()
    fast = _FakeAdapter("dhan", interval=60)
    slow = _FakeAdapter("upstox", interval=300)
    targets = [(fast, _FakeSession("a")), (slow, _FakeSession("b"))]
    runner = _runner(targets, tmp_path, clock=clock)

    await runner.run_once()
    assert (fast.calls, slow.calls) == (1, 1)

    clock.advance(61)
    await runner.run_once()
    assert (fast.calls, slow.calls) == (2, 1)

    clock.advance(240)  # total 301s — slow now due; fast due again too (>=120)
    await runner.run_once()
    assert (fast.calls, slow.calls) == (3, 2)


async def test_missing_capabilities_fall_back_to_default_interval(tmp_path: Path) -> None:
    clock = _FakeClock()
    adapter = _FakeAdapter("dhan")
    adapter.capabilities = None  # no advertised cadence
    runner = _runner([(adapter, _FakeSession())], tmp_path, clock=clock)

    await runner.run_once()
    clock.advance(DEFAULT_INTERVAL_SECONDS - 1)
    await runner.run_once()
    assert adapter.calls == 1
    clock.advance(2)
    await runner.run_once()
    assert adapter.calls == 2


async def test_new_target_is_reconciled_on_first_sight(tmp_path: Path) -> None:
    """A session established mid-flight (login) is due immediately, not after
    a full broker interval."""
    clock = _FakeClock()
    first = _FakeAdapter("dhan", interval=300)
    targets: list[tuple[Any, Any]] = [(first, _FakeSession("a"))]
    runner = ReconciliationRunner(
        lambda: list(targets), home_dir=tmp_path, clock=clock
    )

    await runner.run_once()
    late = _FakeAdapter("upstox", interval=300)
    targets.append((late, _FakeSession("b")))
    await runner.run_once()  # dhan not due; upstox first sight

    assert first.calls == 1
    assert late.calls == 1


# ---------------------------------------------------------------------------
# Audit emission
# ---------------------------------------------------------------------------


async def test_mismatch_emits_audit_event_with_sha256(tmp_path: Path) -> None:
    audit = _FakeAudit()
    adapter = _FakeAdapter(
        "dhan",
        broker_orders=[{"orderid": "B1", "symbol": "RELIANCE", "status": "OPEN", "quantity": "10"}],
    )
    runner = _runner([(adapter, _FakeSession("personal"))], tmp_path, audit=audit)

    payloads = await runner.run_once()

    assert payloads[0]["clean"] is False
    assert len(audit.events) == 1
    event_type, fields = audit.events[0]
    assert event_type == RECONCILIATION_MISMATCH_EVENT
    assert fields["adapter_id"] == "dhan"
    assert fields["account_id"] == "personal"
    assert fields["severity"] == "warning"  # exists_only_on_broker order
    assert fields["orders_diffs"] == 1
    assert fields["positions_diffs"] == 0
    assert fields["holdings_diffs"] == 0
    assert fields["severity_counts"]["warning"] == 1
    sha = fields["report_sha256"]
    assert isinstance(sha, str) and len(sha) == 64
    int(sha, 16)  # valid hex digest


async def test_clean_report_emits_no_audit_event(tmp_path: Path) -> None:
    audit = _FakeAudit()
    runner = _runner([(_FakeAdapter("dhan"), _FakeSession())], tmp_path, audit=audit)

    await runner.run_once()

    assert audit.events == []


async def test_broken_audit_logger_does_not_stop_persistence(tmp_path: Path) -> None:
    class _BrokenAudit:
        def log_event(self, event_type: str, **fields: Any) -> None:
            raise OSError("audit disk full")

    adapter = _FakeAdapter("dhan", broker_orders=[{"orderid": "B1", "symbol": "X", "status": "OPEN"}])
    runner = ReconciliationRunner(
        lambda: [(adapter, _FakeSession("personal"))],
        audit_logger=_BrokenAudit(),
        home_dir=tmp_path,
        clock=_FakeClock(),
    )

    payloads = await runner.run_once()

    assert len(payloads) == 1
    assert len(_jsonl_lines(tmp_path, "dhan", "personal")) == 1


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


async def test_adapter_failure_is_isolated_and_recorded(tmp_path: Path) -> None:
    audit = _FakeAudit()
    broken = _FakeAdapter("dhan", raise_exc=RuntimeError("SDK exploded"))
    healthy = _FakeAdapter("upstox")
    targets = [(broken, _FakeSession("a")), (healthy, _FakeSession("b"))]
    runner = _runner(targets, tmp_path, audit=audit)

    payloads = await runner.run_once()

    # The healthy broker still reconciled.
    assert healthy.calls == 1
    assert len(payloads) == 2

    # The failure is recorded as an error report (critical, empty diffs)…
    error_rows = _jsonl_lines(tmp_path, "dhan", "a")
    assert len(error_rows) == 1
    assert error_rows[0]["error"] == "RuntimeError"
    assert "SDK exploded" not in json.dumps(error_rows[0])
    assert error_rows[0]["clean"] is False
    assert error_rows[0]["severity"] == "critical"
    assert error_rows[0]["orders_diff"] == []

    # …and audited as a mismatch (broker state unknown).
    assert [e for e, _ in audit.events] == [RECONCILIATION_MISMATCH_EVENT]
    assert audit.events[0][1]["adapter_id"] == "dhan"

    # The healthy report is persisted too.
    assert _jsonl_lines(tmp_path, "upstox", "b")[0]["clean"] is True


async def test_failing_broker_backs_off_to_its_cadence(tmp_path: Path) -> None:
    clock = _FakeClock()
    broken = _FakeAdapter("dhan", interval=120, raise_exc=RuntimeError("down"))
    runner = _runner([(broken, _FakeSession())], tmp_path, clock=clock)

    await runner.run_once()
    await runner.run_once()  # immediately again — must NOT hot-loop
    assert broken.calls == 1
    clock.advance(121)
    await runner.run_once()
    assert broken.calls == 2


async def test_targets_provider_failure_returns_empty(tmp_path: Path) -> None:
    def _explode() -> list[tuple[Any, Any]]:
        raise RuntimeError("registry locked")

    runner = ReconciliationRunner(_explode, home_dir=tmp_path, clock=_FakeClock())

    assert await runner.run_once() == []


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def test_safe_component_sanitises_and_falls_back() -> None:
    assert _safe_component("dhan", "unknown") == "dhan"
    assert _safe_component("dh/an", "unknown").startswith("dh_an--")
    assert _safe_component("..", "default").startswith("default--")
    assert _safe_component("", "default") == "default"
    assert _safe_component(None, "default") == "default"
    assert _safe_component("acct-01.b", "default") == "acct-01.b"
    assert _safe_component("acct:a", "default") != _safe_component("acct_a", "default")


async def test_hostile_ids_cannot_escape_reconciliation_tree(tmp_path: Path) -> None:
    adapter = _FakeAdapter("dh/an")
    runner = _runner([(adapter, _FakeSession(".."))], tmp_path)

    await runner.run_once()

    rows = _jsonl_lines(
        tmp_path,
        _safe_component("dh/an", "unknown"),
        _safe_component("..", "default"),
    )
    assert rows[0]["adapter_id"] == "dh/an"  # payload keeps the raw id; only the path is sanitised


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform lacks symlink support")
async def test_report_persistence_refuses_symbolic_link_target(tmp_path: Path) -> None:
    target = tmp_path / "outside.jsonl"
    target.write_text("sentinel\n", encoding="utf-8")
    report_dir = tmp_path / "reconciliation" / "dhan"
    report_dir.mkdir(parents=True)
    (report_dir / "personal.jsonl").symlink_to(target)
    runner = _runner([(_FakeAdapter("dhan"), _FakeSession("personal"))], tmp_path)

    assert len(await runner.run_once()) == 1
    assert target.read_text(encoding="utf-8") == "sentinel\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertion")
async def test_report_persistence_is_owner_only(tmp_path: Path) -> None:
    runner = _runner([(_FakeAdapter("dhan"), _FakeSession("personal"))], tmp_path)

    await runner.run_once()

    path = tmp_path / "reconciliation" / "dhan" / "personal.jsonl"
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    assert path.parent.parent.stat().st_mode & 0o077 == 0


async def test_concurrent_run_once_fails_busy_instead_of_racing(tmp_path: Path) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingAdapter(_FakeAdapter):
        async def reconcile(self, session: Any) -> Any:
            entered.set()
            await release.wait()
            return await super().reconcile(session)

    runner = _runner([(_BlockingAdapter(), _FakeSession())], tmp_path)
    active = asyncio.create_task(runner.run_once())
    await entered.wait()

    with pytest.raises(ReconciliationRunBusyError):
        await runner.run_once()

    release.set()
    await active


async def test_sync_trigger_refuses_its_own_running_event_loop(tmp_path: Path) -> None:
    runner = _runner([], tmp_path)
    runner._loop = asyncio.get_running_loop()

    with pytest.raises(
        ReconciliationRunBusyError,
        match="own event loop",
    ):
        runner.trigger()


# ---------------------------------------------------------------------------
# run() loop lifecycle
# ---------------------------------------------------------------------------


async def test_run_loop_reconciles_on_start_and_every_interval(tmp_path: Path) -> None:
    clock = _FakeClock()
    adapter = _FakeAdapter("dhan", interval=60)
    runner_holder: list[ReconciliationRunner] = []
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(seconds)
        if len(sleeps) >= 4:
            runner_holder[0].stop()

    runner = _runner(
        [(adapter, _FakeSession())], tmp_path, clock=clock, sleep=_fake_sleep, poll_seconds=30.0
    )
    runner_holder.append(runner)

    await runner.run()

    # t=0 (start) and t=60 (after two 30s polls) → exactly 2 reconciles in 4 polls.
    assert adapter.calls == 2
    assert sleeps == [30.0, 30.0, 30.0, 30.0]
    assert runner.is_running is False


async def test_stop_before_sleep_exits_loop(tmp_path: Path) -> None:
    adapter = _FakeAdapter("dhan")
    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:  # pragma: no cover - must not run
        slept.append(seconds)

    runner = _runner([(adapter, _FakeSession())], tmp_path, sleep=_fake_sleep)
    # Stop during the first cycle: run() must exit without ever sleeping.
    original = runner.run_once

    async def _run_once_then_stop() -> list[dict[str, Any]]:
        result = await original()
        runner.stop()
        return result

    runner.run_once = _run_once_then_stop  # type: ignore[method-assign]

    await runner.run()

    assert adapter.calls == 1
    assert slept == []
    assert runner.is_running is False
