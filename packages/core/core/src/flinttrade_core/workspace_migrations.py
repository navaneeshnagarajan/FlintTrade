"""workspace.json schema migration runner.

Owns the full transaction: lock acquisition, read, backup, migrate on a
deep copy, atomic persist, and lock release. On migration failure, the
on-disk workspace.json is restored from the backup before the exception
propagates. Concurrent migration attempts are serialised by a cross-process
kernel lock; stale lock-file contents cannot confer or revoke ownership.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import secrets
import stat
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from filelock import FileLock, Timeout as FileLockTimeout

from .secure_file import (
    PendingDurableUnlinkError,
    assert_hardened,
    cleanup_pending_unlink,
    durable_replace,
    durable_unlink,
    read_owner_owned_bytes,
    read_owner_owned_text,
)

logger = logging.getLogger("flinttrade.core.workspace_migrations")

WORKSPACE_VERSION = "1.3.0"
INT64_MAX = (1 << 63) - 1
_AUTHORITY_FIELDS = ("workspace_instance_id", "workspace_generation", "broker_authority_generation")
_LLM_API_KEY_REF = "secret://llm/api_key"
_LMSTUDIO_DEFAULT_HOSTS = {
    "",
    "http://127.0.0.1:1234",
    "http://localhost:1234",
}
_LMSTUDIO_SECRET_STAGE_PREFIX = ".llm_api_key.lmstudio-retirement."
_LMSTUDIO_RETIREMENT_JOURNAL = ".lmstudio-retirement.transaction.json"
_LMSTUDIO_RETIREMENT_JOURNAL_VERSION = 1
_LMSTUDIO_RETIREMENT_PHASES = {"prepared", "committed"}

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class MigrationLockError(RuntimeError):
    """Raised when migration cannot safely acquire .migration.lock."""


class AtomicWriteRetryExhaustedError(RuntimeError):
    """Raised when a transient atomic rename lock does not clear."""


class WorkspaceVersionConflict(RuntimeError):
    """The expected workspace incarnation/generation is no longer current."""


@dataclass(frozen=True)
class WorkspaceVersion:
    """Complete provenance for one persisted workspace revision."""

    instance_id: UUID
    generation: int


@dataclass(frozen=True)
class BrokerWorkspaceVersion:
    """Workspace incarnation and broker-only authority revision."""

    instance_id: UUID
    generation: int


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("workspace configuration keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("workspace configuration must contain JSON-compatible values")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class WorkspaceSnapshot:
    """Deeply immutable configuration and its conditional-write version."""

    config: Mapping[str, object]
    version: WorkspaceVersion | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", _freeze(dict(self.config)))

    def as_dict(self) -> dict[str, Any]:
        """Return a detached mutable configuration for an explicit edit."""
        return _thaw(self.config)


def _default_services() -> dict[str, Any]:
    return {"connection_epoch": 0, "connections": [], "routing": {}, "budgets": {}, "access_grants": {}}


def _validate_current(config: Any) -> None:
    if not isinstance(config, dict) or config.get("version") != WORKSPACE_VERSION:
        raise ValueError("workspace requires the current schema version")
    identity = config.get("workspace_instance_id")
    try:
        valid_identity = type(identity) is str and str(UUID(identity)) == identity
    except (ValueError, AttributeError):
        valid_identity = False
    if not valid_identity:
        raise ValueError("workspace_instance_id must be a canonical UUID")
    for field in ("workspace_generation", "broker_authority_generation"):
        value = config.get(field)
        if type(value) is not int or not 1 <= value <= INT64_MAX:
            raise ValueError(f"{field} must be an integer in 1..INT64_MAX")
    services = config.get("services")
    if type(services) is not dict:
        raise ValueError("workspace services must be an object")
    epoch = services.get("connection_epoch")
    if type(epoch) is not int or not 0 <= epoch <= INT64_MAX:
        raise ValueError("services.connection_epoch must be an integer in 0..INT64_MAX")
    for key, empty in _default_services().items():
        if type(services.get(key)) is not type(empty):
            raise ValueError(f"services.{key} has an invalid shape")


def _version(config: dict[str, Any]) -> WorkspaceVersion:
    return WorkspaceVersion(UUID(config["workspace_instance_id"]), config["workspace_generation"])


def broker_workspace_version(snapshot: WorkspaceSnapshot) -> BrokerWorkspaceVersion | None:
    """Return broker liveness authority without treating unrelated edits as revocation."""
    if snapshot.version is None:
        return None
    return BrokerWorkspaceVersion(snapshot.version.instance_id, snapshot.config["broker_authority_generation"])


def legacy_openalgo_broker_projection(config: Mapping[str, Any]) -> Any:
    """Return detached sensitive comparison material, never public metadata."""
    openalgo = copy.deepcopy(config.get("openalgo"))
    if isinstance(openalgo, dict):
        # This legacy location stores global Telegram metadata, not broker setup.
        openalgo.pop("telegram_username", None)
    return openalgo


def _broker_authority(config: dict[str, Any]) -> str:
    openalgo = legacy_openalgo_broker_projection(config)
    return json.dumps([config.get("brokers"), openalgo], sort_keys=True, allow_nan=False)


def _mint_authority(config: dict[str, Any]) -> None:
    if any(field in config for field in _AUTHORITY_FIELDS):
        raise ValueError("workspace authority fields are server-owned")
    config.update(workspace_instance_id=str(uuid4()), workspace_generation=1, broker_authority_generation=1)


def default_workspace_config(*, initialized: bool = False) -> dict[str, Any]:
    """Return a fresh workspace config at the current schema version."""
    return {
        "version": WORKSPACE_VERSION,
        "services": _default_services(),
        "initialized": initialized,
        "markets": [],
        "modules": {
            "terminal": True,
            "dashboard": True,
            "screener": True,
            "backtest": True,
            "ai": False,
            "ditto": False,
            "automation": False,
        },
        "storage": {
            "fast": "~/.flinttrade/data",
            "archive": "~/.flinttrade/archive",
        },
        "openalgo": {
            "host": "http://127.0.0.1:5000",
            "port": 5000,
            "ws_port": 8765,
        },
        "ui": {
            "theme": "dark",
            "default_exchange": "NSE",
            "timezone": "Asia/Kolkata",
        },
        "llm": {
            "provider": "",
            "host": "",
            "model": "",
            "api_key_ref": "",
        },
        "notifications": {
            "telegram_enabled": False,
            "telegram_bot_token_ref": "",
            "telegram_chat_id": "",
        },
        "sebi": {
            "max_ops_per_second": 10,
            "audit_retention_years": 5,
            "kill_switch_enabled": True,
        },
        "safety": _default_safety_config(),
        "brokers": {
            "registered": ["openalgo:default"],
            "account_acls": {},
            "execution": {"default": "openalgo:default"},
            "data": {
                "ticks": "openalgo:default",
                "historical": "openalgo:default",
                "option_chains": "openalgo:default",
                "quote": "openalgo:default",
                "global_indices": "",
            },
            "failover": {"enabled": False, "order": []},
            "cost_aware": {"enabled": False, "tasks": []},
        },
        "compliance": {
            "static_ip": "",
            "personal_use_mode": True,
            "ai_disclosure_banner": True,
        },
    }


@contextmanager
def _migration_lock(
    workspace_dir: Path,
    *,
    wait: bool = False,
    timeout: float = 10.0,
) -> Iterator[None]:
    """Acquire workspace_dir/.migration.lock through a kernel-backed lock."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    lock_path = workspace_dir / ".migration.lock"
    lock = FileLock(lock_path, timeout=max(0.0, timeout) if wait else 0, mode=0o600)
    try:
        with lock.acquire():
            yield
    except FileLockTimeout as exc:
        raise MigrationLockError(
            "another FlintTrade process holds the workspace migration lock\n"
            f"  lock file: {lock_path}\n"
            "  stop the other process or retry after it finishes"
        ) from exc


def read_workspace_snapshot(workspace_dir: Path) -> WorkspaceSnapshot:
    """Read and validate an immutable snapshot under the workspace process lock."""
    workspace_dir = workspace_dir.expanduser().resolve()
    with _migration_lock(workspace_dir, wait=True):
        if not (workspace_dir / "workspace.json").exists():
            return WorkspaceSnapshot(default_workspace_config(initialized=True), None)
        current = _run_migrations_locked(workspace_dir)
        return WorkspaceSnapshot(current, _version(current))


def _commit_update_locked(
    workspace_dir: Path,
    current: dict[str, Any] | None,
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> WorkspaceSnapshot:
    candidate = copy.deepcopy(current) if current is not None else default_workspace_config(initialized=True)
    updated = updater(candidate)
    if updated is not None:
        candidate = updated
    if not isinstance(candidate, dict) or candidate.get("version") != WORKSPACE_VERSION:
        raise ValueError("workspace updater must return the current-version configuration")
    if current is None:
        _mint_authority(candidate)
    else:
        for field in _AUTHORITY_FIELDS:
            if type(candidate.get(field)) is not type(current[field]) or candidate.get(field) != current[field]:
                raise ValueError("workspace authority fields are server-owned")
        _validate_current(candidate)
        # Snapshot validation is stricter than JSON encoding (for example,
        # JSON silently coerces integer mapping keys). Admit it before no-op
        # comparison or any authority change can become durable.
        WorkspaceSnapshot(candidate, _version(candidate))
        if json.dumps(candidate, sort_keys=True, allow_nan=False) == json.dumps(current, sort_keys=True, allow_nan=False):
            return WorkspaceSnapshot(current, _version(current))
        candidate["workspace_generation"] = current["workspace_generation"] + 1
        if _broker_authority(candidate) != _broker_authority(current):
            candidate["broker_authority_generation"] = current["broker_authority_generation"] + 1
    _validate_current(candidate)
    snapshot = WorkspaceSnapshot(candidate, _version(candidate))
    payload = json.dumps(snapshot.as_dict(), indent=2, sort_keys=True, allow_nan=False)
    _atomic_write(workspace_dir / "workspace.json", payload)
    return snapshot


def compare_and_swap_workspace(
    workspace_dir: Path,
    expected_version: WorkspaceVersion | None,
    updater: Callable[[dict[str, object]], dict[str, object] | None],
) -> WorkspaceSnapshot:
    """Commit only against the exact workspace version; None admits only absence."""
    if expected_version is not None and (
        type(expected_version) is not WorkspaceVersion
        or type(expected_version.instance_id) is not UUID
        or type(expected_version.generation) is not int
        or not 1 <= expected_version.generation <= INT64_MAX
    ):
        raise ValueError("expected version must contain an exact UUID and integer generation")
    workspace_dir = workspace_dir.expanduser().resolve()
    with _migration_lock(workspace_dir, wait=True):
        exists = (workspace_dir / "workspace.json").exists()
        if expected_version is None and exists:
            raise WorkspaceVersionConflict("workspace already exists")
        if expected_version is not None and not exists:
            raise WorkspaceVersionConflict("workspace no longer exists")
        current = json.loads((workspace_dir / "workspace.json").read_text(encoding="utf-8")) if exists else None
        if exists:
            if isinstance(current, dict) and isinstance(current.get("version"), str) and current["version"] in MIGRATIONS:
                raise WorkspaceVersionConflict("workspace schema changed")
            _validate_current(current)
        if current is not None and _version(current) != expected_version:
            raise WorkspaceVersionConflict("workspace version changed")
        return _commit_update_locked(workspace_dir, current, updater)


def write_workspace_config(
    workspace_dir: Path, config: dict[str, Any], *, expected_version: WorkspaceVersion | None,
) -> dict[str, Any]:
    """Conditionally replace a complete configuration with authority-owned counters."""
    return compare_and_swap_workspace(workspace_dir, expected_version, lambda _current: copy.deepcopy(config)).as_dict()


def update_workspace_config(
    workspace_dir: Path,
    updater: Callable[[dict[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    """Read-modify-write workspace.json atomically without stale-snapshot loss."""
    workspace_dir = workspace_dir.expanduser().resolve()
    with _migration_lock(workspace_dir, wait=True):
        current = _run_migrations_locked(workspace_dir) if (workspace_dir / "workspace.json").exists() else None
        return _commit_update_locked(workspace_dir, current, updater).as_dict()


def _safe_unlink(path: Path) -> None:
    durable_unlink(path)


def _durable_replace(source: Path, destination: Path) -> None:
    durable_replace(source, destination)


def _migrate_010_to_050(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg["version"] = "0.5.0"
    return cfg


def _migrate_050_to_052(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg["version"] = "0.5.2"
    return cfg


def _migrate_052_to_100(cfg: dict[str, Any]) -> dict[str, Any]:
    brokers_default = {
        "registered": ["openalgo:default"],
        "account_acls": {},
        "execution": {"default": "openalgo:default"},
        "data": {
            "ticks": "openalgo:default",
            "historical": "openalgo:default",
            "option_chains": "openalgo:default",
            "quote": "openalgo:default",
            "global_indices": "",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }
    compliance_default = {
        "static_ip": "",
        "personal_use_mode": True,
        "ai_disclosure_banner": True,
    }
    cfg["brokers"] = _merge_defaults(brokers_default, cfg.get("brokers") or {})
    cfg["compliance"] = _merge_defaults(compliance_default, cfg.get("compliance") or {})
    cfg["version"] = "1.0.0"
    return cfg


def _default_safety_config() -> dict[str, Any]:
    return {
        "price_deviation_pct": 5.0,
        "qty_limits": {
            "NSE": 50_000,
            "BSE": 50_000,
            "NFO": 5_000,
            "BFO": 5_000,
            "MCX": 1_000,
            "CDS": 10_000,
            "BCD": 10_000,
            "NCDEX": 5_000,
            "NCO": 5_000,
        },
        "max_positions": 5,
        "max_margin_pct": 60.0,
        "max_net_delta": 500.0,
        "max_net_vega": 10_000.0,
        "pnl_pause_pct": 3.0,
        "pnl_kill_pct": 15.0,
        "check_market_hours": True,
    }


def _migrate_100_to_110(cfg: dict[str, Any]) -> dict[str, Any]:
    existing = cfg.get("safety")
    if existing is not None and not isinstance(existing, dict):
        raise ValueError("workspace safety configuration must be an object")
    cfg["safety"] = _merge_defaults(_default_safety_config(), existing or {})
    cfg["version"] = "1.1.0"
    return cfg


def _normalise_lmstudio_destination(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return raw.rstrip("/")
    if not parsed.scheme or parsed.hostname is None:
        return raw.rstrip("/")

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    userinfo = parsed.netloc.rpartition("@")[0] + "@" if "@" in parsed.netloc else ""
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = f"{userinfo}{hostname}{f':{port}' if port is not None and not default_port else ''}"
    return urlunsplit(
        (
            scheme,
            netloc,
            parsed.path.rstrip("/"),
            parsed.query,
            parsed.fragment,
        )
    )


def _lmstudio_secret_is_bound(cfg: dict[str, Any]) -> bool:
    llm = cfg.get("llm")
    if not isinstance(llm, dict):
        return False
    host = _normalise_lmstudio_destination(llm.get("host"))
    destination = _normalise_lmstudio_destination(llm.get("api_key_destination"))
    if not (
        str(llm.get("provider") or "").strip().lower() == "lmstudio"
        and llm.get("api_key_ref") == _LLM_API_KEY_REF
    ):
        return False
    key_provider = str(llm.get("api_key_provider") or "").strip().lower()
    if not key_provider and not destination:
        return True
    destination_matches = destination == host or (
        host in _LMSTUDIO_DEFAULT_HOSTS and destination in _LMSTUDIO_DEFAULT_HOSTS
    )
    return bool(
        key_provider == "lmstudio"
        and destination
        and destination_matches
    )


def _migrate_110_to_120(cfg: dict[str, Any]) -> dict[str, Any]:
    llm = cfg.get("llm")
    if llm is not None and not isinstance(llm, dict):
        raise ValueError("workspace LLM configuration must be an object")
    if isinstance(llm, dict) and str(llm.get("provider") or "").strip().lower() == "lmstudio":
        llm["provider"] = "ollama"
        llm["host"] = ""
        llm["api_key_ref"] = ""
        llm["api_key_provider"] = ""
        llm["api_key_destination"] = ""
    cfg["version"] = "1.2.0"
    return cfg


def _migrate_120_to_130(cfg: dict[str, Any]) -> dict[str, Any]:
    services = cfg.get("services", {})
    if type(services) is not dict:
        raise ValueError("legacy services must be an object")
    services = copy.deepcopy(services)
    for key, empty in _default_services().items():
        if key in services and (type(services[key]) is not type(empty) or services[key] != empty):
            raise ValueError(f"legacy services.{key} collides with reserved schema")
        services[key] = empty
    _mint_authority(cfg)
    cfg["services"] = services
    cfg["version"] = "1.3.0"
    return cfg


def _merge_defaults(defaults: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge defaults with existing values winning."""
    out = copy.deepcopy(defaults)
    for key, value in existing.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_defaults(out[key], value)
        else:
            out[key] = value
    return out


MIGRATIONS: dict[str, tuple[str, Migration]] = {
    "0.1.0-alpha": ("0.5.0", _migrate_010_to_050),
    "0.5.0": ("0.5.2", _migrate_050_to_052),
    "0.5.2": ("1.0.0", _migrate_052_to_100),
    "1.0.0": ("1.1.0", _migrate_100_to_110),
    "1.1.0": ("1.2.0", _migrate_110_to_120),
    "1.2.0": ("1.3.0", _migrate_120_to_130),
}

KNOWN_VERSIONS: set[str] = {WORKSPACE_VERSION, *MIGRATIONS.keys()}


def _atomic_write(path: Path, content: str | bytes) -> None:
    """Write atomically on the same volume: tmp -> fsync -> rename.

    Windows AV / file-indexer caveat (LO19): when an antivirus scanner or
    Windows Search Indexer holds an open handle on the target file at the
    exact moment os.replace() runs, the atomic rename can fail with
    PermissionError. _atomic_write retries the rename up to 3 times with
    50 ms backoff to handle this transient lock. On persistent failure it
    raises AtomicWriteRetryExhaustedError with the target path so the
    caller's transactional rollback can restore from backup. Same-volume
    atomicity only; callers must keep tmp and target in the same directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        try:
            remaining = memoryview(data)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("atomic workspace write made no progress")
                remaining = remaining[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        for attempt in range(3):
            try:
                _durable_replace(tmp_path, path)
            except PermissionError as exc:
                if attempt == 2:
                    raise AtomicWriteRetryExhaustedError(str(path)) from exc
                time.sleep(0.05)
            else:
                return
    except Exception:
        _safe_unlink(tmp_path)
        raise


def _assert_backup_safe(backup_path: Path) -> None:
    if not backup_path.exists() and not backup_path.is_symlink():
        return
    try:
        payload = read_owner_owned_text(backup_path, max_bytes=16 * 1024 * 1024)
        json.loads(payload)
        if not assert_hardened(backup_path)[0]:
            # Replace safely rather than chmod a caller-swappable pathname.
            _atomic_write(backup_path, payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationLockError(f"existing migration backup is corrupt: {backup_path}") from exc


def _protect_legacy_backups(workspace_dir: Path) -> None:
    allowed = {f"workspace.{version}.bak.json" for version in MIGRATIONS}
    for path in workspace_dir.glob("workspace.*.bak.json"):
        if path.name == "workspace.brokers.bak.json":
            continue  # Separate legacy broker-config rollback owner.
        if path.name not in allowed:
            raise MigrationLockError("unrecognised workspace rollback filename")
        _assert_backup_safe(path)


def _path_is_reparse(path_stat: os.stat_result) -> bool:
    reparse_mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_mask and getattr(path_stat, "st_file_attributes", 0) & reparse_mask)


def _retirement_journal_path(workspace_dir: Path) -> Path:
    return workspace_dir / _LMSTUDIO_RETIREMENT_JOURNAL


def _inspect_retirement_file(path: Path) -> dict[str, int | str]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise MigrationLockError("LM Studio staged secret identity could not be inspected") from exc
    if stat.S_ISLNK(before.st_mode) or _path_is_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise MigrationLockError("LM Studio staged secret identity is unsafe")
    try:
        payload = read_owner_owned_bytes(path)
        after = path.lstat()
    except OSError as exc:
        raise MigrationLockError("LM Studio staged secret identity could not be verified") from exc
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise MigrationLockError("LM Studio staged secret identity changed during inspection")
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "st_dev": after.st_dev,
        "st_ino": after.st_ino,
        "st_uid": after.st_uid,
        "size": after.st_size,
    }


def _retirement_paths(
    workspace_dir: Path,
    journal: dict[str, Any],
) -> tuple[Path, Path, Path]:
    secret_dir = workspace_dir / "secrets"
    return (
        secret_dir / str(journal["secret_name"]),
        secret_dir / str(journal["staged_name"]),
        _retirement_journal_path(workspace_dir),
    )


def _read_lmstudio_retirement_journal(workspace_dir: Path) -> dict[str, Any] | None:
    journal_path = _retirement_journal_path(workspace_dir)
    cleanup_pending_unlink(journal_path)
    try:
        journal = json.loads(read_owner_owned_text(journal_path, max_bytes=16 * 1024))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise MigrationLockError("LM Studio retirement journal is unreadable") from exc

    integer_fields = ("st_dev", "st_ino", "st_uid", "size")
    staged_name = journal.get("staged_name") if isinstance(journal, dict) else None
    if (
        not isinstance(journal, dict)
        or journal.get("version") != _LMSTUDIO_RETIREMENT_JOURNAL_VERSION
        or journal.get("phase") not in _LMSTUDIO_RETIREMENT_PHASES
        or journal.get("secret_name") != "llm_api_key"
        or not isinstance(staged_name, str)
        or Path(staged_name).name != staged_name
        or not staged_name.startswith(_LMSTUDIO_SECRET_STAGE_PREFIX)
        or not isinstance(journal.get("sha256"), str)
        or len(journal["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in journal["sha256"])
        or any(type(journal.get(field)) is not int for field in integer_fields)
        or journal["size"] < 0
    ):
        raise MigrationLockError("LM Studio retirement journal is invalid")
    return journal


def _assert_retirement_identity(path: Path, journal: dict[str, Any]) -> None:
    identity = _inspect_retirement_file(path)
    for field in ("sha256", "st_dev", "st_ino", "st_uid", "size"):
        if identity[field] != journal[field]:
            raise MigrationLockError("LM Studio staged secret identity does not match its journal")


def _path_exists_without_following(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _stage_lmstudio_secret_deletion(workspace_dir: Path) -> dict[str, Any] | None:
    secret_dir = workspace_dir / "secrets"
    secret_path = secret_dir / "llm_api_key"
    try:
        directory_stat = secret_dir.lstat()
    except FileNotFoundError:
        return None
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or _path_is_reparse(directory_stat)
        or not stat.S_ISDIR(directory_stat.st_mode)
    ):
        raise MigrationLockError("LM Studio secret directory is unsafe")
    try:
        secret_path.lstat()
    except FileNotFoundError:
        return None
    identity = _inspect_retirement_file(secret_path)

    for _ in range(8):
        staged_name = f"{_LMSTUDIO_SECRET_STAGE_PREFIX}{secrets.token_hex(16)}"
        staged_path = secret_dir / staged_name
        if not _path_exists_without_following(staged_path):
            break
    else:  # pragma: no cover - cryptographic-name collisions are not practical
        raise MigrationLockError("LM Studio staged secret name could not be allocated")

    journal: dict[str, Any] = {
        "version": _LMSTUDIO_RETIREMENT_JOURNAL_VERSION,
        "phase": "prepared",
        "secret_name": secret_path.name,
        "staged_name": staged_name,
        **identity,
    }
    journal_path = _retirement_journal_path(workspace_dir)
    _atomic_write(journal_path, json.dumps(journal, sort_keys=True))
    try:
        _durable_replace(secret_path, staged_path)
        _assert_retirement_identity(staged_path, journal)
    except Exception:
        rollback_error: Exception | None = None
        try:
            if _path_exists_without_following(staged_path) and not _path_exists_without_following(secret_path):
                _durable_replace(staged_path, secret_path)
            _safe_unlink(journal_path)
        except Exception as exc:  # noqa: BLE001 - preserve proof for startup recovery
            rollback_error = exc
        if rollback_error is not None:
            raise RuntimeError("LM Studio secret staging rollback could not be completed") from rollback_error
        raise
    return journal


def _restore_staged_secret(workspace_dir: Path, journal: dict[str, Any] | None) -> None:
    if journal is None:
        return
    secret_path, staged_path, journal_path = _retirement_paths(workspace_dir, journal)
    secret_exists = _path_exists_without_following(secret_path)
    staged_exists = _path_exists_without_following(staged_path)
    if secret_exists and staged_exists:
        raise MigrationLockError("LM Studio staged secret ownership is ambiguous")
    if staged_exists:
        _assert_retirement_identity(staged_path, journal)
        _durable_replace(staged_path, secret_path)
    elif secret_exists:
        _assert_retirement_identity(secret_path, journal)
    else:
        raise MigrationLockError("LM Studio staged secret cannot be restored")
    _safe_unlink(journal_path)


def _mark_lmstudio_retirement_committed(
    workspace_dir: Path,
    journal: dict[str, Any],
) -> None:
    committed = copy.deepcopy(journal)
    committed["phase"] = "committed"
    _atomic_write(
        _retirement_journal_path(workspace_dir),
        json.dumps(committed, sort_keys=True),
    )


def _rollback_lmstudio_migration(
    workspace_dir: Path,
    workspace_path: Path,
    backup_path: Path,
    migrated: dict[str, Any],
    journal: dict[str, Any] | None,
) -> None:
    current_on_disk = json.loads(workspace_path.read_text(encoding="utf-8"))
    if current_on_disk == migrated:
        _atomic_write(workspace_path, backup_path.read_text(encoding="utf-8"))
    _restore_staged_secret(workspace_dir, journal)


def _lmstudio_retirement_is_committed(cfg: dict[str, Any]) -> bool:
    llm = cfg.get("llm")
    return bool(
        isinstance(llm, dict)
        and str(llm.get("provider") or "").strip().lower() == "ollama"
        and not str(llm.get("host") or "").strip()
        and not str(llm.get("api_key_ref") or "").strip()
        and not str(llm.get("api_key_provider") or "").strip()
        and not str(llm.get("api_key_destination") or "").strip()
    )


def _recover_staged_lmstudio_secret(workspace_dir: Path, cfg: dict[str, Any]) -> None:
    """Recover only the exact secret identity recorded by this migration."""
    journal = _read_lmstudio_retirement_journal(workspace_dir)
    if journal is None:
        return
    secret_path, staged_path, journal_path = _retirement_paths(workspace_dir, journal)
    cleanup_pending_unlink(secret_path)
    cleanup_pending_unlink(staged_path)
    secret_exists = _path_exists_without_following(secret_path)
    staged_exists = _path_exists_without_following(staged_path)
    if secret_exists and staged_exists:
        raise MigrationLockError("LM Studio staged secret ownership is ambiguous")
    if staged_exists:
        _assert_retirement_identity(staged_path, journal)
    elif secret_exists:
        _assert_retirement_identity(secret_path, journal)

    if _lmstudio_secret_is_bound(cfg):
        if staged_exists:
            _durable_replace(staged_path, secret_path)
        elif not secret_exists:
            raise MigrationLockError("LM Studio staged secret cannot be safely restored")
        _safe_unlink(journal_path)
        return

    if not _lmstudio_retirement_is_committed(cfg):
        raise MigrationLockError("LM Studio staged secret retirement cannot be verified")
    if staged_exists:
        _safe_unlink(staged_path)
    elif secret_exists:
        _safe_unlink(secret_path)
    _safe_unlink(journal_path)


def run_migrations(workspace_dir: Path) -> dict[str, Any]:
    """Read, migrate, and atomically persist under the workspace process lock."""
    workspace_dir = workspace_dir.expanduser().resolve()
    with _migration_lock(workspace_dir, wait=True):
        return _run_migrations_locked(workspace_dir)


def _run_migrations_locked(workspace_dir: Path) -> dict[str, Any]:
    """Migration transaction; the caller already owns the cross-process lock."""
    workspace_path = workspace_dir / "workspace.json"
    if not workspace_path.exists():
        return _commit_update_locked(workspace_dir, None, lambda _config: None).as_dict()

    on_disk_cfg = json.loads(workspace_path.read_text(encoding="utf-8"))
    if not isinstance(on_disk_cfg, dict):
        raise ValueError("workspace must be a JSON object")
    current = on_disk_cfg.get("version", "0.1.0-alpha")
    if not isinstance(current, str) or current not in KNOWN_VERSIONS:
        raise ValueError(
            f"workspace.json declares version {current!r}, but this installation only "
            f"knows {sorted(KNOWN_VERSIONS)}. refusing to overwrite — this looks like a downgrade attempt."
        )

    if current == WORKSPACE_VERSION:
        _validate_current(on_disk_cfg)
        _protect_legacy_backups(workspace_dir)
        _recover_staged_lmstudio_secret(workspace_dir, on_disk_cfg)
        return on_disk_cfg

    _protect_legacy_backups(workspace_dir)
    _recover_staged_lmstudio_secret(workspace_dir, on_disk_cfg)

    backup_path = workspace_dir / f"workspace.{current}.bak.json"
    _assert_backup_safe(backup_path)
    _atomic_write(backup_path, json.dumps(on_disk_cfg, indent=2, sort_keys=True))
    logger.info("workspace backup written: %s", backup_path)

    cfg = copy.deepcopy(on_disk_cfg)
    try:
        while current != WORKSPACE_VERSION:
            if current not in MIGRATIONS:
                raise ValueError(f"no migration registered from {current} to {WORKSPACE_VERSION}")
            next_version, fn = MIGRATIONS[current]
            cfg = fn(cfg)
            current = next_version
            logger.info("workspace migrated to %s", current)
    except Exception:
        logger.exception("migration failed — on-disk workspace.json unchanged")
        raise

    if cfg.get("version") != WORKSPACE_VERSION:
        raise RuntimeError(
            f"migration ran but workspace.json did not reach {WORKSPACE_VERSION}; "
            f"got {cfg.get('version')!r}. on-disk file unchanged."
        )

    _validate_current(cfg)
    staged_secret = (
        _stage_lmstudio_secret_deletion(workspace_dir)
        if _lmstudio_secret_is_bound(on_disk_cfg)
        else None
    )
    try:
        _atomic_write(workspace_path, json.dumps(cfg, indent=2, sort_keys=True))
        if staged_secret is not None:
            _mark_lmstudio_retirement_committed(workspace_dir, staged_secret)
    except Exception:
        rollback_error: Exception | None = None
        try:
            _rollback_lmstudio_migration(
                workspace_dir,
                workspace_path,
                backup_path,
                cfg,
                staged_secret,
            )
        except Exception as exc:  # noqa: BLE001 - surface an unproven transaction
            rollback_error = exc
        if rollback_error is not None:
            raise RuntimeError("workspace migration rollback could not be completed") from rollback_error
        raise

    if staged_secret is not None:
        _, staged_path, journal_path = _retirement_paths(workspace_dir, staged_secret)
        _assert_retirement_identity(staged_path, staged_secret)
        try:
            _safe_unlink(staged_path)
        except PendingDurableUnlinkError as exc:
            raise RuntimeError(
                "workspace migration committed; staged secret cleanup is pending"
            ) from exc
        except Exception:
            rollback_error = None
            try:
                _rollback_lmstudio_migration(
                    workspace_dir,
                    workspace_path,
                    backup_path,
                    cfg,
                    staged_secret,
                )
            except Exception as exc:  # noqa: BLE001 - surface an unproven transaction
                rollback_error = exc
            if rollback_error is not None:
                raise RuntimeError("workspace migration rollback could not be completed") from rollback_error
            raise
        _safe_unlink(journal_path)
    return cfg
