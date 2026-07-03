"""Tests for the Fernet-encrypted CredentialStore.

All tests use a temporary in-memory or temp-file SQLite database so they
never touch ``~/.flinttrade/``.
"""

from __future__ import annotations

import pytest
from pathlib import Path

from flinttrade_gateway.credentials import CredentialError, CredentialStore


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

MASTER_PW = "hunter2-not-a-real-password"
ALT_PW = "a-completely-different-password"

CREDS_A: dict[str, str] = {
    "api_key": "abc123",
    "api_secret": "xyz789",
    "totp_secret": "BASE32TOTP",
}
CREDS_B: dict[str, str] = {
    "api_key": "key_B",
    "access_token": "tok_B",
}
CREDS_C: dict[str, str] = {
    "api_key": "key_C",
    "client_id": "client_C",
}


@pytest.fixture()
def store(tmp_path: Path) -> CredentialStore:
    """Fresh CredentialStore backed by a temporary SQLite file."""
    return CredentialStore(tmp_path / "creds.db", MASTER_PW)


@pytest.fixture()
def populated_store(store: CredentialStore) -> CredentialStore:
    """Store pre-loaded with three accounts."""
    store.store("acc_A", "zerodha", "Primary Zerodha", CREDS_A)
    store.store("acc_B", "upstox", "Upstox Derivatives", CREDS_B)
    store.store("acc_C", "angel", "Angel Broking", CREDS_C)
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStoreAndRetrieve:
    def test_store_and_retrieve_round_trip(self, store: CredentialStore) -> None:
        """Credentials stored must be byte-for-byte identical when retrieved."""
        store.store("acc1", "zerodha", "My Account", CREDS_A)
        result = store.retrieve("acc1")
        assert result == CREDS_A

    def test_store_and_retrieve_nested_dict(self, store: CredentialStore) -> None:
        """Nested / complex credential dicts survive the round trip."""
        complex_creds: dict = {
            "api_key": "k",
            "meta": {"env": "prod", "scopes": ["orders", "holdings"]},
            "flags": {"sandbox": False},
        }
        store.store("acc_nested", "broker_x", "Test", complex_creds)
        assert store.retrieve("acc_nested") == complex_creds


class TestErrorHandling:
    def test_retrieve_nonexistent_raises(self, store: CredentialStore) -> None:
        """Retrieving an account that was never stored raises CredentialError."""
        with pytest.raises(CredentialError, match="not found"):
            store.retrieve("ghost_account")

    def test_wrong_master_password_raises(self, tmp_path: Path) -> None:
        """Opening an existing DB with a different password must raise on retrieve."""
        db = tmp_path / "creds.db"
        store1 = CredentialStore(db, MASTER_PW)
        store1.store("acc1", "zerodha", "Label", CREDS_A)

        store2 = CredentialStore(db, ALT_PW)
        with pytest.raises(CredentialError, match="Decryption failed"):
            store2.retrieve("acc1")

    def test_set_primary_nonexistent_raises(self, store: CredentialStore) -> None:
        """set_primary on a missing account raises CredentialError."""
        with pytest.raises(CredentialError, match="not found"):
            store.set_primary("ghost")


class TestRemoveAccount:
    def test_remove_account(self, store: CredentialStore) -> None:
        """After removal the account must no longer be retrievable."""
        store.store("acc1", "zerodha", "Label", CREDS_A)
        assert store.account_exists("acc1")
        store.remove("acc1")
        assert not store.account_exists("acc1")
        with pytest.raises(CredentialError):
            store.retrieve("acc1")

    def test_remove_nonexistent_is_silent(self, store: CredentialStore) -> None:
        """Removing an account that doesn't exist must not raise."""
        store.remove("never_stored")  # must not raise


class TestListAccounts:
    def test_list_accounts_returns_metadata(
        self, populated_store: CredentialStore
    ) -> None:
        """list_accounts must return metadata rows without decrypted credentials."""
        accounts = populated_store.list_accounts()
        assert len(accounts) == 3

        for acc in accounts:
            assert set(acc.keys()) == {
                "account_id",
                "adapter_id",
                "broker",
                "label",
                "is_primary",
                "created_at",
            }
            # Must NOT contain any of the raw credential keys
            assert "api_key" not in acc
            assert "api_secret" not in acc
            assert "encrypted_creds" not in acc

    def test_list_accounts_empty(self, store: CredentialStore) -> None:
        """list_accounts on an empty store returns an empty list."""
        assert store.list_accounts() == []

    def test_list_accounts_ordered_by_created_at(
        self, store: CredentialStore
    ) -> None:
        """Accounts are returned oldest-first (creation order)."""
        store.store("first", "b", "L1", {"k": "v"})
        store.store("second", "b", "L2", {"k": "v"})
        store.store("third", "b", "L3", {"k": "v"})
        ids = [a["account_id"] for a in store.list_accounts()]
        assert ids == ["first", "second", "third"]


class TestSetPrimary:
    def test_set_primary(self, populated_store: CredentialStore) -> None:
        """set_primary must mark exactly one account as primary."""
        populated_store.set_primary("acc_B")
        accounts = {a["account_id"]: a for a in populated_store.list_accounts()}

        assert accounts["acc_B"]["is_primary"] is True
        assert accounts["acc_A"]["is_primary"] is False
        assert accounts["acc_C"]["is_primary"] is False

    def test_set_primary_switches_correctly(
        self, populated_store: CredentialStore
    ) -> None:
        """Changing primary from one account to another clears the previous."""
        populated_store.set_primary("acc_A")
        populated_store.set_primary("acc_C")

        accounts = {a["account_id"]: a for a in populated_store.list_accounts()}
        assert accounts["acc_A"]["is_primary"] is False
        assert accounts["acc_C"]["is_primary"] is True


class TestAccountExists:
    def test_account_exists_true_when_stored(self, store: CredentialStore) -> None:
        store.store("acc1", "zerodha", "Label", CREDS_A)
        assert store.account_exists("acc1") is True

    def test_account_exists_false_when_not_stored(
        self, store: CredentialStore
    ) -> None:
        assert store.account_exists("missing") is False

    def test_account_exists_false_after_remove(self, store: CredentialStore) -> None:
        store.store("acc1", "zerodha", "Label", CREDS_A)
        store.remove("acc1")
        assert store.account_exists("acc1") is False


class TestMultipleAccounts:
    def test_multiple_accounts_list_and_retrieve(
        self, populated_store: CredentialStore
    ) -> None:
        """Storing N accounts must allow independent retrieval of each."""
        assert len(populated_store.list_accounts()) == 3
        assert populated_store.retrieve("acc_A") == CREDS_A
        assert populated_store.retrieve("acc_B") == CREDS_B
        assert populated_store.retrieve("acc_C") == CREDS_C


class TestPerAccountSalt:
    def test_per_account_salt_produces_different_ciphertext(
        self, tmp_path: Path
    ) -> None:
        """Two accounts with identical credentials must have distinct ciphertexts.

        This verifies per-account salting: same plaintext + different salt =>
        different Fernet token (probabilistic but guaranteed by random IV and salt).
        """
        db = tmp_path / "creds.db"
        store = CredentialStore(db, MASTER_PW)
        same_creds = {"api_key": "identical", "secret": "identical"}
        store.store("acc_X", "broker", "Label X", same_creds)
        store.store("acc_Y", "broker", "Label Y", same_creds)

        # Read the raw encrypted blobs directly from SQLite
        import sqlite3

        conn = sqlite3.connect(str(db))
        rows = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT account_id, encrypted_creds FROM accounts"
            ).fetchall()
        }
        conn.close()

        blob_x: bytes = bytes(rows["acc_X"])
        blob_y: bytes = bytes(rows["acc_Y"])

        # Different salt => different Fernet token even for same plaintext
        assert blob_x != blob_y

        # Both must decrypt correctly with the same store instance
        assert store.retrieve("acc_X") == same_creds
        assert store.retrieve("acc_Y") == same_creds


class TestOverwrite:
    def test_store_overwrites_existing(self, store: CredentialStore) -> None:
        """Storing the same account_id twice replaces the credentials."""
        store.store("acc1", "zerodha", "Old Label", {"api_key": "old"})
        store.store("acc1", "zerodha", "New Label", {"api_key": "new"})

        result = store.retrieve("acc1")
        assert result == {"api_key": "new"}

        accounts = store.list_accounts()
        assert len(accounts) == 1
        assert accounts[0]["label"] == "New Label"

    def test_store_overwrite_preserves_primary_flag(
        self, store: CredentialStore
    ) -> None:
        """Overwriting an account respects the is_primary flag in the new call."""
        store.store("acc1", "zerodha", "L", {"k": "v1"}, is_primary=False)
        store.store("acc1", "zerodha", "L", {"k": "v2"}, is_primary=True)
        accounts = store.list_accounts()
        assert accounts[0]["is_primary"] is True


class TestUpdateCredentialsFor:
    """G7 — the write-back API swaps the payload without touching metadata."""

    def test_update_replaces_payload_and_preserves_metadata(self, store: CredentialStore) -> None:
        store.store("111", "dhan", "My Dhan", {"pin": "1234", "totp": "000111"},
                    is_primary=True, adapter_id="dhan")
        store.update_credentials_for("dhan", "111", {"pin": "1234", "access_token": "minted"})

        creds = store.retrieve_for("dhan", "111")
        assert creds == {"pin": "1234", "access_token": "minted"}
        row = next(r for r in store.list_accounts() if r["account_id"] == "111")
        assert row["label"] == "My Dhan"
        assert bool(row["is_primary"]) is True

    def test_update_missing_selector_raises(self, store: CredentialStore) -> None:
        with pytest.raises(CredentialError):
            store.update_credentials_for("dhan", "nope", {"access_token": "x"})


class TestCrossAdapterCollisionGuard:
    """Audit finding: the accounts PK is account_id alone, but the selector is
    composite (adapter_id, account_id). store() must refuse a second adapter
    reusing an account_id rather than silently overwriting the first's creds."""

    def test_second_adapter_same_account_id_is_rejected(self, store: CredentialStore) -> None:
        store.store("SHARED", "dhan", "Dhan", {"access_token": "dhan-tok"}, adapter_id="dhan")
        with pytest.raises(CredentialError, match="already used by adapter"):
            store.store("SHARED", "upstox", "Upstox", {"access_token": "upx-tok"}, adapter_id="upstox")
        # The first adapter's credentials survive intact.
        assert store.retrieve_for("dhan", "SHARED")["access_token"] == "dhan-tok"

    def test_same_adapter_update_still_allowed(self, store: CredentialStore) -> None:
        store.store("A1", "dhan", "Dhan", {"access_token": "old"}, adapter_id="dhan")
        store.store("A1", "dhan", "Dhan", {"access_token": "new"}, adapter_id="dhan")
        assert store.retrieve_for("dhan", "A1")["access_token"] == "new"


class TestUnschedule:
    def test_unschedule_is_idempotent_and_month_end_safe(self) -> None:
        """schedule_daily_refresh must use timedelta (not replace(day+1)) so it
        never raises on the last day of a month; unschedule is idempotent."""
        from unittest.mock import MagicMock

        from flinttrade_gateway.credentials_rotation import CredentialsRotator

        rot = CredentialsRotator(MagicMock(), MagicMock())
        rot.schedule_daily_refresh("dhan", "08:05")  # must not raise regardless of today's date
        rot.unschedule("dhan")
        rot.unschedule("dhan")  # second call is a no-op
