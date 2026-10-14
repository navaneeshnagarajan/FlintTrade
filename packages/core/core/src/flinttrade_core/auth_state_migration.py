"""Verified auth cutover metadata and the normal webhook factory's path selector.

This is not a second store. Only the offline migrator writes selection metadata.
Runtime never guesses authority from the existence of an arbitrary SQLite file.
"""
from __future__ import annotations

import json
import re
from contextlib import closing
from pathlib import Path

from flinttrade_core.auth_state_runtime import AuthStateUnavailable, authority_marker, require_database, validate_schema
from flinttrade_core.legacy_sqlite_migration import database_digest, require_regular, sqlite_connection

_METADATA_SCHEMA = """CREATE TABLE _auth_state_migration (
    version INTEGER PRIMARY KEY CHECK(version=1),
    webhook_store TEXT NOT NULL,
    standalone_present INTEGER NOT NULL,
    standalone_digest TEXT
)"""


def _webhook_contents(path: Path) -> bool:
    from flinttrade_webhooks.webhook_replay import _NONCE_SCHEMA
    from flinttrade_webhooks.webhook_secret_store import _WEBHOOK_SECRET_SCHEMA

    require_regular(path)
    if not path.exists():
        if authority_marker(path).exists():
            raise AuthStateUnavailable("established webhook authority missing")
        return False
    require_database(path)
    with closing(sqlite_connection(path, readonly=True)) as conn:
        validate_schema(conn, _WEBHOOK_SECRET_SCHEMA + _NONCE_SCHEMA, integrity=True)
        return any(conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
                   for table in ("webhooks", "webhook_nonces"))


def record_webhook_selection(workspace: Path, staged: Path) -> None:
    """Pin the sole webhook consumer before publication; never merge ambiguities."""
    standalone = workspace / "webhook_secrets.db"
    migrated_data = _webhook_contents(staged)
    standalone_data = _webhook_contents(standalone)
    if migrated_data and standalone_data:
        raise AuthStateUnavailable("competing webhook authorities; explicit reconciliation required")
    selected = "auth_state.sqlite" if migrated_data else "webhook_secrets.db"
    with closing(sqlite_connection(staged)) as conn, conn:
        conn.execute(_METADATA_SCHEMA)
        conn.execute("INSERT INTO _auth_state_migration VALUES (1,?,?,?)",
                     (selected, int(standalone.exists()), database_digest(standalone) if standalone.exists() else None))


def _selection(target: Path) -> tuple[str, int, str | None]:
    with closing(sqlite_connection(target, readonly=True)) as conn:
        validate_schema(conn, _METADATA_SCHEMA)
        rows = conn.execute("SELECT version,webhook_store,standalone_present,standalone_digest "
                            "FROM _auth_state_migration").fetchall()
    if (len(rows) != 1 or rows[0][0] != 1 or rows[0][1] not in {"auth_state.sqlite", "webhook_secrets.db"}
            or type(rows[0][2]) is not int or rows[0][2] not in (0, 1)
            or (rows[0][3] is not None and not re.fullmatch(r"[0-9a-f]{64}", rows[0][3]))
            or bool(rows[0][2]) != bool(rows[0][3])):
        raise AuthStateUnavailable("invalid auth migration consumer metadata")
    return rows[0][1:]


def validate_staged_selection(workspace: Path, staged: Path) -> None:
    """Recheck the pinned standalone authority while the offline fence is held."""
    _, present, digest = _selection(staged)
    standalone = workspace / "webhook_secrets.db"
    if bool(present) != standalone.exists() or (present and database_digest(standalone) != digest):
        raise AuthStateUnavailable("standalone webhook authority changed during migration")


def verified_auth_migration(workspace: Path) -> tuple[str, int, str | None] | None:
    """Require complete custody and matching DB identity, not frozen live rows.

    Runtime writes legitimately change table contents after cutover. The paired
    immutable receipt/metadata identifies the migrated authority; the CLI alone
    checks its initial full content digest before publication and archival.
    """
    target = workspace / "auth_state.sqlite"
    receipt = workspace / ".auth_state.sqlite.migration.json"
    require_regular(receipt)
    source = workspace / "auth_state.duckdb"
    evidence = [source, receipt.with_name(receipt.name + ".tmp"), target.with_name(target.name + ".new")]
    evidence += [source.with_name(source.name + suffix) for suffix in (".wal", "-wal", "-shm", "-journal")]
    archives = list((workspace / "archive/migrations").glob("*/auth_state.duckdb*"))
    if any(p.exists() or p.is_symlink() for p in evidence):
        raise AuthStateUnavailable("legacy or pending auth authority requires offline migration")
    if not receipt.exists():
        if archives:
            raise AuthStateUnavailable("orphan auth archive evidence")
        if not target.exists() and any(workspace.glob(".migration-*")):
            raise AuthStateUnavailable("unowned migration staging; cannot initialise empty auth authority")
        if target.exists():
            require_database(target)
            with closing(sqlite_connection(target, readonly=True)) as conn:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name IN "
                                "('_migration_receipt','_auth_state_migration','webhooks')").fetchone():
                    raise AuthStateUnavailable("unowned auth migration destination")
        return None
    try:
        state = json.loads(receipt.read_text())
        valid = (state["version"] == 1 and state["phase"] == "complete"
                 and state["source"] == "auth_state.duckdb" and state["destination"] == "auth_state.sqlite"
                 and re.fullmatch(r"[0-9a-f]{32}", state["id"])
                 and re.fullmatch(r"[0-9a-f]{64}", state["target_digest"])
                 and (state["source_digest"] is None or re.fullmatch(r"[0-9a-f]{64}", state["source_digest"])))
        if not valid:
            raise ValueError
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthStateUnavailable("auth migration is incomplete or invalid") from exc
    require_database(target)
    with closing(sqlite_connection(target, readonly=True)) as conn:
        if conn.execute("SELECT id,source_digest FROM _migration_receipt").fetchall() != [
            (state["id"], state["source_digest"]),
        ]:
            raise AuthStateUnavailable("auth migration destination identity mismatch")
    if (workspace / (".migration-" + state["id"])).exists():
        raise AuthStateUnavailable("plaintext migration cleanup incomplete")
    if state["source_digest"] is not None:
        archive = workspace / "archive/migrations" / state["id"] / "auth_state.duckdb.age"
        require_regular(archive)
        with archive.open("rb") as stream:
            if not stream.read(64).startswith(b"age-encryption.org/v1\n"):
                raise AuthStateUnavailable("auth migration encrypted archive missing or invalid")
    return _selection(target)


def select_webhook_store_path(workspace: Path) -> Path:
    """Select the real factory consumer; refuse competing or lost authorities."""
    from flinttrade_core.auth_state import _CREATE_SCHEMA_SQL

    workspace = Path(workspace).absolute()
    metadata = verified_auth_migration(workspace)
    target = workspace / "auth_state.sqlite"
    if target.exists():
        require_database(target)
        with closing(sqlite_connection(target, readonly=True)) as conn:
            validate_schema(conn, _CREATE_SCHEMA_SQL, integrity=True)
    elif authority_marker(target).exists() or any(
        target.with_name(target.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise AuthStateUnavailable("established auth authority missing")
    standalone = workspace / "webhook_secrets.db"
    if metadata is None:
        _webhook_contents(standalone)
        return standalone
    selected, present, _ = metadata
    migrated_data, standalone_data = _webhook_contents(target), _webhook_contents(standalone)
    if present and not standalone.exists():
        raise AuthStateUnavailable("recorded standalone webhook authority missing")
    if (selected == "auth_state.sqlite" and standalone_data) or (selected == "webhook_secrets.db" and migrated_data):
        raise AuthStateUnavailable("competing webhook authorities; no automatic cutover")
    return workspace / selected
