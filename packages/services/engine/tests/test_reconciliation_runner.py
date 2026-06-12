"""ReconciliationRunner — cadence, JSONL persistence, audit, failure isolation.

All fakes are local: a fake adapter producing REAL ``ReconciliationReport``
objects via the gateway's pure ``build_report``, a controllable monotonic
clock, an in-memory audit sink, and an injected sleep so the ``run()`` loop is
exercised without wall-clock waits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from flinttrade_engine.reconciliation_runner import (
    DEFAULT_INTERVAL_SECONDS,
    RECONCILIATION_MISMATCH_EVENT,
    ReconciliationRunner,
    _safe_component,
)
from flinttrade_gateway.reconciliation import build_report

pytestmark = pytest.mark.unit

_TS = datetime(2026, 6, 12, 9, 30, tzinfo=timezone.utc)


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
        self._broker_orders = broker_orders or []
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


async def test_jsonl_appends_one_line_per_run(tmp_path: Path) -> None:
    clock = _FakeClock()
    adapter = _FakeAdapter("dhan", interval=60)
    runner = _runner([(adapter, _FakeSession("personal"))], tmp_path, clock=clock)

    await runner.run_once()
    clock.advance(61)
    await runner.run_once()

    assert adapter.calls == 2
    assert len(_jsonl_lines(tmp_path, "dhan", "personal")) == 2


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
    assert "RuntimeError: SDK exploded" in error_rows[0]["error"]
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
    assert _safe_component("dh/an", "unknown") == "dh_an"
    assert _safe_component("..", "default") == "default"
    assert _safe_component("", "default") == "default"
    assert _safe_component(None, "default") == "default"
    assert _safe_component("acct-01.b", "default") == "acct-01.b"


async def test_hostile_ids_cannot_escape_reconciliation_tree(tmp_path: Path) -> None:
    adapter = _FakeAdapter("dh/an")
    runner = _runner([(adapter, _FakeSession(".."))], tmp_path)

    await runner.run_once()

    rows = _jsonl_lines(tmp_path, "dh_an", "default")
    assert rows[0]["adapter_id"] == "dh/an"  # payload keeps the raw id; only the path is sanitised


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
