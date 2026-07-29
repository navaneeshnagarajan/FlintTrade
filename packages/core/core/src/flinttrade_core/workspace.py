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
    _copy_legacy_database_once(
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
        _copy_legacy_database_once(
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
        _copy_legacy_database_once(
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
        _copy_legacy_directory_once(
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
        _copy_legacy_directory_once(
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
    if not os.environ.get("FLINTTRADE_HOME") and not os.environ.get("FLINTTRADE_WORKSPACE_DIR"):
        _copy_legacy_directory_once(
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
        _copy_legacy_database_once(
            legacy_vault,
            target_vault,
            sidecar_suffixes=("-wal", "-journal"),
            lock_name=".ditto-state-migration.lock",
            label="Ditto credential vault",
        )

    _copy_legacy_database_once(
        legacy_accounts,
        target_accounts,
        sidecar_suffixes=("-wal", "-journal"),
        lock_name=".ditto-state-migration.lock",
        label="Ditto account metadata",
    )


def _copy_legacy_database_once(
    legacy: Path,
    target: Path,
    *,
    sidecar_suffixes: tuple[str, ...],
    lock_name: str,
    label: str,
) -> None:
    """Copy one legacy database family atomically enough for first-open use."""
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
        lock = FileLock(target.parent.parent / lock_name, timeout=10, mode=0o600)
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


def _copy_legacy_directory_once(
    legacy: Path,
    target: Path,
    *,
    lock_name: str,
    label: str,
    excluded_names: frozenset[str] = frozenset(),
    source_lock_name: str | None = None,
    conflict_is_error: bool = False,
    lock_dir: Path | None = None,
) -> None:
    """Copy one legacy directory under migration and optional source locks.

    Args:
        legacy: Source directory from the pre-platform-workspace layout.
        target: Destination directory inside the platform workspace.
        lock_name: File name of the migration lock.
        label: Human-readable name used in log and error messages.
        excluded_names: Entry names ignored when comparing and copying.
        source_lock_name: Lock inside *legacy* held for the duration of the copy.
        conflict_is_error: Raise instead of returning when both sides hold state.
        lock_dir: Directory the migration lock lives in. Defaults to
            ``target.parent.parent``, which is inside the workspace for the
            nested ``data/*`` and ``archive/*`` targets; a target that sits
            directly under the workspace root must pass its own.
    """
    if not legacy.is_dir() or legacy.resolve() == target.resolve():
        return
    legacy_entries = _meaningful_directory_entries(legacy, excluded_names)
    if not legacy_entries:
        return
    if target.exists() and _meaningful_directory_entries(target, excluded_names):
        if conflict_is_error:
            raise WorkspaceStateMigrationError(
                f"Legacy and workspace {label} directories both contain state; both were preserved"
            )
        return

    candidate = target.with_name(f".{target.name}.migrating")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        migration_lock = FileLock((lock_dir or target.parent.parent) / lock_name, timeout=10, mode=0o600)
        with ExitStack() as stack:
            stack.enter_context(migration_lock.acquire())
            if source_lock_name is not None:
                source_lock = FileLock(legacy / source_lock_name, timeout=10, mode=0o600)
                stack.enter_context(source_lock.acquire())
            if target.exists() and _meaningful_directory_entries(target, excluded_names):
                if conflict_is_error:
                    raise WorkspaceStateMigrationError(
                        f"Legacy and workspace {label} directories both contain state; both were preserved"
                    )
                return
            shutil.rmtree(candidate, ignore_errors=True)
            shutil.copytree(
                legacy,
                candidate,
                ignore=lambda _directory, names: [name for name in names if name in excluded_names],
            )
            candidate.chmod(0o700)
            if target.exists():
                target.rmdir()
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
