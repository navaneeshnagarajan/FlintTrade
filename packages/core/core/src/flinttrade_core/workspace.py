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
import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

from .workspace_migrations import WORKSPACE_VERSION, default_workspace_config, run_migrations

logger = logging.getLogger("flinttrade.core.workspace")

_DEFAULT_CONFIG: dict[str, Any] = default_workspace_config()


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
        self._uses_explicit_home = bool(
            home_dir is not None
            or os.environ.get("FLINTTRADE_HOME")
            or os.environ.get("FLINTTRADE_WORKSPACE_DIR")
        )
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
        raw = self.get("storage.fast", "~/.flinttrade/data")
        if self._uses_explicit_home and raw.startswith("~/.flinttrade/"):
            return (self._home / raw.removeprefix("~/.flinttrade/")).resolve()
        return Path(raw).expanduser().resolve()

    @property
    def archive_dir(self) -> Path:
        raw = self.get("storage.archive", "~/.flinttrade/archive")
        if self._uses_explicit_home and raw.startswith("~/.flinttrade/"):
            return (self._home / raw.removeprefix("~/.flinttrade/")).resolve()
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
        """Write workspace.json (pretty JSON, sorted keys)."""
        if config is not None:
            self._config = config
        self._home.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, sort_keys=True)

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
        """Set a config value using dot notation and save."""
        parts = key.split(".")
        node = self._config
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        self.save()

    def ensure_directories(self) -> None:
        """Create all data directories if they don't exist."""
        for d in [self._home, self.fast_data_dir, self.archive_dir, self.log_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of the current config."""
        return dict(self._config)
