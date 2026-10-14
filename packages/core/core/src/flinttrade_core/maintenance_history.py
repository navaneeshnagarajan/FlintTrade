"""Fresh-install provenance reconciled with actual execution/protection owners.

A newly created empty installation is recorded at the already-exclusive public
provisioning boundary. Existing/unanchored history is NEVER upgraded by absence,
PID/JWT expiry, a free lease or a caller-supplied approval document. This proof
covers the current local Paper ownership layout only; native authority refuses.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .backend_instance import BackendInstanceLease
from .installation_state import InstallationState, stable_application_state_root
from .maintenance_custody import MaintenanceRefused
from .run_adoption_store import ModelEvidenceDatabase
from .secure_file import validate_owner_owned_regular_file

_SCHEMA = "CREATE TABLE origin (installation TEXT PRIMARY KEY, workspace TEXT NOT NULL, device INTEGER, inode INTEGER, sources TEXT NOT NULL);"
_SOURCES = ("practice_agent_runs.sqlite", "sandbox/state.sqlite", "protection.sqlite", "protection.registry")


def _default_root() -> Path:
    return Path.home() / ".flinttrade-installation"


def initialise_fresh_history(workspace: Path, lease: BackendInstanceLease) -> bool:
    """Record only a first-ever local installation under its actual kernel lease.

    This creates empty real ledgers, NOT grants. The later explicit maintenance
    request still has to reconcile all these sources and current owners. A
    partial initialisation remains unknown; it is never silently re-created.
    """
    if (os.name != "posix" or type(lease) is not BackendInstanceLease or not lease._is_live()
            or not lease._created or lease._exclusion_lease is None or not lease._exclusion_lease._created
            or lease._lock_path.parent != workspace or workspace != Path.home() / ".flinttrade"
            or stable_application_state_root() != _default_root()):
        return False
    root = _default_root()
    if root.exists() or set(os.listdir(workspace)) - {"backend_instance.lock", "src", "tools", "source-build"}:
        return False
    from flinttrade_ai.run_store import AgentRunStore
    from flinttrade_data.sandbox_engine import SandboxEngine

    from .protection_grants import ProtectionServices

    installation = InstallationState(root)
    # Once identity exists, any error below leaves explicit unknown history.
    database = ModelEvidenceDatabase(root / "maintenance-history.sqlite", _SCHEMA)
    legacy = AgentRunStore(workspace / _SOURCES[0])
    legacy.close()
    manual = SandboxEngine(str(workspace / _SOURCES[1]))
    manual.close()
    protection = ProtectionServices(None, workspace)
    protection._db(create=True)
    protection.close()
    files = {name: [info.st_dev, info.st_ino] for name in _SOURCES
             for info in [validate_owner_owned_regular_file(workspace / name)]}
    info = workspace.stat()
    with database.transaction() as db:
        db.execute("INSERT INTO origin VALUES (?,?,?,?,?)", (str(installation.installation_id), str(workspace),
                                                             info.st_dev, info.st_ino, json.dumps(files)))
    return True


class MaintenanceHistory:
    """Read existing provenance; there is no import-approval or force interface."""

    def __init__(self, installation: InstallationState, workspace: Path) -> None:
        self.installation, self.workspace = installation, workspace
        path = installation.root / "maintenance-history.sqlite"
        if not path.is_file() or not path.with_name(path.name + ".authority.json").is_file():
            raise MaintenanceRefused("execution census incomplete; historical ownership unknown")
        self.database = ModelEvidenceDatabase(path, _SCHEMA)

    def reconcile_idle(self, app: Any, snapshot: dict) -> dict:
        """Compose fresh provenance with concrete, complete current owner reads.

        R20's global registry_complete=False is preserved as an observation.
        Its *scoped* registry completeness is combined with this independently
        anchored legacy/manual provenance; it is never inverted into permission.
        """
        from flinttrade_ai.run_store import AgentRunStore
        from flinttrade_data.sandbox_engine import SandboxEngine
        from flinttrade_engine.scheduler import StrategyScheduler
        from flinttrade_gateway.registry import BrokerRegistry

        from .workspace_migrations import read_workspace_snapshot

        self.installation.assert_mutation_ready()
        with self.database.transaction() as db:
            rows = db.execute("SELECT * FROM origin").fetchall()
        if len(rows) != 1:
            raise MaintenanceRefused("historical coverage provenance incomplete")
        row = rows[0]
        info = self.workspace.stat()
        if row[:4] != (str(self.installation.installation_id), str(self.workspace), info.st_dev, info.st_ino):
            raise MaintenanceRefused("historical coverage belongs to another installation/workspace")
        sources = json.loads(row[4])
        if set(sources) != set(_SOURCES):
            raise MaintenanceRefused("historical coverage source layout unknown")
        for name, identity in sources.items():
            info = validate_owner_owned_regular_file(self.workspace / name)
            if [info.st_dev, info.st_ino] != identity:
                raise MaintenanceRefused("historical execution source custody changed")
        config = read_workspace_snapshot(self.workspace).as_dict()
        brokers = config.get("brokers")
        registry = app.config.get("REGISTRY")
        if (type(brokers) is not dict or brokers.get("registered") != [] or brokers.get("account_acls") != {}
                or type(registry) is not BrokerRegistry or registry.list_exact_states()):
            raise MaintenanceRefused("native/manual account history is not qualified for maintenance")
        scheduler = app.config.get("SCHEDULER")
        if type(scheduler) is not StrategyScheduler:
            raise MaintenanceRefused("legacy strategy ownership census unavailable")
        with scheduler._runner_lock:
            if scheduler.status() or scheduler._owned_runners or scheduler._pending_stop_submissions:
                raise MaintenanceRefused("legacy strategy ownership remains unresolved")
        manual = app.config.get("DATA_SANDBOX_ENGINE")
        if type(manual) is not SandboxEngine or Path(manual._db_path) != self.workspace / "sandbox/state.sqlite":
            raise MaintenanceRefused("manual Paper book ownership unavailable")
        with manual._lock:
            manual.verify_existing_book()
            if manual.get_positions() or manual.get_all_orders() or manual.get_trades():
                raise MaintenanceRefused("manual Paper execution history requires reconciliation")
        actual_legacy = app.config.get("PRACTICE_AGENT_RUN_STORE")
        if (type(actual_legacy) is not AgentRunStore
                or Path(actual_legacy.database_path) != self.workspace / "practice_agent_runs.sqlite"
                or snapshot.get("legacy_runs") != []):
            raise MaintenanceRefused("actual legacy run ownership is incomplete or conflicts with historical coverage")
        legacy = AgentRunStore(self.workspace / "practice_agent_runs.sqlite", strict_existing=True)
        try:
            if legacy.ownership_census():
                raise MaintenanceRefused("legacy run history requires explicit reconciliation")
        finally:
            legacy.close()
        if snapshot.get("session_registry_complete") is not True or type(snapshot.get("runs")) is not list:
            raise MaintenanceRefused("scoped execution census incomplete")
        sessions = app.config["EXECUTION_SESSIONS"]
        for run in snapshot["runs"]:
            books = run.get("books")
            if (run.get("environment") != "paper" or run.get("entries_armed") is not False
                    or run.get("uncertain") is not False or run.get("state") not in {"ready", "rearm_required", "entries_stopped"}
                    or type(books) is not dict or any(books.get(name) != [] for name in ("positions", "orders", "trades"))):
                raise MaintenanceRefused("scoped execution/protection remains active or unresolved")
        if sessions.owners:
            raise MaintenanceRefused("scoped execution workers require explicit reconciliation")
        return {"coverage": "fresh-local-paper-v1", "installation": row[0], "session_registry_complete": True,
                "legacy_runs": [], "manual_book": "observed-never-executed", "native": "not-configured"}
