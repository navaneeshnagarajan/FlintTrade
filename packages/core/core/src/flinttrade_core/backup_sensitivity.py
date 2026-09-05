"""Composition-owned recursive policy for ordinary, non-authority archives.

New stores must register their whole namespace here before ordinary backup can
enumerate them. Unknown paths fail closed, including future coordinator stores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .workspace_migrations import MIGRATIONS

COORDINATED_RESTORE_UNAVAILABLE = "coordinated_restore_unavailable"

# Whole namespaces: never descend, even when nested beneath a market-data root.
_PRIVATE_ROOTS = frozenset(
    {
        "secrets",
        "logs",
        "archive",
        "flows",
        "agent_memory",
        "rag",
        "skills",
        "skill_drafts",
        "plugins",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "contracts",
        "engine-sandbox",
    }
)
_DATABASES = frozenset(
    {
        "credentials.db",
        "credentials.duckdb",
        "ditto_credentials.db",
        "webhook_secrets.db",
        "auth.db",
        "totp_auth.duckdb",
        "auth_state.duckdb",
        "activity.db",
        "order-lifecycle.sqlite3",
        "order_exposure_reservations.sqlite",
        "emergency_intents.sqlite",
        "daily_pnl_state.sqlite",
        "action_center.duckdb",
        "ai_sessions.sqlite",
        "api_analyzer.duckdb",
        "flint.duckdb",
        "sandbox.duckdb",
        "historify_queue.db",
        "ditto_accounts.sqlite",
        "shortcuts.duckdb",
    }
)
_SECURITY_MEMBERS = frozenset(
    {
        "jwt_secret",
        "api_key_pepper",
        "safety_gate_secret",
        "master_password",
        "totp_install_key",
        "backend_instance.lock",
        "backup-password",
        ".env",
        ".totp-migration.lock",
        ".action-center-migration.lock",
    }
)
_WORKSPACE_MEMBERS = frozenset(
    {
        "workspace.json",
        "workspace.brokers.bak.json",
        ".migration.lock",
        ".lmstudio-retirement.transaction.json",
        *(f"workspace.{version}.bak.json" for version in MIGRATIONS),
    }
)
_SENSITIVE_BASES = _DATABASES | _SECURITY_MEMBERS | _WORKSPACE_MEMBERS
_TICK_ROOTS = frozenset({"ticks", "tick_data", "questdb_data"})
_BHAVCOPY_SEGMENTS = frozenset({"equity", "fo", "index", "full"})


class UnclassifiedArchivePath(ValueError):
    """An ordinary archive cannot establish that this namespace is non-authority."""


def _sensitive_family(name: str) -> bool:
    if name in _SENSITIVE_BASES:
        return True
    for base in _SENSITIVE_BASES:
        escaped = re.escape(base)
        if re.fullmatch(
            rf"\.{escaped}(?:\.[A-Za-z0-9_-]+)?\.(?:tmp|publishing|migrating|delete-pending)(?:\.wal)?", name
        ):
            return True
        if base in _DATABASES and re.fullmatch(
            rf"{escaped}(?:\.pre-sqlite\.bak(?:\.[0-9]+)?)?(?:\.wal|-wal|-shm|-journal)?",
            name,
        ):
            return True
    return False


@dataclass(frozen=True)
class WorkspaceBackupSensitivity:
    """One recursive registry shared by archive creation and restore admission."""

    include_ticks: bool = False

    def classify(self, relative: PurePosixPath, *, directory: bool) -> str:
        """Return excluded/directory/file, or refuse an unregistered namespace."""
        if not relative.parts or relative.is_absolute() or any(p in {".", ".."} for p in relative.parts):
            raise UnclassifiedArchivePath(COORDINATED_RESTORE_UNAVAILABLE)
        if any(part.casefold() in _PRIVATE_ROOTS or _sensitive_family(part.casefold()) for part in relative.parts):
            return "excluded"
        if not self.include_ticks and any(part in _TICK_ROOTS for part in relative.parts):
            return "excluded"
        # BhavcopyDownloader owns data/bhavcopy/<segment>/<CSV>. Other data
        # and live database families await dedicated consistency adapters.
        parts = relative.parts
        if directory and parts in {("data",), ("data", "bhavcopy")}:
            return "directory"
        if parts[:2] == ("data", "bhavcopy") and len(parts) >= 3 and parts[2] in _BHAVCOPY_SEGMENTS:
            if directory and len(parts) == 3:
                return "directory"
            if not directory and len(parts) == 4 and relative.suffix.lower() == ".csv":
                return "file"
        raise UnclassifiedArchivePath(COORDINATED_RESTORE_UNAVAILABLE)
