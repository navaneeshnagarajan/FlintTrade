"""Tests for ContractManager — per-broker master contract SQLite caching.

All tests use pytest's ``tmp_path`` fixture so no files are written to
``~/.flinttrade/`` and every test starts with a clean directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flinttrade_gateway.contracts import ContractManager
from flinttrade_gateway.exceptions import ContractError


# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

CONTRACTS_3: list[dict] = [
    {
        "symbol": "NIFTY",
        "broker_symbol": "NIFTY-I",
        "token": "26000",
        "exchange": "NSE_INDEX",
        "lot_size": 50,
    },
    {
        "symbol": "BANKNIFTY",
        "broker_symbol": "BANKNIFTY-I",
        "token": "26009",
        "exchange": "NSE_INDEX",
        "lot_size": 15,
    },
    {
        "symbol": "RELIANCE",
        "broker_symbol": "RELIANCE",
        "token": "2885",
        "exchange": "NSE",
        "lot_size": 1,
    },
]

CONTRACTS_1: list[dict] = [
    {
        "symbol": "INFY",
        "broker_symbol": "INFY",
        "token": "1594",
        "exchange": "NSE",
        "lot_size": 1,
    },
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mgr(tmp_path: Path) -> ContractManager:
    """Fresh ContractManager backed by a temporary directory."""
    return ContractManager(tmp_path / "contracts")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInsertAndLookup:
    def test_insert_and_lookup(self, mgr: ContractManager) -> None:
        """Inserted contracts are individually retrievable by symbol+exchange."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)

        br = mgr.get_br_symbol("NIFTY", "NSE_INDEX", "zerodha")
        assert br == "NIFTY-I"

        br2 = mgr.get_br_symbol("RELIANCE", "NSE", "zerodha")
        assert br2 == "RELIANCE"

        br3 = mgr.get_br_symbol("BANKNIFTY", "NSE_INDEX", "zerodha")
        assert br3 == "BANKNIFTY-I"

    def test_get_token(self, mgr: ContractManager) -> None:
        """Token lookup returns the correct instrument token."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)

        assert mgr.get_token("NIFTY", "NSE_INDEX", "zerodha") == "26000"
        assert mgr.get_token("BANKNIFTY", "NSE_INDEX", "zerodha") == "26009"
        assert mgr.get_token("RELIANCE", "NSE", "zerodha") == "2885"

    def test_get_br_symbol(self, mgr: ContractManager) -> None:
        """broker_symbol lookup returns the broker's own symbol string."""
        mgr.insert_contracts("dhan", CONTRACTS_3)

        result = mgr.get_br_symbol("NIFTY", "NSE_INDEX", "dhan")
        assert result == "NIFTY-I"

    def test_get_oa_symbol(self, mgr: ContractManager) -> None:
        """Reverse lookup: broker_symbol -> FlintTrade canonical symbol."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)

        result = mgr.get_oa_symbol("NIFTY-I", "NSE_INDEX", "zerodha")
        assert result == "NIFTY"

        result2 = mgr.get_oa_symbol("RELIANCE", "NSE", "zerodha")
        assert result2 == "RELIANCE"

    def test_lookup_missing_returns_none(self, mgr: ContractManager) -> None:
        """Lookups for unknown symbols return None without raising."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)

        assert mgr.get_br_symbol("GHOST", "NSE", "zerodha") is None
        assert mgr.get_token("GHOST", "NSE", "zerodha") is None
        assert mgr.get_oa_symbol("GHOST_BR", "NSE", "zerodha") is None


class TestFullRefresh:
    def test_full_refresh_replaces_old_data(self, mgr: ContractManager) -> None:
        """Inserting a new batch atomically replaces the previous batch."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)
        assert mgr.count("zerodha") == 3

        mgr.insert_contracts("zerodha", CONTRACTS_1)
        assert mgr.count("zerodha") == 1

        # Old records must be gone
        assert mgr.get_br_symbol("NIFTY", "NSE_INDEX", "zerodha") is None
        # New record must be present
        assert mgr.get_br_symbol("INFY", "NSE", "zerodha") == "INFY"


class TestCacheStaleness:
    def test_is_cache_stale_no_file(self, mgr: ContractManager) -> None:
        """Returns True when the broker DB does not exist."""
        assert mgr.is_cache_stale("nonexistent_broker") is True

    def test_is_cache_stale_fresh(self, mgr: ContractManager) -> None:
        """Returns False immediately after inserting contracts (file just written)."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)
        # The DB was just written — it must be considered fresh when we pass
        # cutoff_hour=0 (i.e. any time today counts as fresh).
        assert mgr.is_cache_stale("zerodha", cutoff_hour=0) is False


class TestCount:
    def test_count(self, mgr: ContractManager) -> None:
        """count() returns the exact number of inserted rows."""
        assert mgr.count("zerodha") == 0

        mgr.insert_contracts("zerodha", CONTRACTS_3)
        assert mgr.count("zerodha") == 3

        mgr.insert_contracts("zerodha", CONTRACTS_1)
        assert mgr.count("zerodha") == 1


class TestClear:
    def test_clear(self, mgr: ContractManager) -> None:
        """clear() removes all records; subsequent count is 0."""
        mgr.insert_contracts("zerodha", CONTRACTS_3)
        assert mgr.count("zerodha") == 3

        mgr.clear("zerodha")
        assert mgr.count("zerodha") == 0

        # Lookups after clear must return None
        assert mgr.get_br_symbol("NIFTY", "NSE_INDEX", "zerodha") is None


class TestAtomicity:
    def test_atomicity_on_failure(self, mgr: ContractManager) -> None:
        """A batch with a bad record rolls back; original data is preserved.

        We insert 3 valid contracts first, then try to insert a batch that
        contains one record missing the required ``token`` field.  The NOT NULL
        constraint on ``token`` causes the INSERT to fail, the transaction is
        rolled back, and the 3 original rows remain untouched.
        """
        mgr.insert_contracts("zerodha", CONTRACTS_3)
        assert mgr.count("zerodha") == 3

        bad_batch: list[dict] = [
            {
                "symbol": "VALID",
                "broker_symbol": "VALID-BR",
                "token": "9999",
                "exchange": "NSE",
                "lot_size": 1,
            },
            {
                # Missing 'token' — will cause a NOT NULL / binding error
                "symbol": "BROKEN",
                "broker_symbol": "BROKEN-BR",
                "token": None,  # explicit NULL triggers constraint violation
                "exchange": "NSE",
                "lot_size": 1,
            },
        ]

        with pytest.raises(ContractError):
            mgr.insert_contracts("zerodha", bad_batch)

        # Original 3 rows must still be present
        assert mgr.count("zerodha") == 3
        assert mgr.get_br_symbol("NIFTY", "NSE_INDEX", "zerodha") == "NIFTY-I"


class TestMultipleBrokers:
    def test_multiple_brokers_isolated(self, mgr: ContractManager) -> None:
        """Each broker's DB is fully isolated — no cross-contamination."""
        dhan_contracts: list[dict] = [
            {
                "symbol": "NIFTY",
                "broker_symbol": "NIFTY_DHAN",
                "token": "D26000",
                "exchange": "NSE_INDEX",
                "lot_size": 50,
            },
        ]
        zerodha_contracts: list[dict] = [
            {
                "symbol": "NIFTY",
                "broker_symbol": "NIFTY_ZERODHA",
                "token": "Z26000",
                "exchange": "NSE_INDEX",
                "lot_size": 50,
            },
        ]

        mgr.insert_contracts("dhan", dhan_contracts)
        mgr.insert_contracts("zerodha", zerodha_contracts)

        # Each broker sees its own symbol
        assert mgr.get_br_symbol("NIFTY", "NSE_INDEX", "dhan") == "NIFTY_DHAN"
        assert mgr.get_br_symbol("NIFTY", "NSE_INDEX", "zerodha") == "NIFTY_ZERODHA"

        # Each broker sees its own token
        assert mgr.get_token("NIFTY", "NSE_INDEX", "dhan") == "D26000"
        assert mgr.get_token("NIFTY", "NSE_INDEX", "zerodha") == "Z26000"

        # Count is independent per broker
        assert mgr.count("dhan") == 1
        assert mgr.count("zerodha") == 1

        # Clearing one does not affect the other
        mgr.clear("dhan")
        assert mgr.count("dhan") == 0
        assert mgr.count("zerodha") == 1
