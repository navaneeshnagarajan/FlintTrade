"""Trade Journal — DuckDB-backed journal for annotating and analysing trades.

Absorbs patterns from trading-journal (SQLAlchemy CRUD) and adapts them to
FlintTrade's DuckDB-first persistence layer.

Each ``JournalEntry`` extends the raw ``trades`` table with qualitative
metadata (emotions, setup quality, execution quality, tags, notes, screenshot)
stored in a separate ``journal_entries`` DuckDB table.

Usage::

    from packages.data.src.storage import StorageManager
    from packages.data.src.trade_journal import TradeJournal, JournalEntry

    storage = StorageManager()
    storage.initialize()
    journal = TradeJournal(storage)

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
    stats = journal.get_stats()
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .storage import StorageManager

logger = logging.getLogger("flinttrade.data.trade_journal")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_JOURNAL = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id                  VARCHAR PRIMARY KEY,
    symbol              VARCHAR NOT NULL,
    exchange            VARCHAR NOT NULL,
    side                VARCHAR NOT NULL,
    quantity            INTEGER NOT NULL,
    entry_price         DOUBLE NOT NULL,
    exit_price          DOUBLE,
    entry_time          TIMESTAMP,
    exit_time           TIMESTAMP,
    strategy            VARCHAR,
    tags                VARCHAR,
    notes               VARCHAR,
    screenshot_path     VARCHAR,
    emotion_before      VARCHAR,
    emotion_after       VARCHAR,
    setup_quality       INTEGER,
    execution_quality   INTEGER,
    pnl                 DOUBLE,
    pnl_pct             DOUBLE,
    risk_reward_ratio   DOUBLE,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL
);
"""

_IDX_JOURNAL = [
    "CREATE INDEX IF NOT EXISTS idx_journal_symbol ON journal_entries (symbol)",
    "CREATE INDEX IF NOT EXISTS idx_journal_strategy ON journal_entries (strategy)",
    "CREATE INDEX IF NOT EXISTS idx_journal_entry_time ON journal_entries (entry_time)",
]

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
    """Coerce a DuckDB-returned timestamp value to a Python datetime.

    DuckDB ``fetchdf()`` can return timestamps as pandas Timestamps, Python
    datetime objects, or integer/float epoch microseconds depending on the
    driver version and column type.

    Args:
        value: Raw value from a DuckDB TIMESTAMP column.

    Returns:
        A timezone-aware datetime (IST) or ``None`` if the value is null/NaT.
    """
    import math

    if value is None:
        return None
    # pandas NaT
    try:
        import pandas as pd
        if isinstance(value, pd.NaT.__class__) or (
            isinstance(value, float) and math.isnan(value)
        ):
            return None
        if isinstance(value, pd.Timestamp):
            dt = value.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt
    except ImportError:
        pass

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=IST)
        return value

    # Epoch microseconds (int or float)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1_000_000, tz=IST)
        except (OSError, OverflowError, ValueError):
            try:
                return datetime.fromtimestamp(value, tz=IST)
            except (OSError, OverflowError, ValueError):
                return None

    # Last resort: string parsing
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt
    except ValueError:
        return None


def _row_to_entry(row: dict[str, Any]) -> JournalEntry:
    """Convert a DuckDB result row dict to a JournalEntry.

    Tags are stored as a JSON array string in DuckDB; this function deserialises
    them back to ``list[str]``.  Timestamp columns are coerced to timezone-aware
    Python datetimes.

    Args:
        row: Dictionary produced by ``fetchdf().to_dict("records")``.

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

    # DuckDB / pandas returns NULL numeric columns as float NaN.
    # Convert NaN → None so Pydantic Optional[float] validation works correctly.
    import math

    for key, val in row.items():
        if isinstance(val, float) and math.isnan(val):
            row[key] = None

    return JournalEntry.model_validate(row)


def _entry_to_row(entry: JournalEntry) -> dict[str, Any]:
    """Serialise a JournalEntry to a flat dict for DuckDB insertion.

    Tags are JSON-encoded to a single VARCHAR column.

    Args:
        entry: The journal entry to serialise.

    Returns:
        Dict with all columns as scalar values.
    """
    return {
        "id": entry.id,
        "symbol": entry.symbol,
        "exchange": entry.exchange,
        "side": entry.side,
        "quantity": entry.quantity,
        "entry_price": entry.entry_price,
        "exit_price": entry.exit_price,
        "entry_time": entry.entry_time,
        "exit_time": entry.exit_time,
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
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


# ---------------------------------------------------------------------------
# TradeJournal
# ---------------------------------------------------------------------------

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class TradeJournal:
    """DuckDB-backed trade journal with CRUD, stats, CSV export, and tradebook import.

    The journal lives in a ``journal_entries`` table in the same DuckDB file
    as the rest of FlintTrade's data.  Call :meth:`initialize` once before
    first use (or rely on :class:`~storage.StorageManager` to call it for you
    after ``add_journal_schema``).

    Args:
        storage: An initialised :class:`~storage.StorageManager` instance.

    Example::

        journal = TradeJournal(storage)
        journal.initialize()
        eid = journal.add_entry(JournalEntry(
            symbol="BANKNIFTY", exchange="NFO", side="BUY",
            quantity=25, entry_price=48000.0, exit_price=48500.0,
        ))
        entry = journal.get_entry(eid)
        stats = journal.get_stats()
    """

    def __init__(self, storage: StorageManager) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create the ``journal_entries`` table and indexes if they do not exist.

        Safe to call multiple times (CREATE IF NOT EXISTS).
        """
        conn = self._storage.connection
        conn.execute(_SCHEMA_JOURNAL)
        for idx_sql in _IDX_JOURNAL:
            conn.execute(idx_sql)
        logger.info("TradeJournal schema initialised")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_entry(self, entry: JournalEntry) -> str:
        """Insert a new journal entry into DuckDB.

        Args:
            entry: The :class:`JournalEntry` to persist.

        Returns:
            The ``id`` of the newly created entry (UUID string).
        """
        row = _entry_to_row(entry)
        conn = self._storage.connection
        conn.execute(
            """
            INSERT INTO journal_entries VALUES (
                $id, $symbol, $exchange, $side, $quantity,
                $entry_price, $exit_price, $entry_time, $exit_time,
                $strategy, $tags, $notes, $screenshot_path,
                $emotion_before, $emotion_after,
                $setup_quality, $execution_quality,
                $pnl, $pnl_pct, $risk_reward_ratio,
                $created_at, $updated_at
            )
            """,
            row,
        )
        logger.info("Journal entry added: id=%s symbol=%s", entry.id, entry.symbol)
        return entry.id

    def get_entry(self, entry_id: str) -> JournalEntry | None:
        """Fetch a single entry by its UUID.

        Args:
            entry_id: The UUID string of the entry.

        Returns:
            The :class:`JournalEntry`, or ``None`` if not found.
        """
        conn = self._storage.connection
        result = conn.execute(
            "SELECT * FROM journal_entries WHERE id = $id",
            {"id": entry_id},
        ).fetchdf()
        if result.empty:
            return None
        return _row_to_entry(result.to_dict("records")[0])

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
        params: dict[str, Any] = {}

        if filters.start_date:
            clauses.append("entry_time >= $start_date")
            params["start_date"] = filters.start_date

        if filters.end_date:
            clauses.append("entry_time <= CAST($end_date AS DATE) + INTERVAL '1 day'")
            params["end_date"] = filters.end_date

        if filters.symbol:
            clauses.append("symbol = $symbol")
            params["symbol"] = filters.symbol

        if filters.strategy:
            clauses.append("strategy = $strategy")
            params["strategy"] = filters.strategy

        if filters.side:
            clauses.append("side = $side")
            params["side"] = filters.side.upper()

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = filters.limit
        params["offset"] = filters.offset

        sql = f"""
            SELECT * FROM journal_entries
            {where}
            ORDER BY COALESCE(entry_time, created_at) DESC, id
            LIMIT $limit OFFSET $offset
        """
        conn = self._storage.connection
        result = conn.execute(sql, params).fetchdf()

        rows = result.to_dict("records")

        # Post-filter by tags (DuckDB VARCHAR LIKE is cumbersome for JSON arrays)
        entries = [_row_to_entry(r) for r in rows]
        if filters.tags:
            required = set(filters.tags)
            entries = [e for e in entries if required.issubset(set(e.tags))]

        return entries

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
        # Clear pnl so the model_validator recomputes it when exit_price changes.
        if "exit_price" in updates or "entry_price" in updates or "quantity" in updates:
            current_data.pop("pnl", None)
            current_data.pop("pnl_pct", None)
        current_data["updated_at"] = datetime.now(IST)
        updated = JournalEntry.model_validate(current_data)

        row = _entry_to_row(updated)
        # Build SET clause — filter through allowlist to prevent SQL injection,
        # and exclude immutable columns (id, created_at).
        set_keys = [k for k in row if k in _ALLOWED_COLUMNS and k not in ("id", "created_at")]
        set_clause = ", ".join(f"{k} = ${k}" for k in set_keys)
        update_params = {k: row[k] for k in set_keys}
        update_params["id"] = row["id"]
        conn = self._storage.connection
        conn.execute(
            f"UPDATE journal_entries SET {set_clause} WHERE id = $id",
            update_params,
        )
        logger.info("Journal entry updated: id=%s", entry_id)
        return updated

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
        conn = self._storage.connection
        conn.execute("DELETE FROM journal_entries WHERE id = $id", {"id": entry_id})
        logger.info("Journal entry deleted: id=%s", entry_id)
        return True

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

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
            symbol = trade.get("symbol", "")
            exchange = trade.get("exchange", "NSE")
            side = trade.get("action", trade.get("side", "BUY")).upper()
            quantity = int(trade.get("quantity", trade.get("qty", 0)))
            price = float(trade.get("price", trade.get("trade_price", 0.0)))

            # Parse timestamp from tradebook field names OpenAlgo uses
            raw_ts = trade.get("timestamp") or trade.get("time") or trade.get("order_time")
            entry_time: datetime | None = None
            if raw_ts:
                try:
                    if isinstance(raw_ts, (int, float)):
                        entry_time = datetime.fromtimestamp(raw_ts, tz=IST)
                    else:
                        entry_time = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
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
