"""workspace.json schema migration runner.

Owns the full transaction: lock acquisition, read, backup, migrate on a
deep copy, atomic persist, and lock release. On migration failure, the
on-disk workspace.json is restored from the backup before the exception
propagates. Concurrent migration attempts are blocked via a PID-tracked
.migration.lock acquired with O_EXCL; stale locks older than
STALE_LOCK_SECONDS with a dead owner pid are broken safely.
"""

from __future__ import annotations

import copy
import errno
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.workspace_migrations")

WORKSPACE_VERSION = "1.0.0"
STALE_LOCK_SECONDS = 600

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class MigrationLockError(RuntimeError):
    """Raised when migration cannot safely acquire .migration.lock."""


class AtomicWriteRetryExhaustedError(RuntimeError):
    """Raised when a transient atomic rename lock does not clear."""


def default_workspace_config(*, initialized: bool = False) -> dict[str, Any]:
    """Return a fresh workspace config at the current schema version."""
    return {
        "version": WORKSPACE_VERSION,
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
def _migration_lock(workspace_dir: Path) -> Iterator[None]:
    """Acquire workspace_dir/.migration.lock via O_EXCL."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    lock_path = workspace_dir / ".migration.lock"
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, f"{os.getpid()}\n{int(time.time())}\n".encode("utf-8"))
            finally:
                os.close(fd)
            break
        except FileExistsError as exc:
            holder_pid, holder_ts = _read_lock_metadata(lock_path)
            if holder_pid is None:
                _safe_unlink(lock_path)
                continue
            stale = (time.time() - holder_ts) > STALE_LOCK_SECONDS
            alive = _pid_alive(holder_pid)
            if stale and not alive:
                logger.warning("breaking stale migration lock (pid %s, age >%ds)", holder_pid, STALE_LOCK_SECONDS)
                _safe_unlink(lock_path)
                continue
            raise MigrationLockError(
                "another flinttrade process holds the migration lock\n"
                f"  lock file: {lock_path}\n"
                f"  pid: {holder_pid} (alive={alive})\n"
                "  stop the other process, then re-run.\n"
                "  if certain no other process is running, delete the lock:\n"
                f"    rm {lock_path}"
            ) from exc
    try:
        yield
    finally:
        _safe_unlink(lock_path)


def _read_lock_metadata(lock_path: Path) -> tuple[int | None, float]:
    try:
        lines = lock_path.read_text(encoding="utf-8").splitlines()
        return int(lines[0]), float(lines[1]) if len(lines) > 1 else 0.0
    except (FileNotFoundError, ValueError, IndexError):
        return None, 0.0


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _pid_alive(pid: int) -> bool:
    """Return True if pid exists, across POSIX and Windows."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


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
    cfg["version"] = WORKSPACE_VERSION
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
    "0.5.2": (WORKSPACE_VERSION, _migrate_052_to_100),
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
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        for attempt in range(3):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError as exc:
                if attempt == 2:
                    raise AtomicWriteRetryExhaustedError(str(path)) from exc
                time.sleep(0.05)
    except Exception:
        _safe_unlink(tmp_path)
        raise


def _assert_backup_safe(backup_path: Path) -> None:
    if not backup_path.exists():
        return
    try:
        json.loads(backup_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MigrationLockError(f"existing migration backup is corrupt: {backup_path}") from exc


def run_migrations(workspace_dir: Path) -> dict[str, Any]:
    """Read, migrate, and atomically write workspace.json.

    Missing workspace.json is treated as a fresh install: the current default
    config is written at WORKSPACE_VERSION and returned.
    """
    workspace_dir = workspace_dir.expanduser().resolve()
    workspace_path = workspace_dir / "workspace.json"

    with _migration_lock(workspace_dir):
        if not workspace_path.exists():
            cfg = default_workspace_config(initialized=True)
            _atomic_write(workspace_path, json.dumps(cfg, indent=2, sort_keys=True))
            return cfg

        on_disk_cfg = json.loads(workspace_path.read_text(encoding="utf-8"))
        current = on_disk_cfg.get("version", "0.1.0-alpha")

        if current == WORKSPACE_VERSION:
            return on_disk_cfg

        if current not in KNOWN_VERSIONS:
            raise ValueError(
                f"workspace.json declares version {current!r}, but this installation only "
                f"knows {sorted(KNOWN_VERSIONS)}. refusing to overwrite — this looks like a downgrade attempt."
            )

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
            _atomic_write(workspace_path, backup_path.read_text(encoding="utf-8"))
            logger.exception("migration failed — on-disk workspace.json restored from %s", backup_path)
            raise

        if cfg.get("version") != WORKSPACE_VERSION:
            raise RuntimeError(
                f"migration ran but workspace.json did not reach {WORKSPACE_VERSION}; "
                f"got {cfg.get('version')!r}. on-disk file unchanged."
            )

        _atomic_write(workspace_path, json.dumps(cfg, indent=2, sort_keys=True))
        return cfg
