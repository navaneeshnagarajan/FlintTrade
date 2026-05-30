"""Persistent order round-trip latency monitor backed by DuckDB.

Extends the in-memory :class:`~flinttrade_core.monitoring.LatencyTracker`
with DuckDB persistence so that latency history survives process restarts
and can be queried by time window, broker, or order type.

Tracks every order submission → confirmation round-trip with full context
(broker, order_type, status).  Supports percentile statistics, histogram
bucketing for charting, and "slowest N" queries for debugging.

Admin REST routes (registered from ``flinttrade_core.app.create_flask_app``):

- ``GET /v1/admin/latency/stats``       — per-broker percentile summary
- ``GET /v1/admin/latency/histogram``   — histogram for a broker
- ``GET /v1/admin/latency/slow``        — top-N slowest records

Example::

    from flinttrade_engine.latency_monitor import LatencyMonitor

    mon = LatencyMonitor(":memory:")
    mon.record("ZERODHA", "PLACE", 42.1)
    pcts = mon.percentiles("ZERODHA")
    assert pcts["count"] == 1
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.engine.latency_monitor")

# IST as a fixed-offset timezone.
IST = timezone(timedelta(hours=5, minutes=30))

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS latency_log (
    entry_id    VARCHAR PRIMARY KEY,
    timestamp   TIMESTAMP NOT NULL,
    broker      VARCHAR   NOT NULL,
    order_type  VARCHAR   NOT NULL,
    latency_ms  DOUBLE    NOT NULL,
    status      VARCHAR   NOT NULL DEFAULT 'SUCCESS',
    symbol      VARCHAR,
    user_id     VARCHAR
)
"""

_INDEX_SQL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_latlog_ts     ON latency_log(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_latlog_broker ON latency_log(broker)",
    "CREATE INDEX IF NOT EXISTS idx_latlog_type   ON latency_log(order_type)",
]


class LatencyMonitor:
    """Persistent order round-trip latency tracker backed by DuckDB.

    Complements the in-memory :class:`~flinttrade_core.monitoring.LatencyTracker`
    by persisting every measurement to DuckDB for long-term analysis and
    admin dashboard queries.

    Thread-safe — DuckDB handles concurrent writes within the same process.

    Args:
        db_path: Path to the DuckDB file.  Defaults to
            ``~/.flinttrade/latency_log.duckdb``.  Pass ``":memory:"`` for
            ephemeral in-process storage (useful in tests).

    Example::

        mon = LatencyMonitor(":memory:")
        mon.record("ZERODHA", "PLACE", 42.5)
        stats = mon.percentiles()
        assert "ZERODHA" in stats
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        import duckdb  # lazy import

        if db_path is None:
            db_path = Path.home() / ".flinttrade" / "latency_log.duckdb"

        if isinstance(db_path, str) and db_path != ":memory:":
            db_path = Path(db_path)

        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path: str = str(db_path)
        else:
            self._db_path = str(db_path)

        self._conn = duckdb.connect(self._db_path)
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create table and indexes if they do not already exist."""
        self._conn.execute(_CREATE_TABLE_SQL)
        for idx_sql in _INDEX_SQL:
            self._conn.execute(idx_sql)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        broker: str,
        order_type: str,
        latency_ms: float,
        status: str = "SUCCESS",
        symbol: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Persist a single order latency measurement.

        Args:
            broker: Broker identifier (e.g. ``"ZERODHA"``).
            order_type: Order operation type (e.g. ``"PLACE"``,
                ``"MODIFY"``, ``"CANCEL"``).
            latency_ms: Round-trip latency in milliseconds.
            status: ``"SUCCESS"`` or ``"FAILED"`` (default ``"SUCCESS"``).
            symbol: Instrument symbol, if available.
            user_id: Authenticated user identifier, if available.

        Returns:
            The ``entry_id`` assigned to this record (16-char hex string).
        """
        entry_id = secrets.token_hex(8)
        timestamp = datetime.now(IST)

        self._conn.execute(
            """
            INSERT INTO latency_log
                (entry_id, timestamp, broker, order_type, latency_ms,
                 status, symbol, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                entry_id,
                timestamp,
                broker,
                order_type,
                round(latency_ms, 3),
                status,
                symbol,
                user_id,
            ],
        )
        logger.debug(
            "Latency: broker=%s type=%s %.1fms status=%s entry_id=%s",
            broker, order_type, latency_ms, status, entry_id,
        )
        return entry_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def percentiles(
        self,
        broker: str | None = None,
        window_minutes: int = 60,
    ) -> dict[str, Any]:
        """Return latency percentile statistics.

        When *broker* is provided, returns stats for that broker only.
        Otherwise returns an aggregate across all brokers.

        Args:
            broker: Broker filter, or ``None`` for all brokers.
            window_minutes: Lookback window in minutes (default 60).

        Returns:
            Dict with keys: ``p50``, ``p95``, ``p99``, ``mean``, ``count``.
        """
        cutoff = datetime.now(IST) - timedelta(minutes=window_minutes)

        conditions = ["timestamp >= ?"]
        params: list[Any] = [cutoff]
        if broker is not None:
            conditions.append("broker = ?")
            params.append(broker)

        where = "WHERE " + " AND ".join(conditions)

        row = self._conn.execute(
            f"""
            SELECT
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99,
                AVG(latency_ms)                                           AS mean,
                COUNT(*)                                                  AS cnt
            FROM latency_log {where}
            """,
            params,
        ).fetchone()

        if row is None or row[4] == 0:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0, "count": 0}

        return {
            "p50": round(float(row[0] or 0), 2),
            "p95": round(float(row[1] or 0), 2),
            "p99": round(float(row[2] or 0), 2),
            "mean": round(float(row[3] or 0), 2),
            "count": int(row[4]),
        }

    def percentiles_by_broker(
        self,
        window_minutes: int = 60,
    ) -> dict[str, dict[str, Any]]:
        """Return per-broker percentile statistics.

        Args:
            window_minutes: Lookback window in minutes (default 60).

        Returns:
            Dict mapping broker name → ``{p50, p95, p99, mean, count}``.
        """
        cutoff = datetime.now(IST) - timedelta(minutes=window_minutes)

        rows = self._conn.execute(
            """
            SELECT
                broker,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99,
                AVG(latency_ms)                                           AS mean,
                COUNT(*)                                                  AS cnt
            FROM latency_log
            WHERE timestamp >= ?
            GROUP BY broker
            ORDER BY broker
            """,
            [cutoff],
        ).fetchall()

        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result[row[0]] = {
                "p50": round(float(row[1] or 0), 2),
                "p95": round(float(row[2] or 0), 2),
                "p99": round(float(row[3] or 0), 2),
                "mean": round(float(row[4] or 0), 2),
                "count": int(row[5]),
            }
        return result

    def histogram(
        self,
        broker: str,
        bins: int = 20,
        window_minutes: int = 60,
    ) -> list[dict[str, Any]]:
        """Return histogram buckets for rendering a latency distribution chart.

        Splits the [min, max] latency range into *bins* equal-width buckets
        and counts observations in each.

        Args:
            broker: Broker identifier to compute the histogram for.
            bins: Number of histogram buckets (default 20).
            window_minutes: Lookback window in minutes (default 60).

        Returns:
            List of dicts each with keys ``bucket_start``, ``bucket_end``,
            ``count``.  Empty list when there is no data.
        """
        bins = max(2, min(int(bins), 100))
        cutoff = datetime.now(IST) - timedelta(minutes=window_minutes)

        range_row = self._conn.execute(
            """
            SELECT MIN(latency_ms), MAX(latency_ms), COUNT(*)
            FROM latency_log
            WHERE broker = ? AND timestamp >= ?
            """,
            [broker, cutoff],
        ).fetchone()

        if not range_row or not range_row[2]:
            return []

        min_ms: float = float(range_row[0])
        max_ms: float = float(range_row[1])
        total: int = int(range_row[2])

        if total == 0 or min_ms == max_ms:
            # Single unique value — return one bucket.
            return [{"bucket_start": min_ms, "bucket_end": max_ms, "count": total}]

        bucket_width = (max_ms - min_ms) / bins

        # Pull all latencies and bin in Python to avoid DuckDB width_bucket portability issues.
        lat_rows = self._conn.execute(
            """
            SELECT latency_ms
            FROM latency_log
            WHERE broker = ? AND timestamp >= ?
            """,
            [broker, cutoff],
        ).fetchall()

        counts = [0] * bins
        for (lat,) in lat_rows:
            idx = int((float(lat) - min_ms) / bucket_width)
            idx = min(idx, bins - 1)  # clamp last observation
            counts[idx] += 1

        result: list[dict[str, Any]] = []
        for i in range(bins):
            result.append(
                {
                    "bucket_start": round(min_ms + i * bucket_width, 2),
                    "bucket_end": round(min_ms + (i + 1) * bucket_width, 2),
                    "count": counts[i],
                }
            )
        return result

    def slowest_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the slowest *limit* recent order records.

        Args:
            limit: Number of records to return (default 10, clamped to 200).

        Returns:
            List of dicts with keys ``entry_id``, ``timestamp``, ``broker``,
            ``order_type``, ``latency_ms``, ``status``, ``symbol``, ``user_id``.
        """
        limit = max(1, min(int(limit), 200))

        rows = self._conn.execute(
            """
            SELECT entry_id, timestamp, broker, order_type, latency_ms,
                   status, symbol, user_id
            FROM latency_log
            ORDER BY latency_ms DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            ts = row[1]
            ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            result.append(
                {
                    "entry_id": row[0],
                    "timestamp": ts_str,
                    "broker": row[2],
                    "order_type": row[3],
                    "latency_ms": row[4],
                    "status": row[5],
                    "symbol": row[6],
                    "user_id": row[7],
                }
            )
        return result

    def count(self, broker: str | None = None) -> int:
        """Count persisted latency records.

        Args:
            broker: Optional broker filter.

        Returns:
            Integer row count.
        """
        if broker is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM latency_log WHERE broker = ?", [broker]
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM latency_log"
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> "LatencyMonitor":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
