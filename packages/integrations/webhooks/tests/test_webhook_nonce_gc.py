"""Nonce GC retention tests (data-layer §7.4 / §7.5; Database H8 DL-08).

The GC must retain the 70-minute window (10-min replay + 60-min forensic grace),
NOT collapse it to the 10-minute replay window — otherwise the 10–70-min evidence
bucket is discarded. The GC script lives outside any package, so it is loaded by
file path here.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_GC_PATH = Path(__file__).resolve().parents[4] / "scripts" / "webhook_nonce_gc.py"


def _load_gc():
    spec = importlib.util.spec_from_file_location("webhook_nonce_gc", _GC_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gc():
    return _load_gc()


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript(
        "CREATE TABLE webhook_nonces (webhook_id TEXT, nonce TEXT, seen_at REAL, "
        "source_ip_hash TEXT, PRIMARY KEY (webhook_id, nonce));"
    )
    try:
        yield c
    finally:
        c.close()


def test_default_retain_is_4200_seconds(gc) -> None:
    assert gc.GC_RETAIN_SECONDS == 4200
    assert gc.REPLAY_WINDOW_SECONDS == 600
    assert gc.GC_GRACE_SECONDS == 3600


def test_gc_retains_70_minutes(gc, conn) -> None:
    now = 1_000_000.0
    conn.execute(
        "INSERT INTO webhook_nonces VALUES (?,?,?,?)", ("wh", "old", now - 8000, None)
    )   # > 70 min → deleted
    conn.execute(
        "INSERT INTO webhook_nonces VALUES (?,?,?,?)", ("wh", "mid", now - 3000, None)
    )   # < 70 min → kept
    deleted = gc.gc_old_nonces(conn, now=now)
    assert deleted == 1
    remaining = {r[0] for r in conn.execute("SELECT nonce FROM webhook_nonces").fetchall()}
    assert remaining == {"mid"}


def test_gc_keeps_recent(gc, conn) -> None:
    now = 1_000_000.0
    conn.execute(
        "INSERT INTO webhook_nonces VALUES (?,?,?,?)", ("wh", "fresh", now - 300, None)
    )
    deleted = gc.gc_old_nonces(conn, now=now)
    assert deleted == 0
    assert conn.execute("SELECT COUNT(*) FROM webhook_nonces").fetchone()[0] == 1


def test_secret_store_gc_uses_the_same_retention_contract(tmp_path) -> None:
    from flinttrade_webhooks.webhook_replay import REASON_REPLAY
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

    store = WebhookSecretStore(tmp_path / "webhook-secrets.db", "test-master-password")
    path = "/v1/webhook/custom/gc-test"
    assert store.check_and_record_nonce(path, "expired", 1_700.0, now=1_700.0) is None
    assert store.check_and_record_nonce(path, "recent", 5_500.0, now=5_500.0) is None

    assert store.gc_nonces(now=6_000.0) == 1
    assert store.check_and_record_nonce(path, "expired", 6_000.0, now=6_000.0) is None
    assert store.check_and_record_nonce(path, "recent", 6_000.0, now=6_000.0) == REASON_REPLAY


def test_post_window_nonce_reuse_is_rebound_and_immediate_replay_is_blocked(tmp_path) -> None:
    from flinttrade_webhooks.webhook_replay import REASON_REPLAY
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

    store = WebhookSecretStore(tmp_path / "webhook-secrets.db", "test-master-password")
    path = "/v1/webhook/custom/reused-nonce"

    assert store.check_and_record_nonce(path, "reused", 1_000.0, now=1_000.0) is None
    assert store.check_and_record_nonce(path, "reused", 1_601.0, now=1_601.0) is None
    assert store.check_and_record_nonce(path, "reused", 1_602.0, now=1_602.0) == REASON_REPLAY


def test_intake_prunes_expired_nonce_evidence_without_cron(tmp_path) -> None:
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

    db_path = tmp_path / "webhook-secrets.db"
    store = WebhookSecretStore(db_path, "test-master-password")
    path = "/v1/webhook/custom/opportunistic-gc"

    assert store.check_and_record_nonce(path, "expired", 1_000.0, now=1_000.0) is None
    assert store.check_and_record_nonce(path, "current", 6_000.0, now=6_000.0) is None

    with sqlite3.connect(db_path) as conn:
        remaining = {row[0] for row in conn.execute("SELECT nonce FROM webhook_nonces")}
    assert remaining == {"current"}
