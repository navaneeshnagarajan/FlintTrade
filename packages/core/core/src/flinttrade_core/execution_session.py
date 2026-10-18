"""Immutable scope and trusted binding over actual execution owners and ledgers.

Legacy Practice retains its manual sandbox; independent runs use registry-bound
books on the same app. Native Live identities never imply dispatch authority.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from .artifact_activation import RunState
from .evaluation import digest


@dataclass(frozen=True)
class ExecutionSession:
    run_id: str
    actor: str
    account: str
    environment: str

    def __post_init__(self) -> None:
        if (any(type(value) is not str or not value or len(value) > 256 for value in asdict(self).values())
                or self.environment not in {"paper", "live"}):
            raise ValueError("Exact immutable execution scope required")


@dataclass(frozen=True)
class RunExecutionBinding:
    """Trusted app-owned Paper context; never construct from HTTP fields.

    Validation resolves durable identity and book ownership on every use.
    Protection still needs its separate canonical authority; this grants none.
    """

    registry: Any
    scope: ExecutionSession
    generation: int
    sandbox: Any

    def validate(self, *, entries: bool = False) -> None:
        with self.fence(entries=entries):
            pass

    @contextmanager
    def fence(self, *, entries: bool = False) -> Iterator[None]:
        from .execution_sessions import ExecutionSessions

        if type(self.registry) is not ExecutionSessions:
            raise ValueError("trusted execution registry required")
        with self.registry.fence(self, entries=entries):
            yield


def execution_custody(scope: ExecutionSession, store: Any, sandbox: Any) -> str:
    """Pin exact established ledger files/configuration, not a replacement book."""
    from pathlib import Path

    from .secure_file import validate_owner_owned_regular_file
    row = store.get_run(scope.run_id)
    if row is None or row["config"].get("owner") != scope.actor:
        raise ValueError("execution custody unavailable")
    sources = []
    for raw in (store.database_path, sandbox._db_path):
        path = Path(raw).absolute()
        info = validate_owner_owned_regular_file(path)
        sources.append((str(path), info.st_dev, info.st_ino))
    return digest({"scope": asdict(scope), "config": row["config"],
                   "sandbox": asdict(sandbox.config), "sources": sources})


def run_drained(run: Any) -> bool:
    """Prove the actual producer/learner/adapter retired, never a stop ACK."""
    return bool(run is not None and (run.thread is None or not run.thread.is_alive())
                and run.cleanup_complete and not run.evidence_failed and not run.settlement_failed
                and run.adapter is not None and run.adapter._closed
                and (run.trader is None or run.trader.join_background_learning(0)))


class PracticeRunOwner:
    """Adapt the actual supervisor, not a mirrored order/fill ledger.

    Lock order: supervisor -> sandbox -> run store. Sandbox's existing RLock
    serialises config, marks, pending fills, manual and agent writes. Admission
    acquires this fence *after* the canonical contract lock/Laya, never around
    model I/O. No operation here mutates orders, positions, cash or reservations.
    """

    def __init__(self, supervisor: Any) -> None:
        from flinttrade_data.sandbox_engine import SandboxEngine

        from .practice_agent_runtime import PracticeAgentSupervisor
        if not isinstance(supervisor, PracticeAgentSupervisor):
            raise TypeError("Existing Practice supervisor required")
        self.supervisor, self.store = supervisor, supervisor.store
        self.sandbox = supervisor.sandbox
        if not isinstance(self.sandbox, SandboxEngine):
            raise ValueError("Existing sandbox required")
        self.producer = supervisor.run
        self.identity = self.scope(self.producer.run_id)
        self.custody = execution_custody(self.identity, self.store, self.sandbox)

    def scope(self, run_id: str) -> ExecutionSession:
        row = self.store.get_run(run_id)
        if row is None or row["mode"] != "practice":
            raise KeyError(run_id)
        binding = self.supervisor.execution_binding
        if binding is not None:
            binding.validate()
            if row["config"].get("execution_session") != asdict(binding.scope) or binding.scope.run_id != run_id:
                raise ValueError("Execution scope mismatch")
            return binding.scope
        return ExecutionSession(run_id, row["config"]["owner"], "paper:sandbox", "paper")

    @contextmanager
    def fence(self, run_id: str, role: str) -> Iterator[None]:
        if role != "reasoning":
            raise ValueError("Practice has only a qualified reasoning proposal role")
        with self.supervisor.lock, self.sandbox._lock, self.store.run_fence(run_id):
            self.supervisor._require_ownership(accepting=False)
            if self.supervisor.sandbox is not self.sandbox:
                raise ValueError("Execution owner replaced")
            if self.supervisor.execution_binding is None and self.supervisor.app.config.get("DATA_SANDBOX_ENGINE") is not self.sandbox:
                raise ValueError("Execution owner replaced")
            self.scope(run_id)
            yield

    def snapshot(self, run_id: str, role: str) -> RunState:
        with self.fence(run_id, role):
            scope = self.scope(run_id)
            row = self.store.get_run(run_id)
            _, binding = self.store.model_control(run_id, "binding:" + role)
            binding = binding or {"candidate": "unqualified-legacy", "generation": 0, "paused": False}
            run = self.supervisor.run
            owned = (run is not None and run.run_id == run_id and run.owner == scope.actor
                     and run.adapter is not None and not run.evidence_failed)
            protected = False
            if owned:
                try:
                    run.adapter.validate_session()
                    protected = (run.trader is not None and run.thread is not None and run.thread.is_alive()
                                 and not run.cleanup_complete and not run.settlement_failed)
                except Exception:
                    pass
            frontier = digest({"orders": self.sandbox.get_all_orders(), "trades": self.sandbox.get_trades(),
                               "positions": self.sandbox.get_all_positions(), "pnl": self.sandbox.get_pnl()})
            risk = digest({"run": row["config"], "sandbox": asdict(self.sandbox.config)})
            return RunState(run_id, role, scope.account, scope.environment, binding["generation"], 0, risk,
                            frontier, "practice-protection:" + run_id if protected else "", protected,
                            binding["candidate"], bool(owned and not binding["paused"] and not run.stop.is_set()
                                                       and row["status"] in {"starting", "waiting", "running"}))

    def bind(self, candidate: str, expected_state: RunState) -> None:
        if type(candidate) is not str or not candidate or len(candidate) > 128:
            raise ValueError("Exact candidate required")
        with self.fence(expected_state.run_id, expected_state.role):
            if self.snapshot(expected_state.run_id, expected_state.role) != expected_state:
                raise ValueError("Run frontier changed")
            key = "binding:" + expected_state.role
            revision, old = self.store.model_control(expected_state.run_id, key)
            self.store.configure_model_control(expected_state.run_id, key,
                {"candidate": candidate, "generation": expected_state.generation + 1,
                 "paused": old["paused"] if old else False}, expected_revision=revision)

    def pause_entries(self, run_id: str, role: str) -> None:
        with self.fence(run_id, role):
            key = "binding:" + role
            revision, binding = self.store.model_control(run_id, key)
            binding = binding or {"candidate": "unqualified-legacy", "generation": 0, "paused": False}
            if not binding["paused"]:
                self.store.configure_model_control(run_id, key, {**binding, "paused": True}, expected_revision=revision)

    def control(self, run_id: str, key: str) -> tuple[int, dict[str, Any] | None]:
        return self.store.model_control(run_id, key)

    def configure(self, run_id: str, key: str, value: dict[str, Any], *, expected_revision: int) -> int:
        with self.fence(run_id, "reasoning"):
            return self.store.configure_model_control(run_id, key, value, expected_revision=expected_revision)
