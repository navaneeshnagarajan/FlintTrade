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

from collections.abc import Callable
from datetime import datetime, timezone
import functools
import hashlib
import logging
from pathlib import Path
import sqlite3
import threading
from typing import Any, TypeVar

logger = logging.getLogger("flinttrade.ai.session_store")

_T = TypeVar("_T")

_VALID_SURFACES = {"advisor", "tutor", "agent", "saved-chat"}
_TITLE_MAX_CHARS = 120
_DEFAULT_MAX_SESSIONS = 500


def _locked(method: Callable[..., _T]) -> Callable[..., _T]:
    @functools.wraps(method)
    def wrapper(self: "AiSessionStore", *args: Any, **kwargs: Any) -> _T:
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
    return datetime.now(timezone.utc).isoformat()


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
                digest = hashlib.sha1(
                    f"{session_id}:{role}:{content}".encode()
                ).hexdigest()[:20]
                message_id = f"h-{digest}"
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
            inserted += cursor.rowcount if cursor.rowcount > 0 else 0
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
