"""App-owned durable run registry; identity is never the selected UI account.

Books are actual SandboxEngine stores, one per immutable Paper run. This is not
another broker backend, price source or trading/protection permission owner.
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterator

from .backend_instance import require_backend_lease_proof
from .execution_session import ExecutionSession, RunExecutionBinding
from .owner_file_lock import OwnerSafeFileLock
from .run_adoption_store import ModelEvidenceDatabase
from .secure_file import HeldOwnerDirectory, validate_owner_owned_regular_file

_SCHEMA = """
CREATE TABLE sessions (
 run_id TEXT PRIMARY KEY, actor TEXT NOT NULL, account TEXT NOT NULL,
 environment TEXT NOT NULL, kind TEXT NOT NULL, config TEXT NOT NULL,
 generation INTEGER NOT NULL, entries INTEGER NOT NULL, state TEXT NOT NULL,
 book_inode INTEGER, uncertain INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE session_history (run_id TEXT PRIMARY KEY REFERENCES sessions(run_id), inode INTEGER NOT NULL);
"""


class ExecutionSessions:
    """One backend owner for exact run lifecycle, books and recovery evidence."""

    def __init__(self, app: Any, path: Path) -> None:
        self.app, self.path = app, Path(path).absolute()
        self.lock = threading.RLock()
        self.closed = False
        self.proof = require_backend_lease_proof(app.config.get("BACKEND_LEASE_PROOF"))
        self.path.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.lease = OwnerSafeFileLock(str(self.path / "runtime.lock"), timeout=0, thread_local=False)
        self.lease.acquire()
        self.books: dict[str, Any] = {}
        self.owners: dict[str, Any] = {}
        self._reconciling_thread: int | None = None
        try:
            marker = ".execution-owner-" + self.path.name + ".json"
            with HeldOwnerDirectory(self.path.parent) as directory:
                established = directory.exists(marker)
                if established != (self.path / "registry.sqlite").exists():
                    raise ValueError("execution registry custody unknown")
                self.db = ModelEvidenceDatabase(self.path / "registry.sqlite", _SCHEMA)
                if established:
                    if directory.read_text(marker) != self.db.anchor:
                        raise ValueError("execution registry custody changed")
                else:
                    directory.write_text(marker, self.db.anchor)
            # Persist retirement before reconstructing any runner. No replay.
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0, generation=generation+1, state='rearm_required' "
                           "WHERE environment='paper'")
        except BaseException:
            self.lease.release()
            raise

    def _require(self) -> None:
        if self.closed or not self.lease.is_locked or self.app.config.get("BACKEND_LEASE_PROOF") is not self.proof:
            raise ValueError("execution owner unavailable")
        require_backend_lease_proof(self.proof)

    @staticmethod
    def _row(row: tuple[Any, ...]) -> dict[str, Any]:
        names = ("run_id", "actor", "account", "environment", "kind", "config", "generation", "entries_armed",
                 "state", "book_inode", "uncertain")
        result = dict(zip(names, row, strict=True))
        result["config"] = json.loads(result["config"])
        result["entries_armed"] = bool(result["entries_armed"])
        result["uncertain"] = bool(result["uncertain"])
        return result

    def _get(self, scope: ExecutionSession) -> dict[str, Any]:
        self._require()
        with self.db.transaction() as db:
            row = db.execute("SELECT * FROM sessions WHERE run_id=?", (scope.run_id,)).fetchone()
        if row is None or any(self._row(row)[key] != value for key, value in asdict(scope).items()):
            raise ValueError("execution scope mismatch")
        return self._row(row)

    def scope(self, run_id: str, actor: str) -> ExecutionSession:
        """Resolve server-held account/environment, never caller-selected scope."""
        with self.lock:
            self._require()
            with self.db.transaction() as db:
                row = db.execute("SELECT run_id,actor,account,environment FROM sessions WHERE run_id=? AND actor=?",
                                 (run_id, actor)).fetchone()
            if row is None:
                raise ValueError("execution scope mismatch")
            return ExecutionSession(*row)

    def create(self, scope: ExecutionSession, *, kind: str, config: dict[str, Any]) -> dict[str, Any]:
        """Reserve an immutable identity before any runner construction or action."""
        from flinttrade_ai.run_store import _payload
        from flinttrade_data.sandbox_engine import SandboxEngine

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", scope.run_id):
            raise ValueError("exact run identifier required")
        if kind not in {"practice", "strategy"}:
            raise ValueError("unknown execution kind")
        if scope.environment == "paper" and scope.account != "paper:run:" + scope.run_id:
            raise ValueError("execution scope mismatch")
        encoded = _payload(config)
        with self.lock:
            self._require()
            policy = None
            if scope.environment == "paper":
                template = self.app.config.get("DATA_SANDBOX_ENGINE")
                if not isinstance(template, SandboxEngine):
                    raise ValueError("configured Practice policy unavailable")
                with template._lock:
                    policy = replace(template.config)
            with self.db.transaction() as db:
                if db.execute("SELECT 1 FROM sessions WHERE run_id=?", (scope.run_id,)).fetchone():
                    raise ValueError("run identity already exists; read exact status, never replay")
                db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,0,0,?,NULL,0)",
                           (*asdict(scope).values(), kind, encoded,
                            "initialising" if scope.environment == "paper" else "native_unavailable"))
            if scope.environment == "paper":
                book_path = self.path / scope.run_id / "state.sqlite"
                # No pre-existing book may be adopted under a new identity.
                if book_path.exists():
                    raise ValueError("execution book custody unknown")
                book = SandboxEngine(str(book_path), config=policy)
                self.books[scope.run_id] = book
                inode = validate_owner_owned_regular_file(book_path).st_ino
                with self.db.transaction() as db:
                    db.execute("UPDATE sessions SET book_inode=?,state='ready' WHERE run_id=?", (inode, scope.run_id))
            return self.status(scope)

    def _book(self, scope: ExecutionSession, row: dict[str, Any]) -> Any:
        from flinttrade_data.sandbox_engine import SandboxEngine

        if scope.environment != "paper":
            raise ValueError("native execution unavailable")
        path = self.path / scope.run_id / "state.sqlite"
        info = validate_owner_owned_regular_file(path)
        if row["book_inode"] is None or info.st_ino != row["book_inode"]:
            raise ValueError("execution book custody unknown")
        if scope.run_id not in self.books:
            self.books[scope.run_id] = SandboxEngine(str(path), strict_existing=True)
        self.books[scope.run_id].verify_existing_book()
        return self.books[scope.run_id]

    def binding(self, scope: ExecutionSession) -> RunExecutionBinding:
        """Issue a non-serialisable trusted binding, not a bearer capability."""
        with self.lock:
            row = self._get(scope)
            return RunExecutionBinding(self, scope, row["generation"], self._book(scope, row))

    @contextmanager
    def fence(self, binding: RunExecutionBinding, *, entries: bool = False) -> Iterator[None]:
        """Serialise exact lifecycle changes with canonical sandbox admission."""
        with self.lock:
            row = self._get(binding.scope)
            if self._book(binding.scope, row) is not binding.sandbox:
                raise ValueError("execution book replaced")
            if row["uncertain"] and self._reconciling_thread != threading.get_ident():
                raise ValueError("execution reconciliation required")
            if entries and (binding.generation != row["generation"] or not row["entries_armed"]):
                raise ValueError("execution generation retired")
            with binding.sandbox._lock:
                yield

    def status(self, scope: ExecutionSession) -> dict[str, Any]:
        """Read the exact durable identity and actual ledger, including unknowns."""
        with self.lock:
            row = self._get(scope)
            public = {k: v for k, v in row.items() if k != "book_inode"}
            public.update(books=None, protection="unverified", native_ready=False)
            if scope.environment == "paper":
                try:
                    book = self._book(scope, row)
                    with book._lock:
                        public["books"] = {"positions": book.get_positions(), "orders": book.get_all_orders(),
                                           "trades": book.get_trades(), "pnl": book.get_pnl()}
                except Exception:
                    public.update(state="custody_unknown", entries_armed=False)
            return public

    def list(self, actor: str) -> list[dict[str, Any]]:
        """Enumerate all durable identities for the verified actor."""
        with self.lock:
            self._require()
            with self.db.transaction() as db:
                scopes = db.execute("SELECT run_id,actor,account,environment FROM sessions WHERE actor=? ORDER BY run_id",
                                    (actor,)).fetchall()
            return [self.status(ExecutionSession(*scope)) for scope in scopes]

    def stop_entries(self, scope: ExecutionSession, *, expected_generation: int) -> dict[str, Any]:
        """Retire entries only; do not cancel working orders or close positions."""
        with self.lock:
            row = self._get(scope)
            self._generation(row, expected_generation)
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,generation=generation+1,state='entries_stopped' WHERE run_id=?",
                           (scope.run_id,))
            return self.status(scope)

    @staticmethod
    def _generation(row: dict[str, Any], expected: int) -> None:
        if type(expected) is not int or row["generation"] != expected:
            raise ValueError("execution generation mismatch")

    def retire_actor(self, actor: str) -> None:
        """Logout retires entries without claiming protection stopped or flat."""
        with self.lock:
            self._require()
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,generation=generation+1,state='rearm_required' WHERE actor=? AND entries=1",
                           (actor,))

    def retire_entries(self, scope: ExecutionSession) -> None:
        """Core-local idempotent retirement for only the affected run."""
        with self.lock:
            self._get(scope)
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,generation=generation+1,state='rearm_required' "
                           "WHERE run_id=? AND entries=1", (scope.run_id,))

    def observe(self, scope: ExecutionSession, state: str, *, uncertain: bool = False) -> None:
        """Project actual worker terminal evidence, never infer flat from ACK."""
        if state not in {"stopped", "completed", "failed", "reconciliation_required"}:
            return
        with self.lock:
            self._get(scope)
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,generation=generation+entries,state=?,uncertain=MAX(uncertain,?) "
                           "WHERE run_id=?", (state, int(uncertain), scope.run_id))

    def maintenance_snapshot(self) -> dict[str, Any]:
        """Durable census, never a completeness claim from live thread count."""
        try:
            with self.lock:
                self._require()
                with self.db.transaction() as db:
                    scopes = db.execute("SELECT run_id,actor,account,environment FROM sessions ORDER BY run_id").fetchall()
                runs = [self.status(ExecutionSession(*scope)) for scope in scopes]
        except Exception:
            runs = None
        # Registry predates neither manual books nor every historical runner.
        # A complete reconciled legacy-owner census must be supplied by core.
        legacy, manual, protection, strategies = None, None, None, None
        try:
            legacy = self.app.config["PRACTICE_AGENT_RUN_STORE"].ownership_census()
        except Exception:
            pass
        try:
            book = self.app.config["DATA_SANDBOX_ENGINE"]
            with book._lock:
                book.verify_existing_book()
                manual = {"account": "paper:sandbox", "positions": book.get_positions(), "orders": book.get_all_orders()}
        except Exception:
            pass
        try:
            protection = self.app.config["PROTECTION_SERVICES"].maintenance_snapshot()
        except Exception:
            pass
        try:
            strategies = self.app.config["SCHEDULER"].status()
        except Exception:
            pass
        return {"registry_complete": False, "session_registry_complete": runs is not None, "history": "unknown",
                "runs": runs, "legacy_runs": legacy, "manual_paper": manual, "protection": protection,
                "legacy_strategy_workers": strategies, "disposal_authorised": False}

    def start(self, scope: ExecutionSession, *, token: str, expected_generation: int,
              rearm: bool = False) -> dict[str, Any]:
        """Explicitly start the actual runner; no retry of an earlier dispatch."""
        from flinttrade_ai.run_store import AgentRunStore

        from .auth_routes import verify_operator_session_token
        from .practice_agent_runtime import PracticeAgentSupervisor, _enabled, _sandbox_flat

        with self.app.app_context():
            if verify_operator_session_token(token).actor_ref != scope.actor or not _enabled():
                raise ValueError("execution authority unavailable")
        with self.lock:
            row = self._get(scope)
            self._generation(row, expected_generation)
            if scope.environment != "paper":
                raise ValueError("execution kind unavailable")
            states = {"rearm_required", "stopped", "completed"} if rearm else {"ready"}
            if row["state"] not in states or row["uncertain"]:
                raise ValueError("explicit reconciliation and rearm required")
            book = self._book(scope, row)
            previous = self.owners.get(scope.run_id)
            from .execution_session import run_drained
            if (not _sandbox_flat(self.app, sandbox=book)
                    or previous is not None and (not rearm or not run_drained(previous.run))):
                raise ValueError("existing execution ownership must reconcile")
            if self.app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True:
                raise ValueError("execution runtime draining")
            if previous is not None:
                if hasattr(previous, "_close_store"):
                    if not previous._close_store():
                        raise ValueError("existing execution storage still owned")
                else:
                    previous.store.close()
                    previous._closed = True
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=1,generation=generation+1,state='starting' WHERE run_id=?",
                           (scope.run_id,))
            store = None
            try:
                binding = self.binding(scope)
                store_path = self.path / scope.run_id / "runs.sqlite"
                with self.db.transaction() as db:
                    history = db.execute("SELECT inode FROM session_history WHERE run_id=?", (scope.run_id,)).fetchone()
                if history is not None:
                    if not rearm or validate_owner_owned_regular_file(store_path).st_ino != history[0]:
                        raise ValueError("existing run history custody unknown")
                elif store_path.exists():
                    raise ValueError("unregistered run history custody unknown")
                store = AgentRunStore(store_path, strict_existing=history is not None)
                if history is None:
                    with self.db.transaction() as db:
                        db.execute("INSERT INTO session_history VALUES (?,?)", (scope.run_id, store_path.stat().st_ino))
                if row["kind"] == "strategy":
                    from .execution_strategy import ExecutionStrategyOwner
                    supervisor = ExecutionStrategyOwner(self.app, store, execution_binding=binding)
                else:
                    supervisor = PracticeAgentSupervisor(self.app, store, execution_binding=binding)
                self.owners[scope.run_id] = supervisor
            except BaseException:
                self.observe(scope, "reconciliation_required", uncertain=True)
                if store is not None:
                    store.close()
                raise
        try:
            supervisor.start(token, scope.actor, row["config"], rearm=history is not None)
            with self.lock, self.db.transaction() as db:
                db.execute("UPDATE sessions SET state='running' WHERE run_id=? AND entries=1", (scope.run_id,))
        except Exception:
            with self.lock, self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,state='reconciliation_required',uncertain=1 WHERE run_id=?",
                           (scope.run_id,))
            raise
        return self.status(scope)

    def resume_protection(self) -> dict[str, Any]:
        """Resume issued duties only, retaining failed owners and their custody."""
        from flinttrade_ai.run_store import AgentRunStore

        from .practice_agent_runtime import PracticeAgentSupervisor
        protection = self.app.config.get("PROTECTION_SERVICES")
        try:
            scopes = protection.recovery_scopes()
        except Exception:
            return {"state": "unavailable", "runs": None}
        result = []
        with self.lock:
            self._require()
            for scope in scopes:
                state = "unavailable"
                try:
                    row = self._get(scope)
                    owner = self.owners.get(scope.run_id)
                    if owner is not None:
                        run = owner.run
                        if run and run.thread and run.thread.is_alive() and not run.stop.is_set():
                            state = "supervising"
                        elif run and run.cleanup_complete and run.status in {"stopped", "completed"}:
                            state = "settled"
                        result.append({"run_id": scope.run_id, "state": state})
                        continue
                    if row["environment"] != "paper" or row["kind"] != "practice" or row["entries_armed"]:
                        raise ValueError("protection runtime unqualified")
                    store_path = self.path / scope.run_id / "runs.sqlite"
                    with self.db.transaction() as db:
                        history = db.execute("SELECT inode FROM session_history WHERE run_id=?", (scope.run_id,)).fetchone()
                    if history is None or validate_owner_owned_regular_file(store_path).st_ino != history[0]:
                        raise ValueError("existing run history custody unknown")
                    self._reconciling_thread = threading.get_ident()
                    store = AgentRunStore(store_path, strict_existing=True)
                    try:
                        owner = PracticeAgentSupervisor(self.app, store, execution_binding=self.binding(scope))
                    except BaseException:
                        store.close()
                        raise
                    self.owners[scope.run_id] = owner
                    with self.app.app_context():
                        active = owner.resume_protection(protection)
                        models = self.app.config.get("MODEL_RUN_SERVICES")
                        if models is not None:
                            models.attach_practice(owner)
                    with self.db.transaction() as db:
                        db.execute("UPDATE sessions SET uncertain=0,entries=0 WHERE run_id=?", (scope.run_id,))
                    if active:
                        run = owner.run
                        run.thread = threading.Thread(target=owner._worker, args=(run, None),
                                                      name="run-protection-" + scope.run_id, daemon=True)
                        run.thread.start()
                        state = "supervising"
                    else:
                        state = "settled"
                except Exception:
                    # The failed exact owner stays retained; no automatic restart
                    # or replacement of a live/uncertain attempt on later calls.
                    state = "unavailable"
                finally:
                    self._reconciling_thread = None
                result.append({"run_id": scope.run_id, "state": state})
        return {"state": "observed", "runs": result}

    def close_positions(self, scope: ExecutionSession, *, expected_generation: int) -> dict[str, Any]:
        """Request fixed run-only Close separately from retiring new entries."""
        with self.lock:
            row = self._get(scope)
            self._generation(row, expected_generation)
            owner = self.owners.get(scope.run_id)
            if owner is None or owner.run is None or not owner.run.thread or not owner.run.thread.is_alive():
                raise ValueError("protection owner unavailable; reconcile exact run")
            self.stop_entries(scope, expected_generation=expected_generation)
            owner.run.close_requested.set()
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET state='close_requested' WHERE run_id=?", (scope.run_id,))
        return self.status(scope)

    def shutdown(self, timeout: float = 30.0) -> bool:
        """Drain actual workers without inventing liquidation authority."""
        from time import monotonic
        deadline = monotonic() + max(0, timeout)
        with self.lock:
            if self.closed:
                return True
            self._require()
            with self.db.transaction() as db:
                db.execute("UPDATE sessions SET entries=0,generation=generation+1,state='rearm_required' WHERE entries=1")
            owners = list(self.owners.values())
            from .practice_agent_runtime import _sandbox_flat
            retained = {id(owner) for owner in owners if owner.run and owner.run.thread
                        and owner.run.thread.is_alive() and (
                            not _sandbox_flat(self.app, sandbox=owner.sandbox)
                            or owner.run.adapter is not None and owner.run.adapter.reconciliation_required)}
        # Refusing a stop must not strand the still-usable fixed protector.
        # Retire entries above, but keep exposed/uncertain live duties running
        # until a risk rule or an explicit Close reconciles them. No liquidation.
        results = [False if id(owner) in retained else owner.shutdown(max(0, deadline - monotonic()))
                   for owner in owners]
        return all(results)

    def close(self) -> None:
        """Release only after every actual worker has drained; never liquidate."""
        with self.lock:
            if self.closed:
                return
            if any(owner.run and ((owner.run.thread and owner.run.thread.is_alive())
                   or (owner.run.trader is not None and not owner.run.trader.join_background_learning(0)))
                   for owner in self.owners.values()):
                raise RuntimeError("execution consumers still owned")
            protection = self.app.config.get("PROTECTION_SERVICES")
            for run_id, owner in self.owners.items():
                if getattr(owner, "_resources_closed", False):
                    continue
                def dispose(owner=owner, run_id=run_id):
                    self.books[run_id].close()
                    if hasattr(owner, "_close_store"):
                        if not owner._close_store():
                            raise RuntimeError("execution store retained")
                    else:
                        owner.store.close()
                        owner._closed = True
                    owner._resources_closed = True
                if (protection is not None and owner.run is not None
                        and owner.run.adapter is not None and owner.run.adapter._protection is not None):
                    protection.release_after_drain(owner.execution_binding.scope, dispose)
                else:
                    dispose()
            for book in self.books.values():
                book.close()
            self.closed = True
            self.lease.release()
