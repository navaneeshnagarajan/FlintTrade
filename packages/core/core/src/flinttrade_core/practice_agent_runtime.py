"""App-owned, durable Practice supervision using the existing trading engine.

The worker owns its trader, original operator session and learning resources
until they have actually stopped. Recovery records uncertainty; it never
replays a submitted order or reconstructs authority from persisted evidence.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from flask import current_app, jsonify, request

from .practice_agent_model import (
    ModelBudgetExhausted,
    PracticeModelBudget,
    bounded_practice_chat,
    freeze_practice_client,
)

logger = logging.getLogger("flinttrade.core.practice_agent_runtime")
_SUPERVISOR_LOCK = threading.Lock()
_EXTENSION = "practice_agent_supervisor"
_ACTIVE = frozenset({"starting", "waiting", "running", "stopping", "reconciliation_required"})
_EXCHANGES = frozenset({"NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD"})
_PRODUCTS = frozenset({"MIS", "CNC", "NRML"})


def validate_practice_config(body: Any) -> dict[str, Any]:
    """Validate JSON without truthiness defaults, coercion or non-finite values."""
    defaults: dict[str, Any] = {
        "exchange": "NSE", "product": "MIS", "max_position_size": 1,
        "stop_loss_pct": 2.0, "take_profit_pct": 4.0,
        "daily_stop_loss": -10_000.0, "max_trades_per_symbol": 5,
        "cycle_interval_sec": 60, "entry_rationale": "",
        "model_call_limit": 500, "model_output_limit": 512,
    }
    if type(body) is not dict or set(body) - (set(defaults) | {"symbols", "mode"}):
        raise ValueError("Provide an object containing only supported Practice agent parameters")
    if body.get("mode", "practice") != "practice":
        raise ValueError("Practice execution mode cannot be changed")
    symbols = body.get("symbols")
    if type(symbols) is not list or not 1 <= len(symbols) <= 20:
        raise ValueError("symbols must be a list containing 1 to 20 instrument names")
    normalised = []
    for symbol in symbols:
        if type(symbol) is not str or not re.fullmatch(r"[A-Z0-9][A-Z0-9 &._+\-]{0,63}", symbol.strip().upper()):
            raise ValueError("Each symbol must be a non-empty bounded instrument name")
        if symbol.strip().upper() not in normalised:
            normalised.append(symbol.strip().upper())
    result = {**defaults, **{key: value for key, value in body.items() if key not in {"symbols", "mode"}}}
    result["symbols"] = normalised
    rationale = result["entry_rationale"]
    if type(rationale) is not str or len(rationale.strip()) > 2000:
        raise ValueError("entry_rationale must be a string of at most 2,000 characters")
    result["entry_rationale"] = rationale.strip()
    for key, minimum, maximum in (("model_call_limit", 1, 10_000), ("model_output_limit", 16, 4096)):
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(f"{key} must be an integer between {minimum} and {maximum}")
    for key, choices in (("exchange", _EXCHANGES), ("product", _PRODUCTS)):
        value = result[key]
        if type(value) is not str or value.strip().upper() not in choices:
            raise ValueError(f"{key} must be one of {', '.join(sorted(choices))}")
        result[key] = value.strip().upper()
    for key, maximum in (("max_position_size", 1_000_000), ("max_trades_per_symbol", 1000), ("cycle_interval_sec", 3600)):
        if type(result[key]) is not int or not 1 <= result[key] <= maximum:
            raise ValueError(f"{key} must be an integer between 1 and {maximum}")
    for key in ("stop_loss_pct", "take_profit_pct", "daily_stop_loss"):
        value = result[key]
        if type(value) not in {int, float}:
            raise ValueError(f"{key} must be a finite number")
        try:
            value = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{key} must be a finite number") from exc
        if not math.isfinite(value) or (value >= 0 if key == "daily_stop_loss" else not 0 < value <= 100):
            raise ValueError(f"{key} must be negative" if key == "daily_stop_loss" else f"{key} must be above 0 and at most 100")
        result[key] = value
    return result


def _enabled() -> bool:
    from .agent_routes import _agent_flag_enabled  # noqa: PLC0415

    return _agent_flag_enabled()


def _error(message: str, status: int) -> tuple[Any, int]:
    return jsonify({"status": "error", "message": message}), status


def _authorise() -> tuple[str, str, tuple[Any, int] | None]:
    """Resolve a full Practice session into an opaque, stable operator identity."""
    from .auth_routes import (  # noqa: PLC0415
        _session_token_from_request,
        decode_token,
        verify_operator_session_token,
    )

    token = _session_token_from_request()
    try:
        verified = verify_operator_session_token(token)
        payload = decode_token(token)
        expiry = payload.get("exp")
        if payload.get("setup_session") or type(expiry) not in {int, float} or not math.isfinite(expiry):
            return "", "", _error("A full, expiring operator session is required", 401)
    except Exception:  # noqa: BLE001 - unavailable session authority fails closed
        return "", "", _error("A valid full operator session is required", 401)
    if payload.get("mode") != "practice" or request.headers.get("X-FlintTrade-Mode", "practice") != "practice":
        return "", "", _error("This operation requires a Practice session", 403)
    return token, verified.actor_ref, None


def _sandbox_flat(app: Any) -> bool:
    """Prove no exposure and no pending orders, including orders from prior days."""
    sandbox = app.config.get("DATA_SANDBOX_ENGINE")
    if sandbox is None:
        raise RuntimeError("Practice sandbox is unavailable")
    positions = sandbox.get_positions()
    orders = sandbox.get_all_orders()
    if type(positions) is not list or type(orders) is not list:
        raise RuntimeError("Practice books are unavailable")
    # get_positions() is deliberately the engine's open-position query. An
    # unexpected row is not interpreted as proof of zero exposure.
    if positions:
        return False
    terminal = {"COMPLETE", "CANCELLED", "REJECTED"}
    return all(type(row) is dict and row.get("status") in terminal for row in orders)


@dataclass
class _Run:
    run_id: str
    owner: str
    config: dict[str, Any]
    created_at: str
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    trader: Any = None
    adapter: Any = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    status: str = "starting"
    error: str = ""
    data_error: str = ""
    evidence_failed: bool = False
    cleanup_complete: bool = False
    settlement_failed: bool = False
    cycle_sessions: dict[str, str] = field(default_factory=dict)
    llm: Any = None
    llm_closed: bool = False
    model_error: str = ""
    learning_active: bool = False
    model_budget: PracticeModelBudget | None = None
    safety_error: str = ""


class _ObservedLLM:
    """Observe provider availability without retaining prompts or responses."""

    def __init__(self, supervisor: PracticeAgentSupervisor, run: _Run, client: Any) -> None:
        self.supervisor, self.run, self.client = supervisor, run, client

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        operation = "reflection" if self.run.learning_active else "analysis"
        self._require_admission(operation)
        budget = self.run.model_budget
        if budget is None:
            raise RuntimeError("practice_model_budget_unavailable")
        try:
            budget.reserve(operation)
        except ModelBudgetExhausted:
            # A final reserved decision may complete. Only a subsequent
            # attempt stops analysis, without sending another provider request.
            self.run.stop.set()
            if self.run.trader is not None:
                self.run.trader.request_stop(square_off=True)
            self.supervisor._event(self.run, "model_limit_exhausted", {"operation": operation, **budget.snapshot()})
            raise
        # Evidence I/O may have taken time or triggered shutdown. Recheck
        # immediately before dispatch; never hold a safety lease over the call.
        self._require_admission(operation)
        try:
            response = bounded_practice_chat(self.client, budget.output_limit, *args, **kwargs)
            if getattr(response, "error", "") or not str(getattr(response, "content", "") or "").strip():
                raise RuntimeError("configured_model_unavailable")
            return response
        except Exception:
            self.supervisor._event(self.run, "model_unavailable", {"code": "configured_model_unavailable",
                                                                 "operation": operation})
            if operation == "analysis":
                self.run.model_error = "configured_model_unavailable"
                self.run.stop.set()
                if self.run.trader is not None:
                    self.run.trader.request_stop(square_off=True)
            raise RuntimeError("configured_model_unavailable") from None

    def _require_admission(self, operation: str) -> None:
        code = self.supervisor._model_brake(self.run, operation)
        if code is not None:
            self.supervisor._safety_brake(self.run, code, operation)
            raise RuntimeError("practice_model_admission_refused")


class PracticeAgentSupervisor:
    """Own one worker and its durable evidence for the complete app lifetime."""

    def __init__(self, app: Any, store: Any) -> None:
        from .backend_instance import require_backend_lease_proof  # noqa: PLC0415
        from .owner_file_lock import OwnerSafeFileLock  # noqa: PLC0415

        self.app = app
        self._backend_proof = require_backend_lease_proof(app.config.get("BACKEND_LEASE_PROOF"))
        if app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True:
            raise RuntimeError("Practice runtime is not accepting work")
        self.store = store
        self.lock = threading.RLock()
        self.shutdown_requested = threading.Event()
        self.run: _Run | None = None
        self._store_closed = False
        database_path = store.database_path
        if database_path == ":memory:":
            raise ValueError("A durable file-backed Practice run store is required")
        lease_path = Path(database_path).resolve().with_name(Path(database_path).name + ".runtime.lock")
        self._lease = OwnerSafeFileLock(str(lease_path), timeout=0, mode=0o600, thread_local=False)
        # Recovery is a write, so ownership must precede it. A second Flask
        # app/process cannot reclassify and release a worker that is still alive.
        self._lease.acquire()
        try:
            self._require_ownership()
            self.store.recover_interrupted()
        except BaseException:
            self._lease.release()
            raise

    def _require_ownership(self, *, accepting: bool = True) -> None:
        from .backend_instance import require_backend_lease_proof  # noqa: PLC0415

        if (not self._lease.is_locked or self.app.config.get("BACKEND_LEASE_PROOF") is not self._backend_proof
                or (accepting and self.app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True)):
            raise RuntimeError("Practice runtime ownership is unavailable")
        require_backend_lease_proof(self._backend_proof)

    def _snapshot(self, run: _Run) -> dict[str, Any]:
        trader = run.trader
        snapshot = {
            **run.snapshot,
            "enabled": _enabled(), "mode": "practice", "run_id": run.run_id,
            "status": run.status, "agent_status": run.status,
            "running": run.status in {"starting", "waiting", "running", "stopping"},
            "actor_id": "autonomous-trader", "started_at": run.created_at,
            "params": dict(run.config), "error": run.error,
            "stop_failure": str(getattr(trader, "stop_failure", "") or ""),
            "shutdown_complete": run.cleanup_complete,
            "model_usage": run.model_budget.snapshot() if run.model_budget is not None else {},
        }
        # Only the worker may iterate strategy state. Request-thread stop
        # calls publish the last immutable state with fresh lifecycle fields.
        if trader is not None and threading.current_thread() is run.thread:
            state = trader.state
            snapshot.update({
                "cycle_count": state.cycle_count, "daily_pnl": state.daily_pnl,
                "active_positions": dict(state.active_positions),
                "position_details": {key: dict(value) for key, value in state.position_details.items()},
                "trade_counts": dict(state.trade_counts),
                "last_signals": {key: str(value) for key, value in state.last_signals.items()},
                "squared_off": state.squared_off, "stop_loss_hit": state.stop_loss_hit,
            })
        return snapshot

    def _persist(self, run: _Run, status: str, *, error: str = "") -> None:
        with self.lock:
            if run.stop.is_set() and status in {"waiting", "running"}:
                status = "stopping"
            previous = run.status
            run.status = status
            run.error = error
            run.snapshot = self._snapshot(run)
            try:
                if previous != status:
                    self.store.append_event(run.run_id, kind="status_changed", data={"previous": previous, "status": status})
                # Keep the durable active fence until transition evidence has
                # committed. A failure must never leave a free terminal row.
                self.store.update_run(run.run_id, status=status, snapshot=run.snapshot, error=error or None)
            except Exception:
                run.evidence_failed = True
                run.stop.set()
                raise

    def _event(self, run: _Run, kind: str, data: dict[str, Any]) -> None:
        try:
            self.store.append_event(run.run_id, kind=kind, data=data)
        except Exception:
            run.evidence_failed = True
            run.stop.set()
            raise
        if kind == "data_unavailable":
            run.data_error = str(data.get("code") or "market_data_unavailable")[:128]
            # The generic strategy tolerates absent indicators. This production
            # capability requires its configured inputs: brake immediately,
            # before delayed analysis or another symbol can place an entry.
            run.stop.set()
            if run.trader is not None:
                run.trader.request_stop(square_off=True)

    def _entry_brake(self, run: _Run) -> bool:
        """Fresh entry authority, also evaluated inside canonical admission.

        The adapter recognises only proven reducing orders as exceptions to
        this brake. Session validation remains independent and has no exception.
        """
        from .practice_agent_adapter import PracticeAgentError, practice_entry_kill_code  # noqa: PLC0415

        try:
            self._require_ownership(accepting=False)
        except Exception:
            run.stop.set()
            raise PracticeAgentError("practice_runtime_unavailable") from None
        try:
            row = self.store.get_run(run.run_id)
            if (not self._lease.is_locked or row is None or row["mode"] != "practice"
                    or row["status"] not in {"starting", "waiting", "running", "stopping"}
                    or row["config"].get("owner") != run.owner):
                raise RuntimeError("Practice evidence ownership changed")
        except Exception:
            run.evidence_failed = True
            run.stop.set()
            raise PracticeAgentError("practice_reconciliation_required") from None
        if run.evidence_failed:
            raise PracticeAgentError("practice_reconciliation_required")
        kill_code = practice_entry_kill_code(self.app)
        if kill_code is not None:
            self._safety_brake(run, kill_code, "entry")
            return True
        if (run.stop.is_set() or self.shutdown_requested.is_set() or run.data_error
                or self.app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True):
            return True
        with self.app.app_context():
            if not _enabled():
                return True
            trader = run.trader
            if trader is None:
                return True
            current_sessions = self._session_identities(trader)
            return (len(current_sessions) != len(trader.config.symbols)
                    or current_sessions != run.cycle_sessions
                    or trader._is_square_off_time())  # noqa: SLF001

    def _safety_brake(self, run: _Run, code: str, operation: str) -> None:
        """Stop new work and durably record the first safe admission reason."""
        with self.lock:
            run.stop.set()
            if run.trader is not None:
                run.trader.request_stop(square_off=True)
            if not run.safety_error:
                run.safety_error = code
                self._event(run, "safety_brake", {"code": code, "operation": operation})

    def _model_brake(self, run: _Run, operation: str) -> str | None:
        """Fresh admission for analysis and post-settlement model work."""
        from .practice_agent_adapter import PracticeAgentError, practice_entry_kill_code  # noqa: PLC0415

        code = practice_entry_kill_code(self.app)
        if code is not None:
            return code
        if run.evidence_failed:
            return "practice_reconciliation_required"
        try:
            self._require_ownership(accepting=False)
            run.adapter.validate_session()
            # Operator stop and a closed session normally permit reflection
            # after flat proof. They never permit another analysis request.
            if operation == "analysis" and self._entry_brake(run):
                return "practice_entry_stopped"
        except PracticeAgentError as exc:
            return exc.code
        except Exception:
            return "practice_model_admission_unavailable"
        return None

    @staticmethod
    def _session_identities(trader: Any) -> dict[str, str]:
        identities = {}
        for symbol in trader.config.symbols:
            session = trader._effective_session(symbol)  # noqa: SLF001
            if session is not None:
                identities[symbol] = session.opens_at.isoformat() + "/" + session.closes_at.isoformat()
        return identities

    def start(self, token: str, owner: str, config: dict[str, Any], llm: Any = None) -> dict[str, Any]:
        """Claim durable ownership before constructing or executing a trader."""
        from .practice_agent_adapter import PracticeAgentAdapter  # noqa: PLC0415

        config = validate_practice_config(config)
        with self.lock:
            self._require_ownership()
            if self.shutdown_requested.is_set() or self.app.extensions.get(_EXTENSION + "_shutdown"):
                raise RuntimeError("The application is shutting down")
            if self.run is not None and self.run.thread is not None and self.run.thread.is_alive():
                raise RuntimeError("A Practice agent worker is still owned; stop it first")
            if self.run is not None and (self.run.evidence_failed or not self.run.cleanup_complete):
                raise RuntimeError("The preceding Practice worker requires reconciliation")
            if not _sandbox_flat(self.app):
                raise RuntimeError("Practice positions and pending orders must be flat before starting")
            run_id = str(uuid.uuid4())
            row = self.store.create_run(run_id=run_id, mode="practice", config={**config, "owner": owner})
            run = _Run(run_id, owner, config, row["created_at"])
            run.model_budget = PracticeModelBudget(
                config["model_call_limit"], config["model_output_limit"],
                event_sink=lambda kind, data: self._event(run, kind, data),
            )
            run.llm = llm
            self.run = run
            try:
                run.adapter = PracticeAgentAdapter(
                    self.app, token, event_sink=lambda kind, data: self._event(run, kind, data),
                    stop_check=lambda: self._entry_brake(run),
                )
                run.adapter.validate_session()
                run.thread = threading.Thread(target=self._worker, args=(run, llm), name="practice-agent", daemon=True)
                self._event(run, "run_started", {"mode": "practice"})
                run.snapshot = self._snapshot(run)
                run.thread.start()
            except Exception:
                if run.adapter is not None:
                    run.adapter.close()
                self._close_llm(run)
                run.cleanup_complete = True
                self._persist(run, "reconciliation_required" if run.evidence_failed else "failed",
                              error="Practice worker could not start")
                raise
            return dict(run.snapshot)

    def stop(self, owner: str) -> dict[str, Any] | None:
        """Brake entries immediately, retaining ownership throughout cleanup."""
        with self.lock:
            run = self.run
            if run is None or run.owner != owner or run.thread is None or not run.thread.is_alive():
                return None
            run.stop.set()
            if run.trader is not None:
                run.trader.request_stop(square_off=True)
            self._persist(run, "stopping")
            return dict(run.snapshot)

    def snapshot(self, owner: str) -> dict[str, Any]:
        """Return only this operator's immutable last worker snapshot."""
        with self.lock:
            if self.run is not None and self.run.owner == owner:
                result = dict(self.run.snapshot)
                result["running"] = bool(self.run.thread and self.run.thread.is_alive())
                result["enabled"] = _enabled()
                result["model_usage"] = self.run.model_budget.snapshot() if self.run.model_budget is not None else {}
                return result
        rows = self.history(owner, limit=100)
        if rows:
            row = rows[0]
            result = dict(row["snapshot"])
            result.update({
                "run_id": row["run_id"], "mode": "practice", "status": row["status"],
                "agent_status": row["status"], "error": row["error"] or "", "running": False,
                "enabled": _enabled(), "actor_id": "autonomous-trader",
                "started_at": row["created_at"],
                "params": {key: value for key, value in row["config"].items() if key != "owner"},
            })
            return result
        return {"mode": "practice", "status": "idle", "agent_status": "idle", "enabled": _enabled(),
                "running": False, "actor_id": "autonomous-trader", "params": {}, "started_at": ""}

    def history(self, owner: str, *, limit: int) -> list[dict[str, Any]]:
        return [row for row in self.store.list_runs(limit=limit) if row["config"].get("owner") == owner]

    def owned_run(self, owner: str, run_id: str) -> dict[str, Any] | None:
        row = self.store.get_run(run_id)
        return row if row is not None and row["config"].get("owner") == owner else None

    def resolve(self, owner: str, run_id: str) -> dict[str, Any]:
        """Acknowledge interrupted evidence only after authoritative flat proof."""
        with self.lock:
            self._require_ownership()
            row = self.owned_run(owner, run_id)
            if row is None:
                raise KeyError(run_id)
            if self.run is not None and self.run.thread is not None and self.run.thread.is_alive():
                raise RuntimeError("The worker has not finished; reconciliation cannot release it")
            if self.run is not None and self.run.run_id == run_id and not self.run.cleanup_complete:
                raise RuntimeError("Practice resources have not closed; reconciliation cannot release them")
            if (row["status"] in _ACTIVE and row["status"] != "reconciliation_required"
                    and self.run is not None and self.run.run_id == run_id and self.run.evidence_failed):
                # Storage may have recovered since the worker's terminal event
                # failed. Re-establish the durable uncertainty before resolving.
                row = self.store.update_run(run_id, status="reconciliation_required",
                                            snapshot=self.run.snapshot, error=self.run.error)
            if row["status"] != "reconciliation_required":
                raise RuntimeError("Only a run requiring reconciliation can be resolved")
            if not _sandbox_flat(self.app):
                raise RuntimeError("Practice positions or pending orders remain; inspect the sandbox before resolving")
            self.store.append_event(run_id, kind="reconciliation_resolved", data={"flat": True})
            snapshot = {**row["snapshot"], "status": "stopped", "agent_status": "stopped", "running": False,
                        "shutdown_complete": True, "error": "", "stop_failure": "",
                        "active_positions": {}, "position_details": {}, "squared_off": True}
            result = self.store.update_run(run_id, status="stopped", snapshot=snapshot, error=None)
            if self.run is not None and self.run.run_id == run_id:
                self.run.status = "stopped"
                self.run.snapshot = snapshot
                self.run.error = ""
                self.run.evidence_failed = False
                self.run.cleanup_complete = True
            return result

    def _construct_trader(self, run: _Run, llm: Any) -> Any:
        from flinttrade_ai.autonomous_agent import AgentConfig, AutonomousTrader  # noqa: PLC0415

        from .agent_routes import _build_learning_memory, _build_skills_workspace, _build_vault  # noqa: PLC0415

        scheduler = self.app.config["TIME_SCHEDULER"]
        trader_config = {key: value for key, value in run.config.items()
                         if key not in {"model_call_limit", "model_output_limit"}}
        return AutonomousTrader(
            llm_client=_ObservedLLM(self, run, llm), openalgo_client=run.adapter, order_executor=run.adapter,
            config=AgentConfig(**trader_config), vault=_build_vault(), memory=_build_learning_memory(),
            skill_registry=self.app.config.get("SKILL_REGISTRY"), skills_workspace=_build_skills_workspace(),
            market_session_provider=lambda exchange, symbol, day: scheduler.get_market_session(exchange, on=day, symbol=symbol),
            clock=scheduler.now_ist,
        )

    async def _settle_session(self, run: _Run, reason: str) -> None:
        # Retain a failed settlement so the exception handler cannot submit a
        # second reverse order for the same failed/uncertain cleanup attempt.
        run.settlement_failed = True
        self._event(run, "session_ending", {"reason": reason})
        if not await run.trader._finish_square_off(reason):  # noqa: SLF001 - reuse the engine's authoritative exit logic
            raise RuntimeError("Practice square-off incomplete")
        if not _sandbox_flat(self.app) or run.adapter.reconciliation_required:
            raise RuntimeError("Practice sandbox requires reconciliation")
        self._event(run, "session_flat", {"daily_pnl": run.trader.state.daily_pnl})
        if run.model_budget is not None and run.model_budget.exhausted:
            self._event(run, "session_learning_skipped", {"reason": "model_limit_exhausted", **run.model_budget.snapshot()})
            run.settlement_failed = False
            return
        learning_brake = self._model_brake(run, "reflection")
        if learning_brake is not None:
            self._safety_brake(run, learning_brake, "reflection")
            self._event(run, "session_learning_skipped", {"reason": learning_brake})
            run.settlement_failed = False
            return
        run.learning_active = True
        await run.trader._run_post_session_learning()  # noqa: SLF001 - existing bounded learning path, after flat proof
        # A timed-out learner remains an owned resource. Never close its memory
        # or overwrite its owner while it can still persist a lesson.
        await asyncio.to_thread(run.trader.join_background_learning, None)
        run.learning_active = False
        self._event(run, "session_learning_finished", {"closed_trade_count": len(run.trader.state.closed_trades)})
        run.settlement_failed = False

    async def _loop(self, run: _Run) -> None:
        from flinttrade_ai.autonomous_agent import AgentState  # noqa: PLC0415

        from .practice_agent_adapter import practice_entry_kill_code  # noqa: PLC0415

        trader = run.trader
        session_day: str | None = None
        settled_day: str | None = None
        next_cycle = 0.0
        while not run.stop.is_set() and not self.shutdown_requested.is_set():
            run.adapter.validate_session()
            kill_code = practice_entry_kill_code(self.app)
            if kill_code is not None:
                self._safety_brake(run, kill_code, "cycle")
                break
            if not _enabled():
                run.stop.set()
                break
            # Validate the injected clock even on a holiday, rather than silently
            # treating a broken scheduler as a successfully waiting session.
            trader._ist_now()  # noqa: SLF001
            sessions = [trader._effective_session(symbol) for symbol in trader.config.symbols]  # noqa: SLF001
            dates = {session.session_date.isoformat() for session in sessions if session is not None}
            day = min(dates) if dates else None
            boundary = trader._is_square_off_time()  # noqa: SLF001
            if session_day is not None and settled_day != session_day and (day != session_day or boundary):
                await self._settle_session(run, "Market session boundary")
                settled_day = session_day
            if day is not None and day != session_day:
                if not _sandbox_flat(self.app):
                    raise RuntimeError("New session cannot reset while Practice exposure remains")
                trader.state = AgentState(
                    trade_counts=dict.fromkeys(trader.config.symbols, 0),
                    last_signals=dict.fromkeys(trader.config.symbols, "HOLD"),
                )
                session_day = day
                self._event(run, "session_started", {"session_date": day})
                next_cycle = 0.0
            if day is None or day == settled_day or boundary:
                if run.status != "waiting":
                    self._persist(run, "waiting")
            elif monotonic() >= next_cycle:
                self._persist(run, "running")
                run.cycle_sessions = self._session_identities(trader)
                self._event(run, "cycle_started", {"cycle": trader.state.cycle_count + 1})
                result = await trader.run_cycle()
                # The strategy's safe fallback is TradeSignal.HOLD (StrEnum),
                # whereas the durable store deliberately accepts JSON primitives.
                for action in result.get("actions", {}).values():
                    if "signal" in action:
                        action["signal"] = str(action["signal"])
                self._event(run, "cycle_finished", result)
                self._persist(run, "stopping" if run.stop.is_set() else "running")
                if run.data_error:
                    raise RuntimeError("Configured market data unavailable: " + run.data_error)
                if run.model_error:
                    raise RuntimeError("Configured model unavailable")
                if run.adapter.reconciliation_required:
                    raise RuntimeError("Practice dispatch requires reconciliation")
                next_cycle = monotonic() + trader.config.cycle_interval_sec
            # Threading.Event makes both the market wait and the cycle interval
            # promptly interruptible without cancelling an uncertain dispatch.
            await asyncio.to_thread(run.stop.wait, 0.25)
        trader.request_stop(square_off=True)
        self._persist(run, "stopping")
        if session_day != settled_day or not trader.state.squared_off:
            await self._settle_session(run, "Stop requested")

    def _worker(self, run: _Run, llm: Any) -> None:
        terminal = "stopped"
        error = ""
        with self.app.app_context():
            try:
                try:
                    if llm is None:
                        from .agent_routes import _build_llm  # noqa: PLC0415

                        llm = _build_llm()
                    run.llm = llm
                    frozen = freeze_practice_client(llm, output_limit=run.config["model_output_limit"])
                    if frozen is not llm:
                        run.llm = frozen
                        llm.close()
                        llm = frozen
                except Exception:
                    run.model_error = "configured_model_unavailable"
                    self._event(run, "model_unavailable", {"code": run.model_error, "operation": "construction"})
                    raise RuntimeError("configured_model_unavailable") from None
                run.trader = self._construct_trader(run, llm)
                if run.stop.is_set():
                    run.trader.request_stop(square_off=True)
                asyncio.run(self._loop(run))
            except BaseException as exc:  # retain ownership and evidence even after an interrupted worker
                run.stop.set()
                terminal = "failed"
                # Exception text may contain credentials or upstream URLs. Durable
                # failures use local codes only; source adapters supply safe evidence.
                error = "Practice worker stopped: " + type(exc).__name__
                if run.data_error:
                    error = "Configured market data unavailable: " + run.data_error
                if run.model_error:
                    error = "Configured model unavailable; configure a working provider in Settings"
                logger.warning("Practice worker stopped (%s)", type(exc).__name__)
                if run.trader is not None:
                    run.trader.request_stop(square_off=True)
                # Never retry uncertain writes. Ordinary errors may still close
                # known positions, using the original, freshly validated session.
                if (run.trader is not None and not run.adapter.reconciliation_required
                        and not run.evidence_failed and not run.settlement_failed):
                    try:
                        asyncio.run(self._settle_session(run, "Worker stopping after failure"))
                    except Exception:
                        terminal = "reconciliation_required"
            finally:
                try:
                    if run.trader is not None:
                        run.trader.join_background_learning(None)
                        close_memory = getattr(run.trader.memory, "close", None)
                        if callable(close_memory):
                            close_memory()
                    self._close_llm(run)
                    run.cleanup_complete = True
                except Exception:
                    terminal = "reconciliation_required"
                    error = "Practice learning cleanup did not complete"
                try:
                    if (not _sandbox_flat(self.app) or run.adapter.reconciliation_required or run.evidence_failed
                            or (run.trader is not None and (run.trader.state.active_positions or run.trader.stop_failure))):
                        terminal = "reconciliation_required"
                        error = error or "Practice positions, pending orders or dispatch evidence require reconciliation"
                except Exception:
                    terminal = "reconciliation_required"
                    error = "Practice flat state could not be verified"
                run.adapter.close()
                try:
                    self._persist(run, terminal, error=error)
                except Exception:
                    # Leave the durable active row for crash recovery, but expose
                    # the in-memory failure now and refuse dependency teardown.
                    run.status = "reconciliation_required"
                    run.error = "Practice evidence storage failed; reconciliation is required"
                    run.snapshot = self._snapshot(run)

    @staticmethod
    def _close_llm(run: _Run) -> None:
        if run.llm_closed:
            return
        close = getattr(run.llm, "close", None)
        if callable(close):
            close()
        run.llm_closed = True

    def shutdown(self, timeout: float) -> bool:
        self.shutdown_requested.set()
        deadline = monotonic() + max(0.0, timeout)
        with self.lock:
            if self._store_closed:
                return self._release_lease()
            run = self.run
            if run is None:
                return self._close_store()
            run.stop.set()
            if run.trader is not None:
                run.trader.request_stop(square_off=True)
            thread = run.thread
        if thread is not None and thread.ident is not None:
            thread.join(max(0.0, deadline - monotonic()))
            if thread.is_alive():
                return False
        if not run.cleanup_complete or run.evidence_failed or run.status in _ACTIVE:
            return False
        with self.lock:
            return self._close_store()

    def _close_store(self) -> bool:
        if self._store_closed:
            return self._release_lease()
        try:
            self.store.close()
        except Exception:
            logger.warning("Practice evidence storage did not close")
            return False
        self._store_closed = True
        return self._release_lease()

    def _release_lease(self) -> bool:
        try:
            self._lease.release()
            return not self._lease.is_locked
        except Exception:
            logger.warning("Practice runtime ownership could not be released")
            return False


def get_practice_supervisor(app: Any) -> PracticeAgentSupervisor:
    """Initialise one app-owned store and recover interrupted evidence once."""
    with _SUPERVISOR_LOCK:
        supervisor = app.extensions.get(_EXTENSION)
        if supervisor is None:
            from flinttrade_ai.run_store import AgentRunStore  # noqa: PLC0415

            from .workspace import workspace_dir  # noqa: PLC0415

            store = app.config.get("PRACTICE_AGENT_RUN_STORE")
            if store is None:
                store = AgentRunStore(workspace_dir() / "practice_agent_runs.sqlite")
                app.config["PRACTICE_AGENT_RUN_STORE"] = store
            supervisor = PracticeAgentSupervisor(app, store)
            app.extensions[_EXTENSION] = supervisor
        return supervisor


def start_practice_agent() -> tuple[Any, int]:
    """Validate and start a durable Practice worker from a full session."""
    token, owner, denied = _authorise()
    if denied is not None:
        return denied
    if not _enabled():
        return _error("Enable ai.autonomous_agent.enabled in workspace settings first", 403)
    try:
        config = validate_practice_config(request.get_json(silent=True))
    except ValueError as exc:
        return _error(str(exc), 400)
    app = current_app._get_current_object()  # noqa: SLF001
    if app.extensions.get(_EXTENSION + "_shutdown"):
        return _error("The application is shutting down", 409)
    scheduler = app.config.get("TIME_SCHEDULER")
    if not callable(getattr(scheduler, "get_market_session", None)) or not callable(getattr(scheduler, "now_ist", None)):
        return _error("Market calendar is unavailable", 503)
    try:
        snapshot = get_practice_supervisor(app).start(token, owner, config)
    except RuntimeError as exc:
        # These errors are local refusals, never upstream exception messages.
        if str(exc) in {
            "The application is shutting down", "A Practice agent worker is still owned; stop it first",
            "Practice positions and pending orders must be flat before starting",
        }:
            return _error(str(exc), 409)
        return _error("A Practice run is active or requires reconciliation", 409)
    except Exception:
        return _error("Practice agent dependencies or durable evidence are unavailable", 503)
    return jsonify({"status": "success", "data": snapshot}), 202


def stop_practice_agent() -> tuple[Any, int]:
    _, owner, denied = _authorise()
    if denied is not None:
        return denied
    body = request.get_json(silent=True)
    if body is not None and (type(body) is not dict or set(body) - {"square_off"} or body.get("square_off", True) is not True):
        return _error("Practice agent stop always requires square-off", 400)
    try:
        result = get_practice_supervisor(current_app._get_current_object()).stop(owner)  # noqa: SLF001
        if result is None:
            return _error("No Practice agent worker is running for this operator", 404)
        return jsonify({"status": "success", "data": result}), 200
    except Exception:
        return _error("Stop was requested but durable status is unavailable", 503)


def practice_agent_status() -> tuple[Any, int]:
    _, owner, denied = _authorise()
    if denied is not None:
        return denied
    try:
        result = get_practice_supervisor(current_app._get_current_object()).snapshot(owner)  # noqa: SLF001
        return jsonify({"status": "success", "data": result}), 200
    except Exception:
        return _error("Practice agent status is unavailable", 503)


def _query_integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name, str(default))
    if not re.fullmatch(r"[0-9]{1,10}", raw) or not minimum <= int(raw) <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return int(raw)


def list_practice_runs() -> tuple[Any, int]:
    _, owner, denied = _authorise()
    if denied is not None:
        return denied
    try:
        limit = _query_integer("limit", 20, 1, 100)
        result = get_practice_supervisor(current_app._get_current_object()).history(owner, limit=limit)  # noqa: SLF001
        return jsonify({"status": "success", "data": result}), 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        return _error("Practice run history is unavailable", 503)


def practice_run_events(run_id: str) -> tuple[Any, int]:
    _, owner, denied = _authorise()
    if denied is not None:
        return denied
    try:
        after = _query_integer("after", 0, 0, 2_147_483_647)
        limit = _query_integer("limit", 100, 1, 1000)
        supervisor = get_practice_supervisor(current_app._get_current_object())  # noqa: SLF001
        if supervisor.owned_run(owner, run_id) is None:
            return _error("Practice run not found", 404)
        return jsonify({"status": "success", "data": supervisor.store.events(run_id, after=after, limit=limit)}), 200
    except ValueError as exc:
        return _error(str(exc), 400)
    except Exception:
        return _error("Practice run evidence is unavailable", 503)


def resolve_practice_run(run_id: str) -> tuple[Any, int]:
    _, owner, denied = _authorise()
    if denied is not None:
        return denied
    try:
        supervisor = get_practice_supervisor(current_app._get_current_object())  # noqa: SLF001
        result = supervisor.resolve(owner, run_id)
        return jsonify({"status": "success", "data": {**result["snapshot"], "run_id": run_id, "mode": "practice"}}), 200
    except KeyError:
        return _error("Practice run not found", 404)
    except ValueError as exc:
        return _error(str(exc), 400)
    except RuntimeError as exc:
        return _error(str(exc), 409)
    except Exception:
        return _error("Practice reconciliation could not be verified", 503)


def shutdown_practice_agent(app: Any, timeout: float = 30.0) -> bool:
    """Stop the owned worker before dependencies close; retain timed-out owners."""
    with _SUPERVISOR_LOCK:
        app.extensions[_EXTENSION + "_shutdown"] = True
        supervisor = app.extensions.get(_EXTENSION)
    if supervisor is None:
        return True
    return supervisor.shutdown(timeout)
