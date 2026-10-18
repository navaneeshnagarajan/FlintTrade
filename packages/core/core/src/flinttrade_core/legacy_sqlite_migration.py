"""Offline migration-only publication protocol; never a runtime store owner.

Callers supply their real schema/reader validation and archive codec. The shared
workspace maintenance lease is held through snapshot, publication and archival.
A receipt is durable before publication, so an interrupted archive is resumed,
not mistaken for a fresh installation. No existing destination is overwritten.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path
from typing import Any

from flinttrade_core.secure_file import harden, harden_directory


class MigrationRefused(RuntimeError):
    """Source/destination evidence cannot authorise this migration."""


class ArchivePending(MigrationRefused):
    """Destination published; retain evidence and retry archival, not copying."""


def require_regular(path: Path) -> None:
    """Refuse links and non-files rather than following migration artefacts."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise MigrationRefused("unsafe migration file")


def file_digest(path: Path) -> str:
    require_regular(path)
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fsync_directory(path: Path) -> None:
    """Fail closed where directory durability cannot be established."""
    if not hasattr(os, "O_DIRECTORY"):
        raise MigrationRefused("durable directory publication unsupported on this platform")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def private_directory(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise MigrationRefused("unsafe migration directory")
    if not path.exists():
        path.mkdir(mode=0o700)
        harden_directory(path)
        fsync_directory(path.parent)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    """Replace only our durable receipt; never use replace for data publication."""
    require_regular(path)
    tmp = path.with_name(path.name + ".tmp")
    require_regular(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    harden(tmp)
    os.replace(tmp, path)
    fsync_directory(path.parent)


def publish_noreplace(source: Path, target: Path) -> None:
    """Atomic same-filesystem publication with no overwrite race.

    A hard link is the portable POSIX no-replace rename primitive. The staging
    name stays until the receipt is committed; retries recognise identical data.
    """
    require_regular(source)
    require_regular(target)
    os.link(source, target)
    fsync_directory(target.parent)


def sqlite_connection(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """Never allow a validator to create or quarantine a missing/broken DB."""
    require_regular(path)
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(path.absolute().as_uri() + f"?mode={mode}", uri=True)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _typed(value: Any) -> list[Any]:
    if value is None:
        return ["null"]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MigrationRefused("non-finite migration value")
        return ["real", value.hex()]
    if type(value) is int:
        return ["integer", value]
    if isinstance(value, str):
        return ["text", value]
    raise MigrationRefused("unsupported migration value type")


def rows_digest(rows: list[tuple]) -> str:
    """Compare every value, null and duplicate, independent of query ordering."""
    encoded = sorted(json.dumps([_typed(v) for v in row], ensure_ascii=True) for row in rows)
    return hashlib.sha256(json.dumps(encoded).encode()).hexdigest()


def database_digest(path: Path) -> str:
    """Logical identity survives harmless reader WAL/checkpoint changes."""
    with closing(sqlite_connection(path, readonly=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise MigrationRefused("SQLite integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise MigrationRefused("SQLite relationships invalid")
        schema = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
        tables = [r[1] for r in schema if r[0] == "table"]
        contents = [(table, rows_digest(conn.execute(f'SELECT * FROM "{table.replace(chr(34), chr(34)*2)}"')
                                       .fetchall())) for table in tables]
        return rows_digest(schema + contents)


def seal_database(path: Path) -> None:
    """Flush the complete DB out of WAL before publishing its single file."""
    with closing(sqlite_connection(path)) as conn:
        conn.execute("PRAGMA synchronous=FULL")
        if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
            raise MigrationRefused("SQLite checkpoint busy")
        if conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise MigrationRefused("SQLite journal still active")
    harden(path)
    fsync_file(path)
    fsync_directory(path.parent)


def sqlite_value(value: Any, affinity: str) -> Any:
    """Only lossless explicit conversions; never truncate quantities/nulls."""
    if value is None:
        return None
    if affinity == "TEXT":
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, str):
            return value
    elif affinity == "BLOB" and isinstance(value, bytes):
        return value
    elif affinity == "INTEGER" and type(value) in (int, float):
        if math.isfinite(value) and int(value) == value and -(2**63) <= value < 2**63:
            return int(value)
    elif affinity == "REAL" and type(value) in (int, float):
        if math.isfinite(value) and float(value) == value:
            return float(value)
    raise MigrationRefused("unrepresentable migration value")


def copy_source(source: Path, target: Path, expected: str) -> None:
    shutil.copyfile(source, target)
    harden(target)
    fsync_file(target)
    if file_digest(target) != expected or file_digest(source) != expected:
        raise MigrationRefused("source changed during snapshot")


def archive_plain(source: Path | None, archive: Path, expected: str | None) -> None:
    """Retain exact source bytes; never truncate a purported secure deletion."""
    if source is not None:
        if file_digest(source) != expected:
            raise MigrationRefused("source changed before archival")
        if not archive.exists():
            publish_noreplace(source, archive)
    if file_digest(archive) != expected:
        raise MigrationRefused("archive does not match source")
    harden(archive)
    fsync_file(archive)
    fsync_directory(archive.parent)


def _source_unchanged(source: Path, expected: str | None, *, allow_missing: bool = False) -> None:
    require_regular(source)
    for suffix in (".wal", "-wal", "-shm", "-journal"):
        if source.with_name(source.name + suffix).exists():
            raise MigrationRefused("legacy sidecar present; stop/checkpoint its owner before migration")
    if expected is None:
        if source.exists():
            raise MigrationRefused("unexpected source appeared")
    elif not source.exists():
        if not allow_missing:
            raise MigrationRefused("recorded source missing")
    elif file_digest(source) != expected:
        raise MigrationRefused("recorded source changed")


def migrate_database(
    workspace: Path,
    *,
    source_name: str,
    destination_name: str,
    build: Callable[[Path | None, Path], None],
    validate: Callable[[Path | None, Path], None],
    archive_codec: Callable[[Path | None, Path, str | None], None] = archive_plain,
    archive_suffix: str = "",
) -> Path:
    """Publish and archive under the SAME backend-cooperating maintenance lease."""
    from flinttrade_core.workspace_maintenance import acquire_workspace_maintenance  # noqa: PLC0415

    workspace = workspace.expanduser().absolute()
    if any(p.is_symlink() for p in (workspace, *workspace.parents)):
        raise MigrationRefused("symlinked workspace refused")
    with acquire_workspace_maintenance(workspace), ExitStack() as stack:
        source = workspace / source_name
        require_regular(source)
        if source.exists():
            import duckdb  # noqa: PLC0415

            # Also fence standalone legacy writers that predate backend leases.
            # Hold the real engine read lock through publication and archival.
            stack.enter_context(closing(duckdb.connect(str(source), read_only=True, config={"threads": 1})))
        return _migrate_locked(workspace, source_name, destination_name, build, validate, archive_codec, archive_suffix)


def _migrate_locked(workspace, source_name, destination_name, build, validate, archive_codec, archive_suffix):
    source, target = workspace / source_name, workspace / destination_name
    receipt = workspace / f".{destination_name}.migration.json"
    for path in (source, target, receipt):
        require_regular(path)
    if receipt.exists():
        try:
            state = json.loads(receipt.read_text())
            valid = (state["version"] == 1 and state["source"] == source_name
                     and state["destination"] == destination_name
                     and re.fullmatch(r"[0-9a-f]{32}", state["id"])
                     and state["phase"] in {"preparing", "prepared", "published", "archived", "complete"}
                     and (state["source_digest"] is None or re.fullmatch(r"[0-9a-f]{64}", state["source_digest"])))
            if not valid:
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise MigrationRefused("invalid migration receipt; manual reconciliation required") from exc
    else:
        artefacts = [workspace / (destination_name + suffix) for suffix in (".new", "-wal", "-shm", "-journal")]
        artefacts.extend((workspace / ".migration-tmp", receipt.with_name(receipt.name + ".tmp")))
        if target.exists() or any(p.exists() for p in artefacts):
            raise MigrationRefused("unowned destination/staging state; manual reconciliation required")
        archive_root = workspace / "archive" / "migrations"
        if archive_root.exists() and any(archive_root.rglob(source_name + "*")):
            raise MigrationRefused("archive without receipt; manual reconciliation required")
        digest = file_digest(source) if source.exists() else None
        _source_unchanged(source, digest)
        state = {"version": 1, "id": uuid.uuid4().hex, "source": source_name, "destination": destination_name,
                 "source_digest": digest, "phase": "preparing"}
        _write_state(receipt, state)
    stage_dir = workspace / (".migration-" + state["id"])
    private_directory(stage_dir)
    snapshot, staged = stage_dir / "source.duckdb", stage_dir / "target.sqlite"
    expected = state["source_digest"]
    try:
        if state["phase"] == "preparing":
            if target.exists():
                raise MigrationRefused("unverified destination exists")
            _source_unchanged(source, expected)
            # Only this receipt's private staging may be discarded. Never a public DB.
            for child in stage_dir.iterdir():
                require_regular(child)
                child.unlink()
            if expected is not None:
                copy_source(source, snapshot, expected)
            build(snapshot if expected else None, staged)
            validate(snapshot if expected else None, staged)
            with closing(sqlite_connection(staged)) as conn:
                conn.execute("CREATE TABLE _migration_receipt (id TEXT PRIMARY KEY, source_digest TEXT)")
                conn.execute("INSERT INTO _migration_receipt VALUES (?, ?)", (state["id"], expected))
                conn.commit()
            seal_database(staged)
            state.update(phase="prepared", target_digest=database_digest(staged))
            _write_state(receipt, state)
        if state["phase"] == "prepared":
            _source_unchanged(source, expected)
            if not target.exists():
                if database_digest(staged) != state["target_digest"]:
                    raise MigrationRefused("staged database changed")
                validate(snapshot if expected else None, staged)
                seal_database(staged)
                publish_noreplace(staged, target)
            if database_digest(target) != state["target_digest"]:
                raise MigrationRefused("destination differs from verified migration")
            fsync_file(target)
            fsync_directory(workspace)
            state["phase"] = "published"
            _write_state(receipt, state)
        if not target.exists() or database_digest(target) != state["target_digest"]:
            raise MigrationRefused("published destination missing or changed; never recreate it")
        _source_unchanged(source, expected, allow_missing=state["phase"] in {"archived", "complete"})
        if expected is not None:
            archive_root = workspace / "archive"
            for directory in (archive_root, archive_root / "migrations", archive_root / "migrations" / state["id"]):
                private_directory(directory)
            archive = archive_root / "migrations" / state["id"] / (source_name + archive_suffix)
            archive_codec(source if source.exists() else None, archive, expected)
            if state["phase"] != "complete":
                state["phase"] = "archived"
                _write_state(receipt, state)
                if source.exists():
                    source.unlink()
                fsync_directory(workspace)
        # Staging may still be a hard link to the target; unlink only, never overwrite.
        # Completion includes retiring plaintext staging, not merely archiving.
        for child in stage_dir.iterdir():
            require_regular(child)
            child.unlink()
        stage_dir.rmdir()
        fsync_directory(workspace)
        state["phase"] = "complete"
        _write_state(receipt, state)
        return target
    except Exception as exc:
        if target.exists() and state["phase"] in {"prepared", "published", "archived"}:
            try:
                owned_publication = database_digest(target) == state.get("target_digest")
            except Exception:
                owned_publication = False
            if owned_publication:
                raise ArchivePending("published destination retained; archival pending, rerun to resume") from exc
        # A racing or corrupted destination is not proof of our publication.
        raise
