"""Fail-closed current webhook consumer after auth-state cutover."""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path

import duckdb
import pytest

from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("damage", ["missing", "empty", "missing_nonces", "duckdb", "corrupt"])
def test_webhook_authority_is_never_recreated(damage: str, tmp_path: Path) -> None:
    path = tmp_path / "webhook_secrets.db"
    password = secrets.token_urlsafe(24)
    store = WebhookSecretStore(path, password)
    store.store_secret("/synthetic", "fixture", "fixture", secrets.token_urlsafe(24))
    if damage == "missing":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    elif damage == "corrupt":
        path.write_bytes(b"corrupt authority")
    elif damage == "missing_nonces":
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE webhook_nonces")
    else:
        path.unlink()
        with duckdb.connect(str(path), config={"threads": 1}) as db:
            db.execute("CREATE TABLE credentials (retained BLOB)")
    original = path.read_bytes() if path.exists() else None
    with pytest.raises((RuntimeError, sqlite3.DatabaseError, OSError)):
        WebhookSecretStore(path, password)
    assert (path.read_bytes() if path.exists() else None) == original
    with pytest.raises((RuntimeError, sqlite3.DatabaseError, OSError)):
        store.has_secret("/synthetic")
    assert not list(tmp_path.glob("*.pre-sqlite.bak*"))


def test_webhook_restart_read_does_not_discard_historical_nonce_evidence(tmp_path: Path) -> None:
    path = tmp_path / "webhook_secrets.db"
    password, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    store = WebhookSecretStore(path, password)
    store.store_secret("/synthetic", "fixture", "fixture", secret)
    assert store.check_and_record_nonce("/synthetic", "old-evidence", 1000.0, now=1000.0) is None
    reopened = WebhookSecretStore(path, password)
    matches = reopened.get_secret("/synthetic") == secret
    assert matches, "secret mismatch after restart"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT nonce FROM webhook_nonces").fetchall() == [("old-evidence",)]
