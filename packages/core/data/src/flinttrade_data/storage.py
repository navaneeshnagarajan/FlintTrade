"""DuckDB storage manager — connection pooling, schema creation, query helpers.

Tables: ticks, trades, audit, daily_summary
All timestamps stored as UTC. Queries accept IST date ranges and convert internally.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from flinttrade_core.workspace import duckdb_path

logger = logging.getLogger("flinttrade.data.storage")
IST = timezone(timedelta(hours=5, minutes=30))
_SCHEMA_INITIALISE_LOCK = threading.RLock()
MAX_TICK_REPLAY_QUERY_ROWS = 100_001
_TICK_STORE_ID_KEY = "tick_store_id"
_TICK_HIGH_WATER_KEY = "tick_ingest_high_water"
_TICK_PRUNED_HIGH_WATER_KEY = "tick_pruned_ingest_high_water"
_TICK_PRUNED_BEFORE_KEY = "tick_pruned_before_utc"
_TICK_LINEAGE_PREDECESSOR_KEY = "tick_lineage_predecessor_store_id"
_TICK_LINEAGE_ANCESTORS_KEY = "tick_lineage_ancestor_store_ids"
_TICK_LINEAGE_RECOVERY_KEY = "tick_lineage_recovery"
_NO_PRUNE_CUTOFF = "1970-01-01T00:00:00+00:00"
_UNCERTAIN_PRUNE_CUTOFF = "9999-12-31T23:59:59+00:00"
_MAX_INGEST_SEQ = 2**63 - 1
_MAX_LINEAGE_SOURCE_STORE_IDS = 16


class TickReplayCursorError(ValueError):
    """Base class for persisted tick replay cursor failures."""


class TickReplayStoreMismatchError(TickReplayCursorError):
    """Raised when a cursor belongs to a different tick store."""


class TickReplayCursorAheadError(TickReplayCursorError):
    """Raised when storage has rolled back behind a persisted cursor."""


class TickReplayCursorPrunedError(TickReplayCursorError):
    """Raised when retention removed a row committed after the cursor."""


@dataclass(frozen=True, slots=True)
class TickReplayCursor:
    """Stable tick-store lineage and its latest committed ingest sequence."""

    store_id: str
    ingest_seq: int

    def __post_init__(self) -> None:
        if not isinstance(self.store_id, str):
            raise ValueError("store_id must be a canonical UUID")
        try:
            parsed_store_id = uuid.UUID(self.store_id)
        except (AttributeError, ValueError) as exc:
            raise ValueError("store_id must be a canonical UUID") from exc
        if str(parsed_store_id) != self.store_id:
            raise ValueError("store_id must be a canonical UUID")
        if (
            isinstance(self.ingest_seq, bool)
            or not isinstance(self.ingest_seq, int)
            or not 0 <= self.ingest_seq <= _MAX_INGEST_SEQ
        ):
            raise ValueError("ingest_seq must be a non-negative BIGINT")


@dataclass(frozen=True, slots=True)
class TickReplayLineageHandoff:
    """One metadata-proven transition from a checkpoint lineage to storage."""

    from_store_id: str
    to_store_id: str
    ancestor_store_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from_store_id = TickReplayCursor(self.from_store_id, 0).store_id
        to_store_id = TickReplayCursor(self.to_store_id, 0).store_id
        if from_store_id == to_store_id:
            raise ValueError("lineage handoff must change the store identity")
        if not isinstance(self.ancestor_store_ids, tuple):
            raise ValueError("lineage handoff ancestors must be a tuple")
        ancestors = tuple(TickReplayCursor(store_id, 0).store_id for store_id in self.ancestor_store_ids)
        source_store_ids = (*ancestors, from_store_id)
        if len(source_store_ids) > _MAX_LINEAGE_SOURCE_STORE_IDS:
            raise ValueError("lineage handoff exceeds the source-store bound")
        if len(set(source_store_ids)) != len(source_store_ids) or to_store_id in source_store_ids:
            raise ValueError("lineage handoff store identities must be distinct")

    @property
    def source_store_ids(self) -> tuple[str, ...]:
        """Return every unacknowledged source, ending with the immediate predecessor."""
        return (*self.ancestor_store_ids, self.from_store_id)


@dataclass(frozen=True, slots=True)
class TickReplayLineageRecovery:
    """Explicit recovery authority for a store whose prior identity was missing."""

    to_store_id: str
    reason: str

    def __post_init__(self) -> None:
        TickReplayCursor(self.to_store_id, 0)
        if self.reason not in {"missing_store_identity", "pristine_store_replacement"}:
            raise ValueError("tick storage lineage recovery reason is invalid")


def _encode_store_ids(store_ids: tuple[str, ...]) -> str:
    return json.dumps(list(store_ids), separators=(",", ":"))


def _decode_store_ids(value: str) -> tuple[str, ...]:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("lineage handoff ancestors are invalid") from None
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("lineage handoff ancestors are invalid")
    return tuple(decoded)


def _encode_lineage_recovery(recovery: TickReplayLineageRecovery) -> str:
    return json.dumps(
        {"reason": recovery.reason, "to_store_id": recovery.to_store_id},
        separators=(",", ":"),
        sort_keys=True,
    )


def _decode_lineage_recovery(value: str) -> TickReplayLineageRecovery:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        raise ValueError("tick storage lineage recovery is invalid") from None
    if not isinstance(decoded, dict) or set(decoded) != {"reason", "to_store_id"}:
        raise ValueError("tick storage lineage recovery is invalid")
    return TickReplayLineageRecovery(
        to_store_id=decoded["to_store_id"],
        reason=decoded["reason"],
    )


def _metadata_high_water(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= _MAX_INGEST_SEQ else None


def _metadata_prune_cutoff(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _normalise_ts(value: Any) -> Any:
    """Store aware timestamps as naive UTC for DuckDB TIMESTAMP columns."""
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _timestamp_provenance(value: Any) -> str:
    """Validate whether a stored timestamp is source-authored or untrusted."""
    if not isinstance(value, str) or value not in {"source", "unknown"}:
        raise ValueError("timestamp_provenance must be 'source' or 'unknown'")
    return value


def _ist_date_window(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Convert inclusive IST date strings to UTC-naive storage bounds."""
    start = datetime.combine(date.fromisoformat(start_date), time.min, tzinfo=IST)
    end = datetime.combine(date.fromisoformat(end_date), time.min, tzinfo=IST) + timedelta(days=1)
    return _normalise_ts(start), _normalise_ts(end)


def _default_db_path() -> str:
    """Resolve the shared DuckDB path through the workspace authority."""
    return str(duckdb_path())


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_TICKS_SEQUENCE = "CREATE SEQUENCE IF NOT EXISTS ticks_ingest_seq START 1;"

_SCHEMA_TICKS = """
CREATE TABLE IF NOT EXISTS ticks (
    ts          TIMESTAMP NOT NULL,
    symbol      VARCHAR NOT NULL,
    exchange    VARCHAR NOT NULL,
    mode        VARCHAR NOT NULL,
    ltp         DOUBLE,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    bid         DOUBLE,
    ask         DOUBLE,
    oi          BIGINT,
    prev_close  DOUBLE,
    depth_json  VARCHAR,
    timestamp_provenance VARCHAR NOT NULL DEFAULT 'unknown',
    ingest_seq  BIGINT NOT NULL DEFAULT nextval('ticks_ingest_seq')
);
"""

_MIGRATE_TICKS_INGEST_SEQUENCE = """
ALTER TABLE ticks
ADD COLUMN IF NOT EXISTS ingest_seq BIGINT DEFAULT nextval('ticks_ingest_seq');
"""

_REQUIRE_TICKS_INGEST_SEQUENCE = """
ALTER TABLE ticks ALTER COLUMN ingest_seq SET NOT NULL;
"""

_MIGRATE_TICKS_TIMESTAMP_PROVENANCE = """
ALTER TABLE ticks
ADD COLUMN IF NOT EXISTS timestamp_provenance VARCHAR DEFAULT 'unknown';
"""

_REQUIRE_TICKS_TIMESTAMP_PROVENANCE = """
ALTER TABLE ticks ALTER COLUMN timestamp_provenance SET NOT NULL;
"""

_BACKFILL_TICKS_TIMESTAMP_PROVENANCE = """
UPDATE ticks SET timestamp_provenance = 'unknown' WHERE timestamp_provenance IS NULL;
"""

_SCHEMA_STORAGE_METADATA = """
CREATE TABLE IF NOT EXISTS flinttrade_storage_metadata (
    key     VARCHAR PRIMARY KEY,
    value   VARCHAR NOT NULL
);
"""

_SCHEMA_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    ts              TIMESTAMP NOT NULL,
    orderid         VARCHAR NOT NULL,
    symbol          VARCHAR NOT NULL,
    exchange        VARCHAR NOT NULL,
    action          VARCHAR NOT NULL,
    quantity        INTEGER NOT NULL,
    price           DOUBLE NOT NULL,
    product         VARCHAR,
    strategy        VARCHAR,
    entry_price     DOUBLE,
    exit_price      DOUBLE,
    pnl             DOUBLE,
    slippage        DOUBLE,
    fees            DOUBLE
);
"""

_SCHEMA_AUDIT = """
CREATE TABLE IF NOT EXISTS audit (
    ts          TIMESTAMP NOT NULL,
    event_type  VARCHAR NOT NULL,
    strategy    VARCHAR,
    symbol      VARCHAR,
    exchange    VARCHAR,
    action      VARCHAR,
    quantity    VARCHAR,
    price       VARCHAR,
    layer       VARCHAR,
    verdict     VARCHAR,
    reason      VARCHAR,
    details     VARCHAR
);
"""

_SCHEMA_DAILY_SUMMARY = """
CREATE TABLE IF NOT EXISTS daily_summary (
    trade_date      DATE NOT NULL,
    strategy        VARCHAR,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    gross_pnl       DOUBLE DEFAULT 0.0,
    fees            DOUBLE DEFAULT 0.0,
    net_pnl         DOUBLE DEFAULT 0.0,
    max_drawdown    DOUBLE DEFAULT 0.0
);
"""

_ALL_SCHEMAS = [
    _SCHEMA_TICKS,
    _SCHEMA_TRADES,
    _SCHEMA_AUDIT,
    _SCHEMA_DAILY_SUMMARY,
    _SCHEMA_STORAGE_METADATA,
]

# Indexes — without these, every query does a full table scan.
_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ticks_sym_ex_ts_seq ON ticks (symbol, exchange, ts, ingest_seq)",
    "CREATE INDEX IF NOT EXISTS idx_trades_strategy_ts ON trades (strategy, ts)",
    "CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts ON trades (symbol, ts)",
    "CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades (ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit (ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_event ON audit (event_type, ts)",
    "CREATE INDEX IF NOT EXISTS idx_daily_summary_date ON daily_summary (trade_date, strategy)",
]
_DROP_TICKS_INDEXES = (
    "DROP INDEX IF EXISTS idx_ticks_sym_ex_ts",
    "DROP INDEX IF EXISTS idx_ticks_sym_ex_ts_seq",
)


# ---------------------------------------------------------------------------
# StorageManager
# ---------------------------------------------------------------------------


class StorageManager:
    """DuckDB connection manager with schema initialisation and query helpers.

    Usage::

        storage = StorageManager("/data/flinttrade/flint.duckdb")
        storage.initialise()
        storage.insert_tick(...)
        ticks = storage.get_ticks("RELIANCE", "NSE", "2026-03-01", "2026-03-16")
        storage.close()
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
            logger.info("DuckDB connected: %s", self._db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            logger.info("DuckDB closed: %s", self._db_path)

    def __enter__(self) -> StorageManager:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    def initialise(self) -> None:
        """Create all tables and indexes if they don't exist."""
        with _SCHEMA_INITIALISE_LOCK:
            self.connection.execute(_SCHEMA_TICKS_SEQUENCE)
            for ddl in _ALL_SCHEMAS:
                self.connection.execute(ddl)
            tick_columns = {row[1]: row for row in self.connection.execute("PRAGMA table_info('ticks')").fetchall()}
            migrated_legacy_ingest_sequence = "ingest_seq" not in tick_columns
            if migrated_legacy_ingest_sequence:
                self.connection.execute(_MIGRATE_TICKS_INGEST_SEQUENCE)
            if "timestamp_provenance" not in tick_columns:
                self.connection.execute(_MIGRATE_TICKS_TIMESTAMP_PROVENANCE)
            tick_columns = {row[1]: row for row in self.connection.execute("PRAGMA table_info('ticks')").fetchall()}
            requires_constraint_migration = not (
                tick_columns["ingest_seq"][3] and tick_columns["timestamp_provenance"][3]
            )
            if requires_constraint_migration:
                # DuckDB refuses ALTER COLUMN while any index depends on the
                # table, even when that index does not mention the new column.
                for statement in _DROP_TICKS_INDEXES:
                    self.connection.execute(statement)
            try:
                if not tick_columns["ingest_seq"][3]:
                    self.connection.execute(_REQUIRE_TICKS_INGEST_SEQUENCE)
                if not tick_columns["timestamp_provenance"][3]:
                    self.connection.execute(_BACKFILL_TICKS_TIMESTAMP_PROVENANCE)
                    self.connection.execute(_REQUIRE_TICKS_TIMESTAMP_PROVENANCE)
            finally:
                if requires_constraint_migration:
                    self.connection.execute(_INDEXES[0])
            for idx in _INDEXES:
                self.connection.execute(idx)

            conn = self.connection
            conn.execute("BEGIN TRANSACTION")
            try:
                existing_metadata = dict(conn.execute("SELECT key, value FROM flinttrade_storage_metadata").fetchall())
                had_store_identity = _TICK_STORE_ID_KEY in existing_metadata
                lineage_metadata_complete = all(
                    key in existing_metadata
                    for key in (
                        _TICK_HIGH_WATER_KEY,
                        _TICK_PRUNED_HIGH_WATER_KEY,
                        _TICK_PRUNED_BEFORE_KEY,
                    )
                )
                observed_row = conn.execute("SELECT COALESCE(MAX(ingest_seq), 0) FROM ticks").fetchone()
                observed_high_water = int(observed_row[0]) if observed_row is not None else 0
                stored_high_water = _metadata_high_water(existing_metadata.get(_TICK_HIGH_WATER_KEY))
                stored_pruned_high_water = _metadata_high_water(
                    existing_metadata.get(_TICK_PRUNED_HIGH_WATER_KEY)
                )
                stored_prune_cutoff = _metadata_prune_cutoff(
                    existing_metadata.get(_TICK_PRUNED_BEFORE_KEY)
                )
                recovered_pruned_high_water = (
                    stored_pruned_high_water
                    if stored_pruned_high_water is not None
                    else max(observed_high_water, stored_high_water or 0)
                )
                recovered_high_water = max(
                    observed_high_water,
                    stored_high_water or 0,
                    recovered_pruned_high_water,
                )
                recovered_prune_cutoff = stored_prune_cutoff
                if migrated_legacy_ingest_sequence and not existing_metadata:
                    recovered_pruned_high_water = 0
                    recovered_prune_cutoff = _NO_PRUNE_CUTOFF
                if recovered_prune_cutoff is None:
                    recovered_prune_cutoff = (
                        _UNCERTAIN_PRUNE_CUTOFF
                        if existing_metadata or observed_high_water > 0
                        else _NO_PRUNE_CUTOFF
                    )
                if not had_store_identity or not lineage_metadata_complete:
                    new_store_id = str(uuid.uuid4())
                    if had_store_identity:
                        try:
                            old_store_id = TickReplayCursor(
                                str(existing_metadata[_TICK_STORE_ID_KEY]),
                                0,
                            ).store_id
                            predecessor = existing_metadata.get(_TICK_LINEAGE_PREDECESSOR_KEY)
                            ancestor_value = existing_metadata.get(_TICK_LINEAGE_ANCESTORS_KEY)
                            if predecessor is None:
                                if ancestor_value is not None:
                                    raise ValueError("lineage handoff ancestors have no predecessor")
                                source_store_ids: tuple[str, ...] = ()
                            else:
                                ancestors = () if ancestor_value is None else _decode_store_ids(ancestor_value)
                                existing_handoff = TickReplayLineageHandoff(
                                    from_store_id=str(predecessor),
                                    to_store_id=old_store_id,
                                    ancestor_store_ids=ancestors,
                                )
                                source_store_ids = existing_handoff.source_store_ids[
                                    -(_MAX_LINEAGE_SOURCE_STORE_IDS - 1) :
                                ]
                            new_handoff = TickReplayLineageHandoff(
                                from_store_id=old_store_id,
                                to_store_id=new_store_id,
                                ancestor_store_ids=source_store_ids,
                            )
                            recovery_value = existing_metadata.get(_TICK_LINEAGE_RECOVERY_KEY)
                            recovery = None if recovery_value is None else _decode_lineage_recovery(recovery_value)
                            if recovery is not None and recovery.to_store_id != old_store_id:
                                raise ValueError("lineage recovery targets a different store")
                        except (TypeError, ValueError) as exc:
                            raise RuntimeError("tick storage lineage predecessor is invalid") from exc
                        self._set_metadata_value(
                            _TICK_LINEAGE_PREDECESSOR_KEY,
                            new_handoff.from_store_id,
                        )
                        if new_handoff.ancestor_store_ids:
                            self._set_metadata_value(
                                _TICK_LINEAGE_ANCESTORS_KEY,
                                _encode_store_ids(new_handoff.ancestor_store_ids),
                            )
                        else:
                            self._delete_metadata_value(_TICK_LINEAGE_ANCESTORS_KEY)
                        if recovery is not None:
                            self._set_metadata_value(
                                _TICK_LINEAGE_RECOVERY_KEY,
                                _encode_lineage_recovery(
                                    TickReplayLineageRecovery(
                                        to_store_id=new_store_id,
                                        reason=recovery.reason,
                                    )
                                ),
                            )
                    else:
                        self._delete_metadata_value(_TICK_LINEAGE_PREDECESSOR_KEY)
                        self._delete_metadata_value(_TICK_LINEAGE_ANCESTORS_KEY)
                        recovery_reason = (
                            "missing_store_identity"
                            if existing_metadata or observed_high_water > 0
                            else "pristine_store_replacement"
                        )
                        self._set_metadata_value(
                            _TICK_LINEAGE_RECOVERY_KEY,
                            _encode_lineage_recovery(
                                TickReplayLineageRecovery(
                                    to_store_id=new_store_id,
                                    reason=recovery_reason,
                                )
                            ),
                        )
                    self._set_metadata_value(_TICK_STORE_ID_KEY, new_store_id)
                    self._set_metadata_value(
                        _TICK_HIGH_WATER_KEY,
                        str(recovered_high_water),
                    )
                    self._set_metadata_value(
                        _TICK_PRUNED_HIGH_WATER_KEY,
                        str(recovered_pruned_high_water),
                    )
                    self._set_metadata_value(
                        _TICK_PRUNED_BEFORE_KEY,
                        recovered_prune_cutoff,
                    )
                    if existing_metadata:
                        logger.warning("Tick replay lineage rotated because lineage metadata was incomplete")
                else:
                    self._advance_tick_replay_high_water(observed_high_water)
                self._read_tick_store_id()
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        logger.info("DuckDB schema initialised (tables + indexes)")

    # ------------------------------------------------------------------
    # Tick storage
    # ------------------------------------------------------------------

    def insert_tick(
        self,
        ts: datetime,
        symbol: str,
        exchange: str,
        mode: str,
        *,
        ltp: float | None = None,
        open_: float | None = None,
        high: float | None = None,
        low: float | None = None,
        close: float | None = None,
        volume: int | None = None,
        bid: float | None = None,
        ask: float | None = None,
        oi: int | None = None,
        prev_close: float | None = None,
        depth_json: str | None = None,
        timestamp_provenance: str = "unknown",
    ) -> None:
        """Insert a single tick row (append-only)."""
        conn = self.connection
        conn.execute("BEGIN TRANSACTION")
        try:
            inserted = conn.execute(
                """INSERT INTO ticks
                   (ts, symbol, exchange, mode, ltp, open, high, low, close,
                    volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   RETURNING ingest_seq""",
                [
                    _normalise_ts(ts),
                    symbol,
                    exchange,
                    mode,
                    ltp,
                    open_,
                    high,
                    low,
                    close,
                    volume,
                    bid,
                    ask,
                    oi,
                    prev_close,
                    depth_json,
                    _timestamp_provenance(timestamp_provenance),
                ],
            ).fetchone()
            if inserted is None:
                raise RuntimeError("tick insert did not return its ingest sequence")
            self._advance_tick_replay_high_water(int(inserted[0]))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def insert_ticks_batch(self, rows: list[tuple]) -> None:
        """Bulk insert ticks ATOMICALLY. Each tuple matches the ticks column order.

        Provenance-aware rows contain 16 fields and end in ``"source"``.
        Legacy 15-field rows remain insertable but are marked ``"unknown"``
        so restart replay cannot treat receipt-substituted history as source time.

        The batch runs in an explicit transaction so a mid-batch failure (e.g. a
        bad row, disk-full) rolls the WHOLE batch back rather than leaving a
        partially-committed prefix. This is what lets the TickRecorder safely
        retain-and-retry a failed buffer without duplicating already-committed
        rows (the ticks table has no unique constraint, so a partial commit
        followed by a full retry would otherwise double-insert the prefix).
        """
        if not rows:
            return
        conn = self.connection
        normalised_rows = []
        for row in rows:
            if len(row) == 15:
                row = (*row, "unknown")
            if len(row) != 16:
                raise ValueError("tick rows must contain 15 legacy or 16 provenance-aware fields")
            normalised_rows.append((_normalise_ts(row[0]), *row[1:15], _timestamp_provenance(row[15])))
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.executemany(
                """INSERT INTO ticks
                   (ts, symbol, exchange, mode, ltp, open, high, low, close,
                    volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                normalised_rows,
            )
            sequence_row = conn.execute("SELECT currval('ticks_ingest_seq')").fetchone()
            if sequence_row is None:
                raise RuntimeError("tick batch did not advance its ingest sequence")
            self._advance_tick_replay_high_water(int(sequence_row[0]))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def prune_ticks(self, days_to_keep: int) -> int:
        """Delete ticks older than ``days_to_keep`` days; return rows removed.

        Keeps the append-only tick store bounded. A non-positive window is a
        no-op — it never deletes everything by accident. The cut-off is computed
        in Python (a naive datetime, matching the naive ``ts`` column) so the
        comparison is timezone-consistent.
        """
        if days_to_keep <= 0:
            return 0
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_to_keep)
        conn = self.connection
        conn.execute("BEGIN TRANSACTION")
        try:
            row = conn.execute(
                "SELECT COUNT(*), MAX(ingest_seq) FROM ticks WHERE ts < ?",
                [cutoff],
            ).fetchone()
            removed = int(row[0]) if row is not None else 0
            pruned_high_water = int(row[1]) if row is not None and row[1] is not None else 0
            conn.execute("DELETE FROM ticks WHERE ts < ?", [cutoff])
            if removed:
                self._advance_metadata_high_water(
                    _TICK_PRUNED_HIGH_WATER_KEY,
                    pruned_high_water,
                )
                self._advance_prune_cutoff(cutoff)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return removed

    def get_ticks(
        self,
        symbol: str,
        exchange: str,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query ticks by symbol, exchange, and date range (YYYY-MM-DD strings).

        When ``limit`` is supplied, the query reads only the most recent rows
        from DuckDB and reverses that bounded result for chronological output.
        """
        start, end = _ist_date_window(start_date, end_date)
        params: list[Any] = [symbol, exchange, start, end]
        order_clause = "ORDER BY ts, ingest_seq"
        if limit is not None:
            if limit <= 0:
                return []
            order_clause = "ORDER BY ts DESC, ingest_seq DESC LIMIT ?"
            params.append(limit)
        result = self.connection.execute(
            f"""SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                       volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance
                FROM ticks
                WHERE symbol = ? AND exchange = ?
                  AND ts >= ? AND ts < ?
                {order_clause}""",  # noqa: S608 - clause is selected from fixed literals above
            params,
        )
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        if limit is not None:
            rows.reverse()
        return [dict(zip(columns, row)) for row in rows]

    def get_tick_replay_cursor(self) -> TickReplayCursor:
        """Return this store's identity and latest committed global tick sequence."""
        store_id = self._read_tick_store_id()
        ingest_seq = self._read_tick_replay_high_water()
        return TickReplayCursor(store_id=store_id, ingest_seq=ingest_seq)

    def get_tick_replay_lineage_handoff(
        self,
    ) -> TickReplayLineageHandoff | None:
        """Return the unacknowledged metadata-proven lineage transition."""
        metadata = dict(
            self.connection.execute(
                "SELECT key, value FROM flinttrade_storage_metadata WHERE key IN (?, ?, ?)",
                [_TICK_STORE_ID_KEY, _TICK_LINEAGE_PREDECESSOR_KEY, _TICK_LINEAGE_ANCESTORS_KEY],
            ).fetchall()
        )
        predecessor = metadata.get(_TICK_LINEAGE_PREDECESSOR_KEY)
        ancestor_value = metadata.get(_TICK_LINEAGE_ANCESTORS_KEY)
        if predecessor is None:
            if ancestor_value is not None:
                raise RuntimeError("tick storage lineage handoff is invalid")
            return None
        try:
            ancestors = () if ancestor_value is None else _decode_store_ids(str(ancestor_value))
            return TickReplayLineageHandoff(
                from_store_id=str(predecessor),
                to_store_id=str(metadata[_TICK_STORE_ID_KEY]),
                ancestor_store_ids=ancestors,
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError("tick storage lineage handoff is invalid") from exc

    def acknowledge_tick_replay_lineage_handoff(
        self,
        handoff: TickReplayLineageHandoff,
    ) -> bool:
        """Clear exactly one successfully published lineage transition."""
        if not isinstance(handoff, TickReplayLineageHandoff):
            raise TypeError("handoff must be a TickReplayLineageHandoff")
        current = self.get_tick_replay_lineage_handoff()
        if current is None:
            return False
        if current != handoff:
            raise RuntimeError("tick storage lineage handoff changed")
        encoded_ancestors = _encode_store_ids(handoff.ancestor_store_ids)
        deleted = self.connection.execute(
            """DELETE FROM flinttrade_storage_metadata
               WHERE key IN (?, ?)
                 AND (SELECT value FROM flinttrade_storage_metadata WHERE key = ?) = ?
                 AND (SELECT value FROM flinttrade_storage_metadata WHERE key = ?) = ?
                 AND (
                       (? = '' AND NOT EXISTS (
                           SELECT 1 FROM flinttrade_storage_metadata WHERE key = ?
                       ))
                       OR (SELECT value FROM flinttrade_storage_metadata WHERE key = ?) = ?
                 )
               RETURNING key""",
            [
                _TICK_LINEAGE_PREDECESSOR_KEY,
                _TICK_LINEAGE_ANCESTORS_KEY,
                _TICK_STORE_ID_KEY,
                handoff.to_store_id,
                _TICK_LINEAGE_PREDECESSOR_KEY,
                handoff.from_store_id,
                encoded_ancestors if handoff.ancestor_store_ids else "",
                _TICK_LINEAGE_ANCESTORS_KEY,
                _TICK_LINEAGE_ANCESTORS_KEY,
                encoded_ancestors,
            ],
        ).fetchall()
        expected_deleted = 1 + int(bool(handoff.ancestor_store_ids))
        if len(deleted) != expected_deleted:
            raise RuntimeError("tick storage lineage handoff changed")
        return True

    def get_tick_replay_lineage_recovery(
        self,
    ) -> TickReplayLineageRecovery | None:
        """Return explicit authority to recover a lineage whose store ID was missing."""
        metadata = dict(
            self.connection.execute(
                "SELECT key, value FROM flinttrade_storage_metadata WHERE key IN (?, ?)",
                [_TICK_STORE_ID_KEY, _TICK_LINEAGE_RECOVERY_KEY],
            ).fetchall()
        )
        value = metadata.get(_TICK_LINEAGE_RECOVERY_KEY)
        if value is None:
            return None
        try:
            recovery = _decode_lineage_recovery(str(value))
        except ValueError as exc:
            raise RuntimeError("tick storage lineage recovery is invalid") from exc
        if recovery.to_store_id != metadata.get(_TICK_STORE_ID_KEY):
            raise RuntimeError("tick storage lineage recovery targets a different store")
        return recovery

    def acknowledge_tick_replay_lineage_recovery(
        self,
        recovery: TickReplayLineageRecovery,
    ) -> bool:
        """Clear exactly one successfully published missing-identity recovery."""
        if not isinstance(recovery, TickReplayLineageRecovery):
            raise TypeError("recovery must be a TickReplayLineageRecovery")
        current = self.get_tick_replay_lineage_recovery()
        if current is None:
            return False
        if current != recovery:
            raise RuntimeError("tick storage lineage recovery changed")
        deleted = self.connection.execute(
            """DELETE FROM flinttrade_storage_metadata
               WHERE key = ? AND value = ?
                 AND (SELECT value FROM flinttrade_storage_metadata WHERE key = ?) = ?
               RETURNING key""",
            [
                _TICK_LINEAGE_RECOVERY_KEY,
                _encode_lineage_recovery(recovery),
                _TICK_STORE_ID_KEY,
                recovery.to_store_id,
            ],
        ).fetchall()
        if len(deleted) != 1:
            raise RuntimeError("tick storage lineage recovery changed")
        return True

    def validate_tick_replay_cursor(
        self,
        cursor: TickReplayCursor,
    ) -> TickReplayCursor:
        """Validate cursor lineage and rollback safety; return the current cursor."""
        return self._validate_tick_replay_cursor_in_transaction(cursor)

    def _validate_tick_replay_cursor_in_transaction(
        self,
        cursor: TickReplayCursor,
        *,
        session_start: datetime | None = None,
    ) -> TickReplayCursor:
        """Validate one cursor inside the caller's current DuckDB snapshot."""
        if not isinstance(cursor, TickReplayCursor):
            raise TypeError("cursor must be a TickReplayCursor")
        current = self.get_tick_replay_cursor()
        if cursor.store_id != current.store_id:
            raise TickReplayStoreMismatchError("cursor belongs to a different tick store")
        if cursor.ingest_seq > current.ingest_seq:
            raise TickReplayCursorAheadError("cursor is ahead of tick storage")
        pruned_high_water = self._read_metadata_high_water(_TICK_PRUNED_HIGH_WATER_KEY)
        requested_session_is_complete = session_start is not None and session_start >= self._read_prune_cutoff()
        if cursor.ingest_seq < pruned_high_water and not requested_session_is_complete:
            raise TickReplayCursorPrunedError("tick retention removed rows committed after the replay cursor")
        return current

    def get_ticks_after_cursor(
        self,
        cursor: TickReplayCursor,
        symbol: str,
        exchange: str,
        session_date: str | None,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return the earliest rows committed after ``cursor``.

        Callers should request ``max_ticks + 1`` rows. Receiving at most
        ``max_ticks`` proves the cursor-bound tail is complete; receiving the
        extra row proves replay must fail closed or use a newer checkpoint.
        Unlike :meth:`get_ticks`, rows include ``ingest_seq`` so duplicate source
        timestamps retain a stable persistence order. Pass ``session_date`` to
        build a complete session prefix from a zero cursor; pass ``None`` when a
        checkpoint already defines the represented history and every later
        commit must be replayed regardless of its source timestamp.
        """
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_TICK_REPLAY_QUERY_ROWS:
            raise ValueError(f"limit must be between 1 and {MAX_TICK_REPLAY_QUERY_ROWS}")
        date_clause = ""
        params: list[Any] = [cursor.ingest_seq, symbol, exchange]
        session_start: datetime | None = None
        if session_date is not None:
            start, end = _ist_date_window(session_date, session_date)
            session_start = start
            date_clause = "AND ts >= ? AND ts < ?"
            params.extend((start, end))
        params.append(limit)
        conn = self.connection
        conn.execute("BEGIN TRANSACTION")
        try:
            self._validate_tick_replay_cursor_in_transaction(
                cursor,
                session_start=session_start,
            )
            result = conn.execute(
                f"""SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                          volume, bid, ask, oi, prev_close, depth_json,
                          timestamp_provenance, ingest_seq
                   FROM ticks
                   WHERE ingest_seq > ?
                     AND symbol = ? AND exchange = ?
                     {date_clause}
                   ORDER BY ingest_seq
                   LIMIT ?""",  # noqa: S608 - date_clause is selected from fixed literals above
                params,
            )
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return [dict(zip(columns, row)) for row in rows]

    def _read_tick_store_id(self) -> str:
        """Read and validate the durable tick-store identity."""
        try:
            row = self.connection.execute(
                "SELECT value FROM flinttrade_storage_metadata WHERE key = ?",
                [_TICK_STORE_ID_KEY],
            ).fetchone()
        except duckdb.Error as exc:
            raise RuntimeError("tick storage is not initialised") from exc
        if row is None:
            raise RuntimeError("tick storage identity is missing")
        try:
            return TickReplayCursor(str(row[0]), 0).store_id
        except ValueError as exc:
            raise RuntimeError("tick storage identity is invalid") from exc

    def _advance_tick_replay_high_water(self, observed: int | None = None) -> None:
        """Persist the greatest committed sequence without per-flush table scans."""
        if observed is None:
            row = self.connection.execute("SELECT COALESCE(MAX(ingest_seq), 0) FROM ticks").fetchone()
            observed = int(row[0]) if row is not None else 0
        self._advance_metadata_high_water(_TICK_HIGH_WATER_KEY, observed)

    def _advance_metadata_high_water(self, key: str, observed: int) -> None:
        if not 0 <= observed <= _MAX_INGEST_SEQ:
            raise RuntimeError("tick storage high-water mark is invalid")
        existing = self.connection.execute(
            "SELECT value FROM flinttrade_storage_metadata WHERE key = ?",
            [key],
        ).fetchone()
        if existing is None:
            self.connection.execute(
                "INSERT INTO flinttrade_storage_metadata (key, value) VALUES (?, ?)",
                [key, str(observed)],
            )
            return
        try:
            high_water = int(existing[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("tick storage high-water mark is invalid") from exc
        if not 0 <= high_water <= _MAX_INGEST_SEQ:
            raise RuntimeError("tick storage high-water mark is invalid")
        if observed > high_water:
            self.connection.execute(
                "UPDATE flinttrade_storage_metadata SET value = ? WHERE key = ?",
                [str(observed), key],
            )

    def _set_metadata_value(self, key: str, value: str) -> None:
        existing = self.connection.execute(
            "SELECT 1 FROM flinttrade_storage_metadata WHERE key = ?",
            [key],
        ).fetchone()
        if existing is None:
            self.connection.execute(
                "INSERT INTO flinttrade_storage_metadata (key, value) VALUES (?, ?)",
                [key, value],
            )
        else:
            self.connection.execute(
                "UPDATE flinttrade_storage_metadata SET value = ? WHERE key = ?",
                [value, key],
            )

    def _delete_metadata_value(self, key: str) -> None:
        self.connection.execute(
            "DELETE FROM flinttrade_storage_metadata WHERE key = ?",
            [key],
        )

    def _advance_prune_cutoff(self, cutoff: datetime) -> None:
        current = self._read_prune_cutoff()
        if cutoff > current:
            self._set_metadata_value(
                _TICK_PRUNED_BEFORE_KEY,
                cutoff.replace(tzinfo=UTC).isoformat(),
            )

    def _read_prune_cutoff(self) -> datetime:
        row = self.connection.execute(
            "SELECT value FROM flinttrade_storage_metadata WHERE key = ?",
            [_TICK_PRUNED_BEFORE_KEY],
        ).fetchone()
        if row is None:
            raise RuntimeError("tick storage prune cutoff is missing")
        try:
            cutoff = datetime.fromisoformat(str(row[0]))
        except ValueError as exc:
            raise RuntimeError("tick storage prune cutoff is invalid") from exc
        if cutoff.tzinfo is not None:
            cutoff = cutoff.astimezone(UTC).replace(tzinfo=None)
        return cutoff

    def _read_tick_replay_high_water(self) -> int:
        return self._read_metadata_high_water(_TICK_HIGH_WATER_KEY)

    def _read_metadata_high_water(self, key: str) -> int:
        row = self.connection.execute(
            "SELECT value FROM flinttrade_storage_metadata WHERE key = ?",
            [key],
        ).fetchone()
        if row is None:
            raise RuntimeError("tick storage high-water mark is missing")
        try:
            value = int(row[0])
        except (TypeError, ValueError) as exc:
            raise RuntimeError("tick storage high-water mark is invalid") from exc
        if not 0 <= value <= _MAX_INGEST_SEQ:
            raise RuntimeError("tick storage high-water mark is invalid")
        return value

    def get_ticks_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all ticks for a given date."""
        start, end = _ist_date_window(trade_date, trade_date)
        result = self.connection.execute(
            """SELECT ts, symbol, exchange, mode, ltp, open, high, low, close,
                      volume, bid, ask, oi, prev_close, depth_json, timestamp_provenance
               FROM ticks
               WHERE ts >= ? AND ts < ?
               ORDER BY ts, ingest_seq""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Trade storage
    # ------------------------------------------------------------------

    def insert_trade(
        self,
        ts: datetime,
        orderid: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        *,
        product: str = "",
        strategy: str = "",
        entry_price: float | None = None,
        exit_price: float | None = None,
        pnl: float | None = None,
        slippage: float | None = None,
        fees: float | None = None,
    ) -> None:
        """Insert a single trade row."""
        self.connection.execute(
            """INSERT INTO trades
               (ts, orderid, symbol, exchange, action, quantity, price,
                product, strategy, entry_price, exit_price, pnl, slippage, fees)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                _normalise_ts(ts),
                orderid,
                symbol,
                exchange,
                action,
                quantity,
                price,
                product,
                strategy,
                entry_price,
                exit_price,
                pnl,
                slippage,
                fees,
            ],
        )

    def get_trades_by_strategy(
        self,
        strategy: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Get trades filtered by strategy and date range."""
        start, end = _ist_date_window(start_date, end_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE strategy = ?
                 AND ts >= ? AND ts < ?
               ORDER BY ts""",
            [strategy, start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_trades_by_date(self, trade_date: str) -> list[dict[str, Any]]:
        """Get all trades for a given date."""
        start, end = _ist_date_window(trade_date, trade_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE ts >= ? AND ts < ?
               ORDER BY ts""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def get_trades_by_date_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Get all trades between two dates (inclusive), across every strategy.

        Args:
            start_date: Inclusive lower bound (``YYYY-MM-DD``).
            end_date: Inclusive upper bound (``YYYY-MM-DD``).

        Returns:
            Trade rows ordered by timestamp. Used by the journal route for
            history-window queries (e.g. the performance dashboard) where no
            single strategy is specified.
        """
        start, end = _ist_date_window(start_date, end_date)
        result = self.connection.execute(
            """SELECT ts, orderid, symbol, exchange, action, quantity, price,
                      product, strategy, entry_price, exit_price, pnl, slippage, fees
               FROM trades
               WHERE ts >= ? AND ts < ?
               ORDER BY ts""",
            [start, end],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def upsert_daily_summary(
        self,
        trade_date: date,
        strategy: str,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        gross_pnl: float,
        fees: float,
        net_pnl: float,
        max_drawdown: float = 0.0,
    ) -> None:
        """Insert or replace a daily summary row."""
        # DuckDB doesn't have UPSERT, so delete + insert
        self.connection.execute(
            "DELETE FROM daily_summary WHERE trade_date = ? AND strategy = ?",
            [trade_date, strategy],
        )
        self.connection.execute(
            """INSERT INTO daily_summary
               (trade_date, strategy, total_trades, winning_trades, losing_trades,
                gross_pnl, fees, net_pnl, max_drawdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [trade_date, strategy, total_trades, winning_trades, losing_trades, gross_pnl, fees, net_pnl, max_drawdown],
        )

    def get_daily_summaries(
        self,
        start_date: str,
        end_date: str,
        strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get daily summaries for a date range, optionally filtered by strategy."""
        if strategy:
            result = self.connection.execute(
                """SELECT trade_date, strategy, total_trades, winning_trades,
                          losing_trades, gross_pnl, fees, net_pnl, max_drawdown
                   FROM daily_summary
                   WHERE trade_date >= ? AND trade_date <= ? AND strategy = ?
                   ORDER BY trade_date""",
                [start_date, end_date, strategy],
            )
        else:
            result = self.connection.execute(
                """SELECT trade_date, strategy, total_trades, winning_trades,
                          losing_trades, gross_pnl, fees, net_pnl, max_drawdown
                   FROM daily_summary
                   WHERE trade_date >= ? AND trade_date <= ?
                   ORDER BY trade_date""",
                [start_date, end_date],
            )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_trades_csv(
        self,
        start_date: str,
        end_date: str,
        strategy: str | None = None,
    ) -> str:
        """Export trades to CSV string over the inclusive [start_date, end_date] range."""
        trades = (
            self.get_trades_by_strategy(strategy, start_date, end_date)
            if strategy
            else self.get_trades_by_date_range(start_date, end_date)
        )
        if not trades:
            return ""

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
        return output.getvalue()
