"""Webhook nonce replay defence (data-layer §7.4 / §12; Database H8 + Identity M5).

Replay *defence* is the receiver's responsibility and MUST run before a signed
external-intent payload is acted on — never rely on the nightly nonce GC for
security. Two independent gates:

  - freshness: reject any payload whose own ``timestamp`` is older than the
    10-minute replay window, even if its nonce was never seen (defeats a captured
    payload replayed after the window).
  - uniqueness: reject any ``(webhook_id, nonce)`` already recorded inside the
    window (defeats an in-window double-submit).

The nonce table is the canonical §7.1 ``webhook_nonces`` shape; the auth-state
migrator owns the authoritative DDL, and ``ensure_nonce_schema`` here is the
idempotent ``CREATE … IF NOT EXISTS`` mirror so the store is usable before a
full migration has run.
"""

from __future__ import annotations

import math
import time

# Database H8 + Identity M5 (data-layer §7.4):
REPLAY_WINDOW_SECONDS = 600        # 10 min — TradingView/ChartInk freshness norm
GC_GRACE_SECONDS = 3600            # 60 min forensic-evidence grace
GC_RETAIN_SECONDS = REPLAY_WINDOW_SECONDS + GC_GRACE_SECONDS

# Audit reasons surfaced to the receiver so it can emit the right event.
REASON_STALE = "WEBHOOK_STALE"
REASON_REPLAY = "WEBHOOK_REPLAY_REJECTED"

_NONCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_nonces (
    webhook_id      TEXT NOT NULL,
    nonce           TEXT NOT NULL,
    seen_at         REAL NOT NULL,
    source_ip_hash  TEXT,
    PRIMARY KEY (webhook_id, nonce)
);
CREATE INDEX IF NOT EXISTS idx_webhook_nonces_gc ON webhook_nonces(seen_at);
"""


def ensure_nonce_schema(conn) -> None:
    """Idempotently create the ``webhook_nonces`` table + GC index."""
    conn.executescript(_NONCE_SCHEMA)


def is_stale(payload_ts: float, now: float | None = None) -> bool:
    """True if the payload's own timestamp is outside the freshness window."""
    now = time.time() if now is None else now
    if not math.isfinite(payload_ts) or not math.isfinite(now):
        return True
    return abs(now - payload_ts) > REPLAY_WINDOW_SECONDS


def is_known_nonce(conn, webhook_id: str, nonce: str, now: float | None = None) -> bool:
    """True if this ``(webhook_id, nonce)`` was already seen inside the window."""
    now = time.time() if now is None else now
    row = conn.execute(
        "SELECT 1 FROM webhook_nonces "
        "WHERE webhook_id = ? AND nonce = ? AND seen_at > ?",
        (webhook_id, nonce, now - REPLAY_WINDOW_SECONDS),
    ).fetchone()
    return row is not None


def check_replay(
    conn,
    webhook_id: str,
    nonce: str,
    payload_ts: float,
    now: float | None = None,
) -> str | None:
    """Classify a payload before it is acted on.

    Returns ``None`` if fresh and unseen (caller should then ``record_nonce``),
    ``REASON_STALE`` if outside the freshness window, or ``REASON_REPLAY`` if the
    nonce was already seen within the window. Freshness is checked first so a
    stale replay is reported as stale (the more specific cause).
    """
    now = time.time() if now is None else now
    if is_stale(payload_ts, now):
        return REASON_STALE
    if is_known_nonce(conn, webhook_id, nonce, now):
        return REASON_REPLAY
    return None


def record_nonce(
    conn,
    webhook_id: str,
    nonce: str,
    seen_at: float | None = None,
    source_ip_hash: str | None = None,
) -> None:
    """Persist a nonce after it has passed :func:`check_replay`.

    Rebinds an expired nonce to the newly accepted timestamp. Without the
    conflict update, a legitimate post-window reuse would leave the old row in
    place and an immediate replay of the newly signed request could pass. The
    store serialises check + record with ``BEGIN IMMEDIATE``.
    """
    seen_at = time.time() if seen_at is None else seen_at
    conn.execute(
        "INSERT INTO webhook_nonces (webhook_id, nonce, seen_at, source_ip_hash) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(webhook_id, nonce) DO UPDATE SET "
        "seen_at = excluded.seen_at, source_ip_hash = excluded.source_ip_hash",
        (webhook_id, nonce, seen_at, source_ip_hash),
    )


def gc_old_nonces(
    conn,
    retain_seconds: int = GC_RETAIN_SECONDS,
    now: float | None = None,
) -> int:
    """Delete replay nonces older than the defence window plus audit grace."""
    cutoff = (time.time() if now is None else now) - retain_seconds
    cursor = conn.execute("DELETE FROM webhook_nonces WHERE seen_at < ?", (cutoff,))
    return cursor.rowcount
