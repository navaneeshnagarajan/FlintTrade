"""Trade Journal — SQLite + FTS5 journal for annotating and analysing trades.

Each ``JournalEntry`` extends the raw ``trades`` table with qualitative
metadata (emotions, setup quality, execution quality, tags, notes, screenshot)
in a dedicated ``journal.sqlite`` database, alongside a normalised
``journal_tags`` table (exact tag-subset filtering) and a ``journal_fts`` FTS5
index (full-text search over symbol/notes/tags/strategy). The FTS index is kept
in sync by SQL triggers, so every add/update/delete is searchable immediately.
The same database also holds ``daily_notes`` (one free-text note per IST
trading day) and ``journal_screenshots`` (trade-log screenshot metadata; the
image bytes live on disk under the workspace ``journal_screenshots/`` dir).

Storage uses :func:`flinttrade_core.db.open_sqlite`, the same WAL-hardened path
every other FlintTrade store runs on. Pass ``":memory:"`` for tests.

Usage::

    from flinttrade_journal.trade_journal import TradeJournal, JournalEntry

    journal = TradeJournal()  # journal.sqlite under the workspace directory
    journal.initialise()

    entry_id = journal.add_entry(JournalEntry(
        symbol="NIFTY26APR24500CE",
        exchange="NFO",
        side="BUY",
        quantity=50,
        entry_price=120.0,
        exit_price=145.0,
        strategy="Iron Condor",
        tags=["options", "nifty"],
        notes="Clean breakout above resistance.",
        setup_quality=4,
        execution_quality=5,
    ))
    hits = journal.search("breakout")
    stats = journal.get_stats()
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import csv
import functools
import hashlib
import io
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.journal.trade_journal")

IST = timezone(timedelta(hours=5, minutes=30))

_T = TypeVar("_T")


def _locked(method: Callable[..., _T]) -> Callable[..., _T]:
    """Serialise a :class:`TradeJournal` method on the instance lock.

    A single sqlite3 connection is shared across Flask's request threads (the
    journal is one app-wide singleton). ``check_same_thread=False`` avoids the
    cross-thread open error, but CPython's sqlite3 does NOT serialise the
    prepare→bind→step cycle, so two threads driving the same connection corrupt
    each other's statement state (SQLITE_MISUSE, garbage reads). A reentrant
    lock makes every public operation atomic — and composite methods (update →
    get, import → list + add) re-acquire it safely.
    """

    @functools.wraps(method)
    def wrapper(self: TradeJournal, *args: Any, **kwargs: Any) -> _T:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

# Timestamps are stored as ISO-8601 TEXT; date() parses them for range filters.
# journal_tags normalises the JSON `tags` column so an exact tag-subset filter is
# a single indexed query. journal_fts (FTS5) is kept in sync by triggers, so a
# search reflects the latest write with no manual index maintenance.
_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS journal_entries (
        id                  TEXT PRIMARY KEY,
        symbol              TEXT NOT NULL,
        exchange            TEXT NOT NULL,
        side                TEXT NOT NULL,
        quantity            INTEGER NOT NULL,
        entry_price         REAL NOT NULL,
        exit_price          REAL,
        entry_time          TEXT,
        exit_time           TEXT,
        strategy            TEXT,
        tags                TEXT,
        notes               TEXT,
        screenshot_path     TEXT,
        emotion_before      TEXT,
        emotion_after       TEXT,
        setup_quality       INTEGER,
        execution_quality   INTEGER,
        pnl                 REAL,
        pnl_pct             REAL,
        risk_reward_ratio   REAL,
        created_at          TEXT NOT NULL,
        updated_at          TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_journal_symbol ON journal_entries (symbol)",
    "CREATE INDEX IF NOT EXISTS idx_journal_strategy ON journal_entries (strategy)",
    "CREATE INDEX IF NOT EXISTS idx_journal_entry_time ON journal_entries (entry_time)",
    """
    CREATE TABLE IF NOT EXISTS journal_tags (
        entry_id TEXT NOT NULL,
        tag      TEXT NOT NULL,
        PRIMARY KEY (entry_id, tag)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_journal_tags_tag ON journal_tags (tag)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS journal_fts
    USING fts5(id UNINDEXED, symbol, notes, tags, strategy)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_ai AFTER INSERT ON journal_entries BEGIN
        INSERT INTO journal_fts(rowid, id, symbol, notes, tags, strategy)
        VALUES (new.rowid, new.id, new.symbol,
                COALESCE(new.notes, ''), COALESCE(new.tags, ''), COALESCE(new.strategy, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_ad AFTER DELETE ON journal_entries BEGIN
        DELETE FROM journal_fts WHERE rowid = old.rowid;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS journal_au_after AFTER UPDATE ON journal_entries BEGIN
        DELETE FROM journal_fts WHERE rowid = new.rowid;
        INSERT INTO journal_fts(rowid, id, symbol, notes, tags, strategy)
        VALUES (new.rowid, new.id, new.symbol,
                COALESCE(new.notes, ''), COALESCE(new.tags, ''), COALESCE(new.strategy, ''));
    END
    """,
    # One free-text note per IST trading day (TradeJournal NotesTab).
    """
    CREATE TABLE IF NOT EXISTS daily_notes (
        date        TEXT PRIMARY KEY,
        content     TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    # Trade-log screenshot metadata; bytes live on disk under the workspace
    # `journal_screenshots/` directory. The UNIQUE(trade_key, content_sha256)
    # key makes re-attaching the same image to the same trade idempotent.
    """
    CREATE TABLE IF NOT EXISTS journal_screenshots (
        id              TEXT PRIMARY KEY,
        trade_key       TEXT NOT NULL,
        content_sha256  TEXT NOT NULL,
        content_type    TEXT NOT NULL,
        size            INTEGER NOT NULL,
        created_at      TEXT NOT NULL,
        UNIQUE(trade_key, content_sha256)
    )
    """,
]

# ---------------------------------------------------------------------------
# Screenshot constants
# ---------------------------------------------------------------------------

# Allowed data-URL content types → on-disk file extension.
_SCREENSHOT_CONTENT_TYPES: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}

_MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024  # 2 MiB decoded
# Base64 encodes 3 bytes into 4 chars — any payload longer than this must
# decode to more than 2 MiB, so it can be rejected before decoding.
_MAX_SCREENSHOT_B64_CHARS = ((_MAX_SCREENSHOT_BYTES + 2) // 3) * 4
_MAX_TRADE_KEY_CHARS = 300

# ---------------------------------------------------------------------------
# SQL column allowlist — prevents SQL injection via dynamic SET clauses.
# Only mutable user-facing columns are listed here.  Computed columns
# (pnl, pnl_pct, risk_reward_ratio) and immutable columns (id, created_at)
# are excluded because they are either recomputed by the model validator or
# must never change after insertion.
# ---------------------------------------------------------------------------

_ALLOWED_COLUMNS: frozenset[str] = frozenset({
    "symbol",
    "exchange",
    "side",
    "quantity",
    "entry_price",
    "exit_price",
    "entry_time",
    "exit_time",
    "strategy",
    "tags",
    "notes",
    "screenshot_path",
    "emotion_before",
    "emotion_after",
    "setup_quality",
    "execution_quality",
    "pnl",
    "pnl_pct",
    "risk_reward_ratio",
    "updated_at",
})


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class JournalEntry(BaseModel):
    """A single trade journal entry with qualitative and quantitative fields.

    Args:
        id: Auto-generated UUID if not provided.
        symbol: Instrument symbol (e.g. ``"NIFTY26APR24500CE"``).
        exchange: Exchange code (e.g. ``"NFO"``, ``"NSE"``, ``"MCX"``).
        side: Trade direction — ``"BUY"`` or ``"SELL"``.
        quantity: Number of units / lots traded.
        entry_price: Price at which the position was opened.
        exit_price: Price at which the position was closed (``None`` if open).
        entry_time: IST timestamp of entry. Defaults to now if omitted.
        exit_time: IST timestamp of exit (``None`` if open).
        strategy: Name of the strategy that generated this trade.
        tags: Free-form labels (e.g. ``["options", "trending"]``).
        notes: Free-text trade notes / rationale.
        screenshot_path: Path to a chart screenshot on disk.
        emotion_before: Emotional state before entry (e.g. ``"calm"``, ``"FOMO"``).
        emotion_after: Emotional state after exit (e.g. ``"satisfied"``, ``"regret"``).
        setup_quality: Self-assessed setup quality from 1 (poor) to 5 (excellent).
        execution_quality: Self-assessed execution quality from 1 to 5.
        pnl: Realised P&L (auto-computed if entry_price + exit_price are present).
        pnl_pct: P&L as percentage of entry value (auto-computed).
        risk_reward_ratio: R:R ratio stored for reference.
        created_at: Creation timestamp (auto-set on creation).
        updated_at: Last update timestamp (auto-updated on mutation).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float | None = None
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    strategy: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    screenshot_path: str | None = None
    emotion_before: str | None = None
    emotion_after: str | None = None
    setup_quality: int | None = None
    execution_quality: int | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    risk_reward_ratio: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(IST))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(IST))

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        """Normalise and validate the trade side.

        Args:
            v: Raw side value.

        Returns:
            Upper-cased side string.

        Raises:
            ValueError: If side is not ``"BUY"`` or ``"SELL"``.
        """
        upper = v.upper()
        if upper not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got {v!r}")
        return upper

    @field_validator("setup_quality", "execution_quality", mode="before")
    @classmethod
    def validate_quality(cls, v: Any) -> Any:
        """Validate quality scores are in range 1–5.

        Args:
            v: Raw quality value.

        Returns:
            Validated integer or None.

        Raises:
            ValueError: If value is not between 1 and 5 inclusive.
        """
        if v is None:
            return v
        iv = int(v)
        if not 1 <= iv <= 5:
            raise ValueError(f"Quality scores must be 1–5, got {v!r}")
        return iv

    @model_validator(mode="after")
    def compute_pnl(self) -> JournalEntry:
        """Auto-compute P&L fields when entry and exit prices are available.

        Returns:
            Self with pnl and pnl_pct populated if both prices are set.
        """
        if self.exit_price is not None and self.pnl is None:
            if self.side == "BUY":
                self.pnl = (self.exit_price - self.entry_price) * self.quantity
            else:
                self.pnl = (self.entry_price - self.exit_price) * self.quantity

            entry_value = self.entry_price * self.quantity
            if entry_value != 0:
                self.pnl_pct = (self.pnl / entry_value) * 100
        return self


class JournalStats(BaseModel):
    """Aggregated statistics over a set of journal entries.

    Args:
        total_entries: Total number of entries examined.
        closed_entries: Number of entries with an exit price.
        win_count: Number of profitable closed trades.
        loss_count: Number of losing closed trades.
        win_rate: Win rate as a percentage (0–100).
        avg_pnl: Average P&L per closed trade.
        total_pnl: Sum of all closed trade P&Ls.
        best_trade_pnl: Highest single-trade P&L.
        worst_trade_pnl: Lowest single-trade P&L.
        avg_setup_quality: Average self-assessed setup quality.
        avg_execution_quality: Average self-assessed execution quality.
        by_strategy: P&L breakdown per strategy name.
        by_day_of_week: P&L breakdown per weekday (0=Monday … 6=Sunday).
    """

    total_entries: int = 0
    closed_entries: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    best_trade_pnl: float | None = None
    worst_trade_pnl: float | None = None
    avg_setup_quality: float | None = None
    avg_execution_quality: float | None = None
    by_strategy: dict[str, float] = Field(default_factory=dict)
    by_day_of_week: dict[str, float] = Field(default_factory=dict)


class JournalFilters(BaseModel):
    """Filter parameters for listing journal entries.

    Args:
        start_date: Earliest entry_time date (ISO format ``"YYYY-MM-DD"``).
        end_date: Latest entry_time date (ISO format ``"YYYY-MM-DD"``).
        symbol: Exact symbol match.
        strategy: Exact strategy match.
        tags: Require all listed tags to be present.
        side: ``"BUY"`` or ``"SELL"`` filter.
        limit: Maximum number of results. Defaults to 500.
        offset: Pagination offset. Defaults to 0.
    """

    start_date: str | None = None
    end_date: str | None = None
    symbol: str | None = None
    strategy: str | None = None
    tags: list[str] = Field(default_factory=list)
    side: str | None = None
    limit: int = 500
    offset: int = 0


# ---------------------------------------------------------------------------
# Helper — row dict ↔ JournalEntry
# ---------------------------------------------------------------------------


_TIMESTAMP_COLS = frozenset(
    {"entry_time", "exit_time", "created_at", "updated_at"}
)


def _coerce_timestamp(value: Any) -> datetime | None:
    """Coerce a stored ISO-8601 TEXT timestamp to a timezone-aware datetime.

    SQLite returns timestamp columns as the TEXT they were written as (or
    ``None`` for NULL); naive strings are assumed IST.

    Args:
        value: Raw value from a SQLite TEXT timestamp column.

    Returns:
        A timezone-aware datetime (IST) or ``None`` if null/unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=IST)
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=IST)


def _to_iso(value: datetime | None) -> str | None:
    """Serialise a datetime to ISO-8601 TEXT for SQLite (``None`` passes through)."""
    return value.isoformat() if value is not None else None


def _row_to_entry(row: dict[str, Any]) -> JournalEntry:
    """Convert a SQLite result row dict to a JournalEntry.

    Tags are stored as a JSON array string; this deserialises them back to
    ``list[str]``. Timestamp columns are coerced from ISO-8601 TEXT to
    timezone-aware datetimes.

    Args:
        row: Dictionary produced from a :class:`sqlite3.Row`.

    Returns:
        Hydrated :class:`JournalEntry` instance.
    """
    row = dict(row)
    tags_raw = row.get("tags")
    if isinstance(tags_raw, str) and tags_raw:
        try:
            row["tags"] = json.loads(tags_raw)
        except json.JSONDecodeError:
            row["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        row["tags"] = []

    for col in _TIMESTAMP_COLS:
        if col in row:
            row[col] = _coerce_timestamp(row[col])

    return JournalEntry.model_validate(row)


def _entry_to_row(entry: JournalEntry) -> dict[str, Any]:
    """Serialise a JournalEntry to a flat dict for SQLite insertion.

    Tags are JSON-encoded to a single TEXT column; datetimes to ISO-8601 TEXT.

    Args:
        entry: The journal entry to serialise.

    Returns:
        Dict with all columns as SQLite-storable scalar values.
    """
    return {
        "id": entry.id,
        "symbol": entry.symbol,
        "exchange": entry.exchange,
        "side": entry.side,
        "quantity": entry.quantity,
        "entry_price": entry.entry_price,
        "exit_price": entry.exit_price,
        "entry_time": _to_iso(entry.entry_time),
        "exit_time": _to_iso(entry.exit_time),
        "strategy": entry.strategy,
        "tags": json.dumps(entry.tags),
        "notes": entry.notes,
        "screenshot_path": entry.screenshot_path,
        "emotion_before": entry.emotion_before,
        "emotion_after": entry.emotion_after,
        "setup_quality": entry.setup_quality,
        "execution_quality": entry.execution_quality,
        "pnl": entry.pnl,
        "pnl_pct": entry.pnl_pct,
        "risk_reward_ratio": entry.risk_reward_ratio,
        "created_at": _to_iso(entry.created_at),
        "updated_at": _to_iso(entry.updated_at),
    }


# ---------------------------------------------------------------------------
# TradeJournal
# ---------------------------------------------------------------------------

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


_DB_NAME = "journal.sqlite"
_SCREENSHOTS_DIR_NAME = "journal_screenshots"
_MEMORY_DB = ":memory:"

# One lock name for the whole journal unit, plus a per-artefact lock for each
# half. The unit lock is what keeps the database and its images together; the
# per-artefact locks exist only because the shared copy helpers take a name,
# and they are uncontended by construction (the unit lock already serialises
# every caller). They must be DISTINCT paths — two ``FileLock`` instances on
# one path inside a single process block against each other.
_UNIT_LOCK_NAME = ".journal-migration.lock"
_DB_LOCK_NAME = ".journal-db-migration.lock"
_SCREENSHOTS_LOCK_NAME = ".journal-screenshots-migration.lock"

# A journal with years of screenshots is a multi-gigabyte copy; a Gunicorn boot
# herd must not fail-closed on the 10s default while one worker performs it.
_MIGRATION_TIMEOUT_SECONDS: float = 60.0


def _legacy_journal_path() -> Path:
    """Return the pre-``workspace_dir()`` journal database location.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/journal.sqlite`` — the fixed ``~/.flinttrade``
        root every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / _DB_NAME


def _legacy_screenshots_dir() -> Path:
    """Return the pre-``workspace_dir()`` journal screenshot directory.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/journal_screenshots``.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / _SCREENSHOTS_DIR_NAME


def _default_journal_path() -> Path:
    """Resolve the journal database under the active workspace, migrating once.

    ``FLINTTRADE_JOURNAL_DB`` remains an explicit override and skips the
    migration probe entirely. Otherwise the journal resolves to
    ``journal.sqlite`` inside the workspace directory, and a pre-workspace
    journal is copied across once together with its screenshot directory.

    There is deliberately no fallback for a broken ``flinttrade_core`` import:
    the previous one silently opened an empty journal at a hardcoded home path,
    so an installation fault presented to the operator as a journal that had
    lost every trade. Raising instead surfaces the fault (``app.py`` degrades
    the journal routes to 503 without blocking boot).

    Returns:
        Absolute path of the journal SQLite database.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: A legacy
            journal could not be preserved in the workspace.
    """
    env = os.getenv("FLINTTRADE_JOURNAL_DB")
    if env:
        return Path(env).expanduser()

    from flinttrade_core.workspace import default_workspace_active, workspace_dir  # noqa: PLC0415

    target = workspace_dir() / _DB_NAME
    if default_workspace_active():
        _migrate_legacy_journal_unit(target, target.parent / _SCREENSHOTS_DIR_NAME)
    return target


def _migrate_legacy_journal_unit(target_db: Path, target_screenshots: Path) -> None:
    """Copy the legacy journal database and its screenshot directory as one unit.

    Copy, never move: the legacy journal is retained as a backup. The database
    is the unit's completion marker, so an existing workspace database skips the
    whole unit — never just the database — because a journal migrated without
    its image directory silently loses every screenshot behind rows that still
    reference them. For the same reason the images are copied *first*: the
    marker only appears once the unit is whole, and an interrupted copy is
    retried on the next boot.

    Args:
        target_db: Workspace location of the journal SQLite database.
        target_screenshots: Workspace location of the screenshot directory.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The copy could
            not be completed; the legacy journal is retained.
    """
    # ``FileLock`` is re-used from ``flinttrade_core.workspace`` rather than
    # imported from ``filelock`` directly: this package declares
    # ``flinttrade-core`` but not ``filelock``, and borrowing the resolver's own
    # object adds no dependency edge.
    from flinttrade_core.workspace import (  # noqa: PLC0415
        FileLock,
        FileLockTimeout,
        WorkspaceStateMigrationError,
        copy_legacy_database_once,
        copy_legacy_directory_once,
    )

    if target_db.exists():
        return
    legacy_db = _legacy_journal_path()
    if not legacy_db.exists():
        return

    try:
        unit_lock = FileLock(target_db.parent / _UNIT_LOCK_NAME, timeout=_MIGRATION_TIMEOUT_SECONDS, mode=0o600)
        with unit_lock.acquire():
            if target_db.exists():
                # A sibling worker won the unit lock and migrated the journal.
                logger.info("Legacy trade journal already migrated by a concurrent process")
                return
            copy_legacy_directory_once(
                _legacy_screenshots_dir(),
                target_screenshots,
                lock_name=_SCREENSHOTS_LOCK_NAME,
                lock_dir=target_screenshots.parent,
                label="trade journal screenshots",
                timeout=_MIGRATION_TIMEOUT_SECONDS,
            )
            copy_legacy_database_once(
                legacy_db,
                target_db,
                sidecar_suffixes=("-wal", "-journal"),
                lock_name=_DB_LOCK_NAME,
                lock_dir=target_db.parent,
                label="trade journal database",
                timeout=_MIGRATION_TIMEOUT_SECONDS,
            )
    except WorkspaceStateMigrationError:
        raise
    except (FileLockTimeout, OSError) as exc:
        logger.error("Could not migrate the legacy trade journal into %s: %s", target_db.parent, exc)
        raise WorkspaceStateMigrationError(
            f"Could not preserve the legacy trade journal; source retained at {legacy_db}"
        ) from exc


class TradeJournal:
    """SQLite + FTS5 trade journal with CRUD, stats, search, CSV, and import.

    The journal owns its own ``journal.sqlite`` database (opened via
    :func:`flinttrade_core.db.open_sqlite`), with ``journal_entries`` +
    ``journal_tags`` + an FTS5 ``journal_fts`` index. Call :meth:`initialise`
    once before first use. Pass ``db_path=":memory:"`` for tests, or inject an
    existing :class:`sqlite3.Connection` via ``connection`` to share one.

    Args:
        db_path: Path to the journal SQLite file. Defaults to
            ``journal.sqlite`` under the FlintTrade workspace, resolved at call
            time so an environment override set after import is honoured. An
            explicit path skips the legacy-migration probe. Ignored when
            ``connection`` is supplied.
        connection: An open :class:`sqlite3.Connection` to use directly
            (chiefly for tests / an injected in-memory DB).
        screenshots_dir: Directory for trade-log screenshot files. Defaults to
            ``journal_screenshots/`` next to the journal SQLite file (i.e.
            inside the FlintTrade workspace). Created lazily on first write.
            The ``:memory:`` and injected-``connection`` forms have no journal
            file to sit beside, so they fall back to the active workspace
            directory — resolved on first use, and never through the
            legacy-migration probe.

    Example::

        journal = TradeJournal()  # journal.sqlite under the workspace directory
        journal.initialise()
        eid = journal.add_entry(JournalEntry(
            symbol="BANKNIFTY", exchange="NFO", side="BUY",
            quantity=25, entry_price=48000.0, exit_price=48500.0,
        ))
        entry = journal.get_entry(eid)
        stats = journal.get_stats()
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        connection: sqlite3.Connection | None = None,
        screenshots_dir: str | Path | None = None,
    ) -> None:
        resolved_db_path: Path | None = None
        if connection is not None:
            self._conn = connection
        else:
            resolved_db_path = Path(db_path).expanduser() if db_path is not None else _default_journal_path()
            self._conn = open_sqlite(str(resolved_db_path))
        self._conn.row_factory = sqlite3.Row
        # Serialises the shared connection across Flask request threads (see _locked).
        self._lock = threading.RLock()
        # Screenshot bytes live on disk next to the SQLite file (workspace dir)
        # unless a directory is injected. Created lazily on first write.
        #
        # Every explicit construction form — an injected directory, an explicit
        # ``db_path`` (``:memory:`` included), an injected connection — must
        # resolve WITHOUT calling ``_default_journal_path()``, because that is
        # the legacy-migration probe: an in-memory or caller-supplied journal
        # that reached it would migrate the operator's legacy screenshots on
        # their behalf, and the ``:memory:`` form would touch the filesystem it
        # exists to avoid.
        self._screenshots_dir: Path | None
        if screenshots_dir is not None:
            self._screenshots_dir = Path(screenshots_dir).expanduser()
        elif resolved_db_path is not None and str(resolved_db_path) != _MEMORY_DB:
            self._screenshots_dir = resolved_db_path.parent / _SCREENSHOTS_DIR_NAME
        else:
            # No journal file to sit beside: deferred to the workspace lookup
            # in :attr:`screenshots_dir`, so construction touches no disk.
            self._screenshots_dir = None

    @property
    def screenshots_dir(self) -> Path:
        """Directory holding the trade-log screenshot files.

        Resolved on first access for the ``:memory:`` and injected-connection
        forms, which have no journal file to sit beside: they fall back to the
        active workspace directory via a plain :func:`workspace_dir` lookup,
        never the legacy-migration probe.

        Returns:
            The directory screenshot bytes are read from and written to.
        """
        if self._screenshots_dir is None:
            from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

            self._screenshots_dir = workspace_dir() / _SCREENSHOTS_DIR_NAME
        return self._screenshots_dir

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> TradeJournal:
        return self

    def __exit__(self, *args: Any) -> None:
        with contextlib.suppress(sqlite3.Error):
            self.close()

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    @_locked
    def initialise(self) -> None:
        """Create the journal tables, indexes, FTS index, and sync triggers.

        Safe to call multiple times (every statement is ``IF NOT EXISTS``).
        """
        for stmt in _SCHEMA_STATEMENTS:
            self._conn.execute(stmt)
        self._conn.commit()
        logger.info("TradeJournal schema initialised")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def _sync_tags(self, entry_id: str, tags: list[str]) -> None:
        """Replace the normalised ``journal_tags`` rows for an entry."""
        self._conn.execute("DELETE FROM journal_tags WHERE entry_id = ?", (entry_id,))
        unique = {t for t in tags if t}
        if unique:
            self._conn.executemany(
                "INSERT OR IGNORE INTO journal_tags (entry_id, tag) VALUES (?, ?)",
                [(entry_id, t) for t in unique],
            )

    @_locked
    def add_entry(self, entry: JournalEntry) -> str:
        """Insert a new journal entry (with its tags; FTS syncs via trigger).

        Args:
            entry: The :class:`JournalEntry` to persist.

        Returns:
            The ``id`` of the newly created entry (UUID string).
        """
        row = _entry_to_row(entry)
        cols = list(row.keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        self._conn.execute(
            f"INSERT INTO journal_entries ({', '.join(cols)}) VALUES ({placeholders})",
            row,
        )
        self._sync_tags(entry.id, entry.tags)
        self._conn.commit()
        logger.info("Journal entry added: id=%s symbol=%s", entry.id, entry.symbol)
        return entry.id

    @_locked
    def get_entry(self, entry_id: str) -> JournalEntry | None:
        """Fetch a single entry by its UUID.

        Args:
            entry_id: The UUID string of the entry.

        Returns:
            The :class:`JournalEntry`, or ``None`` if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM journal_entries WHERE id = :id",
            {"id": entry_id},
        ).fetchone()
        if row is None:
            return None
        return _row_to_entry(dict(row))

    @_locked
    def list_entries(self, filters: JournalFilters | None = None) -> list[JournalEntry]:
        """List journal entries, optionally filtered.

        Args:
            filters: A :class:`JournalFilters` instance. If ``None``, returns
                the most recent 500 entries ordered by ``entry_time DESC``.

        Returns:
            List of :class:`JournalEntry` objects.
        """
        if filters is None:
            filters = JournalFilters()

        clauses: list[str] = []
        params: list[Any] = []

        # Compare the stored LOCAL (IST) date prefix, falling back to created_at
        # when entry_time is absent. substr(...,1,10) avoids SQLite date()'s
        # UTC conversion (which shifted pre-05:30-IST entries a day earlier), and
        # the COALESCE keeps entries with no entry_time (e.g. manually logged via
        # the widget) from being silently dropped by every date-range filter.
        _date_expr = "substr(COALESCE(entry_time, created_at), 1, 10)"
        if filters.start_date:
            clauses.append(f"{_date_expr} >= ?")
            params.append(filters.start_date)
        if filters.end_date:
            clauses.append(f"{_date_expr} <= ?")
            params.append(filters.end_date)
        if filters.symbol:
            clauses.append("symbol = ?")
            params.append(filters.symbol)
        if filters.strategy:
            clauses.append("strategy = ?")
            params.append(filters.strategy)
        if filters.side:
            clauses.append("side = ?")
            params.append(filters.side.upper())
        if filters.tags:
            # Exact subset: keep entries carrying EVERY requested tag (SQL,
            # via the normalised journal_tags table — no Python post-filter).
            wanted = [t for t in dict.fromkeys(filters.tags) if t]
            if wanted:
                marks = ", ".join("?" for _ in wanted)
                clauses.append(
                    f"id IN (SELECT entry_id FROM journal_tags WHERE tag IN ({marks}) "
                    "GROUP BY entry_id HAVING COUNT(DISTINCT tag) = ?)"
                )
                params.extend(wanted)
                params.append(len(wanted))

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT * FROM journal_entries {where} "
            "ORDER BY COALESCE(entry_time, created_at) DESC, id LIMIT ? OFFSET ?"
        )
        params.append(filters.limit)
        params.append(filters.offset)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_entry(dict(r)) for r in rows]

    @_locked
    def update_entry(self, entry_id: str, updates: dict[str, Any]) -> JournalEntry | None:
        """Partially update an existing entry.

        Only the keys present in ``updates`` are changed. ``pnl`` and
        ``pnl_pct`` are recomputed automatically if ``exit_price`` or
        ``entry_price`` appear in the update dict.

        Args:
            entry_id: UUID of the entry to update.
            updates: Dict of field name → new value.

        Returns:
            The updated :class:`JournalEntry`, or ``None`` if not found.
        """
        existing = self.get_entry(entry_id)
        if existing is None:
            return None

        # Merge updates — re-validate through the model to trigger validators.
        current_data = existing.model_dump()
        current_data.update(updates)
        # Clear pnl so the model_validator recomputes it when any input to the
        # P&L formula changes — including `side`, whose flip inverts the sign
        # (omitting it left a closed BUY→SELL correction showing the old profit).
        if updates.keys() & {"exit_price", "entry_price", "quantity", "side"}:
            current_data.pop("pnl", None)
            current_data.pop("pnl_pct", None)
        current_data["updated_at"] = datetime.now(IST)
        updated = JournalEntry.model_validate(current_data)

        row = _entry_to_row(updated)
        # Build SET clause — filter through allowlist to prevent SQL injection,
        # and exclude immutable columns (id, created_at).
        set_keys = [k for k in row if k in _ALLOWED_COLUMNS and k not in ("id", "created_at")]
        set_clause = ", ".join(f"{k} = :{k}" for k in set_keys)
        update_params = {k: row[k] for k in set_keys}
        update_params["id"] = row["id"]
        self._conn.execute(
            f"UPDATE journal_entries SET {set_clause} WHERE id = :id",
            update_params,
        )
        self._sync_tags(updated.id, updated.tags)
        self._conn.commit()
        logger.info("Journal entry updated: id=%s", entry_id)
        return updated

    @_locked
    def delete_entry(self, entry_id: str) -> bool:
        """Delete a journal entry by UUID.

        Args:
            entry_id: UUID of the entry to delete.

        Returns:
            ``True`` if the row existed and was deleted, ``False`` otherwise.
        """
        existing = self.get_entry(entry_id)
        if existing is None:
            return False
        self._conn.execute("DELETE FROM journal_tags WHERE entry_id = :id", {"id": entry_id})
        self._conn.execute("DELETE FROM journal_entries WHERE id = :id", {"id": entry_id})
        self._conn.commit()
        logger.info("Journal entry deleted: id=%s", entry_id)
        return True

    # ------------------------------------------------------------------
    # Full-text search
    # ------------------------------------------------------------------

    @_locked
    def search(self, query: str, *, limit: int = 100, offset: int = 0) -> list[JournalEntry]:
        """Full-text search entries by symbol / notes / tags / strategy.

        Uses the FTS5 ``journal_fts`` index (ranked by relevance). A blank query
        returns nothing; a malformed FTS query (unbalanced quotes, stray
        operators) yields an empty list rather than raising, so caller input is
        never a 500.

        Args:
            query: FTS5 MATCH expression (e.g. ``"breakout"``, ``"nifty OR banknifty"``).
            limit: Maximum results (default 100).
            offset: Pagination offset (default 0).

        Returns:
            Matching :class:`JournalEntry` objects, most-relevant first.
        """
        term = query.strip()
        if not term:
            return []
        sql = (
            "SELECT je.* FROM journal_entries je "
            "JOIN journal_fts f ON f.rowid = je.rowid "
            "WHERE journal_fts MATCH ? ORDER BY rank LIMIT ? OFFSET ?"
        )
        try:
            rows = self._conn.execute(sql, (term, limit, offset)).fetchall()
        except sqlite3.OperationalError:
            # Malformed MATCH syntax — retry as a quoted phrase before giving up.
            try:
                phrase = '"' + term.replace('"', '""') + '"'
                rows = self._conn.execute(sql, (phrase, limit, offset)).fetchall()
            except sqlite3.OperationalError:
                logger.warning("Journal FTS query rejected: %r", term)
                return []
        return [_row_to_entry(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @_locked
    def get_stats(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> JournalStats:
        """Compute aggregated statistics over a date range.

        Args:
            start_date: Earliest entry_time date ``"YYYY-MM-DD"`` (inclusive).
            end_date: Latest entry_time date ``"YYYY-MM-DD"`` (inclusive).

        Returns:
            A :class:`JournalStats` instance with win rate, avg P&L, breakdown
            by strategy and day-of-week.
        """
        filters = JournalFilters(
            start_date=start_date,
            end_date=end_date,
            limit=100_000,
        )
        entries = self.list_entries(filters)

        closed = [e for e in entries if e.pnl is not None]
        wins = [e for e in closed if (e.pnl or 0) > 0]
        losses = [e for e in closed if (e.pnl or 0) < 0]

        total_pnl = sum(e.pnl for e in closed)  # type: ignore[misc]
        avg_pnl = (total_pnl / len(closed)) if closed else 0.0
        win_rate = (len(wins) / len(closed) * 100) if closed else 0.0

        best = max((e.pnl for e in closed), default=None)
        worst = min((e.pnl for e in closed), default=None)

        setup_scores = [e.setup_quality for e in entries if e.setup_quality is not None]
        exec_scores = [e.execution_quality for e in entries if e.execution_quality is not None]

        avg_setup = (sum(setup_scores) / len(setup_scores)) if setup_scores else None
        avg_exec = (sum(exec_scores) / len(exec_scores)) if exec_scores else None

        # By strategy
        by_strategy: dict[str, float] = {}
        for e in closed:
            key = e.strategy or "Unknown"
            by_strategy[key] = by_strategy.get(key, 0.0) + (e.pnl or 0.0)

        # By day of week (based on entry_time)
        by_dow: dict[str, float] = {}
        for e in closed:
            if e.entry_time is not None:
                day_name = _DAY_NAMES[e.entry_time.weekday()]
                by_dow[day_name] = by_dow.get(day_name, 0.0) + (e.pnl or 0.0)

        return JournalStats(
            total_entries=len(entries),
            closed_entries=len(closed),
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=round(win_rate, 2),
            avg_pnl=round(avg_pnl, 2),
            total_pnl=round(total_pnl, 2),
            best_trade_pnl=best,
            worst_trade_pnl=worst,
            avg_setup_quality=round(avg_setup, 2) if avg_setup is not None else None,
            avg_execution_quality=round(avg_exec, 2) if avg_exec is not None else None,
            by_strategy=by_strategy,
            by_day_of_week=by_dow,
        )

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    @_locked
    def export_csv(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> str:
        """Export journal entries to a CSV string.

        Args:
            start_date: Earliest entry_time date ``"YYYY-MM-DD"`` (inclusive).
            end_date: Latest entry_time date ``"YYYY-MM-DD"`` (inclusive).

        Returns:
            UTF-8 CSV string with a header row followed by one data row per entry.
        """
        filters = JournalFilters(start_date=start_date, end_date=end_date, limit=100_000)
        entries = self.list_entries(filters)

        fieldnames = [
            "id", "symbol", "exchange", "side", "quantity",
            "entry_price", "exit_price", "entry_time", "exit_time",
            "strategy", "tags", "notes", "screenshot_path",
            "emotion_before", "emotion_after",
            "setup_quality", "execution_quality",
            "pnl", "pnl_pct", "risk_reward_ratio",
            "created_at", "updated_at",
        ]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for entry in entries:
            row = _entry_to_row(entry)
            # Tags already JSON-encoded in _entry_to_row
            writer.writerow({k: row.get(k, "") for k in fieldnames})

        return buf.getvalue()

    @_locked
    def import_from_tradebook(self, trades: list[dict[str, Any]]) -> list[str]:
        """Auto-create journal entries from OpenAlgo tradebook rows.

        Each tradebook trade becomes a :class:`JournalEntry` with the
        qualitative fields (notes, emotions, quality scores) left blank so the
        trader can fill them in later.

        Duplicate detection: if an entry already exists for the same
        ``symbol + side + quantity + entry_price`` on the same calendar day, it
        is skipped to avoid double-importing.

        Args:
            trades: List of dicts in OpenAlgo tradebook format.  Expected keys:
                ``symbol``, ``exchange``, ``action`` (BUY/SELL), ``quantity``,
                ``price``, ``orderid`` (optional), ``product`` (optional),
                ``timestamp`` / ``time`` (optional).

        Returns:
            List of entry IDs that were created (skipped entries are omitted).
        """
        created_ids: list[str] = []

        for trade in trades:
            # Untrusted input (a webhook / API caller can post arbitrary JSON):
            # a non-dict row, a null side, or a non-numeric qty/price must skip
            # this row, never raise — malformed input is a skipped row, not a 500.
            if not isinstance(trade, dict):
                logger.warning("Skipping non-object tradebook row: %r", trade)
                continue
            try:
                symbol = str(trade.get("symbol") or "")
                exchange = str(trade.get("exchange") or "NSE")
                side = str(trade.get("action") or trade.get("side") or "BUY").upper()
                quantity = int(trade.get("quantity") or trade.get("qty") or 0)
                price = float(trade.get("price") or trade.get("trade_price") or 0.0)
            except (TypeError, ValueError):
                logger.warning("Skipping malformed tradebook row: %r", trade)
                continue

            # Parse timestamp from tradebook field names OpenAlgo uses
            raw_ts = trade.get("timestamp") or trade.get("time") or trade.get("order_time")
            entry_time: datetime | None = None
            if raw_ts:
                try:
                    if isinstance(raw_ts, (int, float)):
                        entry_time = datetime.fromtimestamp(raw_ts, tz=IST)
                    else:
                        entry_time = datetime.fromisoformat(str(raw_ts))
                except (ValueError, OSError):
                    entry_time = datetime.now(IST)

            if not symbol or quantity == 0 or price == 0.0:
                logger.warning("Skipping invalid tradebook row: %s", trade)
                continue

            # Simple duplicate check: same symbol + side + qty + price + day
            entry_date = entry_time.date() if entry_time else date.today()
            existing = self.list_entries(
                JournalFilters(
                    symbol=symbol,
                    start_date=entry_date.isoformat(),
                    end_date=entry_date.isoformat(),
                    side=side,
                    limit=50,
                )
            )
            duplicate = any(
                e.quantity == quantity and abs(e.entry_price - price) < 0.001
                for e in existing
            )
            if duplicate:
                logger.debug(
                    "Skipping duplicate tradebook import: %s %s qty=%d @ %.2f",
                    side, symbol, quantity, price,
                )
                continue

            entry = JournalEntry(
                symbol=symbol,
                exchange=exchange,
                side=side,
                quantity=quantity,
                entry_price=price,
                entry_time=entry_time,
                strategy=trade.get("strategy") or trade.get("product") or "",
                tags=["imported"],
                notes=f"Auto-imported from tradebook. OrderID: {trade.get('orderid', 'N/A')}",
            )
            created_ids.append(self.add_entry(entry))

        logger.info(
            "Tradebook import complete: %d trades processed, %d entries created",
            len(trades),
            len(created_ids),
        )
        return created_ids

    # ------------------------------------------------------------------
    # Daily notes (one free-text note per IST trading day)
    # ------------------------------------------------------------------

    @_locked
    def get_daily_note(self, note_date: str) -> dict[str, Any] | None:
        """Fetch the daily note for a given date.

        Args:
            note_date: The trading day in ``"YYYY-MM-DD"`` format.

        Returns:
            ``{"date", "content", "updated_at"}`` or ``None`` if no note exists.
        """
        row = self._conn.execute(
            "SELECT date, content, updated_at FROM daily_notes WHERE date = ?",
            (note_date,),
        ).fetchone()
        return dict(row) if row is not None else None

    @_locked
    def upsert_daily_note(self, note_date: str, content: str) -> dict[str, Any]:
        """Insert or update the daily note for a date.

        Empty ``content`` deletes the stored row (an empty note is "no note"),
        and the empty record is returned so callers see the resulting state.

        Args:
            note_date: The trading day in ``"YYYY-MM-DD"`` format.
            content: Full note text; ``""`` deletes the note.

        Returns:
            The saved record ``{"date", "content", "updated_at"}`` —
            ``updated_at`` is ``None`` when the note was deleted.
        """
        if content == "":
            self._conn.execute("DELETE FROM daily_notes WHERE date = ?", (note_date,))
            self._conn.commit()
            return {"date": note_date, "content": "", "updated_at": None}
        now_iso = datetime.now(IST).isoformat()
        self._conn.execute(
            "INSERT INTO daily_notes (date, content, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at",
            (note_date, content, now_iso),
        )
        self._conn.commit()
        return {"date": note_date, "content": content, "updated_at": now_iso}

    @_locked
    def list_daily_notes(self) -> list[dict[str, Any]]:
        """List all daily notes, newest date first.

        Returns:
            One dict per note with ``date``, ``updated_at``, ``word_count``,
            and ``preview`` (first 120 characters of the content).
        """
        rows = self._conn.execute(
            "SELECT date, content, updated_at FROM daily_notes ORDER BY date DESC"
        ).fetchall()
        return [
            {
                "date": row["date"],
                "updated_at": row["updated_at"],
                "word_count": len(row["content"].split()),
                "preview": row["content"][:120],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Trade-log screenshots (metadata in SQLite, bytes on disk)
    # ------------------------------------------------------------------

    def _screenshot_path(self, screenshot_id: str, content_type: str) -> Path:
        """Resolve the on-disk file path for a screenshot row."""
        ext = _SCREENSHOT_CONTENT_TYPES.get(content_type, "bin")
        return self.screenshots_dir / f"{screenshot_id}.{ext}"

    @staticmethod
    def _screenshot_meta_row(record: dict[str, Any]) -> dict[str, Any]:
        """Build the metadata-only API-facing screenshot dict (no image bytes)."""
        return {
            "id": record["id"],
            "trade_key": record["trade_key"],
            "content_type": record["content_type"],
            "size": record["size"],
            "created_at": record["created_at"],
        }

    @staticmethod
    def _screenshot_public_row(record: dict[str, Any], blob: bytes) -> dict[str, Any]:
        """Build the API-facing screenshot dict (row fields + re-encoded data URL)."""
        row = TradeJournal._screenshot_meta_row(record)
        encoded = base64.b64encode(blob).decode("ascii")
        row["data_url"] = f"data:{record['content_type']};base64,{encoded}"
        return row

    @staticmethod
    def _decode_screenshot_data_url(data_url: str) -> tuple[str, bytes]:
        """Validate and decode a screenshot data URL.

        Args:
            data_url: ``data:image/(png|jpeg|webp|gif);base64,<payload>``.

        Returns:
            ``(content_type, decoded_bytes)``.

        Raises:
            ValueError: If the prefix, content type, encoding, or decoded size
                is invalid.
        """
        prefix, sep, payload = data_url.partition(";base64,")
        if not sep or not prefix.startswith("data:"):
            raise ValueError("data_url must be a base64 data URL (data:image/...;base64,...)")
        content_type = prefix[len("data:"):]
        if content_type not in _SCREENSHOT_CONTENT_TYPES:
            raise ValueError("Unsupported screenshot type — PNG, JPEG, WebP, or GIF required")
        if len(payload) > _MAX_SCREENSHOT_B64_CHARS:
            raise ValueError("Screenshot exceeds the 2 MiB size limit")
        try:
            blob = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("data_url payload is not valid base64") from exc
        if not blob:
            raise ValueError("Screenshot payload is empty")
        if len(blob) > _MAX_SCREENSHOT_BYTES:
            raise ValueError("Screenshot exceeds the 2 MiB size limit")
        return content_type, blob

    @_locked
    def add_screenshot(self, trade_key: str, data_url: str) -> tuple[dict[str, Any], bool]:
        """Attach a screenshot to a trade (idempotent per trade + content hash).

        The decoded bytes are written to ``<screenshots_dir>/<id>.<ext>`` and
        the metadata row goes to ``journal_screenshots``. Posting the same
        image for the same ``trade_key`` again returns the existing row
        (re-creating its file if it went missing on disk).

        Args:
            trade_key: Opaque frontend trade identity, non-empty, ≤ 300 chars.
            data_url: ``data:image/(png|jpeg|webp|gif);base64,`` URL, ≤ 2 MiB
                decoded.

        Returns:
            ``(row, created)`` where ``row`` is the API-facing dict (with a
            re-encoded ``data_url``) and ``created`` is ``False`` when an
            existing row was deduplicated.

        Raises:
            ValueError: On any validation failure (maps to HTTP 400).
        """
        if not isinstance(trade_key, str) or not trade_key or len(trade_key) > _MAX_TRADE_KEY_CHARS:
            raise ValueError("trade_key must be a non-empty string of at most 300 characters")
        if not isinstance(data_url, str):
            raise ValueError("data_url must be a string")
        content_type, blob = self._decode_screenshot_data_url(data_url)
        sha = hashlib.sha256(blob).hexdigest()

        existing = self._conn.execute(
            "SELECT * FROM journal_screenshots WHERE trade_key = ? AND content_sha256 = ?",
            (trade_key, sha),
        ).fetchone()
        if existing is not None:
            record = dict(existing)
            path = self._screenshot_path(record["id"], record["content_type"])
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
            return self._screenshot_public_row(record, blob), False

        record = {
            "id": str(uuid.uuid4()),
            "trade_key": trade_key,
            "content_sha256": sha,
            "content_type": content_type,
            "size": len(blob),
            "created_at": datetime.now(IST).isoformat(),
        }
        path = self._screenshot_path(record["id"], content_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        try:
            self._conn.execute(
                "INSERT INTO journal_screenshots (id, trade_key, content_sha256, content_type, size, created_at) "
                "VALUES (:id, :trade_key, :content_sha256, :content_type, :size, :created_at)",
                record,
            )
            self._conn.commit()
        except sqlite3.Error:
            # Keep disk and DB consistent — no orphan file on a failed insert.
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
            raise
        logger.info("Screenshot added: id=%s trade_key=%s size=%d", record["id"], trade_key, len(blob))
        return self._screenshot_public_row(record, blob), True

    def list_screenshots(self, include_data: bool = False) -> list[dict[str, Any]]:
        """List all screenshots, newest first — metadata only by default.

        The default response is the lightweight metadata row (``id``,
        ``trade_key``, ``content_type``, ``size``, ``created_at``); at the
        25-image cap the old always-embedded shape weighed tens of MB per
        listing. Callers that still want every image inlined pass
        ``include_data=True`` (compatibility shape); :meth:`get_screenshot`
        is the lazy per-image byte path.

        Only the SQLite read holds the store lock; the (potentially large)
        file reads and base64 encodes run after it is released, so a big
        collection cannot block every other journal request for the duration.

        Rows whose file has gone missing on disk are skipped (with a warning)
        rather than surfacing a broken record — in metadata mode too, so a
        listed row is always fetchable by id.

        Args:
            include_data: When ``True``, embed each row's re-encoded base64
                ``data_url``.

        Returns:
            List of ``{"id", "trade_key", "content_type", "size",
            "created_at"}`` dicts, each with a ``"data_url"`` key added when
            ``include_data`` is ``True``.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM journal_screenshots ORDER BY created_at DESC, id"
            ).fetchall()
        records = [dict(row) for row in rows]
        out: list[dict[str, Any]] = []
        for record in records:
            path = self._screenshot_path(record["id"], record["content_type"])
            if not include_data:
                if not path.exists():
                    logger.warning("Screenshot file missing on disk; skipping row id=%s", record["id"])
                    continue
                out.append(self._screenshot_meta_row(record))
                continue
            try:
                blob = path.read_bytes()
            except OSError:
                logger.warning("Screenshot file missing on disk; skipping row id=%s", record["id"])
                continue
            out.append(self._screenshot_public_row(record, blob))
        return out

    def get_screenshot(self, screenshot_id: str) -> dict[str, Any] | None:
        """Fetch one screenshot row with its re-encoded data URL.

        As with :meth:`list_screenshots`, only the SQLite read holds the
        store lock; the file read and base64 encode run after release.

        Args:
            screenshot_id: UUID of the screenshot row.

        Returns:
            The API-facing dict (row fields + ``data_url``), or ``None`` when
            the row does not exist or its file has gone missing on disk.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM journal_screenshots WHERE id = ?",
                (screenshot_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        path = self._screenshot_path(record["id"], record["content_type"])
        try:
            blob = path.read_bytes()
        except OSError:
            logger.warning("Screenshot file missing on disk for row id=%s", record["id"])
            return None
        return self._screenshot_public_row(record, blob)

    @_locked
    def delete_screenshot(self, screenshot_id: str) -> bool:
        """Delete a screenshot row and its file on disk.

        Args:
            screenshot_id: UUID of the screenshot row.

        Returns:
            ``True`` if the row existed and was deleted, ``False`` otherwise.
        """
        row = self._conn.execute(
            "SELECT id, content_type FROM journal_screenshots WHERE id = ?",
            (screenshot_id,),
        ).fetchone()
        if row is None:
            return False
        self._conn.execute("DELETE FROM journal_screenshots WHERE id = ?", (screenshot_id,))
        self._conn.commit()
        with contextlib.suppress(OSError):
            self._screenshot_path(row["id"], row["content_type"]).unlink(missing_ok=True)
        logger.info("Screenshot deleted: id=%s", screenshot_id)
        return True
