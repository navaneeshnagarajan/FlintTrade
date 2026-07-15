"""Webhook replay-defence tests (data-layer §7.4 / §7.5; Database H8 + Identity M5)."""

from __future__ import annotations

import sqlite3

import pytest

from flinttrade_webhooks.webhook_replay import (
    REASON_REPLAY,
    REASON_STALE,
    check_replay,
    ensure_nonce_schema,
    is_known_nonce,
    is_stale,
    record_nonce,
)

WEBHOOK = "wh-1"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    ensure_nonce_schema(c)
    try:
        yield c
    finally:
        c.close()


def test_fresh_unseen_nonce_passes(conn) -> None:
    now = 10_000.0
    assert check_replay(conn, WEBHOOK, "n1", payload_ts=now, now=now) is None


def test_replay_within_window_rejected(conn) -> None:
    """Same nonce twice inside 600s → second is REASON_REPLAY."""
    now = 10_000.0
    assert check_replay(conn, WEBHOOK, "n1", payload_ts=now, now=now) is None
    record_nonce(conn, WEBHOOK, "n1", seen_at=now)
    assert check_replay(conn, WEBHOOK, "n1", payload_ts=now + 5, now=now + 5) == REASON_REPLAY


def test_replay_window_is_10_minutes(conn) -> None:
    """A 700s-old payload is stale even though its nonce was never seen."""
    now = 10_000.0
    assert check_replay(conn, WEBHOOK, "never-seen", payload_ts=now - 700, now=now) == REASON_STALE


def test_stale_takes_precedence_over_replay(conn) -> None:
    now = 10_000.0
    record_nonce(conn, WEBHOOK, "n1", seen_at=now - 800)
    # both stale AND a known nonce — stale is the reported reason
    assert check_replay(conn, WEBHOOK, "n1", payload_ts=now - 800, now=now) == REASON_STALE


def test_same_nonce_different_webhook_is_not_replay(conn) -> None:
    now = 10_000.0
    record_nonce(conn, WEBHOOK, "shared", seen_at=now)
    assert check_replay(conn, "wh-other", "shared", payload_ts=now, now=now) is None


def test_nonce_outside_window_no_longer_blocks(conn) -> None:
    """A nonce last seen >600s ago is no longer a replay (GC will sweep it)."""
    now = 10_000.0
    record_nonce(conn, WEBHOOK, "n1", seen_at=now - 700)
    assert is_known_nonce(conn, WEBHOOK, "n1", now=now) is False


def test_is_stale_boundary() -> None:
    now = 10_000.0
    assert is_stale(now - 600, now) is False   # exactly at window — fresh
    assert is_stale(now - 601, now) is True     # one second past — stale
    assert is_stale(now + 601, now) is True     # future skew beyond window — stale


@pytest.mark.parametrize("payload_ts", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_timestamp_is_always_stale(conn, payload_ts: float) -> None:
    assert is_stale(payload_ts, 1_000.0) is True
    assert check_replay(conn, WEBHOOK, "non-finite", payload_ts=payload_ts, now=1_000.0) == REASON_STALE


def test_record_nonce_rebinds_the_accepted_timestamp(conn) -> None:
    now = 10_000.0
    record_nonce(conn, WEBHOOK, "n1", seen_at=now)
    record_nonce(conn, WEBHOOK, "n1", seen_at=now + 1)  # no IntegrityError
    rows = conn.execute(
        "SELECT seen_at FROM webhook_nonces WHERE webhook_id=? AND nonce=?", (WEBHOOK, "n1")
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == now + 1
