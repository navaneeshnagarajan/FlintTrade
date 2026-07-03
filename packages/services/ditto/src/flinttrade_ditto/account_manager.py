"""Multi-account manager — registry, health checks, groups, encrypted storage.

Each broker account corresponds to a separate OpenAlgo instance running on a
different port. Ditto manages them as a unified pool for position mirroring.
API keys are encrypted at rest using Fernet symmetric encryption.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from flinttrade_core.db import open_sqlite

logger = logging.getLogger("flinttrade.ditto.accounts")

IST = timezone(timedelta(hours=5, minutes=30))
def _default_db() -> str:
    """Resolve SQLite path: env override > workspace > fallback."""
    env = os.getenv("DATA_DIR")
    if env:
        return env + "/ditto_accounts.sqlite"
    try:
        from flinttrade_core.workspace import Workspace
        return str(Workspace().fast_data_dir / "ditto_accounts.sqlite")
    except Exception:
        return str(Path.home() / ".flinttrade" / "data" / "ditto_accounts.sqlite")


# ---------------------------------------------------------------------------
# Account dataclass
# ---------------------------------------------------------------------------


@dataclass
class BrokerAccount:
    """A single broker account connected via its own OpenAlgo instance."""

    account_id: str
    openalgo_host: str
    api_key: str
    name: str = ""
    enabled: bool = True
    allocation_weight: float = 1.0  # Relative weight for weighted allocation
    group: str = "default"  # "family", "personal", "HNI", etc.
    max_loss_daily: float = 50000.0
    is_master: bool = False

    @property
    def display(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"{self.account_id} ({self.name}) [{status}] group={self.group} weight={self.allocation_weight}"


@dataclass
class AccountHealth:
    """Health check result for a single account."""

    account_id: str
    reachable: bool = False
    latency_ms: float = 0.0
    error: str = ""
    checked_at: str = ""


@dataclass
class AccountStatus:
    """Consolidated connection + daily-reauth status for the Account Manager.

    Derived from a live OpenAlgo ping: a 200 means the broker session is
    authenticated today; a 4xx means it is reachable but needs re-auth; a
    connection failure means it is offline.
    """

    account_id: str
    name: str
    enabled: bool
    connected: bool = False       # OpenAlgo reachable (any HTTP response)
    authenticated: bool = False   # broker session valid today (ping 200)
    needs_reauth: bool = True     # daily re-auth required
    latency_ms: float = 0.0
    error: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict  # noqa: PLC0415

        return asdict(self)


# ---------------------------------------------------------------------------
# Fernet encryption for API keys at rest
# ---------------------------------------------------------------------------


def _get_fernet(key: str | None = None):
    """Get a Fernet instance for encrypting/decrypting API keys."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ImportError("cryptography required — pip install cryptography")

    encryption_key = key or os.getenv("DITTO_ENCRYPTION_KEY", "")
    if not encryption_key:
        raise ValueError(
            "DITTO_ENCRYPTION_KEY environment variable is required. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)


def encrypt_value(plaintext: str, key: str | None = None) -> str:
    """Encrypt a string value."""
    f = _get_fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, key: str | None = None) -> str:
    """Decrypt a string value."""
    f = _get_fernet(key)
    return f.decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    openalgo_host TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    allocation_weight REAL DEFAULT 1.0,
    account_group TEXT DEFAULT 'default',
    max_loss_daily REAL DEFAULT 50000.0,
    is_master INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
"""


# ---------------------------------------------------------------------------
# AccountManager
# ---------------------------------------------------------------------------


class AccountManager:
    """Manage multiple OpenAlgo broker accounts.

    Usage::

        mgr = AccountManager()
        mgr.add_account(BrokerAccount(
            account_id="acc1",
            openalgo_host="http://your-openalgo-host:5001",
            api_key="your-api-key-1",
            name="Personal",
            group="personal", allocation_weight=1.0,
        ))
        mgr.add_account(BrokerAccount(
            account_id="acc2",
            openalgo_host="http://your-openalgo-host:5002",
            api_key="your-api-key-2",
            name="Family",
            group="family", allocation_weight=2.0,
        ))
        health = mgr.health_check_all()
        active = mgr.get_enabled_accounts()
    """

    def __init__(
        self,
        db_path: str | None = None,
        encryption_key: str | None = None,
    ) -> None:
        self._db_path = db_path or _default_db()
        self._enc_key = encryption_key
        self._conn: sqlite3.Connection | None = None
        self._cache: dict[str, BrokerAccount] = {}
        self._http = httpx.Client(timeout=10.0)

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = open_sqlite(self._db_path, durability="normal")
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
        self._http.close()

    def __enter__(self) -> AccountManager:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_account(self, account: BrokerAccount) -> None:
        """Register a new broker account."""
        conn = self._get_conn()
        now = datetime.now(IST).isoformat()
        encrypted_key = encrypt_value(account.api_key, self._enc_key)

        conn.execute(
            """INSERT OR REPLACE INTO accounts
               (account_id, name, openalgo_host, api_key_encrypted, enabled,
                allocation_weight, account_group, max_loss_daily, is_master,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                account.account_id, account.name, account.openalgo_host,
                encrypted_key, int(account.enabled), account.allocation_weight,
                account.group, account.max_loss_daily, int(account.is_master),
                now, now,
            ],
        )
        conn.commit()
        self._cache[account.account_id] = account
        logger.info("Account added: %s", account.display)

    def remove_account(self, account_id: str) -> None:
        """Remove a broker account."""
        conn = self._get_conn()
        conn.execute("DELETE FROM accounts WHERE account_id = ?", [account_id])
        conn.commit()
        self._cache.pop(account_id, None)

    def get_account(self, account_id: str) -> BrokerAccount | None:
        """Get a single account by ID."""
        if account_id in self._cache:
            return self._cache[account_id]
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM accounts WHERE account_id = ?", [account_id],
        ).fetchone()
        if not row:
            return None
        return self._row_to_account(row)

    def list_accounts(self) -> list[BrokerAccount]:
        """List all registered accounts."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM accounts ORDER BY account_id").fetchall()
        return [self._row_to_account(r) for r in rows]

    def get_enabled_accounts(self) -> list[BrokerAccount]:
        """Get only enabled accounts."""
        return [a for a in self.list_accounts() if a.enabled]

    def get_accounts_by_group(self, group: str) -> list[BrokerAccount]:
        """Get accounts in a specific group."""
        return [a for a in self.list_accounts() if a.group == group and a.enabled]

    def get_master_account(self) -> BrokerAccount | None:
        """Get the designated master account."""
        for a in self.list_accounts():
            if a.is_master and a.enabled:
                return a
        return None

    def enable_account(self, account_id: str) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE accounts SET enabled = 1 WHERE account_id = ?", [account_id])
        conn.commit()
        if account_id in self._cache:
            self._cache[account_id].enabled = True

    def disable_account(self, account_id: str) -> None:
        conn = self._get_conn()
        conn.execute("UPDATE accounts SET enabled = 0 WHERE account_id = ?", [account_id])
        conn.commit()
        if account_id in self._cache:
            self._cache[account_id].enabled = False

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self, account: BrokerAccount) -> AccountHealth:
        """Ping a single account's OpenAlgo instance."""
        result = AccountHealth(
            account_id=account.account_id,
            checked_at=datetime.now(IST).isoformat(),
        )
        url = f"{account.openalgo_host.rstrip('/')}/api/v1/ping"
        try:
            start = __import__("time").monotonic()
            resp = self._http.post(url, json={"apikey": account.api_key})
            elapsed = (__import__("time").monotonic() - start) * 1000
            result.latency_ms = round(elapsed, 1)
            if resp.status_code == 200:
                result.reachable = True
            else:
                result.error = f"HTTP {resp.status_code}"
        except Exception:
            result.error = "OpenAlgo health check failed"

        return result

    def health_check_all(self) -> list[AccountHealth]:
        """Ping all enabled accounts."""
        results: list[AccountHealth] = []
        for account in self.get_enabled_accounts():
            results.append(self.health_check(account))
        return results

    def connection_status(self, account: BrokerAccount) -> AccountStatus:
        """Live connection + daily-reauth status for one account.

        Pings the account's OpenAlgo and classifies the result so the Account
        Manager can drive the operator: 200 = authenticated, 4xx = re-auth
        required, connection error = offline.
        """
        import time  # noqa: PLC0415

        status = AccountStatus(
            account_id=account.account_id,
            name=account.name,
            enabled=account.enabled,
            checked_at=datetime.now(IST).isoformat(),
        )
        url = f"{account.openalgo_host.rstrip('/')}/api/v1/ping"
        try:
            start = time.monotonic()
            resp = self._http.post(url, json={"apikey": account.api_key})
            status.latency_ms = round((time.monotonic() - start) * 1000, 1)
            status.connected = True  # we got an HTTP response → reachable
            if resp.status_code == 200:
                status.authenticated = True
                status.needs_reauth = False
            else:
                status.error = f"HTTP {resp.status_code}"
        except Exception:  # noqa: BLE001 - offline/connection error
            status.connected = False
            status.error = "OpenAlgo connection failed"
        return status

    def account_status_all(self) -> list[AccountStatus]:
        """Consolidated status for every account (the Account Manager surface)."""
        return [self.connection_status(a) for a in self.list_accounts()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _row_to_account(self, row: tuple) -> BrokerAccount:
        """Convert a SQLite row to BrokerAccount."""
        try:
            api_key = decrypt_value(row[3], self._enc_key)
        except Exception:
            api_key = ""
            logger.warning("Could not decrypt Ditto account auth material")

        account = BrokerAccount(
            account_id=row[0],
            name=row[1] or "",
            openalgo_host=row[2],
            api_key=api_key,
            enabled=bool(row[4]),
            allocation_weight=float(row[5]),
            group=row[6] or "default",
            max_loss_daily=float(row[7]),
            is_master=bool(row[8]),
        )
        self._cache[account.account_id] = account
        return account
