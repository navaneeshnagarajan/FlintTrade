"""AI session store — SQLite + FTS5 persistence for AI chat sessions.

Cross-session recall (reference-map AI2, hermes H5 port): every advisor/tutor
exchange persists server-side so past conversations survive browser resets
and are full-text searchable ("what did the advisor say about BANKNIFTY?").

Follows the house SQLite+FTS5 shape proven by
:class:`flinttrade_journal.trade_journal.TradeJournal` (G31): one shared
connection serialised by an RLock across Flask request threads, an FTS5
index kept in sync by triggers, and a malformed-query-safe ``search()``
that retries caller input as a quoted phrase before returning empty.

Capture is best-effort by design — recording must never break a chat — and
idempotent per message id, because the advisor receives the FULL message
history on every request.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger("flinttrade.ai.session_store")

_T = TypeVar("_T")

_VALID_SURFACES = {"advisor", "tutor", "agent", "saved-chat"}
_TITLE_MAX_CHARS = 120
_DEFAULT_MAX_SESSIONS = 500

# Content-hash message ids. This digest is a dedup key — "the client replayed a
# message it already sent" — not a credential digest and not an integrity check
# against an adversary: the only writer is the operator's own terminal. It is
# still SHA-256 rather than SHA-1, because nothing here wanted SHA-1's
# properties in the first place. Truncated to 20 hex characters (80 bits): an
# accidental collision would merge two distinct messages, and 80 bits is orders
# of magnitude beyond what a store capped at a few hundred sessions can reach.
_CONTENT_ID_PREFIX = "h-"
_CONTENT_ID_HEX_CHARS = 20
# Bumped when a stored shape changes; tracked in SQLite's ``user_version``.
# 1: content-hash message ids re-keyed from SHA-1 onto SHA-256.
_SCHEMA_VERSION = 1


def _content_message_id(session_id: str, role: str, content: str) -> str:
    """Derive the deterministic id for a message the client did not name.

    Args:
        session_id: The owning session's id.
        role: ``user`` or ``assistant``.
        content: The message text.

    Returns:
        The ``h-``-prefixed content-hash id.
    """
    digest = hashlib.sha256(f"{session_id}:{role}:{content}".encode()).hexdigest()
    return f"{_CONTENT_ID_PREFIX}{digest[:_CONTENT_ID_HEX_CHARS]}"


def _locked(method: Callable[..., _T]) -> Callable[..., _T]:
    @functools.wraps(method)
    def wrapper(self: AiSessionStore, *args: Any, **kwargs: Any) -> _T:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id         TEXT PRIMARY KEY,
        surface    TEXT NOT NULL,
        title      TEXT NOT NULL,
        started_at TEXT NOT NULL,
        last_at    TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_last_at ON sessions (last_at)",
    """
    CREATE TABLE IF NOT EXISTS messages (
        id         TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id)",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(id UNINDEXED, session_id UNINDEXED, content)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, id, session_id, content)
        VALUES (new.rowid, new.id, new.session_id, new.content);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
        DELETE FROM messages_fts WHERE rowid = old.rowid;
    END
    """,
]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AiSessionStore:
    """SQLite + FTS5 store for AI chat sessions.

    Args:
        db_path: SQLite file path, or ``":memory:"`` for tests.
    """

    def __init__(self, db_path: Path | str) -> None:
        if isinstance(db_path, Path):
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # Serialises the shared connection across Flask request threads.
        self._lock = threading.RLock()
        for statement in _SCHEMA_STATEMENTS:
            self._conn.execute(statement)
        self._conn.commit()
        self._migrate_content_ids()

    def _migrate_content_ids(self) -> None:
        """Re-key legacy content-hash message ids onto the current digest.

        The content-hash id is the whole of the store's idempotency: the
        advisor replays the full history on every request and relies on those
        ids colliding with the rows already stored. A store written before the
        SHA-256 switch would therefore gain a second copy of every message the
        first time an old conversation was continued. Recomputing the ids from
        the columns that produced them fixes that without touching any other
        stored data. Gated on ``PRAGMA user_version``, so it runs once.
        """
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= _SCHEMA_VERSION:
            return
        rows = self._conn.execute(
            "SELECT rowid, id, session_id, role, content FROM messages WHERE id LIKE ?",
            (f"{_CONTENT_ID_PREFIX}%",),
        ).fetchall()
        rekeyed = 0
        for row in rows:
            new_id = _content_message_id(row["session_id"], row["role"], row["content"])
            if new_id == row["id"]:
                continue
            # OR IGNORE: if the recomputed id somehow already exists, the old
            # row simply keeps its id rather than aborting the whole migration.
            cursor = self._conn.execute(
                "UPDATE OR IGNORE messages SET id = ? WHERE rowid = ?",
                (new_id, row["rowid"]),
            )
            if cursor.rowcount:
                # The FTS mirror carries an UNINDEXED copy of the id; keep it
                # truthful even though searches read the id from ``messages``.
                self._conn.execute(
                    "UPDATE messages_fts SET id = ? WHERE rowid = ?",
                    (new_id, row["rowid"]),
                )
                rekeyed += 1
        self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION:d}")
        self._conn.commit()
        if rekeyed:
            logger.info("Re-keyed %d legacy content-hash message ids", rekeyed)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @_locked
    def record_exchange(
        self,
        session_id: str,
        surface: str,
        messages: list[dict[str, Any]],
        *,
        title: str | None = None,
    ) -> int:
        """Upsert a session and insert any NEW messages (idempotent by id).

        Args:
            session_id: Stable client-owned conversation id.
            surface: One of ``advisor``/``tutor``/``agent``/``saved-chat``.
            messages: ``{role, content}`` dicts (``id`` and ``created_at``
                optional) — the full history is fine on every call. When
                ``id`` is absent, a deterministic content-hash id is derived,
                so the same (session, role, content) never inserts twice
                across requests regardless of client-side ids. (Identical
                repeated texts in one session therefore collapse to one row —
                acceptable for a search store.) When ``created_at`` (ISO
                string) is present it is stored verbatim so imported
                conversations keep their original message times; otherwise
                the recording time is used.
            title: Optional explicit session title (imports carry one). When
                absent the title derives from the first user message.

        Returns:
            Number of newly inserted messages.

        Raises:
            ValueError: On a blank session id or unknown surface — recording
                callers wrap this best-effort.
        """
        session_id = (session_id or "").strip()
        if not session_id:
            raise ValueError("session_id is required")
        if surface not in _VALID_SURFACES:
            raise ValueError(f"surface must be one of {sorted(_VALID_SURFACES)}")

        now = _now_iso()
        clean: list[tuple[str, str, str, str]] = []
        for message in messages:
            role = str(message.get("role", "") or "").strip()
            content = str(message.get("content", "") or "")
            if role not in {"user", "assistant"} or not content.strip():
                continue
            message_id = str(message.get("id", "") or "").strip()
            if not message_id:
                message_id = _content_message_id(session_id, role, content)
            created_at = str(message.get("created_at", "") or "").strip() or now
            clean.append((message_id, role, content, created_at))
        if not clean:
            return 0

        session_title = (title or "").strip().replace("\n", " ")[:_TITLE_MAX_CHARS]
        if not session_title:
            first_user = next((c for (_i, r, c, _t) in clean if r == "user"), clean[0][2])
            session_title = first_user.strip().replace("\n", " ")[:_TITLE_MAX_CHARS]

        self._conn.execute(
            """
            INSERT INTO sessions (id, surface, title, started_at, last_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET last_at = excluded.last_at
            """,
            (session_id, surface, session_title, now, now),
        )
        inserted = 0
        for message_id, role, content, created_at in clean:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO messages (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, session_id, role, content, created_at),
            )
            inserted += max(0, cursor.rowcount)
        self._conn.commit()
        return inserted

    @_locked
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages. Returns True when it existed."""
        cursor = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    @_locked
    def prune(self, max_sessions: int = _DEFAULT_MAX_SESSIONS) -> int:
        """Keep the newest ``max_sessions`` sessions; delete the rest.

        Returns:
            Number of sessions removed.
        """
        rows = self._conn.execute(
            "SELECT id FROM sessions ORDER BY last_at DESC LIMIT -1 OFFSET ?",
            (max(0, max_sessions),),
        ).fetchall()
        for row in rows:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
        self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @_locked
    def list_sessions(self, *, limit: int = 50, surface: str | None = None) -> list[dict[str, Any]]:
        """Newest-first session summaries with message counts."""
        where = "WHERE s.surface = ?" if surface else ""
        params: list[Any] = [surface] if surface else []
        rows = self._conn.execute(
            f"""
            SELECT s.id, s.surface, s.title, s.started_at, s.last_at,
                   COUNT(m.id) AS message_count
            FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
            {where}
            GROUP BY s.id ORDER BY s.last_at DESC LIMIT ?
            """,
            [*params, max(1, limit)],
        ).fetchall()
        return [dict(row) for row in rows]

    @_locked
    def session_surface(self, session_id: str) -> str | None:
        """Surface of the stored session, or None when the id is unknown.

        A lightweight existence probe for the import route's cross-surface
        collision check — unlike :meth:`get_session` it never loads messages.
        """
        row = self._conn.execute(
            "SELECT surface FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return str(row["surface"]) if row is not None else None

    @_locked
    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """One session with its ordered messages, or None."""
        session = self._conn.execute(
            "SELECT id, surface, title, started_at, last_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if session is None:
            return None
        messages = self._conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY created_at, rowid",
            (session_id,),
        ).fetchall()
        result = dict(session)
        result["messages"] = [dict(m) for m in messages]
        return result

    @_locked
    def search(self, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Full-text search across message content (FTS5, relevance-ranked).

        A blank query returns nothing; malformed MATCH syntax retries as a
        quoted phrase and then yields an empty list — caller input is never
        a 500.
        """
        term = (query or "").strip()
        if not term:
            return []
        sql = (
            "SELECT m.id, m.session_id, m.role, m.created_at, s.surface, s.title, "
            "snippet(messages_fts, 2, '[', ']', ' … ', 12) AS snippet "
            "FROM messages_fts f "
            "JOIN messages m ON m.rowid = f.rowid "
            "JOIN sessions s ON s.id = m.session_id "
            "WHERE messages_fts MATCH ? ORDER BY rank LIMIT ?"
        )
        try:
            rows = self._conn.execute(sql, (term, max(1, limit))).fetchall()
        except sqlite3.OperationalError:
            try:
                phrase = '"' + term.replace('"', '""') + '"'
                rows = self._conn.execute(sql, (phrase, max(1, limit))).fetchall()
            except sqlite3.OperationalError:
                logger.warning("AI session FTS query rejected: %r", term)
                return []
        return [dict(row) for row in rows]

    @_locked
    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()
