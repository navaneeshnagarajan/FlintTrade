"""Engine-side reconciliation runner — cadence, persistence, audit (contract §14.2).

For every ACTIVE native ``(adapter, session)`` pair supplied by the injected
``targets`` callable, the runner invokes ``adapter.reconcile(session)`` once on
first sight (app start, or first credential-replay login mid-flight) and then
every ``Capabilities.reconcile_recommended_seconds``, per broker. Each report
is persisted as one JSONL line under
``<flinttrade home>/reconciliation/<broker_id>/<account_id>.jsonl`` and every
NON-CLEAN report additionally emits a ``RECONCILIATION_MISMATCH`` audit event
carrying the report's sha256 plus a per-diff summary.

One broker's failure never stops the loop: adapters already encapsulate broker
fetch failures as error reports (§14.3), and an UNEXPECTED ``reconcile`` raise
is isolated here, logged, and recorded as a synthesised error report of the
same shape — so the JSONL history shows the gap honestly and the next cycle
retries. Persistence and audit emission are individually guarded too.

Adapters remain duck-typed, but their ``reconcile`` result must be the exact
gateway :class:`ReconciliationReport` contract constructed by ``build_report``.
Gateway report construction is imported lazily when binding a public report to
its private validated snapshots, keeping no import-time gateway dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import stat
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from flinttrade_core.secure_file import fsync_parent_directory, harden, harden_directory

logger = logging.getLogger("flinttrade.engine.reconciliation_runner")

RECONCILIATION_MISMATCH_EVENT = "RECONCILIATION_MISMATCH"

#: Fallback cadence when an adapter advertises no usable recommendation.
DEFAULT_INTERVAL_SECONDS = 300

#: How often the loop re-checks which targets are due. Deliberately shorter
#: than any broker cadence so a session established mid-flight gets its first
#: reconcile within one poll, not one full broker interval.
DEFAULT_POLL_SECONDS = 30.0

_JSONL_READ_CHUNK_BYTES = 64 * 1024
_PERSIST_LOCK_TIMEOUT_SECONDS = 10.0

_SEVERITY_NAMES = ("info", "warning", "critical")
_SEVERITY_RANK = {name: rank for rank, name in enumerate(_SEVERITY_NAMES)}

_ORDER_DIFF_FIELDS = (
    "order_id",
    "symbol",
    "discrepancy",
    "severity",
    "flinttrade_status",
    "broker_status",
    "detail",
)
_POSITION_DIFF_FIELDS = (
    "symbol",
    "exchange",
    "product",
    "flinttrade_qty",
    "broker_qty",
    "discrepancy",
    "severity",
)
_HOLDING_DIFF_FIELDS = (
    "symbol",
    "exchange",
    "flinttrade_qty",
    "broker_qty",
    "discrepancy",
    "severity",
)

_ORDER_SEVERITY_BY_DISCREPANCY = {
    "exists_only_on_broker": "warning",
    "exists_only_in_flinttrade": "critical",
    "status_mismatch": "warning",
    "qty_mismatch": "warning",
}
_POSITION_SEVERITY_BY_DISCREPANCY = {
    "exists_only_on_broker": "critical",
    "exists_only_in_flinttrade": "critical",
    "qty_mismatch": "critical",
}
_HOLDING_SEVERITY_BY_DISCREPANCY = {
    "exists_only_on_broker": "warning",
    "exists_only_in_flinttrade": "warning",
    "qty_mismatch": "warning",
}


def _safe_component(raw: Any, fallback: str) -> str:
    """Sanitise a broker/account id into a single safe path component.

    Anything outside ``[A-Za-z0-9._-]`` becomes ``_``; results that are empty
    or consist solely of separators/dots (e.g. ``".."``) collapse to
    ``fallback`` so a hostile id can never traverse out of the
    ``reconciliation/`` tree.
    """
    text = str(raw or "").strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in text)
    if not text:
        return fallback
    if not cleaned or set(cleaned) <= {".", "_", "-"}:
        cleaned = fallback
    if cleaned != text:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        return f"{cleaned}--{digest}"
    return cleaned


def _account_ref(account_id: Any) -> str:
    """Return a non-secret account reference suitable for logs."""
    return hashlib.sha256(str(account_id or "").encode("utf-8")).hexdigest()[:10]


def _error_payload(adapter_id: str, account_id: str, error: str) -> dict[str, Any]:
    """A synthesised error report mirroring ``ReconciliationReport.as_dict()``.

    Used when ``reconcile`` itself raises unexpectedly (the adapter normally
    returns an error report for broker fetch failures, §14.3). Diff lists are
    empty — diffing against an unknown broker state would fabricate
    discrepancies — and severity is critical because broker state is unknown.
    """
    return {
        "adapter_id": adapter_id,
        "account_id": account_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "orders_diff": [],
        "positions_diff": [],
        "holdings_diff": [],
        "error": error,
        "clean": False,
        "severity": "critical",
        "severity_counts": {"info": 0, "warning": 0, "critical": 0},
    }


def _normalise_diff_rows(
    payload: Mapping[str, Any],
    field: str,
    *,
    fields: tuple[str, ...],
    numeric_fields: tuple[str, ...],
    severity_by_discrepancy: Mapping[str, str],
) -> list[dict[str, Any]] | None:
    """Validate and canonicalise one list of report diff rows."""
    value = payload.get(field)
    if not isinstance(value, list):
        return None
    string_fields = tuple(name for name in fields if name not in numeric_fields)
    normalised: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping) or any(name not in row for name in fields):
            return None
        if any(type(row[name]) is not str for name in string_fields):
            return None
        for name in numeric_fields:
            number = row[name]
            if type(number) not in (int, float):
                return None
            try:
                if not math.isfinite(number):
                    return None
            except OverflowError:
                return None
        expected_severity = severity_by_discrepancy.get(row["discrepancy"])
        if expected_severity is None or row["severity"] != expected_severity:
            return None
        normalised.append({name: row[name] for name in fields})
    return normalised


def _normalise_report_payload(payload: Any) -> dict[str, Any] | None:
    """Return the canonical persisted report shape, or ``None`` if malformed."""
    if not isinstance(payload, Mapping):
        return None
    raw_adapter_id = payload.get("adapter_id")
    raw_account_id = payload.get("account_id")
    raw_generated_at = payload.get("generated_at")
    if (
        type(raw_adapter_id) is not str
        or type(raw_account_id) is not str
        or type(raw_generated_at) is not str
    ):
        return None
    adapter_id = raw_adapter_id.strip().lower()
    account_id = raw_account_id.strip()
    generated_at = raw_generated_at.strip()
    if not adapter_id or not account_id or not generated_at:
        return None

    orders_diff = _normalise_diff_rows(
        payload,
        "orders_diff",
        fields=_ORDER_DIFF_FIELDS,
        numeric_fields=(),
        severity_by_discrepancy=_ORDER_SEVERITY_BY_DISCREPANCY,
    )
    positions_diff = _normalise_diff_rows(
        payload,
        "positions_diff",
        fields=_POSITION_DIFF_FIELDS,
        numeric_fields=("flinttrade_qty", "broker_qty"),
        severity_by_discrepancy=_POSITION_SEVERITY_BY_DISCREPANCY,
    )
    holdings_diff = _normalise_diff_rows(
        payload,
        "holdings_diff",
        fields=_HOLDING_DIFF_FIELDS,
        numeric_fields=("flinttrade_qty", "broker_qty"),
        severity_by_discrepancy=_HOLDING_SEVERITY_BY_DISCREPANCY,
    )
    if orders_diff is None or positions_diff is None or holdings_diff is None:
        return None

    raw_counts = payload.get("severity_counts")
    if not isinstance(raw_counts, Mapping) or len(raw_counts) != len(_SEVERITY_NAMES):
        return None
    counts: dict[str, int] = {}
    for name in _SEVERITY_NAMES:
        value = raw_counts.get(name)
        if type(value) is not int or value < 0:
            return None
        counts[name] = value

    clean = payload.get("clean")
    error = payload.get("error")
    severity = payload.get("severity")
    if type(clean) is not bool or type(error) is not str or type(severity) is not str:
        return None

    all_diffs = [*orders_diff, *positions_diff, *holdings_diff]
    actual_counts = {name: 0 for name in _SEVERITY_NAMES}
    for row in all_diffs:
        actual_counts[row["severity"]] += 1
    if counts != actual_counts:
        return None

    if error:
        if clean or all_diffs or severity != "critical":
            return None
    elif all_diffs:
        highest_severity = max(
            (row["severity"] for row in all_diffs),
            key=_SEVERITY_RANK.__getitem__,
        )
        if clean or severity != highest_severity:
            return None
    elif not clean or severity:
        return None

    normalised = {
        "adapter_id": adapter_id,
        "account_id": account_id,
        "generated_at": generated_at,
        "orders_diff": orders_diff,
        "positions_diff": positions_diff,
        "holdings_diff": holdings_diff,
        "error": error,
        "clean": clean,
        "severity": severity,
        "severity_counts": counts,
    }
    try:
        json.dumps(normalised, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return None
    return normalised


def _validate_history_record(
    decoded: Any,
    *,
    adapter_id: str,
    account_id: str,
    record_number: int,
) -> None:
    """Reject a decoded history record that is malformed or misfiled."""
    previous = _normalise_report_payload(decoded)
    if previous is None:
        raise ValueError(f"reconciliation history record {record_number} is malformed")
    if previous["adapter_id"] != adapter_id or previous["account_id"] != account_id:
        raise ValueError(f"reconciliation history record {record_number} has a mismatched identity")


def _prepare_jsonl_tail(
    descriptor: int,
    size: int,
    *,
    adapter_id: str,
    account_id: str,
) -> bytes:
    """Validate all history and repair only an undecodable final fragment."""
    if size == 0:
        return b""
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = size
    pending = bytearray()
    record_number = 0
    while remaining > 0:
        chunk = os.read(descriptor, min(_JSONL_READ_CHUNK_BYTES, remaining))
        if not chunk:
            raise OSError("reconciliation history changed while it was validated")
        pending.extend(chunk)
        remaining -= len(chunk)
        while (separator := pending.find(b"\n")) >= 0:
            encoded = bytes(pending[:separator])
            del pending[: separator + 1]
            record_number += 1
            try:
                decoded = json.loads(encoded.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"newline-terminated reconciliation record {record_number} is invalid"
                ) from exc
            _validate_history_record(
                decoded,
                adapter_id=adapter_id,
                account_id=account_id,
                record_number=record_number,
            )

    if not pending:
        return b""

    record_number += 1
    try:
        decoded = json.loads(bytes(pending).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        os.ftruncate(descriptor, size - len(pending))
        os.fsync(descriptor)
        return b""
    _validate_history_record(
        decoded,
        adapter_id=adapter_id,
        account_id=account_id,
        record_number=record_number,
    )
    return b"\n"


class ReconciliationRunBusyError(RuntimeError):
    """A reconciliation cycle is already in progress."""


class ReconciliationRunner:
    """Periodic broker-vs-flinttrade reconciliation over the active natives.

    Args:
        targets: Zero-argument callable returning the CURRENT iterable of
            ``(adapter, session)`` pairs to reconcile. Re-evaluated every
            cycle so targets may appear (login) or vanish (logout) mid-run.
        audit_logger: Object with ``log_event(event_type, **fields)`` (the
            hash-chain :class:`flinttrade_data.audit_logger.AuditLogger`);
            ``None`` disables audit emission (reports are still persisted).
        home_dir: Root directory for JSONL persistence. Defaults to the
            canonical FlintTrade home (``flinttrade_core.workspace.workspace_dir``,
            which honours ``FLINTTRADE_WORKSPACE_DIR`` / ``FLINTTRADE_HOME``).
        poll_seconds: Loop wake-up cadence; each wake-up reconciles only the
            targets that are due.
        default_interval_seconds: Per-broker cadence fallback when the adapter
            advertises no positive ``reconcile_recommended_seconds``.
        state_recorder: Optional callback that atomically adopts the private
            broker snapshots retained on a successful report. It runs only
            after the report JSONL line is durably appended.
        clock: Monotonic clock override for tests.
        sleep: ``async (seconds) -> None`` override for tests; defaults to
            :func:`asyncio.sleep`.
    """

    def __init__(
        self,
        targets: Callable[[], Iterable[tuple[Any, Any]]],
        *,
        audit_logger: Any | None = None,
        home_dir: Path | str | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        default_interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        state_recorder: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._targets = targets
        self._audit = audit_logger
        self._home: Path | None = Path(home_dir) if home_dir is not None else None
        self._poll = poll_seconds
        self._default_interval = default_interval_seconds
        self._state_recorder = state_recorder
        self._clock = clock
        self._sleep: Callable[[float], Awaitable[Any]] = sleep if sleep is not None else asyncio.sleep
        self._next_due: dict[tuple[str, str], float] = {}
        self._running = False
        self._run_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True while the polling loop is active."""
        return self._running

    def stop(self) -> None:
        """Signal the loop to exit after the current cycle (idempotent)."""
        self._running = False

    async def run(self) -> None:
        """Poll until :meth:`stop` is called (or the task is cancelled).

        Designed to be launched as a background task on the app's event loop
        (``asyncio.create_task(runner.run())``) — it never raises out of a
        cycle; only :class:`asyncio.CancelledError` propagates so the task
        cancels cleanly at shutdown.
        """
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        logger.info("Reconciliation runner started (poll every %.0fs)", self._poll)
        try:
            while self._running:
                try:
                    await self.run_once()
                except ReconciliationRunBusyError:
                    logger.info("Reconciliation cycle skipped because a manual cycle is active")
                if not self._running:
                    break
                await self._sleep(self._poll)
        finally:
            self._running = False
            self._loop = None
            logger.info("Reconciliation runner stopped")

    def trigger(
        self,
        *,
        timeout: float = 30.0,
        selectors: Iterable[str] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Run one selector-bounded cycle from a synchronous operator thread."""
        selector_filter = self._selector_filter(selectors)
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is loop:
                raise ReconciliationRunBusyError(
                    "cannot synchronously trigger reconciliation on its own event loop"
                )
            future = asyncio.run_coroutine_threadsafe(
                self.run_once(selectors=selector_filter, force=force),
                loop,
            )
            return future.result(timeout=max(0.1, float(timeout)))
        return asyncio.run(self.run_once(selectors=selector_filter, force=force))

    # ------------------------------------------------------------------
    # One cycle
    # ------------------------------------------------------------------

    async def run_once(
        self,
        *,
        selectors: Iterable[str] | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Reconcile every DUE target once; return the report payload dicts.

        A target is due on first sight, and again once its per-broker interval
        has elapsed. All failure modes (targets provider, identity reads,
        ``reconcile`` raises, persistence, audit) are isolated per target so
        one broker can never starve the others.
        """
        if not self._run_lock.acquire(blocking=False):
            raise ReconciliationRunBusyError("reconciliation cycle already in progress")
        try:
            return await self._run_once_locked(
                selectors=self._selector_filter(selectors),
                force=force,
            )
        finally:
            self._run_lock.release()

    @staticmethod
    def _selector_filter(selectors: Iterable[str] | None) -> frozenset[str] | None:
        """Canonicalise an optional exact broker/account selector allowlist."""
        if selectors is None:
            return None
        canonical: set[str] = set()
        for selector in selectors:
            raw = str(selector or "").strip()
            broker_id, separator, account_id = raw.partition(":")
            if not separator or not broker_id.strip() or not account_id.strip() or ":" in account_id:
                raise ValueError("reconciliation selectors must be exact broker:account values")
            canonical.add(f"{broker_id.strip().lower()}:{account_id.strip()}")
        return frozenset(canonical)

    async def _run_once_locked(
        self,
        *,
        selectors: frozenset[str] | None,
        force: bool,
    ) -> list[dict[str, Any]]:
        """Implementation of one cycle while the cross-thread lock is held."""
        payloads: list[dict[str, Any]] = []
        try:
            targets = list(self._targets())
        except Exception as exc:
            logger.error("Reconciliation targets provider failed: %s", exc)
            return payloads
        for adapter, session in targets:
            try:
                broker_id = str(getattr(adapter, "broker_id", "") or "unknown").lower()
                account_id = str(getattr(session, "account_id", "") or "")
            except Exception:  # pragma: no cover - defensive identity read
                continue
            key = (broker_id, account_id)
            if selectors is not None and f"{broker_id}:{account_id}" not in selectors:
                continue
            now = self._clock()
            due = self._next_due.get(key)
            if not force and due is not None and now < due:
                continue
            # Schedule the next run BEFORE reconciling so a consistently
            # failing broker still backs off to its cadence (no hot loop).
            self._next_due[key] = now + self._interval_for(adapter)
            outcome = await self._reconcile_one(adapter, session, broker_id, account_id)
            if outcome is None:
                continue
            payload, report = outcome
            payloads.append(payload)
            persisted = self._persist(payload)
            if persisted:
                if payload.get("clean", False):
                    self._clear_mismatch_state(payload)
                else:
                    self._emit_mismatch(payload)
                snapshot_generation = self._record_snapshot(report, payload)
                if snapshot_generation is not None:
                    payload["snapshot_generation"] = snapshot_generation
        return payloads

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _interval_for(self, adapter: Any) -> float:
        """The adapter's recommended cadence, clamped to a positive value."""
        try:
            raw = getattr(getattr(adapter, "capabilities", None), "reconcile_recommended_seconds", None)
            seconds = int(raw) if raw is not None else 0
        except Exception:
            seconds = 0
        return float(seconds if seconds > 0 else self._default_interval)

    @staticmethod
    def _validate_report_contract(
        report: Any,
        payload: Any,
        *,
        broker_id: str,
        account_id: str,
    ) -> Any:
        """Rebuild and bind one private snapshot to its exact public report."""
        from flinttrade_gateway.reconciliation import (  # noqa: PLC0415
            EMPTY_LOCAL_STATE,
            ReconciliationReport,
            build_report,
            is_canonical_reconciliation_report,
            original_reconciliation_evidence_sha256,
            reconciliation_evidence_sha256,
        )

        if type(report) is not ReconciliationReport or not is_canonical_reconciliation_report(report):
            raise TypeError("reconcile() did not return the canonical ReconciliationReport contract")
        report_adapter_id = getattr(report, "adapter_id", None)
        report_account_id = getattr(report, "account_id", None)
        if (
            type(report_adapter_id) is not str
            or report_adapter_id != broker_id
            or type(report_account_id) is not str
            or report_account_id != account_id
        ):
            raise ValueError("reconciliation report identity does not match selected target")
        if report.error:
            if (
                report.broker_orders
                or report.broker_positions
                or report.broker_holdings
                or report.local_state != EMPTY_LOCAL_STATE
                or report._evidence_sha256
            ):
                raise ValueError("error reconciliation report carries private evidence")
        else:
            original_evidence_sha256 = original_reconciliation_evidence_sha256(report)
            evidence_sha256 = reconciliation_evidence_sha256(
                adapter_id=report.adapter_id,
                account_id=report.account_id,
                generated_at=report.generated_at,
                broker_orders=report.broker_orders,
                broker_positions=report.broker_positions,
                broker_holdings=report.broker_holdings,
                local_state=report.local_state,
            )
            if not original_evidence_sha256 or not hmac.compare_digest(
                evidence_sha256,
                original_evidence_sha256,
            ):
                raise ValueError("reconciliation report evidence binding mismatch")

        canonical_report = build_report(
            adapter_id=report_adapter_id,
            account_id=report_account_id,
            generated_at=getattr(report, "generated_at"),
            broker_orders=getattr(report, "broker_orders"),
            broker_positions=getattr(report, "broker_positions"),
            broker_holdings=getattr(report, "broker_holdings"),
            local_state=getattr(report, "local_state"),
            error=getattr(report, "error"),
        )
        current_payload = report.as_dict()
        if payload is not None and payload != current_payload:
            raise ValueError("reconciliation report changed after its public payload was captured")
        supplied_payload = current_payload if payload is None else payload
        if not isinstance(supplied_payload, dict):
            raise TypeError(
                f"{broker_id}.reconcile() report as_dict() returned {type(supplied_payload).__name__}"
            )
        payload_adapter_id = supplied_payload.get("adapter_id")
        payload_account_id = supplied_payload.get("account_id")
        if (
            type(payload_adapter_id) is not str
            or payload_adapter_id != broker_id
            or type(payload_account_id) is not str
            or payload_account_id != account_id
        ):
            raise ValueError("reconciliation report payload identity does not match selected target")
        normalised = _normalise_report_payload(supplied_payload)
        if normalised is None:
            raise ValueError("reconciliation report payload is malformed")
        canonical_payload = canonical_report.as_dict()
        supplied_json = json.dumps(
            supplied_payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        canonical_json = json.dumps(
            canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        if supplied_payload != canonical_payload or supplied_json != canonical_json:
            raise ValueError("reconciliation report does not match its validated snapshots")
        if normalised != canonical_payload:
            raise ValueError("reconciliation report payload is not canonical")
        return canonical_report

    async def _reconcile_one(
        self, adapter: Any, session: Any, broker_id: str, account_id: str
    ) -> tuple[dict[str, Any], Any | None] | None:
        """Run and evidence-bind one reconcile; synthesise errors on failure."""
        try:
            report = await adapter.reconcile(session)
            canonical_report = self._validate_report_contract(
                report,
                None,
                broker_id=broker_id,
                account_id=account_id,
            )
            return canonical_report.as_dict(), canonical_report
        except asyncio.CancelledError:  # pragma: no cover - shutdown passthrough
            raise
        except Exception as exc:
            logger.warning(
                "Reconcile failed for %s account %s (%s)",
                broker_id,
                _account_ref(account_id),
                type(exc).__name__,
            )
            return _error_payload(broker_id, account_id, type(exc).__name__), None

    def _resolve_home(self) -> Path:
        if self._home is None:
            from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

            self._home = workspace_dir()
        return self._home

    def _persist(self, payload: dict[str, Any]) -> bool:
        """Durably append one validated report under its per-file process lock."""
        try:
            normalised = _normalise_report_payload(payload)
            if normalised is None:
                raise ValueError("reconciliation report payload is malformed")
            broker = _safe_component(normalised["adapter_id"], "unknown")
            account = _safe_component(normalised["account_id"], "default")
            path = self._resolve_home() / "reconciliation" / broker / f"{account}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            harden_directory(path.parent.parent)
            harden_directory(path.parent)
            lock_path = path.with_name(f".{path.name}.lock")
            with OwnerSafeFileLock(
                lock_path,
                timeout=_PERSIST_LOCK_TIMEOUT_SECONDS,
                mode=0o600,
                thread_local=False,
            ):
                harden(lock_path)
                if path.is_symlink():
                    raise OSError("reconciliation report path is a symbolic link")
                created = not path.exists()
                flags = (
                    os.O_RDWR
                    | os.O_APPEND
                    | os.O_CREAT
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                )
                descriptor = os.open(path, flags, 0o600)
                try:
                    opened = os.fstat(descriptor)
                    current = path.stat(follow_symlinks=False)
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or stat.S_ISLNK(current.st_mode)
                        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                    ):
                        raise OSError("reconciliation report path is unsafe")
                    harden(path)
                    delimiter = _prepare_jsonl_tail(
                        descriptor,
                        opened.st_size,
                        adapter_id=normalised["adapter_id"],
                        account_id=normalised["account_id"],
                    )
                    encoded = delimiter + (
                        json.dumps(
                            normalised,
                            ensure_ascii=False,
                            sort_keys=True,
                            allow_nan=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                    offset = 0
                    while offset < len(encoded):
                        written = os.write(descriptor, encoded[offset:])
                        if written <= 0:
                            raise OSError("reconciliation report write made no progress")
                        offset += written
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                if created:
                    fsync_parent_directory(path)
            return True
        except Exception as exc:
            logger.warning(
                "Could not persist reconciliation report for %s account %s (%s)",
                payload.get("adapter_id"),
                _account_ref(payload.get("account_id")),
                type(exc).__name__,
            )
            return False

    def _mismatch_state_path(self, payload: dict[str, Any]) -> Path:
        broker = _safe_component(payload.get("adapter_id"), "unknown")
        account = _safe_component(payload.get("account_id"), "default")
        return self._resolve_home() / "reconciliation" / broker / f"{account}.mismatch.json"

    @staticmethod
    def _mismatch_fingerprint(payload: dict[str, Any]) -> str:
        stable = dict(payload)
        stable.pop("generated_at", None)
        return hashlib.sha256(
            json.dumps(stable, ensure_ascii=True, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def _read_mismatch_fingerprint(self, payload: dict[str, Any]) -> str:
        path = self._mismatch_state_path(payload)
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
            return ""
        if not isinstance(state, dict):
            return ""
        return str(state.get("fingerprint") or "")

    def _write_mismatch_fingerprint(self, payload: dict[str, Any], fingerprint: str) -> None:
        path = self._mismatch_state_path(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        encoded = json.dumps(
            {"fingerprint": fingerprint},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _clear_mismatch_state(self, payload: dict[str, Any]) -> None:
        try:
            self._mismatch_state_path(payload).unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("Could not clear reconciliation mismatch fingerprint: %s", type(exc).__name__)

    def _record_snapshot(self, report: Any | None, payload: dict[str, Any]) -> int | None:
        """Record canonical broker observations after persistence; never raises."""
        if self._state_recorder is None or report is None or payload.get("error"):
            return None
        try:
            broker_id = payload.get("adapter_id")
            account_id = payload.get("account_id")
            if type(broker_id) is not str or type(account_id) is not str:
                raise ValueError("reconciliation report payload identity is malformed")
            canonical_report = self._validate_report_contract(
                report,
                payload,
                broker_id=broker_id,
                account_id=account_id,
            )
            generation = self._state_recorder(
                adapter_id=broker_id,
                account_id=account_id,
                orders=tuple(canonical_report.broker_orders),
                positions=tuple(canonical_report.broker_positions),
                holdings=tuple(canonical_report.broker_holdings),
                observed_at=str(payload.get("generated_at", "")),
            )
            if generation is None or isinstance(generation, bool):
                return None
            canonical_generation = int(generation)
            return canonical_generation if canonical_generation > 0 else None
        except Exception as exc:
            logger.warning(
                "Could not adopt reconciliation snapshot for %s account %s (%s)",
                payload.get("adapter_id"),
                _account_ref(payload.get("account_id")),
                type(exc).__name__,
            )
            return None

    def _emit_mismatch(self, payload: dict[str, Any]) -> None:
        """Emit each distinct mismatch once across cycles and restarts."""
        if self._audit is None:
            return
        fingerprint = self._mismatch_fingerprint(payload)
        if self._read_mismatch_fingerprint(payload) == fingerprint:
            return
        try:
            digest = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            self._audit.log_event(
                RECONCILIATION_MISMATCH_EVENT,
                adapter_id=str(payload.get("adapter_id", "")),
                account_id=str(payload.get("account_id", "")),
                severity=str(payload.get("severity", "")),
                report_sha256=digest,
                orders_diffs=len(payload.get("orders_diff") or ()),
                positions_diffs=len(payload.get("positions_diff") or ()),
                holdings_diffs=len(payload.get("holdings_diff") or ()),
                severity_counts=dict(payload.get("severity_counts") or {}),
                error=str(payload.get("error", "")),
            )
            self._write_mismatch_fingerprint(payload, fingerprint)
        except Exception as exc:
            logger.warning(
                "Could not emit %s audit event (%s)",
                RECONCILIATION_MISMATCH_EVENT,
                type(exc).__name__,
            )


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "DEFAULT_POLL_SECONDS",
    "RECONCILIATION_MISMATCH_EVENT",
    "ReconciliationRunBusyError",
    "ReconciliationRunner",
]
