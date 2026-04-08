"""Track expired option chains for backtesting and analysis (ExpiryTrack).

Captures option chain snapshots before expiry using OpenAlgo's ``optionchain``
endpoint and stores them in DuckDB for historical analysis.

Schema: symbol, expiry_date, strike, option_type (CE/PE), oi, volume, ltp, iv

Usage::

    tracker = ExpiryTracker(client, db_path=":memory:")
    tracker.capture_snapshot("NIFTY", "260326")
    chain = tracker.get_historical_chain("NIFTY", "260326")
    expiries = tracker.list_expiries("NIFTY")
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.historical.expiry_tracker")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# DuckDB schema
# ---------------------------------------------------------------------------

_SCHEMA_OPTION_CHAIN = """
CREATE TABLE IF NOT EXISTS expired_option_chains (
    captured_at   TIMESTAMP NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    expiry_date   VARCHAR NOT NULL,
    strike        DOUBLE NOT NULL,
    option_type   VARCHAR NOT NULL,
    oi            BIGINT DEFAULT 0,
    volume        BIGINT DEFAULT 0,
    ltp           DOUBLE DEFAULT 0.0,
    iv            DOUBLE DEFAULT 0.0
);
"""

_INDEX_OPTION_CHAIN = (
    "CREATE INDEX IF NOT EXISTS idx_expired_oc_sym_exp "
    "ON expired_option_chains (symbol, expiry_date)"
)


# ---------------------------------------------------------------------------
# ExpiryTracker
# ---------------------------------------------------------------------------


class ExpiryTracker:
    """Capture and store option chain snapshots for expired expiries.

    Args:
        client: OpenAlgo client for fetching live option chain data.
        db_path: Path to the DuckDB database. Use ``":memory:"`` for tests.
    """

    def __init__(
        self,
        client: OpenAlgoClient | None = None,
        db_path: str = "",
    ) -> None:
        self._client = client
        if not db_path:
            db_path = str(Path.home() / ".flinttrade" / "data" / "expiry_tracker.duckdb")
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            if self._db_path == ":memory:":
                self._conn = duckdb.connect(":memory:")
            else:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they do not exist."""
        self.connection.execute(_SCHEMA_OPTION_CHAIN)
        self.connection.execute(_INDEX_OPTION_CHAIN)

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture_snapshot(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> int:
        """Fetch the current option chain and store it as a snapshot.

        Uses the OpenAlgo ``optionchain`` endpoint to get CE/PE data for
        all strikes at the given expiry.

        Args:
            symbol: Underlying symbol (e.g. ``"NIFTY"``).
            expiry: Expiry date string (e.g. ``"260326"`` or ``"2026-03-26"``).
            exchange: Exchange segment (default ``"NFO"``).

        Returns:
            Number of rows inserted.
        """
        if self._client is None:
            logger.error("No OpenAlgo client — cannot capture snapshot")
            return 0

        try:
            data = self._client.optionchain(symbol, exchange, expiry)
        except Exception as exc:
            logger.error("Failed to fetch option chain for %s %s: %s", symbol, expiry, exc)
            return 0

        rows = self._parse_option_chain(data, symbol, exchange, expiry)
        if not rows:
            logger.warning("No option chain data returned for %s %s", symbol, expiry)
            return 0

        now = datetime.now(IST)
        insert_rows = [
            (now, r["symbol"], r["exchange"], r["expiry_date"],
             r["strike"], r["option_type"], r["oi"], r["volume"],
             r["ltp"], r["iv"])
            for r in rows
        ]

        self.connection.executemany(
            """INSERT INTO expired_option_chains
               (captured_at, symbol, exchange, expiry_date, strike,
                option_type, oi, volume, ltp, iv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            insert_rows,
        )

        logger.info(
            "Captured %d option chain rows for %s expiry %s",
            len(insert_rows), symbol, expiry,
        )
        return len(insert_rows)

    @staticmethod
    def _parse_option_chain(
        data: Any,
        symbol: str,
        exchange: str,
        expiry: str,
    ) -> list[dict[str, Any]]:
        """Parse OpenAlgo optionchain response into flat rows.

        OpenAlgo returns the option chain in various formats depending on
        broker. This method handles the common shapes:
        - List of dicts with ``strike_price``, ``call_oi``, ``put_oi``, etc.
        - Dict with ``data`` key containing the list.
        """
        records: list[dict[str, Any]] = []

        # Unwrap nested response
        if isinstance(data, dict):
            chain_list = data.get("data", data.get("optionchain", []))
            if isinstance(chain_list, dict):
                chain_list = chain_list.get("data", [])
        elif isinstance(data, list):
            chain_list = data
        else:
            return records

        if not isinstance(chain_list, list):
            return records

        for entry in chain_list:
            if not isinstance(entry, dict):
                continue

            strike = float(entry.get("strike_price", entry.get("strike", 0)))
            if strike <= 0:
                continue

            # CE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "CE",
                "oi": int(entry.get("call_oi", entry.get("ce_oi", 0))),
                "volume": int(entry.get("call_volume", entry.get("ce_volume", 0))),
                "ltp": float(entry.get("call_ltp", entry.get("ce_ltp", 0))),
                "iv": float(entry.get("call_iv", entry.get("ce_iv", 0))),
            })

            # PE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "PE",
                "oi": int(entry.get("put_oi", entry.get("pe_oi", 0))),
                "volume": int(entry.get("put_volume", entry.get("pe_volume", 0))),
                "ltp": float(entry.get("put_ltp", entry.get("pe_ltp", 0))),
                "iv": float(entry.get("put_iv", entry.get("pe_iv", 0))),
            })

        return records

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_historical_chain(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> list[dict[str, Any]]:
        """Retrieve a stored option chain snapshot.

        Returns the most recent snapshot for the given symbol and expiry.

        Args:
            symbol: Underlying symbol.
            expiry: Expiry date string.
            exchange: Exchange segment.

        Returns:
            List of dicts with keys: strike, option_type, oi, volume, ltp, iv,
            captured_at, symbol, exchange, expiry_date.
        """
        result = self.connection.execute(
            """SELECT captured_at, symbol, exchange, expiry_date,
                      strike, option_type, oi, volume, ltp, iv
               FROM expired_option_chains
               WHERE symbol = ? AND expiry_date = ? AND exchange = ?
               ORDER BY strike, option_type""",
            [symbol, expiry, exchange],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def list_expiries(
        self,
        symbol: str,
        exchange: str = "NFO",
    ) -> list[str]:
        """List all expiry dates for which snapshots exist.

        Args:
            symbol: Underlying symbol.
            exchange: Exchange segment.

        Returns:
            Sorted list of unique expiry date strings.
        """
        result = self.connection.execute(
            """SELECT DISTINCT expiry_date
               FROM expired_option_chains
               WHERE symbol = ? AND exchange = ?
               ORDER BY expiry_date""",
            [symbol, exchange],
        )
        return [row[0] for row in result.fetchall()]
