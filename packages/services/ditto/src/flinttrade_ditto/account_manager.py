"""Non-secret copy-trading metadata referencing native broker accounts.

Credentials and sessions belong to the gateway account store. Copy-trading
metadata never stores remote origins, API keys, or authentication material.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flinttrade_gateway.brokers.native_factory import NATIVE_ADAPTER_SPECS


def _default_db() -> str:
    from flinttrade_core.workspace import ditto_accounts_path

    return str(ditto_accounts_path())


@dataclass
class BrokerAccount:
    """A single broker account connected via its own broker instance."""

    account_id: str
    adapter_id: str
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

    Derived from a live broker ping: a 200 means the broker session is
    authenticated today; a 4xx means it is reachable but needs re-auth; a
    connection failure means it is offline.
    """

    account_id: str
    name: str
    enabled: bool
    connected: bool = False       # broker reachable (any HTTP response)
    authenticated: bool = False   # broker session valid today (ping 200)
    needs_reauth: bool = True     # daily re-auth required
    latency_ms: float = 0.0
    error: str = ""
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:

        return asdict(self)


class AccountManager:
    """Store native account references; gateway owns session health."""

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or _default_db()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""CREATE TABLE IF NOT EXISTS native_copy_accounts (
            account_id TEXT NOT NULL, adapter_id TEXT NOT NULL,
            name TEXT NOT NULL, enabled INTEGER NOT NULL,
            allocation_weight REAL NOT NULL, account_group TEXT NOT NULL,
            max_loss_daily REAL NOT NULL, is_master INTEGER NOT NULL,
            PRIMARY KEY(adapter_id, account_id))""")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> AccountManager:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def add_account(self, account: BrokerAccount) -> None:
        if account.adapter_id not in NATIVE_ADAPTER_SPECS or not account.account_id:
            raise ValueError("A built-in native broker account is required")
        self._conn.execute(
            "INSERT OR REPLACE INTO native_copy_accounts VALUES(?,?,?,?,?,?,?,?)",
            (account.account_id, account.adapter_id, account.name, int(account.enabled),
             account.allocation_weight, account.group, account.max_loss_daily, int(account.is_master)),
        )
        self._conn.commit()

    def remove_account(self, account_id: str) -> None:
        account = self.get_account(account_id)
        if account is not None:
            self._conn.execute("DELETE FROM native_copy_accounts WHERE account_id=? AND adapter_id=?",
                               (account_id, account.adapter_id))
            self._conn.commit()

    def get_account(self, account_id: str) -> BrokerAccount | None:
        rows = [account for account in self.list_accounts() if account.account_id == account_id]
        if len(rows) > 1:
            raise ValueError("Copy account identity is ambiguous; select a composite native account")
        return rows[0] if rows else None

    def list_accounts(self) -> list[BrokerAccount]:
        return [BrokerAccount(
            account_id=row["account_id"], adapter_id=row["adapter_id"], name=row["name"],
            enabled=bool(row["enabled"]), allocation_weight=row["allocation_weight"],
            group=row["account_group"], max_loss_daily=row["max_loss_daily"],
            is_master=bool(row["is_master"]),
        ) for row in self._conn.execute("SELECT * FROM native_copy_accounts ORDER BY adapter_id,account_id")]

    def get_enabled_accounts(self) -> list[BrokerAccount]:
        return [account for account in self.list_accounts() if account.enabled]

    def get_accounts_by_group(self, group: str) -> list[BrokerAccount]:
        return [account for account in self.list_accounts() if account.group == group]

    def get_master_account(self) -> BrokerAccount | None:
        return next((account for account in self.list_accounts() if account.is_master), None)

    def enable_account(self, account_id: str) -> None:
        account = self.get_account(account_id)
        if account is not None:
            account.enabled = True
            self.add_account(account)

    def disable_account(self, account_id: str) -> None:
        account = self.get_account(account_id)
        if account is not None:
            account.enabled = False
            self.add_account(account)

    def health_check(self, account: BrokerAccount) -> AccountHealth:
        return AccountHealth(account_id=account.account_id,
                             error="Native copy-trading session ownership is unavailable")

    def health_check_all(self) -> list[AccountHealth]:
        return [self.health_check(account) for account in self.list_accounts()]

    def connection_status(self, account: BrokerAccount) -> AccountStatus:
        return AccountStatus(account_id=account.account_id, name=account.name, enabled=account.enabled,
                             error="Native copy-trading session ownership is unavailable")

    def account_status_all(self) -> list[AccountStatus]:
        return [self.connection_status(account) for account in self.list_accounts()]
