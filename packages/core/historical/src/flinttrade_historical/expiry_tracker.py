"""Track expired option chains for backtesting and analysis (ExpiryTrack).

Captures option chain snapshots before expiry using OpenAlgo's ``optionchain``
endpoint and stores them in DuckDB for historical analysis.

Adapts patterns from MarketCalls/ExpiryFlow:
- DuckDB schema with composite primary keys and download metadata tracking
- Date-chunked downloads with skip-if-exists deduplication
- Thread-safe rate limiting for broker API calls
- Migration tracking via ``_migrations`` table

Schema: symbol, expiry_date, strike, option_type (CE/PE), oi, volume, ltp, iv

Usage::

    tracker = ExpiryTracker(client, db_path=":memory:")
    tracker.capture_snapshot("NIFTY", "260326")
    chain = tracker.get_historical_chain("NIFTY", "260326")
    expiries = tracker.list_expiries("NIFTY")
"""

from __future__ import annotations

import logging
import asyncio
import inspect
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb

from flinttrade_core.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.historical.expiry_tracker")


def _legacy_db_path() -> Path:
    """Return the pre-``workspace_dir()`` tracker DB location.

    Module-level so tests can monkeypatch the probe away from the real home
    directory.

    Returns:
        ``<legacy dot-directory>/data/expiry_tracker.duckdb`` — the fixed
        ``~/.flinttrade`` root every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / "data" / "expiry_tracker.duckdb"


def _migrate_legacy_expiry_db(legacy: Path, new: Path) -> None:
    """Copy a pre-``workspace_dir()`` tracker DB into the workspace once.

    The default DB path moved from the hardcoded
    ``~/.flinttrade/data/expiry_tracker.duckdb`` to
    ``workspace_dir()/data/expiry_tracker.duckdb`` (macOS: ``~/Library/
    Application Support/flinttrade``; Windows: ``%APPDATA%/flinttrade``).
    Delegates to the shared workspace copy machinery, which copies — never
    moves — the DB together with its DuckDB ``.wal`` sidecar, retains the
    legacy family as a backup, serialises concurrent callers on a migration
    lock, and treats an existing workspace copy as the winner. No-op on Linux
    where the two paths coincide. (Sibling migration:
    ``flinttrade_historical.watchlist_routes._migrate_legacy_watchlist_db``.)

    Args:
        legacy: Pre-workspace tracker DB to copy from.
        new: Destination inside the active workspace.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The copy could
            not be completed; the legacy DB is retained.
    """
    from flinttrade_core.workspace import copy_legacy_database_once  # noqa: PLC0415

    copy_legacy_database_once(
        legacy,
        new,
        sidecar_suffixes=(".wal",),
        lock_name=".expiry-tracker-migration.lock",
        label="expiry tracker DB",
    )


def _default_db_path() -> Path:
    """Resolve the workspace-scoped default DB path, migrating any legacy file.

    Uses :func:`flinttrade_core.workspace.workspace_dir` so the tracker honours
    ``FLINTTRADE_WORKSPACE_DIR``/``FLINTTRADE_HOME`` and the platform-specific
    workspace root instead of the old hardcoded ``~/.flinttrade``.

    Returns:
        Absolute path of ``expiry_tracker.duckdb`` under the workspace's
        ``data`` directory.
    """
    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    new = workspace_dir() / "data" / "expiry_tracker.duckdb"
    _migrate_legacy_expiry_db(_legacy_db_path(), new)
    return new

# Any object exposing one of these is treated as a client, not a provider.
_CHAIN_METHOD_NAMES = ("get_option_chain", "option_chain", "optionchain")

IST = timezone(timedelta(hours=5, minutes=30))
_CAPTURE_WRITE_LOCK = threading.Lock()


def _parse_expiry(expiry: str) -> date | None:
    """Parse every expiry format accepted by historical capture."""
    value = expiry.strip().upper()
    for date_format in ("%Y-%m-%d", "%y%m%d", "%d%b%y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue
    return None


def normalise_expiry(expiry: str) -> str:
    """Return an ISO expiry when recognised, preserving unknown broker values."""
    parsed = _parse_expiry(expiry)
    return parsed.isoformat() if parsed is not None else expiry.strip().upper()


def _expiry_aliases(expiry: str) -> tuple[str, ...]:
    """Return canonical and legacy spellings for one expiry date."""
    raw = expiry.strip().upper()
    parsed = _parse_expiry(raw)
    if parsed is None:
        return (raw,)
    values = (
        parsed.isoformat(),
        parsed.strftime("%y%m%d"),
        parsed.strftime("%d%b%y").upper(),
        raw,
    )
    return tuple(dict.fromkeys(values))

# ---------------------------------------------------------------------------
# Rate limiter (adapted from ExpiryFlow's DataApiRateLimiter)
# ---------------------------------------------------------------------------

_MAX_DAYS_PER_CHUNK = 30


class SnapshotRateLimiter:
    """Thread-safe rate limiter for snapshot capture API calls.

    Prevents overwhelming the broker API when bulk-capturing snapshots.
    Pattern adapted from ExpiryFlow's ``DataApiRateLimiter``.

    Args:
        max_per_second: Maximum API calls per second.
        max_per_day: Maximum API calls per day (0 = unlimited).
    """

    def __init__(
        self,
        max_per_second: int = 5,
        max_per_day: int = 0,
    ) -> None:
        self._max_per_second = max_per_second
        self._max_per_day = max_per_day
        self._second_timestamps: list[float] = []
        self._day_count = 0
        self._day_start = time.time()
        self._lock = threading.Lock()

    def wait_if_needed(self) -> None:
        """Block until a request slot is available.

        Raises:
            RuntimeError: If the daily limit has been reached.
        """
        with self._lock:
            now = time.time()
            # Reset daily counter after 24h
            if now - self._day_start >= 86400:
                self._day_count = 0
                self._day_start = now
            if self._max_per_day > 0 and self._day_count >= self._max_per_day:
                raise RuntimeError(
                    f"Daily API limit reached ({self._max_per_day} requests)"
                )
            # Enforce per-second limit
            self._second_timestamps = [
                t for t in self._second_timestamps if now - t < 1.0
            ]
            if len(self._second_timestamps) >= self._max_per_second:
                sleep_time = 1.0 - (now - self._second_timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
            self._second_timestamps.append(time.time())
            self._day_count += 1

    @property
    def requests_today(self) -> int:
        """Number of requests made since the daily counter last reset."""
        return self._day_count


# ---------------------------------------------------------------------------
# DuckDB schema (enhanced with ExpiryFlow patterns: metadata + migrations)
# ---------------------------------------------------------------------------

_SCHEMA_OPTION_CHAIN = """
CREATE TABLE IF NOT EXISTS expired_option_chains (
    captured_at   TIMESTAMP NOT NULL,
    snapshot_id   VARCHAR NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    expiry_date   VARCHAR NOT NULL,
    strike        DOUBLE NOT NULL,
    option_type   VARCHAR NOT NULL,
    oi            BIGINT DEFAULT 0,
    volume        BIGINT DEFAULT 0,
    ltp           DOUBLE DEFAULT 0.0,
    iv            DOUBLE DEFAULT 0.0,
    PRIMARY KEY (symbol, expiry_date, strike, option_type, captured_at)
);
"""

_INDEX_OPTION_CHAIN = (
    "CREATE INDEX IF NOT EXISTS idx_expired_oc_sym_exp "
    "ON expired_option_chains (symbol, expiry_date)"
)

_SCHEMA_DOWNLOAD_METADATA = """
CREATE TABLE IF NOT EXISTS download_metadata (
    id              INTEGER PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    exchange        VARCHAR NOT NULL,
    expiry_date     VARCHAR NOT NULL,
    from_date       DATE NOT NULL,
    to_date         DATE NOT NULL,
    row_count       INTEGER NOT NULL DEFAULT 0,
    downloaded_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_SCHEMA_DOWNLOAD_SEQ = (
    "CREATE SEQUENCE IF NOT EXISTS download_metadata_id_seq START 1"
)

_SCHEMA_MIGRATIONS = (
    "CREATE TABLE IF NOT EXISTS _migrations (name VARCHAR PRIMARY KEY)"
)


# ---------------------------------------------------------------------------
# ExpiryTracker
# ---------------------------------------------------------------------------


class ExpiryTracker:
    """Capture and store option chain snapshots for expired expiries.

    Enhanced with patterns from ExpiryFlow:
    - Download metadata tracking (skip-if-exists deduplication)
    - Date range chunking for bulk captures
    - Rate limiting for broker API calls
    - Migration tracking

    Args:
        client: OpenAlgo client for fetching live option chain data, OR a
            zero-argument callable returning the CURRENT client (e.g.
            ``flinttrade_core.openalgo_client.get_openalgo_client``). Passing a
            provider keeps the tracker resolving the authoritative shared
            client across startup fallback and settings hot-reload. Normal hot
            reload reconfigures that object in place rather than closing it.
        db_path: Path to the DuckDB database. Use ``":memory:"`` for tests.
        rate_limiter: Optional rate limiter. A default (5 req/s) is created
            if ``None``.
    """

    def __init__(
        self,
        client: OpenAlgoClient | Callable[[], Any] | None = None,
        db_path: str = "",
        rate_limiter: SnapshotRateLimiter | None = None,
    ) -> None:
        self._client = client
        if not db_path:
            db_path = str(_default_db_path())
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._rate_limiter = rate_limiter or SnapshotRateLimiter()
        self.last_capture_error: str | None = None
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
        """Create tables, indexes, and run pending migrations.

        Follows ExpiryFlow's migration pattern: a ``_migrations`` table
        records which schema changes have already been applied.
        """
        self.connection.execute(_SCHEMA_MIGRATIONS)
        self.connection.execute(_SCHEMA_OPTION_CHAIN)
        table_info = self.connection.execute(
            "PRAGMA table_info('expired_option_chains')"
        ).fetchall()
        columns = {row[1] for row in table_info}
        if "snapshot_id" not in columns:
            self.connection.execute(
                "ALTER TABLE expired_option_chains ADD COLUMN snapshot_id VARCHAR"
            )
            table_info = self.connection.execute(
                "PRAGMA table_info('expired_option_chains')"
            ).fetchall()
        legacy_groups = self.connection.execute(
            """SELECT DISTINCT symbol, exchange, expiry_date, captured_at
               FROM expired_option_chains
               WHERE snapshot_id IS NULL
               ORDER BY symbol, exchange, expiry_date, captured_at"""
        ).fetchall()
        for symbol, exchange, expiry_date, captured_at in legacy_groups:
            legacy_snapshot_id = "legacy-" + uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"flinttrade:expiry-snapshot:{symbol}:{exchange}:{expiry_date}:{captured_at}",
            ).hex
            self.connection.execute(
                """UPDATE expired_option_chains
                   SET snapshot_id = ?
                   WHERE snapshot_id IS NULL AND symbol = ? AND exchange = ?
                     AND expiry_date = ? AND captured_at = ?""",
                [legacy_snapshot_id, symbol, exchange, expiry_date, captured_at],
            )
        snapshot_column = next(row for row in table_info if row[1] == "snapshot_id")
        if not snapshot_column[3]:
            self.connection.execute("DROP INDEX IF EXISTS idx_expired_oc_sym_exp")
            self.connection.execute(
                "ALTER TABLE expired_option_chains ALTER COLUMN snapshot_id SET NOT NULL"
            )
        self.connection.execute(
            "INSERT OR IGNORE INTO _migrations VALUES ('expired_option_chains_snapshot_id_v1')"
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO _migrations VALUES ('expired_option_chains_snapshot_id_backfill_v2')"
        )
        self.connection.execute(_INDEX_OPTION_CHAIN)
        self.connection.execute(_SCHEMA_DOWNLOAD_METADATA)
        self.connection.execute(_SCHEMA_DOWNLOAD_SEQ)

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
        self.last_capture_error = None
        client = self._resolve_client()
        if client is None:
            self.last_capture_error = "No OpenAlgo client configured"
            logger.error("No OpenAlgo client configured — cannot capture snapshot")
            return 0

        try:
            data = self._fetch_option_chain(client, symbol, exchange, expiry)
        except Exception as exc:
            self.last_capture_error = str(exc)
            logger.error("Failed to fetch option chain for %s %s: %s", symbol, expiry, exc)
            return 0

        canonical_expiry = normalise_expiry(expiry)
        rows = self._parse_option_chain(data, symbol, exchange, canonical_expiry)
        if not rows:
            logger.warning("No option chain data returned for %s %s", symbol, expiry)
            return 0

        snapshot_id = uuid.uuid4().hex
        with _CAPTURE_WRITE_LOCK:
            now = datetime.now(IST).replace(tzinfo=None)
            latest = self.connection.execute(
                """SELECT MAX(captured_at) FROM expired_option_chains
                   WHERE symbol = ? AND expiry_date = ? AND exchange = ?""",
                [symbol, canonical_expiry, exchange],
            ).fetchone()
            if latest is not None and latest[0] is not None and now <= latest[0]:
                now = latest[0] + timedelta(microseconds=1)

            insert_rows = [
                (now, snapshot_id, r["symbol"], r["exchange"], r["expiry_date"],
                 r["strike"], r["option_type"], r["oi"], r["volume"],
                 r["ltp"], r["iv"])
                for r in rows
            ]

            self.connection.executemany(
                """INSERT INTO expired_option_chains
                   (captured_at, snapshot_id, symbol, exchange, expiry_date,
                    strike, option_type, oi, volume, ltp, iv)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                insert_rows,
            )

            self._record_download(
                symbol, exchange, canonical_expiry, len(insert_rows)
            )

        logger.info(
            "Captured %d option chain rows for %s expiry %s",
            len(insert_rows), symbol, expiry,
        )
        return len(insert_rows)

    def _resolve_client(self) -> Any | None:
        """Return the client to use for THIS capture call.

        ``self._client`` may be a client instance or a zero-argument provider
        callable. Resolving per call keeps the tracker on the authoritative
        client if startup fallback replaces it; normal settings hot-reload now
        reconfigures the shared object in place.
        Provider detection: a plain callable that exposes none of the
        option-chain methods is treated as a provider; client objects (and
        test mocks, which expose every attribute) are returned as-is.
        """
        candidate = self._client
        if candidate is None:
            return None
        if callable(candidate) and not any(
            callable(getattr(candidate, name, None)) for name in _CHAIN_METHOD_NAMES
        ):
            try:
                return candidate()
            except Exception as exc:  # noqa: BLE001 - capture reports "no client"
                logger.warning("OpenAlgo client provider failed for ExpiryTracker: %s", exc)
                return None
        return candidate

    def _fetch_option_chain(self, client: Any, symbol: str, exchange: str, expiry: str) -> Any:
        """Call the given broker/OpenAlgo client using supported chain shapes."""
        if client is None:
            raise RuntimeError("No OpenAlgo client configured")

        payload = {
            "symbol": symbol,
            "underlying": symbol,
            "exchange": exchange,
            "expiry": expiry,
            "expiry_date": expiry.replace("-", ""),
        }
        attempts: list[tuple[str, tuple[Any, ...]]] = [
            ("get_option_chain", (payload,)),
            ("option_chain", (symbol, exchange, expiry)),
            ("option_chain", (symbol, exchange)),
            ("option_chain", (symbol,)),
            ("optionchain", (symbol, exchange, expiry)),
            ("optionchain", (symbol, exchange)),
            ("optionchain", (symbol,)),
        ]

        last_type_error: TypeError | None = None
        for method_name, args in attempts:
            method = getattr(client, method_name, None)
            if not callable(method):
                continue
            try:
                return self._resolve_client_result(method(*args))
            except TypeError as exc:
                last_type_error = exc
                continue

        if last_type_error is not None:
            raise last_type_error
        raise AttributeError("Configured client does not expose an option-chain method")

    @staticmethod
    def _resolve_client_result(value: Any) -> Any:
        """Resolve async client calls from this synchronous capture API."""
        if not inspect.isawaitable(value):
            return value
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)
        raise RuntimeError("capture_snapshot cannot resolve async option-chain calls inside a running event loop")

    @staticmethod
    def _as_mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            return dumped if isinstance(dumped, dict) else None
        legacy_dict = getattr(value, "dict", None)
        if callable(legacy_dict):
            dumped = legacy_dict()
            return dumped if isinstance(dumped, dict) else None
        return None

    @staticmethod
    def _get_number(entry: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
        for key in keys:
            value = entry.get(key)
            if value not in (None, ""):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return default
        return default

    @staticmethod
    def _get_int(entry: dict[str, Any], keys: tuple[str, ...]) -> int:
        return int(ExpiryTracker._get_number(entry, keys, 0.0))

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

        # Unwrap typed clients, OpenAlgo envelopes, and gateway/native shapes.
        data_map = ExpiryTracker._as_mapping(data)
        if data_map is not None:
            chain_list = data_map.get(
                "chain",
                data_map.get("strikes", data_map.get("data", data_map.get("optionchain", []))),
            )
            if isinstance(chain_list, dict):
                chain_map = ExpiryTracker._as_mapping(chain_list) or {}
                chain_list = chain_map.get("chain", chain_map.get("strikes", chain_map.get("data", [])))
        elif isinstance(data, list):
            chain_list = data
        else:
            return records

        if not isinstance(chain_list, list):
            return records

        for entry in chain_list:
            entry_map = ExpiryTracker._as_mapping(entry)
            if entry_map is None:
                continue

            strike = ExpiryTracker._get_number(entry_map, ("strike_price", "strike", "strikePrice"))
            if strike <= 0:
                continue

            ce = ExpiryTracker._as_mapping(entry_map.get("ce")) or {}
            pe = ExpiryTracker._as_mapping(entry_map.get("pe")) or {}

            # CE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "CE",
                "oi": ExpiryTracker._get_int(ce, ("oi", "open_interest"))
                or ExpiryTracker._get_int(entry_map, ("call_oi", "ce_oi")),
                "volume": ExpiryTracker._get_int(ce, ("volume",))
                or ExpiryTracker._get_int(entry_map, ("call_volume", "ce_volume")),
                "ltp": ExpiryTracker._get_number(ce, ("ltp", "last_price"))
                or ExpiryTracker._get_number(entry_map, ("call_ltp", "ce_ltp")),
                "iv": ExpiryTracker._get_number(ce, ("iv", "implied_volatility"))
                or ExpiryTracker._get_number(entry_map, ("call_iv", "ce_iv")),
            })

            # PE row
            records.append({
                "symbol": symbol,
                "exchange": exchange,
                "expiry_date": expiry,
                "strike": strike,
                "option_type": "PE",
                "oi": ExpiryTracker._get_int(pe, ("oi", "open_interest"))
                or ExpiryTracker._get_int(entry_map, ("put_oi", "pe_oi")),
                "volume": ExpiryTracker._get_int(pe, ("volume",))
                or ExpiryTracker._get_int(entry_map, ("put_volume", "pe_volume")),
                "ltp": ExpiryTracker._get_number(pe, ("ltp", "last_price"))
                or ExpiryTracker._get_number(entry_map, ("put_ltp", "pe_ltp")),
                "iv": ExpiryTracker._get_number(pe, ("iv", "implied_volatility"))
                or ExpiryTracker._get_number(entry_map, ("put_iv", "pe_iv")),
            })

        return records

    # ------------------------------------------------------------------
    # Download metadata (adapted from ExpiryFlow)
    # ------------------------------------------------------------------

    def has_snapshot(
        self,
        symbol: str,
        expiry: str,
        exchange: str = "NFO",
    ) -> bool:
        """Check whether a snapshot already exists for this symbol/expiry.

        Adapted from ExpiryFlow's ``_has_data`` skip-if-exists pattern:
        avoids redundant API calls when data has already been captured.

        Args:
            symbol: Underlying symbol.
            expiry: Expiry date string.
            exchange: Exchange segment.

        Returns:
            True if at least one row exists for this combination.
        """
        aliases = _expiry_aliases(expiry)
        placeholders = ", ".join("?" for _ in aliases)
        row = self.connection.execute(
            f"""SELECT COUNT(*) FROM download_metadata
                WHERE symbol = ? AND expiry_date IN ({placeholders})
                  AND exchange = ?""",  # noqa: S608 - placeholders only
            [symbol, *aliases, exchange],
        ).fetchone()
        return row is not None and row[0] > 0

    def _record_download(
        self,
        symbol: str,
        exchange: str,
        expiry: str,
        row_count: int,
    ) -> None:
        """Record a successful download in the metadata table.

        Args:
            symbol: Underlying symbol.
            exchange: Exchange segment.
            expiry: Expiry date string.
            row_count: Number of rows captured.
        """
        today = date.today()
        self.connection.execute(
            """INSERT INTO download_metadata
               (id, symbol, exchange, expiry_date, from_date, to_date,
                row_count, downloaded_at)
               VALUES (nextval('download_metadata_id_seq'),
                       ?, ?, ?, ?::DATE, ?::DATE, ?, CURRENT_TIMESTAMP)""",
            [symbol, exchange, expiry, today.isoformat(), today.isoformat(), row_count],
        )

    def get_download_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent download metadata records.

        Adapted from ExpiryFlow's ``get_download_history``.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts with download metadata.
        """
        result = self.connection.execute(
            """SELECT symbol, exchange, expiry_date, from_date, to_date,
                      row_count, downloaded_at
               FROM download_metadata
               ORDER BY downloaded_at DESC
               LIMIT ?""",
            [limit],
        )
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    # ------------------------------------------------------------------
    # Bulk capture (adapted from ExpiryFlow's download_service)
    # ------------------------------------------------------------------

    def capture_multiple(
        self,
        symbol: str,
        expiries: list[str],
        exchange: str = "NFO",
        skip_existing: bool = True,
    ) -> dict[str, int]:
        """Capture snapshots for multiple expiries with rate limiting.

        Adapted from ExpiryFlow's ``run_download_job`` pattern:
        - Iterates over expiries
        - Skips already-downloaded data
        - Rate-limits API calls

        Args:
            symbol: Underlying symbol.
            expiries: List of expiry date strings.
            exchange: Exchange segment.
            skip_existing: If True, skip expiries that already have data.

        Returns:
            Dict mapping expiry to row count captured (0 if skipped).
        """
        results: dict[str, int] = {}
        for expiry in expiries:
            if skip_existing and self.has_snapshot(symbol, expiry, exchange):
                logger.info(
                    "Skipping %s %s — snapshot already exists", symbol, expiry
                )
                results[expiry] = 0
                continue
            try:
                self._rate_limiter.wait_if_needed()
                count = self.capture_snapshot(symbol, expiry, exchange)
                results[expiry] = count
            except RuntimeError as exc:
                logger.error("Rate limit hit during bulk capture: %s", exc)
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to capture %s %s: %s", symbol, expiry, exc
                )
                results[expiry] = 0
        return results

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
        aliases = _expiry_aliases(expiry)
        placeholders = ", ".join("?" for _ in aliases)
        latest = self.connection.execute(
            f"""SELECT snapshot_id, captured_at
                FROM expired_option_chains
                WHERE symbol = ? AND expiry_date IN ({placeholders})
                  AND exchange = ?
                ORDER BY captured_at DESC, snapshot_id DESC NULLS LAST
                LIMIT 1""",  # noqa: S608 - placeholders only
            [symbol, *aliases, exchange],
        ).fetchone()
        if latest is None:
            return []

        snapshot_id, _captured_at = latest

        result = self.connection.execute(
            f"""SELECT captured_at, symbol, exchange, expiry_date,
                       strike, option_type, oi, volume, ltp, iv
                FROM expired_option_chains
                WHERE symbol = ? AND expiry_date IN ({placeholders})
                  AND exchange = ? AND snapshot_id = ?
                ORDER BY strike, option_type""",  # noqa: S608 - placeholders only
            [symbol, *aliases, exchange, snapshot_id],
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
               WHERE symbol = ? AND exchange = ?""",
            [symbol, exchange],
        )
        return sorted({normalise_expiry(row[0]) for row in result.fetchall()})
