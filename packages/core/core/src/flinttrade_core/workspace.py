"""FlintTrade workspace configuration — ~/.flinttrade/workspace.json.

Cross-platform workspace location:
  Linux:   ~/.flinttrade/
  macOS:   ~/Library/Application Support/flinttrade/
  Windows: %APPDATA%/flinttrade/
  Override: FLINTTRADE_HOME env var

All user preferences and UI-owned integration settings live in workspace.json.
.env is retained only as an advanced dev/server fallback.
"""

from __future__ import annotations

import copy
import filecmp
import json
import logging
import os
import platform
import shutil
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout as FileLockTimeout

from .workspace_migrations import (
    WORKSPACE_VERSION,
    default_workspace_config,
    run_migrations,
    update_workspace_config,
    write_workspace_config,
)

logger = logging.getLogger("flinttrade.core.workspace")

_DEFAULT_CONFIG: dict[str, Any] = default_workspace_config()
_LEGACY_FAST_DATA_PATH = "~/.flinttrade/data"
_LEGACY_ARCHIVE_PATH = "~/.flinttrade/archive"


class WorkspaceStateMigrationError(RuntimeError):
    """Legacy operator state could not be preserved in the platform workspace."""


def _default_home() -> Path:
    """Resolve the platform-appropriate workspace directory."""
    env = os.environ.get("FLINTTRADE_HOME")
    if env:
        return Path(env).expanduser().resolve()

    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "flinttrade"
    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "flinttrade"
        return Path.home() / "AppData" / "Roaming" / "flinttrade"
    # Linux and everything else
    return Path.home() / ".flinttrade"


def workspace_dir() -> Path:
    """Resolve the active FlintTrade workspace directory and ensure it exists.

    Priority order:

    1. ``FLINTTRADE_WORKSPACE_DIR`` env var — used by pytest workers to give
       each test process its own isolated directory so that DuckDB's exclusive
       write locks do not collide across parallel runs.
    2. ``FLINTTRADE_HOME`` env var (handled by :func:`_default_home`) — manual
       override for non-standard installations.
    3. Platform default (``~/.flinttrade`` on Linux, ``%APPDATA%/flinttrade``
       on Windows, ``~/Library/Application Support/flinttrade`` on macOS).

    The returned directory is always created (``parents=True, exist_ok=True``)
    so callers can immediately open files inside it.

    Returns:
        An absolute :class:`~pathlib.Path` pointing to the workspace root.
    """
    override = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    if override:
        p = Path(override).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        _lock_workspace_perms(p)
        return p
    p = _default_home()
    p.mkdir(parents=True, exist_ok=True)
    _lock_workspace_perms(p)
    return p


def legacy_dotdir() -> Path:
    """Return the pre-workspace literal root (``~/.flinttrade``).

    For legacy-migration probes only. Never use this to decide where new
    state is written — that is :func:`workspace_dir`.

    Returns:
        The literal dot-directory, regardless of platform.
    """
    return Path.home() / ".flinttrade"


def default_workspace_active() -> bool:
    """Return True when no workspace environment override is in force.

    Legacy-migration probes must be gated on this so pytest workers
    (which always export ``FLINTTRADE_WORKSPACE_DIR``) never touch the
    developer's real home directory.

    Returns:
        True when neither ``FLINTTRADE_WORKSPACE_DIR`` nor
        ``FLINTTRADE_HOME`` is set.
    """
    return not (os.environ.get("FLINTTRADE_WORKSPACE_DIR") or os.environ.get("FLINTTRADE_HOME"))


def duckdb_path() -> Path:
    """Resolve the shared DuckDB file from one cross-platform source of truth.

    ``DUCKDB_PATH`` remains an explicit server/test override. Desktop and normal
    runtime callers otherwise follow the workspace's configured fast-data
    directory instead of rebuilding a Linux-only ``~/.flinttrade`` fallback.
    """
    override = os.environ.get("DUCKDB_PATH")
    if override:
        return Path(override).expanduser()
    workspace = Workspace()
    target = workspace.fast_data_dir / "flint.duckdb"
    if _uses_implicit_default_storage(workspace, "storage.fast", _LEGACY_FAST_DATA_PATH):
        _migrate_legacy_duckdb(_legacy_duckdb_path(), target)
    return target


def _legacy_duckdb_path() -> Path:
    """Return the pre-platform-workspace shared DuckDB location."""
    return _legacy_fast_data_dir() / "flint.duckdb"


def _migrate_legacy_duckdb(legacy: Path, target: Path) -> None:
    """Copy a legacy shared DuckDB and WAL once, retaining the originals."""
    copy_legacy_database_once(
        legacy,
        target,
        sidecar_suffixes=(".wal",),
        lock_name=".duckdb-migration.lock",
        label="shared DuckDB",
    )


def sandbox_state_path() -> Path:
    """Resolve the canonical Practice SQLite database and preserve old state."""
    override = os.environ.get("SANDBOX_STATE_PATH") or os.environ.get("SANDBOX_DB_PATH")
    if override:
        return Path(override).expanduser()
    target = (Workspace().workspace_dir / "sandbox" / "state.sqlite").resolve()
    if not os.environ.get("FLINTTRADE_HOME") and not os.environ.get("FLINTTRADE_WORKSPACE_DIR"):
        copy_legacy_database_once(
            _legacy_sandbox_state_path(),
            target,
            sidecar_suffixes=("-wal", "-journal"),
            lock_name=".sandbox-state-migration.lock",
            label="Practice SQLite database",
        )
    return target


def _legacy_sandbox_state_path() -> Path:
    """Return the pre-platform-workspace Practice SQLite location."""
    return Path.home() / ".flinttrade" / "sandbox" / "state.sqlite"


def historify_queue_path() -> Path:
    """Resolve the durable Historify queue and preserve its SQLite state."""
    override = os.environ.get("HISTORIFY_QUEUE_DB")
    if override:
        return Path(override).expanduser()
    workspace = Workspace()
    target = workspace.fast_data_dir / "historify_queue.db"
    if _uses_implicit_default_storage(workspace, "storage.fast", _LEGACY_FAST_DATA_PATH):
        copy_legacy_database_once(
            _legacy_fast_data_dir() / "historify_queue.db",
            target,
            sidecar_suffixes=("-wal", "-journal"),
            lock_name=".historify-queue-migration.lock",
            label="Historify queue",
        )
    return target


def ditto_accounts_path() -> Path:
    """Resolve Ditto metadata and migrate its adjacent canonical vault together."""
    override = os.environ.get("DATA_DIR")
    if override:
        return Path(override).expanduser() / "ditto_accounts.sqlite"
    workspace = Workspace()
    target = workspace.fast_data_dir / "ditto_accounts.sqlite"
    if _uses_implicit_default_storage(workspace, "storage.fast", _LEGACY_FAST_DATA_PATH):
        _migrate_legacy_ditto_state(_legacy_fast_data_dir(), target.parent)
    return target


def audit_log_dir() -> Path:
    """Resolve the append-only audit chain directory without forking old state."""
    override = os.environ.get("AUDIT_LOG_DIR")
    if override:
        return Path(override).expanduser()
    workspace = Workspace()
    target = workspace.archive_dir / "audit"
    if _uses_implicit_default_storage(workspace, "storage.archive", _LEGACY_ARCHIVE_PATH):
        copy_legacy_directory_once(
            _legacy_archive_dir() / "audit",
            target,
            lock_name=".audit-directory-migration.lock",
            label="audit chain",
            excluded_names=frozenset({".audit-chain.lock"}),
            source_lock_name=".audit-chain.lock",
            conflict_is_error=True,
        )
    return target


def bhavcopy_dir() -> Path:
    """Resolve local bhavcopy archives and copy the legacy cache once."""
    workspace = Workspace()
    target = workspace.fast_data_dir / "bhavcopy"
    if _uses_implicit_default_storage(workspace, "storage.fast", _LEGACY_FAST_DATA_PATH):
        copy_legacy_directory_once(
            _legacy_fast_data_dir() / "bhavcopy",
            target,
            lock_name=".bhavcopy-directory-migration.lock",
            label="bhavcopy archive",
        )
    return target


def plugins_dir() -> Path:
    """Resolve the user plugin directory and copy the legacy one once.

    The default workspace moved off ``~/.flinttrade`` on macOS and Windows, so
    plugins an operator had already dropped into ``~/.flinttrade/plugins``
    stopped being discovered on the next upgrade — silently, because a missing
    plugin directory is not an error. They are therefore migrated exactly like
    the shared DuckDB, the audit chain and the Practice database before them.

    The copy is skipped when ``FLINTTRADE_HOME`` or ``FLINTTRADE_WORKSPACE_DIR``
    is set (an explicitly chosen workspace is never seeded from someone else's
    plugins) and when the platform workspace already holds plugins
    (target-exists-wins). The legacy directory is copied, never moved, so a
    downgrade still finds it.

    Returns:
        The platform workspace's ``plugins`` directory. It is not created here:
        :class:`~flinttrade_core.plugin_loader.PluginLoader` treats a missing
        directory as "no plugins", which is the correct fresh-install answer.

    Raises:
        WorkspaceStateMigrationError: When a legacy plugin directory exists but
            could not be preserved.
    """
    target = workspace_dir() / "plugins"
    if default_workspace_active():
        copy_legacy_directory_once(
            _legacy_plugins_dir(),
            target,
            lock_name=".plugins-directory-migration.lock",
            label="user plugins",
            # ``plugins`` sits directly under the workspace root, so the helper's
            # default lock location (``target.parent.parent``) would drop a lock
            # file OUTSIDE the workspace — in ``%APPDATA%`` or ``~/Library``.
            lock_dir=target.parent,
        )
    return target


def _legacy_plugins_dir() -> Path:
    """Return the pre-platform-workspace user plugin directory."""
    return Path.home() / ".flinttrade" / "plugins"


def _legacy_fast_data_dir() -> Path:
    return Path.home() / ".flinttrade" / "data"


def _legacy_archive_dir() -> Path:
    return Path.home() / ".flinttrade" / "archive"


def _uses_implicit_default_storage(workspace: Workspace, key: str, default: str) -> bool:
    return (
        workspace.get(key, default) == default
        and not os.environ.get("FLINTTRADE_HOME")
        and not os.environ.get("FLINTTRADE_WORKSPACE_DIR")
    )


def _migrate_legacy_ditto_state(legacy_dir: Path, target_dir: Path) -> None:
    legacy_accounts = legacy_dir / "ditto_accounts.sqlite"
    target_accounts = target_dir / "ditto_accounts.sqlite"
    if target_accounts.exists() or not legacy_accounts.exists():
        return

    legacy_vault = legacy_dir / "ditto_credentials.db"
    target_vault = target_dir / "ditto_credentials.db"
    if target_vault.exists():
        if not legacy_vault.exists() or not filecmp.cmp(legacy_vault, target_vault, shallow=False):
            raise WorkspaceStateMigrationError(
                "Ditto migration found an unmatched target credential vault; both states were preserved"
            )
    elif legacy_vault.exists():
        copy_legacy_database_once(
            legacy_vault,
            target_vault,
            sidecar_suffixes=("-wal", "-journal"),
            lock_name=".ditto-state-migration.lock",
            label="Ditto credential vault",
        )

    copy_legacy_database_once(
        legacy_accounts,
        target_accounts,
        sidecar_suffixes=("-wal", "-journal"),
        lock_name=".ditto-state-migration.lock",
        label="Ditto account metadata",
    )


def copy_legacy_database_once(
    legacy: Path,
    target: Path,
    *,
    sidecar_suffixes: tuple[str, ...],
    lock_name: str,
    label: str,
    lock_dir: Path | None = None,
    timeout: float = 10.0,
) -> None:
    """Copy one legacy database family atomically enough for first-open use.

    Idempotent: an existing ``target`` always wins silently, and the legacy
    family is retained for rollback. Concurrent callers serialise on a file
    lock; a sibling completing the copy while this caller waits is treated as
    success.

    Args:
        legacy: Pre-workspace database file to copy from.
        target: Destination inside the active workspace.
        sidecar_suffixes: Sidecar suffixes copied alongside the main file,
            e.g. ``(".wal",)`` for DuckDB or ``("-wal", "-journal")`` for
            SQLite.
        lock_name: File name of the migration lock.
        label: Human-readable name used in log and error messages.
        lock_dir: Directory the migration lock is created in. ``None`` keeps
            the historical placement (``target.parent.parent``). Pass
            ``target.parent`` for targets directly under the workspace root so
            the lock never lands outside the workspace.
        timeout: Seconds to wait for the migration lock before failing.

    Raises:
        WorkspaceStateMigrationError: The copy could not be completed; the
            legacy source is retained.
    """
    candidate = target.with_name(f".{target.name}.migrating")
    sidecars = tuple(
        (
            Path(f"{legacy}{suffix}"),
            Path(f"{target}{suffix}"),
            Path(f"{candidate}{suffix}"),
        )
        for suffix in sidecar_suffixes
    )
    try:
        if target.exists() or not legacy.exists() or legacy.resolve() == target.resolve():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_base = lock_dir if lock_dir is not None else target.parent.parent
        lock = FileLock(lock_base / lock_name, timeout=timeout, mode=0o600)
        with lock.acquire():
            if target.exists() or not legacy.exists():
                return
            candidate.unlink(missing_ok=True)
            for _source, _destination, staged in sidecars:
                staged.unlink(missing_ok=True)
            shutil.copy2(legacy, candidate)
            candidate.chmod(0o600)
            for source, _destination, staged in sidecars:
                if source.exists():
                    shutil.copy2(source, staged)
                    staged.chmod(0o600)
            if target.exists():
                return
            for _source, destination, staged in sidecars:
                if staged.exists():
                    staged.replace(destination)
            candidate.replace(target)
            logger.info("Migrated legacy %s from %s to %s", label, legacy, target)
    except (FileLockTimeout, OSError) as exc:
        logger.error("Could not migrate legacy %s %s -> %s: %s", label, legacy, target, exc)
        raise WorkspaceStateMigrationError(
            f"Could not preserve legacy {label}; source retained at {legacy}"
        ) from exc
    finally:
        _remove_staged_file(candidate)
        for _source, _destination, staged in sidecars:
            _remove_staged_file(staged)


def copy_legacy_directory_once(
    legacy: Path,
    target: Path,
    *,
    lock_name: str,
    label: str,
    excluded_names: frozenset[str] = frozenset(),
    source_lock_name: str | None = None,
    conflict_is_error: bool = False,
    lock_dir: Path | None = None,
    timeout: float = 10.0,
) -> None:
    """Copy one legacy directory under migration and optional source locks.

    Idempotent: a target that already contains meaningful entries wins, and
    the legacy tree is retained. Because the copy retains its source, a target
    that already holds every legacy entry is a *completed* migration — this
    call's own, a sibling worker's, or an earlier boot's — and is never a
    conflict, whichever side of the migration lock it is observed from. Only a
    target that has *lost* legacy state is divergent.

    Args:
        legacy: Pre-workspace directory to copy from.
        target: Destination inside the active workspace.
        lock_name: File name of the migration lock.
        label: Human-readable name used in log and error messages.
        excluded_names: Entry names ignored both when copying and when judging
            whether a directory contains meaningful state.
        source_lock_name: Optional lock file inside ``legacy`` to hold during
            the copy, serialising against live writers of the source.
        conflict_is_error: When True, a populated target that does not already
            hold the legacy state raises instead of silently skipping.
        lock_dir: Directory the migration lock is created in. ``None`` keeps
            the historical placement (``target.parent.parent``). Pass
            ``target.parent`` for targets directly under the workspace root so
            the lock never lands outside the workspace.
        timeout: Seconds to wait for each lock before failing.

    Raises:
        WorkspaceStateMigrationError: The copy could not be completed, or a
            divergent target was found with ``conflict_is_error=True``; the
            legacy source is retained in both cases.
    """
    if not legacy.is_dir() or legacy.resolve() == target.resolve():
        return
    legacy_entries = _meaningful_directory_entries(legacy, excluded_names)
    if not legacy_entries:
        return
    if target.exists() and _meaningful_directory_entries(target, excluded_names):
        # How the two cases are told apart WITHOUT depending on arrival order —
        # a late worker cannot observe whether the target predates this boot:
        #
        #   Already migrated. The copy never moves, so a target produced from
        #   this legacy tree still holds every legacy entry, each target file
        #   being its legacy counterpart plus whatever the running app appended
        #   afterwards (the audit chain is append-only). Copying again would
        #   preserve nothing. This covers the winner's N-1 Gunicorn siblings
        #   that reach the pre-lock probe *after* the winner has finished, and
        #   equally every boot after the first.
        #
        #   Divergent. A legacy entry is absent from the target, or a target
        #   file has diverged from its legacy counterpart instead of extending
        #   it — so the target was not produced from this legacy tree and
        #   copying over it would destroy operator state. Under
        #   ``conflict_is_error`` that still raises, and both trees are kept.
        if _legacy_state_survives_in(legacy, target, excluded_names):
            logger.info("Legacy %s already present at %s; keeping the workspace copy", label, target)
            return
        if conflict_is_error:
            raise WorkspaceStateMigrationError(
                f"Legacy and workspace {label} directories both contain state; both were preserved"
            )
        return

    candidate = target.with_name(f".{target.name}.migrating")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_base = lock_dir if lock_dir is not None else target.parent.parent
        migration_lock = FileLock(lock_base / lock_name, timeout=timeout, mode=0o600)
        with ExitStack() as stack:
            stack.enter_context(migration_lock.acquire())
            if source_lock_name is not None:
                source_lock = FileLock(legacy / source_lock_name, timeout=timeout, mode=0o600)
                stack.enter_context(source_lock.acquire())
            if target.exists() and _meaningful_directory_entries(target, excluded_names):
                # The pre-lock check above saw no populated target, so anything
                # here now was written by a sibling process that won the
                # migration lock first (Gunicorn workers all probe at boot).
                # That is completion, not a conflict — even under
                # ``conflict_is_error``, which only guards *pre-existing*
                # divergent state.
                logger.info("Legacy %s already migrated to %s by a concurrent process", label, target)
                return
            shutil.rmtree(candidate, ignore_errors=True)
            shutil.copytree(
                legacy,
                candidate,
                ignore=lambda _directory, names: [name for name in names if name in excluded_names],
            )
            candidate.chmod(0o700)
            if target.exists():
                _drain_into_existing_target(candidate, target)
            else:
                candidate.replace(target)
            logger.info("Migrated legacy %s from %s to %s", label, legacy, target)
    except WorkspaceStateMigrationError:
        raise
    except (FileLockTimeout, OSError) as exc:
        logger.error("Could not migrate legacy %s %s -> %s: %s", label, legacy, target, exc)
        raise WorkspaceStateMigrationError(
            f"Could not preserve legacy {label}; source retained at {legacy}"
        ) from exc
    finally:
        shutil.rmtree(candidate, ignore_errors=True)


def _drain_into_existing_target(candidate: Path, target: Path) -> None:
    """Move the staged tree into a target directory that already exists.

    ``Path.replace`` cannot swap a directory in over a non-empty one, yet a
    target holding nothing but excluded entries — a runtime log directory, a
    source lock file, a strategy state directory — has already been judged
    empty of meaningful state and must still receive the migration. Entries
    are moved one at a time and an entry whose name is already present is left
    behind, so nothing in the target is ever overwritten.

    Args:
        candidate: The staged copy of the legacy tree, a sibling of ``target``.
        target: The existing destination directory.
    """
    for entry in candidate.iterdir():
        destination = target / entry.name
        if destination.exists():
            continue
        entry.replace(destination)
    try:
        target.chmod(0o700)
    except OSError:  # pragma: no cover - read-only filesystems, Windows ACLs
        logger.warning("Could not restrict permissions on migrated directory %s", target)


def _legacy_state_survives_in(legacy: Path, target: Path, excluded_names: frozenset[str]) -> bool:
    """Report whether every legacy entry is still readable inside the target.

    This is the copy-once idempotence test, not an equality test. Migration
    copies rather than moves, so a target derived from ``legacy`` keeps all of
    its entries for good; the running application only ever appends to them
    (the audit chain is append-only JSONL), which is why a target file counts
    as holding its legacy counterpart when it merely *starts with* it. A
    target that fails this test was not produced from ``legacy``, so copying
    over it would discard state the operator can still see.

    Args:
        legacy: Pre-workspace directory being migrated from.
        target: Destination directory inside the active workspace.
        excluded_names: Entry names ignored on both sides, matching the names
            the copy itself skips.

    Returns:
        True when nothing in ``legacy`` would be lost by leaving ``target``
        exactly as it is.
    """
    for entry in _meaningful_directory_entries(legacy, excluded_names):
        counterpart = target / entry.name
        if entry.is_dir():
            if not counterpart.is_dir() or not _legacy_state_survives_in(entry, counterpart, excluded_names):
                return False
        elif not counterpart.is_file() or not _file_starts_with(counterpart, entry):
            return False
    return True


def _file_starts_with(candidate: Path, prefix: Path, chunk_size: int = 1 << 16) -> bool:
    """Report whether ``candidate`` begins with the whole of ``prefix``.

    Streamed in chunks so a multi-gigabyte audit chain is never read into
    memory. An unreadable file is reported as *not* a continuation, keeping
    the caller on the conservative branch.

    Args:
        candidate: File that may extend ``prefix``.
        prefix: File whose bytes must appear at the start of ``candidate``.
        chunk_size: Bytes compared per read.

    Returns:
        True when ``candidate`` is ``prefix`` or an append-only extension.
    """
    try:
        if prefix.stat().st_size > candidate.stat().st_size:
            return False
        with prefix.open("rb") as prefix_stream, candidate.open("rb") as candidate_stream:
            while True:
                expected = prefix_stream.read(chunk_size)
                if not expected:
                    return True
                if candidate_stream.read(len(expected)) != expected:
                    return False
    except OSError:
        return False


def _meaningful_directory_entries(path: Path, excluded_names: frozenset[str]) -> list[Path]:
    if not path.is_dir():
        return []
    return [entry for entry in path.iterdir() if entry.name not in excluded_names]


def _remove_staged_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove staged workspace migration file %s", path)


def _lock_workspace_perms(p: Path) -> None:
    """Best-effort restrict workspace directory perms to owner-only.

    On Linux / macOS the workspace holds the master password, API key
    pepper, auth DB, credential DB, and DuckDB telemetry logs — any
    local user on a multi-tenant host could read them otherwise. POSIX
    ``chmod 0o700`` denies group/other access. Failure is non-fatal
    (read-only filesystems, Windows ACL paths). Pytest workspaces under
    ``/tmp`` benefit from this too without breaking the test runner.
    """
    try:
        p.chmod(0o700)
    except OSError:
        pass


class Workspace:
    """Central configuration for a FlintTrade installation.

    Manages ``workspace.json`` which stores all user preferences —
    storage paths, enabled modules, LLM config, notification settings, etc.
    """

    def __init__(self, home_dir: Path | None = None) -> None:
        if home_dir is not None:
            self._home = home_dir.expanduser().resolve()
        elif os.environ.get("FLINTTRADE_WORKSPACE_DIR"):
            self._home = workspace_dir().expanduser().resolve()
        elif os.environ.get("FLINTTRADE_HOME"):
            self._home = (home_dir or _default_home()).expanduser().resolve()
        else:
            self._home = workspace_dir().expanduser().resolve()
        self._config: dict[str, Any] = {}
        if self.config_path.exists():
            self._config = self.load()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def workspace_dir(self) -> Path:
        return self._home

    @property
    def config_path(self) -> Path:
        return self._home / "workspace.json"

    @property
    def fast_data_dir(self) -> Path:
        raw = self.get("storage.fast", _LEGACY_FAST_DATA_PATH)
        if raw == _LEGACY_FAST_DATA_PATH:
            return (self._home / "data").resolve()
        return Path(raw).expanduser().resolve()

    @property
    def archive_dir(self) -> Path:
        raw = self.get("storage.archive", _LEGACY_ARCHIVE_PATH)
        if raw == _LEGACY_ARCHIVE_PATH:
            return (self._home / "archive").resolve()
        return Path(raw).expanduser().resolve()

    @property
    def log_dir(self) -> Path:
        return self._home / "logs"

    @property
    def is_initialized(self) -> bool:
        return self.config_path.exists() and self._config.get("initialized", False)

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """Load workspace.json from disk and run schema migrations."""
        if not self.config_path.exists():
            self.initialise()
        try:
            self._config = run_migrations(self.workspace_dir)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load workspace.json: %s — using defaults", exc)
            # deepcopy: _DEFAULT_CONFIG contains nested dicts ("ui", "modules",
            # "storage", etc.). dict() does a shallow copy, so calls like
            # ws.set("ui.theme", "light") would mutate the SHARED nested dict
            # inside _DEFAULT_CONFIG itself — poisoning every subsequent
            # Workspace() that initialises from defaults. Surfaced in CI as
            # the test_get_dot_notation flake when pytest-randomly happened
            # to schedule test_set_and_persist first.
            self._config = copy.deepcopy(_DEFAULT_CONFIG)
        if self._config.get("version") != WORKSPACE_VERSION:
            raise RuntimeError(
                f"workspace not migrated to {WORKSPACE_VERSION}; got {self._config.get('version')!r}"
            )
        return self._config

    def save(self, config: dict[str, Any] | None = None) -> None:
        """Atomically replace workspace.json with a complete configuration."""
        if config is not None:
            self._config = copy.deepcopy(config)
        self._home.mkdir(parents=True, exist_ok=True)
        self._config = write_workspace_config(self.workspace_dir, self._config)

    def initialise(self, config: dict[str, Any] | None = None) -> None:
        """First-time setup — create dirs, write default config.

        deepcopy of ``_DEFAULT_CONFIG`` (not ``dict()``) because the default
        config contains nested dicts that later ``set()`` calls would mutate
        in place — sharing those mutations across every Workspace instance.
        """
        self._config = config or copy.deepcopy(_DEFAULT_CONFIG)
        self._config["initialized"] = True
        self.ensure_directories()
        self.save()
        logger.info("Workspace initialised at %s", self._home)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value using dot notation (e.g. 'storage.fast')."""
        parts = key.split(".")
        node: Any = self._config
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        """Set a value against the latest on-disk snapshot and persist atomically."""
        parts = key.split(".")

        def apply(config: dict[str, Any]) -> None:
            node = config
            for part in parts[:-1]:
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            node[parts[-1]] = value

        self._config = update_workspace_config(self.workspace_dir, apply)

    def update(
        self,
        updater: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> dict[str, Any]:
        """Apply one caller-owned mutation to the latest workspace transaction."""
        self._config = update_workspace_config(self.workspace_dir, updater)
        return copy.deepcopy(self._config)

    def ensure_directories(self) -> None:
        """Create all data directories if they don't exist."""
        for d in [self._home, self.fast_data_dir, self.archive_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of the current config."""
        return copy.deepcopy(self._config)
