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

The runner is deliberately duck-typed against the gateway contract
(``broker_id`` / ``capabilities.reconcile_recommended_seconds`` /
``reconcile`` returning an object with ``as_dict()``) so the engine package
keeps zero import-time dependency on ``flinttrade_gateway``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger("flinttrade.engine.reconciliation_runner")

RECONCILIATION_MISMATCH_EVENT = "RECONCILIATION_MISMATCH"

#: Fallback cadence when an adapter advertises no usable recommendation.
DEFAULT_INTERVAL_SECONDS = 300

#: How often the loop re-checks which targets are due. Deliberately shorter
#: than any broker cadence so a session established mid-flight gets its first
#: reconcile within one poll, not one full broker interval.
DEFAULT_POLL_SECONDS = 30.0


def _safe_component(raw: Any, fallback: str) -> str:
    """Sanitise a broker/account id into a single safe path component.

    Anything outside ``[A-Za-z0-9._-]`` becomes ``_``; results that are empty
    or consist solely of separators/dots (e.g. ``".."``) collapse to
    ``fallback`` so a hostile id can never traverse out of the
    ``reconciliation/`` tree.
    """
    text = str(raw or "").strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in text)
    if not cleaned or set(cleaned) <= {".", "_", "-"}:
        return fallback
    return cleaned


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
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._targets = targets
        self._audit = audit_logger
        self._home: Path | None = Path(home_dir) if home_dir is not None else None
        self._poll = poll_seconds
        self._default_interval = default_interval_seconds
        self._clock = clock
        self._sleep: Callable[[float], Awaitable[Any]] = sleep if sleep is not None else asyncio.sleep
        self._next_due: dict[tuple[str, str], float] = {}
        self._running = False

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
        logger.info("Reconciliation runner started (poll every %.0fs)", self._poll)
        try:
            while self._running:
                await self.run_once()
                if not self._running:
                    break
                await self._sleep(self._poll)
        finally:
            self._running = False
            logger.info("Reconciliation runner stopped")

    # ------------------------------------------------------------------
    # One cycle
    # ------------------------------------------------------------------

    async def run_once(self) -> list[dict[str, Any]]:
        """Reconcile every DUE target once; return the report payload dicts.

        A target is due on first sight, and again once its per-broker interval
        has elapsed. All failure modes (targets provider, identity reads,
        ``reconcile`` raises, persistence, audit) are isolated per target so
        one broker can never starve the others.
        """
        payloads: list[dict[str, Any]] = []
        try:
            targets = list(self._targets())
        except Exception as exc:
            logger.error("Reconciliation targets provider failed: %s", exc)
            return payloads
        for adapter, session in targets:
            try:
                broker_id = str(getattr(adapter, "broker_id", "") or "unknown")
                account_id = str(getattr(session, "account_id", "") or "")
            except Exception:  # pragma: no cover - defensive identity read
                continue
            key = (broker_id, account_id)
            now = self._clock()
            due = self._next_due.get(key)
            if due is not None and now < due:
                continue
            # Schedule the next run BEFORE reconciling so a consistently
            # failing broker still backs off to its cadence (no hot loop).
            self._next_due[key] = now + self._interval_for(adapter)
            payload = await self._reconcile_one(adapter, session, broker_id, account_id)
            if payload is None:
                continue
            payloads.append(payload)
            self._persist(payload)
            if not payload.get("clean", False):
                self._emit_mismatch(payload)
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

    async def _reconcile_one(
        self, adapter: Any, session: Any, broker_id: str, account_id: str
    ) -> dict[str, Any] | None:
        """Run one adapter reconcile; never raises (synthesises error reports)."""
        try:
            report = await adapter.reconcile(session)
            payload = report.as_dict()
            if not isinstance(payload, dict):
                raise TypeError(f"{broker_id}.reconcile() report as_dict() returned {type(payload).__name__}")
            return payload
        except asyncio.CancelledError:  # pragma: no cover - shutdown passthrough
            raise
        except Exception as exc:
            logger.warning(
                "Reconcile failed for %s:%s — %s: %s", broker_id, account_id, type(exc).__name__, exc
            )
            return _error_payload(broker_id, account_id, f"{type(exc).__name__}: {exc}")

    def _resolve_home(self) -> Path:
        if self._home is None:
            from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

            self._home = workspace_dir()
        return self._home

    def _persist(self, payload: dict[str, Any]) -> None:
        """Append the report as one JSONL line (§14.2); never raises."""
        try:
            broker = _safe_component(payload.get("adapter_id"), "unknown")
            account = _safe_component(payload.get("account_id"), "default")
            path = self._resolve_home() / "reconciliation" / broker / f"{account}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:
            logger.warning(
                "Could not persist reconciliation report for %s:%s — %s",
                payload.get("adapter_id"),
                payload.get("account_id"),
                exc,
            )

    def _emit_mismatch(self, payload: dict[str, Any]) -> None:
        """Emit the RECONCILIATION_MISMATCH audit event (§14.2); never raises."""
        if self._audit is None:
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
        except Exception as exc:
            logger.warning("Could not emit %s audit event: %s", RECONCILIATION_MISMATCH_EVENT, exc)
