"""Bridge to QuestDB for high-performance tick storage and aggregation.

QuestDB provides sub-millisecond queries on time-series data — ideal for
tick-level market data that DuckDB handles less efficiently at scale.

QuestDB exposes two interfaces this module uses:
  - ILP (InfluxDB Line Protocol) over TCP port 9009 — bulk tick ingestion
  - HTTP REST API port 9000 — SQL queries and health checks

ILP wire format per line::

    <table>,<tag_set> <field_set> [unix_timestamp_ns]
    ticks,symbol=NIFTY,exchange=NFO ltp=22450.5,volume=1234i 1717000000000000000

Usage::

    bridge = QuestDBBridge()
    if bridge.check_health():
        inserted = bridge.insert_ticks([
            {"symbol": "NIFTY", "exchange": "NFO", "ltp": 22450.5, "volume": 1234},
        ])
        bars = bridge.aggregate_ohlcv("NIFTY", "5m", "2026-04-08T09:15:00", "2026-04-08T15:30:00")
"""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

import httpx

logger = logging.getLogger("flinttrade.data.questdb_bridge")

# QuestDB REST API query endpoint
_QUERY_PATH = "/exec"
_HEALTH_PATH = "/health"

# ILP line format constraints
_RESERVED_CHARS = {" ", ",", "=", "\n"}


def _escape_tag(value: str) -> str:
    """Escape ILP tag values (spaces, commas, equals signs)."""
    return value.replace(",", "\\,").replace(" ", "\\ ").replace("=", "\\=")


def _build_ilp_line(tick: dict[str, Any], table: str = "ticks") -> str | None:
    """Convert a tick dict to an ILP line string.

    Required fields: ``symbol``, ``exchange``, ``ltp``
    Optional fields: ``open``, ``high``, ``low``, ``close``, ``volume``,
                     ``bid``, ``ask``, ``oi``, ``timestamp_ns``

    Returns ``None`` if required fields are missing.
    """
    symbol = tick.get("symbol", "")
    exchange = tick.get("exchange", "")
    if not symbol or not exchange:
        return None

    ltp = tick.get("ltp")
    if ltp is None:
        return None

    # Tags (indexed, low-cardinality)
    tags = f"symbol={_escape_tag(symbol)},exchange={_escape_tag(exchange)}"

    # Fields (values — at least ltp required)
    fields: list[str] = [f"ltp={float(ltp)}"]

    for float_field in ("open", "high", "low", "close", "bid", "ask"):
        val = tick.get(float_field)
        if val is not None:
            fields.append(f"{float_field}={float(val)}")

    for int_field in ("volume", "oi"):
        val = tick.get(int_field)
        if val is not None:
            fields.append(f"{int_field}={int(val)}i")

    fields_str = ",".join(fields)

    # Timestamp (nanoseconds); default to now
    ts_ns = tick.get("timestamp_ns")
    if ts_ns is None:
        ts_ns = int(time.time_ns())

    return f"{table},{tags} {fields_str} {ts_ns}"


class QuestDBBridgeError(Exception):
    """Raised when a QuestDB operation fails."""


class QuestDBBridge:
    """Bridge to QuestDB for high-performance tick storage and aggregation.

    QuestDB provides sub-millisecond queries on time-series data — ideal for
    tick-level market data that DuckDB handles less efficiently at scale.

    Args:
        host: QuestDB host (ILP and HTTP). Default ``"127.0.0.1"``.
        ilp_port: ILP TCP ingestion port. Default ``9009``.
        http_port: HTTP REST API port. Default ``9000``.
        table: ILP table name for ticks. Default ``"ticks"``.
        timeout: HTTP request timeout in seconds.

    Example::

        bridge = QuestDBBridge()
        bridge.insert_ticks([{"symbol": "RELIANCE", "exchange": "NSE", "ltp": 2980.5}])
        rows = bridge.aggregate_ohlcv("RELIANCE", "1m", "2026-04-08T09:15", "2026-04-08T15:30")
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        ilp_port: int = 9009,
        http_port: int = 9000,
        table: str = "ticks",
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.ilp_port = ilp_port
        self.http_port = http_port
        self.table = table
        self._http = httpx.Client(
            base_url=f"http://{host}:{http_port}",
            timeout=timeout,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> QuestDBBridge:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def check_health(self) -> bool:
        """Check QuestDB is running via its HTTP health endpoint.

        Returns:
            ``True`` if QuestDB responds with HTTP 200, ``False`` otherwise.
        """
        try:
            resp = self._http.get(_HEALTH_PATH)
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("QuestDB health check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # ILP tick ingestion
    # ------------------------------------------------------------------

    def insert_ticks(self, ticks: list[dict[str, Any]]) -> int:
        """Bulk insert ticks via ILP (InfluxDB Line Protocol) over TCP.

        Each tick dict must have: ``symbol``, ``exchange``, ``ltp``.
        Optional: ``open``, ``high``, ``low``, ``close``, ``volume``,
        ``bid``, ``ask``, ``oi``, ``timestamp_ns``.

        Args:
            ticks: List of tick dictionaries.

        Returns:
            Number of ticks successfully sent.

        Raises:
            QuestDBBridgeError: If the TCP connection fails.
        """
        if not ticks:
            return 0

        lines: list[str] = []
        for tick in ticks:
            line = _build_ilp_line(tick, self.table)
            if line:
                lines.append(line)

        if not lines:
            logger.warning("insert_ticks: no valid ticks to insert (missing required fields)")
            return 0

        payload = "\n".join(lines) + "\n"

        try:
            with socket.create_connection((self.host, self.ilp_port), timeout=10) as sock:
                sock.sendall(payload.encode("utf-8"))
        except OSError as exc:
            raise QuestDBBridgeError(
                f"QuestDB ILP TCP connection to {self.host}:{self.ilp_port} failed: {exc}"
            ) from exc

        count = len(lines)
        logger.debug("QuestDB ILP: sent %d lines", count)
        return count

    # ------------------------------------------------------------------
    # SQL queries
    # ------------------------------------------------------------------

    def query(self, sql: str) -> list[dict[str, Any]]:
        """Execute a SQL query via QuestDB's REST API.

        Calls ``GET /exec?query=<sql>`` and parses the columnar response
        into a list of row dicts.

        Args:
            sql: SQL query string.

        Returns:
            List of row dicts, e.g.
            ``[{"symbol": "NIFTY", "ltp": 22450.5, ...}, ...]``

        Raises:
            QuestDBBridgeError: If the request fails or QuestDB returns an error.
        """
        try:
            resp = self._http.get(_QUERY_PATH, params={"query": sql})
        except Exception as exc:
            raise QuestDBBridgeError(f"QuestDB query request failed: {exc}") from exc

        if resp.status_code != 200:
            raise QuestDBBridgeError(
                f"QuestDB query returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        body: dict[str, Any] = resp.json()

        # QuestDB returns {"columns": [...], "dataset": [[...], ...], "error": "..."}
        error = body.get("error")
        if error:
            raise QuestDBBridgeError(f"QuestDB query error: {error}")

        columns: list[dict[str, str]] = body.get("columns", [])
        dataset: list[list[Any]] = body.get("dataset", [])

        col_names = [col["name"] for col in columns]
        rows = [dict(zip(col_names, row)) for row in dataset]
        logger.debug("QuestDB query: %d rows returned", len(rows))
        return rows

    def aggregate_ohlcv(
        self,
        symbol: str,
        interval: str,
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        """Aggregate ticks into OHLCV bars using QuestDB's SAMPLE BY clause.

        Uses QuestDB's time-series ``SAMPLE BY`` aggregation for high-performance
        OHLCV bar computation directly in the database.

        Args:
            symbol: Instrument symbol, e.g. ``"NIFTY"``.
            interval: Bar interval string. QuestDB format: ``"1m"``, ``"5m"``,
                ``"15m"``, ``"1h"``, ``"1d"``.
            start: ISO 8601 start timestamp, e.g. ``"2026-04-08T09:15:00"``.
            end: ISO 8601 end timestamp, e.g. ``"2026-04-08T15:30:00"``.

        Returns:
            List of OHLCV bar dicts with keys:
            ``timestamp``, ``open``, ``high``, ``low``, ``close``, ``volume``.

        Raises:
            QuestDBBridgeError: If the query fails.
        """
        sql = (
            f"SELECT timestamp, first(ltp) AS open, max(ltp) AS high, "
            f"min(ltp) AS low, last(ltp) AS close, sum(volume) AS volume "
            f"FROM '{self.table}' "
            f"WHERE symbol = '{symbol}' "
            f"AND timestamp BETWEEN '{start}' AND '{end}' "
            f"SAMPLE BY {interval} ALIGN TO CALENDAR"
        )
        return self.query(sql)

    def get_latest_tick(self, symbol: str) -> dict[str, Any] | None:
        """Get the most recent tick for a symbol.

        Args:
            symbol: Instrument symbol, e.g. ``"RELIANCE"``.

        Returns:
            Most recent tick dict, or ``None`` if no data exists for the symbol.

        Raises:
            QuestDBBridgeError: If the query fails.
        """
        sql = (
            f"SELECT * FROM '{self.table}' "
            f"WHERE symbol = '{symbol}' "
            f"ORDER BY timestamp DESC LIMIT 1"
        )
        rows = self.query(sql)
        return rows[0] if rows else None
