"""Multi-account manager — registry, health checks, groups.

Each broker account corresponds to a separate OpenAlgo instance running on a
different port. Ditto manages them as a unified pool for position mirroring.

API keys are stored in the **canonical credential vault**
(:class:`flinttrade_gateway.credentials.CredentialStore` — Fernet with a per-row
random salt + a PBKDF2-derived key from the operator's master password), keyed by
``(adapter_id="openalgo", account_id)`` in a Ditto-scoped vault file. Non-secret
account metadata (host, group, weight, limits, flags) lives in the local
``ditto_accounts.sqlite``. The former Ditto-only ``DITTO_ENCRYPTION_KEY`` Fernet
store was folded into the vault on 2026-07-09 (map U5) — there is no longer a
separate weak-crypto credential store.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from flinttrade_core.db import open_sqlite

if TYPE_CHECKING:
    from flinttrade_gateway.credentials import CredentialStore

logger = logging.getLogger("flinttrade.ditto.accounts")

IST = timezone(timedelta(hours=5, minutes=30))

# Vault routing key for Ditto-managed OpenAlgo accounts. Ditto accounts are
# OpenAlgo instances, so they are stored under the openalgo adapter — but in a
# Ditto-scoped vault FILE, never the shared native-broker store (whose boot
# reconnect would otherwise try to authenticate them as bridge sessions).
_DITTO_ADAPTER_ID = "openalgo"


def _default_db() -> str:
    """Resolve the metadata SQLite path through the canonical workspace helper."""
    from flinttrade_core.workspace import ditto_accounts_path  # noqa: PLC0415

    return str(ditto_accounts_path())


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
# SQLite schema — NON-SECRET account metadata only (api_key lives in the vault)
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    openalgo_host TEXT NOT NULL,
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

    Secrets are read/written through an injected
    :class:`~flinttrade_gateway.credentials.CredentialStore` (the canonical
    vault). Pass either a ``credential_store`` or a ``master_password`` (used to
    open a Ditto-scoped vault next to the metadata DB). Reads that need the
    api_key (health/status) re-source it from the vault.

    Usage::

        mgr = AccountManager(credential_store=store)
        mgr.add_account(BrokerAccount(
            account_id="acc1",
            openalgo_host="http://your-openalgo-host:5001",
            api_key="your-api-key-1",
            name="Personal", group="personal", allocation_weight=1.0,
        ))
        active = mgr.get_enabled_accounts()
    """

    def __init__(
        self,
        db_path: str | None = None,
        credential_store: CredentialStore | None = None,
        master_password: str | None = None,
    ) -> None:
        self._db_path = db_path or _default_db()
        self._conn: sqlite3.Connection | None = None
        self._cache: dict[str, BrokerAccount] = {}
        self._http = httpx.Client(timeout=10.0)
        self._cred = self._resolve_credential_store(credential_store, master_password)

    def _resolve_credential_store(
        self, credential_store: CredentialStore | None, master_password: str | None
    ) -> CredentialStore:
        if credential_store is not None:
            return credential_store
        if master_password:
            from flinttrade_gateway.credentials import CredentialStore  # noqa: PLC0415

            vault_path = Path(self._db_path).parent / "ditto_credentials.db"
            vault_path.parent.mkdir(parents=True, exist_ok=True)
            return CredentialStore(vault_path, master_password)
        raise ValueError(
            "AccountManager requires a credential_store or master_password — "
            "Ditto account API keys are stored in the canonical vault."
        )

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = open_sqlite(self._db_path, durability="normal")
            self._conn.execute(_SCHEMA)
            self._conn.commit()
            self._migrate_legacy_api_key_column(self._conn)
        return self._conn

    def _migrate_legacy_api_key_column(self, conn: sqlite3.Connection) -> None:
        """Fold a legacy ``api_key_encrypted`` column into the vault, then drop it.

        Pre-2026-07-09 databases stored the api_key as Fernet ciphertext keyed by
        ``DITTO_ENCRYPTION_KEY``. Best-effort migrate each into the vault (when the
        legacy key is still available to decrypt it), then drop the column so new
        writes never touch weak-crypto storage again.
        """
        cols = {row[1] for row in conn.execute("PRAGMA table_info(accounts)")}
        if "api_key_encrypted" not in cols:
            return
        legacy_key = os.getenv("DITTO_ENCRYPTION_KEY", "")
        migrated = 0
        for account_id, ciphertext in conn.execute(
            "SELECT account_id, api_key_encrypted FROM accounts"
        ).fetchall():
            if not ciphertext or not legacy_key:
                continue
            try:
                from cryptography.fernet import Fernet  # noqa: PLC0415

                plaintext = Fernet(legacy_key.encode()).decrypt(ciphertext.encode()).decode()
            except Exception:
                continue
            try:
                self._cred.store(
                    account_id,
                    broker=_DITTO_ADAPTER_ID,
                    label=account_id,
                    credentials={"api_key": plaintext},
                    adapter_id=_DITTO_ADAPTER_ID,
                )
                migrated += 1
            except Exception:  # noqa: BLE001 - migration is best-effort
                logger.warning("Could not migrate legacy Ditto api_key into the vault")
        conn.execute("ALTER TABLE accounts DROP COLUMN api_key_encrypted")
        conn.commit()
        logger.info(
            "Migrated %d legacy Ditto api_key(s) into the vault; dropped api_key_encrypted",
            migrated,
        )

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
        """Register a new broker account (secret → vault, metadata → sqlite)."""
        self._cred.store(
            account.account_id,
            broker=_DITTO_ADAPTER_ID,
            label=account.name or account.account_id,
            credentials={"api_key": account.api_key},
            adapter_id=_DITTO_ADAPTER_ID,
        )
        conn = self._get_conn()
        now = datetime.now(IST).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO accounts
               (account_id, name, openalgo_host, enabled,
                allocation_weight, account_group, max_loss_daily, is_master,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                account.account_id, account.name, account.openalgo_host,
                int(account.enabled), account.allocation_weight,
                account.group, account.max_loss_daily, int(account.is_master),
                now, now,
            ],
        )
        conn.commit()
        self._cache[account.account_id] = account
        logger.info("Account added: %s", account.display)

    def remove_account(self, account_id: str) -> None:
        """Remove a broker account (metadata + vault credential)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM accounts WHERE account_id = ?", [account_id])
        conn.commit()
        self._cache.pop(account_id, None)
        try:
            self._cred.remove_for(_DITTO_ADAPTER_ID, account_id)
        except Exception:  # noqa: BLE001 - vault row may already be absent
            logger.info("No vault credential to remove for Ditto account")

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

    def _api_key_for(self, account_id: str) -> str:
        """Read an account's api_key from the vault (empty string if absent)."""
        try:
            creds = self._cred.retrieve_for(_DITTO_ADAPTER_ID, account_id)
        except Exception:
            logger.warning("Could not read Ditto account auth material from the vault")
            return ""
        return str(creds.get("api_key", ""))

    def _row_to_account(self, row: sqlite3.Row | tuple) -> BrokerAccount:
        """Convert a metadata row to a BrokerAccount (api_key sourced from vault)."""
        account = BrokerAccount(
            account_id=row[0],
            name=row[1] or "",
            openalgo_host=row[2],
            api_key=self._api_key_for(row[0]),
            enabled=bool(row[3]),
            allocation_weight=float(row[4]),
            group=row[5] or "default",
            max_loss_daily=float(row[6]),
            is_master=bool(row[7]),
        )
        self._cache[account.account_id] = account
        return account
