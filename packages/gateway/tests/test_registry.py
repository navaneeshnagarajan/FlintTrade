"""Tests for BrokerRegistry: multi-account management.

All tests mock BrokerSession so no real broker adapters are imported.
BrokerSession is patched at the class level inside the registry module so
every instantiation receives a MagicMock whose authenticate() succeeds by
default.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from registry import BrokerRegistry
from models import BrokerAccountInfo, AccountStatus
from exceptions import BrokerNotFoundError, SessionError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BROKER = "zerodha"          # known live broker
_BROKER2 = "fyers"
_SANDBOX = "dhan_sandbox"
_LABEL = "Primary Zerodha"
_LABEL2 = "Secondary Fyers"
_TOKEN = "tok_abc123"
_CREDS: dict[str, str] = {"api_key": "key", "totp": "123456"}

# Patch target: BrokerSession as imported inside registry.py
_SESSION_PATCH = "registry.BrokerSession"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(
    account_id: str = "AB1234",
    broker: str = _BROKER,
    label: str = _LABEL,
    status: AccountStatus = AccountStatus.connected,
) -> MagicMock:
    """Return a MagicMock that mimics a successfully-authenticated BrokerSession."""
    mock = MagicMock()
    mock.authenticate.return_value = None  # authenticate() returns None on success
    mock.info = BrokerAccountInfo(
        account_id=account_id,
        broker=broker,
        label=label,
        status=status,
        is_primary=False,
    )
    return mock


def _registry_with_account(
    account_id: str = "AB1234",
    broker: str = _BROKER,
    label: str = _LABEL,
    mock_session: MagicMock | None = None,
) -> tuple[BrokerRegistry, MagicMock]:
    """Return a registry with one pre-added account plus the mock session."""
    if mock_session is None:
        mock_session = _make_mock_session(account_id=account_id, broker=broker, label=label)

    registry = BrokerRegistry()
    with patch(_SESSION_PATCH, return_value=mock_session):
        registry.add_account(account_id, broker, label, _CREDS)

    return registry, mock_session


# ---------------------------------------------------------------------------
# 1. get_supported_brokers_excludes_sandbox
# ---------------------------------------------------------------------------


class TestGetSupportedBrokers:
    def test_get_supported_brokers_excludes_sandbox(self) -> None:
        """dhan_sandbox must not appear in get_supported_brokers() results."""
        registry = BrokerRegistry()
        brokers = registry.get_supported_brokers()
        names = [b.name for b in brokers]
        assert _SANDBOX not in names

    def test_get_supported_brokers_includes_live_brokers(self) -> None:
        """Live broker entries must be present in the supported list."""
        registry = BrokerRegistry()
        brokers = registry.get_supported_brokers()
        names = [b.name for b in brokers]
        assert _BROKER in names
        assert _BROKER2 in names

    def test_get_supported_brokers_none_are_sandbox(self) -> None:
        """Every entry returned must have is_sandbox == False."""
        registry = BrokerRegistry()
        for info in registry.get_supported_brokers():
            assert info.is_sandbox is False


# ---------------------------------------------------------------------------
# 2. add_account — success
# ---------------------------------------------------------------------------


class TestAddAccountSuccess:
    def test_add_account_success_returns_broker_account_info(self) -> None:
        """add_account() must return a BrokerAccountInfo on success."""
        mock_session = _make_mock_session()
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_session):
            info = registry.add_account("AB1234", _BROKER, _LABEL, _CREDS)
        assert isinstance(info, BrokerAccountInfo)

    def test_add_account_success_calls_authenticate(self) -> None:
        """add_account() must call session.authenticate with the given credentials."""
        mock_session = _make_mock_session()
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_session):
            registry.add_account("AB1234", _BROKER, _LABEL, _CREDS)
        mock_session.authenticate.assert_called_once_with(_CREDS)

    def test_add_account_session_stored_in_registry(self) -> None:
        """After add_account(), the session must be retrievable via get_session()."""
        mock_session = _make_mock_session()
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_session):
            registry.add_account("AB1234", _BROKER, _LABEL, _CREDS)
        retrieved = registry.get_session("AB1234")
        assert retrieved is mock_session

    def test_add_account_passes_correct_args_to_session_constructor(self) -> None:
        """BrokerSession must be constructed with (account_id, broker_name, label)."""
        mock_session = _make_mock_session()
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_session) as mock_cls:
            registry.add_account("AB1234", _BROKER, _LABEL, _CREDS)
        mock_cls.assert_called_once_with("AB1234", _BROKER, _LABEL)


# ---------------------------------------------------------------------------
# 3. add_account — unknown broker raises
# ---------------------------------------------------------------------------


class TestAddAccountUnknownBroker:
    def test_add_account_unknown_broker_raises(self) -> None:
        """add_account() must raise BrokerNotFoundError for an unknown broker."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.add_account("AB1234", "not_a_real_broker", _LABEL, _CREDS)

    def test_add_account_unknown_broker_error_message(self) -> None:
        """The BrokerNotFoundError message must mention the unknown broker name."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError, match="not_a_real_broker"):
            registry.add_account("AB1234", "not_a_real_broker", _LABEL, _CREDS)

    def test_add_account_sandbox_raises(self) -> None:
        """Sandbox broker names must NOT be filtered at add_account level (they exist in catalog)."""
        # dhan_sandbox IS in the catalog, so it should not raise BrokerNotFoundError.
        # This test verifies the behavior is consistent with catalog contents.
        mock_session = _make_mock_session(broker=_SANDBOX)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_session):
            # Should succeed — sandbox is in the catalog
            info = registry.add_account("SB001", _SANDBOX, "Sandbox", _CREDS)
        assert info.broker == _SANDBOX


# ---------------------------------------------------------------------------
# 4. remove_account
# ---------------------------------------------------------------------------


class TestRemoveAccount:
    def test_remove_account_removes_from_registry(self) -> None:
        """After remove_account(), get_session() must raise BrokerNotFoundError."""
        registry, _ = _registry_with_account("AB1234")
        registry.remove_account("AB1234")
        with pytest.raises(BrokerNotFoundError):
            registry.get_session("AB1234")

    def test_remove_account_calls_disconnect(self) -> None:
        """remove_account() must call session.disconnect()."""
        registry, mock_session = _registry_with_account("AB1234")
        registry.remove_account("AB1234")
        mock_session.disconnect.assert_called_once()

    def test_remove_account_clears_primary_flag(self) -> None:
        """Removing the primary account must clear the primary designation."""
        registry, _ = _registry_with_account("AB1234")
        registry.set_primary("AB1234")
        registry.remove_account("AB1234")
        with pytest.raises(SessionError):
            registry.get_primary_session()

    def test_remove_account_not_found_in_list_after_removal(self) -> None:
        """list_accounts() must not include the removed account."""
        registry, _ = _registry_with_account("AB1234")
        registry.remove_account("AB1234")
        account_ids = [a.account_id for a in registry.list_accounts()]
        assert "AB1234" not in account_ids


# ---------------------------------------------------------------------------
# 5. remove_nonexistent_raises
# ---------------------------------------------------------------------------


class TestRemoveNonexistentRaises:
    def test_remove_nonexistent_raises(self) -> None:
        """remove_account() must raise BrokerNotFoundError for unknown ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.remove_account("GHOST")

    def test_remove_nonexistent_error_message(self) -> None:
        """The error message must identify the missing account ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError, match="GHOST"):
            registry.remove_account("GHOST")


# ---------------------------------------------------------------------------
# 6. get_session
# ---------------------------------------------------------------------------


class TestGetSession:
    def test_get_session_returns_correct_session(self) -> None:
        """get_session() must return the exact session stored under account_id."""
        mock_session = _make_mock_session(account_id="AB1234")
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)
        result = registry.get_session("AB1234")
        assert result is mock_session

    def test_get_session_two_accounts_returns_correct_one(self) -> None:
        """get_session() must disambiguate between multiple registered accounts."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)
        assert registry.get_session("AA001") is mock_a
        assert registry.get_session("BB002") is mock_b


# ---------------------------------------------------------------------------
# 7. get_session_missing_raises
# ---------------------------------------------------------------------------


class TestGetSessionMissingRaises:
    def test_get_session_missing_raises(self) -> None:
        """get_session() must raise BrokerNotFoundError for an unregistered ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.get_session("NONEXISTENT")

    def test_get_session_missing_error_mentions_id(self) -> None:
        """The error message must include the missing account ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError, match="NONEXISTENT"):
            registry.get_session("NONEXISTENT")


# ---------------------------------------------------------------------------
# 8. list_accounts
# ---------------------------------------------------------------------------


class TestListAccounts:
    def test_list_accounts_empty_registry(self) -> None:
        """list_accounts() must return an empty list when no accounts are added."""
        registry = BrokerRegistry()
        assert registry.list_accounts() == []

    def test_list_accounts_two_accounts_returns_two(self) -> None:
        """list_accounts() must return one entry per registered account."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)
        accounts = registry.list_accounts()
        assert len(accounts) == 2

    def test_list_accounts_returns_broker_account_info_objects(self) -> None:
        """Each entry from list_accounts() must be a BrokerAccountInfo."""
        registry, _ = _registry_with_account("AB1234")
        for item in registry.list_accounts():
            assert isinstance(item, BrokerAccountInfo)

    def test_list_accounts_contains_correct_ids(self) -> None:
        """list_accounts() must include the registered account IDs."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)
        ids = {a.account_id for a in registry.list_accounts()}
        assert ids == {"AA001", "BB002"}


# ---------------------------------------------------------------------------
# 9. set_primary
# ---------------------------------------------------------------------------


class TestSetPrimary:
    def test_set_primary_marks_correct_account(self) -> None:
        """set_primary() must make list_accounts() report is_primary=True for that account."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)

        registry.set_primary("AA001")
        accounts = {a.account_id: a for a in registry.list_accounts()}
        assert accounts["AA001"].is_primary is True
        assert accounts["BB002"].is_primary is False

    def test_set_primary_transfers_to_new_account(self) -> None:
        """Calling set_primary() again must move the flag to the new account."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)

        registry.set_primary("AA001")
        registry.set_primary("BB002")
        accounts = {a.account_id: a for a in registry.list_accounts()}
        assert accounts["BB002"].is_primary is True
        assert accounts["AA001"].is_primary is False

    def test_set_primary_unknown_account_raises(self) -> None:
        """set_primary() must raise BrokerNotFoundError for an unregistered ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.set_primary("GHOST")


# ---------------------------------------------------------------------------
# 10. get_primary_session
# ---------------------------------------------------------------------------


class TestGetPrimarySession:
    def test_get_primary_session_returns_correct_session(self) -> None:
        """get_primary_session() must return the session whose account was set as primary."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)

        registry.set_primary("BB002")
        primary = registry.get_primary_session()
        assert primary is mock_b

    def test_get_primary_session_after_switch(self) -> None:
        """get_primary_session() must reflect the latest set_primary() call."""
        mock_a = _make_mock_session(account_id="AA001")
        mock_b = _make_mock_session(account_id="BB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("AA001", _BROKER, _LABEL, _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("BB002", _BROKER2, _LABEL2, _CREDS)

        registry.set_primary("AA001")
        assert registry.get_primary_session() is mock_a
        registry.set_primary("BB002")
        assert registry.get_primary_session() is mock_b


# ---------------------------------------------------------------------------
# 11. get_primary_none_raises
# ---------------------------------------------------------------------------


class TestGetPrimaryNoneRaises:
    def test_get_primary_none_raises(self) -> None:
        """get_primary_session() must raise SessionError when no primary is set."""
        registry = BrokerRegistry()
        with pytest.raises(SessionError):
            registry.get_primary_session()

    def test_get_primary_none_after_only_add(self) -> None:
        """Adding an account without set_primary() must not auto-promote it."""
        registry, _ = _registry_with_account("AB1234")
        with pytest.raises(SessionError):
            registry.get_primary_session()

    def test_get_primary_session_raises_session_error_not_broker_not_found(self) -> None:
        """The exception raised must be SessionError, not BrokerNotFoundError."""
        registry = BrokerRegistry()
        with pytest.raises(SessionError):
            registry.get_primary_session()
        # Verify it is NOT a BrokerNotFoundError
        try:
            registry.get_primary_session()
        except SessionError:
            pass
        except BrokerNotFoundError:
            pytest.fail("Expected SessionError but got BrokerNotFoundError")


# ---------------------------------------------------------------------------
# 12. delegated place_order
# ---------------------------------------------------------------------------


class TestDelegatedPlaceOrder:
    def test_delegated_place_order_calls_session(self) -> None:
        """place_order() must delegate to session.place_order() with order_data."""
        mock_session = _make_mock_session()
        expected: dict[str, Any] = {"order_id": "ORD001", "status": "placed"}
        mock_session.place_order.return_value = expected
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        order_data = {"symbol": "NIFTY25JUN21000CE", "qty": 50, "price": 120.0}
        result = registry.place_order("AB1234", order_data)

        mock_session.place_order.assert_called_once_with(order_data)
        assert result == expected

    def test_delegated_place_order_unknown_account_raises(self) -> None:
        """place_order() for an unregistered account must raise BrokerNotFoundError."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.place_order("GHOST", {"symbol": "NIFTY"})

    def test_delegated_get_positions_calls_session(self) -> None:
        """get_positions() must delegate to session.get_positions()."""
        mock_session = _make_mock_session()
        mock_session.get_positions.return_value = {"positions": []}
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        result = registry.get_positions("AB1234")
        mock_session.get_positions.assert_called_once()
        assert result == {"positions": []}

    def test_delegated_get_orders_calls_session(self) -> None:
        """get_orders() must delegate to session.get_orders()."""
        mock_session = _make_mock_session()
        mock_session.get_orders.return_value = {"orders": []}
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        registry.get_orders("AB1234")
        mock_session.get_orders.assert_called_once()

    def test_delegated_get_quotes_calls_session(self) -> None:
        """get_quotes() must delegate to session.get_quotes() with symbol list."""
        mock_session = _make_mock_session()
        mock_session.get_quotes.return_value = {"ltp": 22500.0}
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        result = registry.get_quotes("AB1234", "NIFTY", "NSE")
        mock_session.get_quotes.assert_called_once_with(["NIFTY"])
        assert result == {"ltp": 22500.0}

    def test_delegated_get_funds_calls_session(self) -> None:
        """get_funds() must delegate to session.get_funds()."""
        mock_session = _make_mock_session()
        mock_session.get_funds.return_value = {"available": 50000.0}
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        result = registry.get_funds("AB1234")
        mock_session.get_funds.assert_called_once()
        assert result == {"available": 50000.0}


# ---------------------------------------------------------------------------
# 13. reconnect_with_credentials
# ---------------------------------------------------------------------------


class TestReconnectWithCredentials:
    def test_reconnect_with_credentials_calls_authenticate(self) -> None:
        """reconnect_account() with credentials must call session.authenticate."""
        mock_session = _make_mock_session()
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)
        new_creds = {"api_key": "new_key", "totp": "999999"}

        registry.reconnect_account("AB1234", credentials=new_creds)
        # authenticate was already called once during add_account; now called again
        assert mock_session.authenticate.call_count == 2
        mock_session.authenticate.assert_called_with(new_creds)

    def test_reconnect_with_credentials_returns_broker_account_info(self) -> None:
        """reconnect_account() must return a BrokerAccountInfo."""
        registry, _ = _registry_with_account("AB1234")
        new_creds = {"api_key": "new_key"}
        info = registry.reconnect_account("AB1234", credentials=new_creds)
        assert isinstance(info, BrokerAccountInfo)

    def test_reconnect_unknown_account_raises(self) -> None:
        """reconnect_account() must raise BrokerNotFoundError for unknown ID."""
        registry = BrokerRegistry()
        with pytest.raises(BrokerNotFoundError):
            registry.reconnect_account("GHOST", credentials=_CREDS)

    def test_reconnect_no_creds_no_store_raises(self) -> None:
        """reconnect_account() without credentials or store must raise ValueError."""
        registry, _ = _registry_with_account("AB1234")
        with pytest.raises(ValueError):
            registry.reconnect_account("AB1234")


# ---------------------------------------------------------------------------
# 14. reconnect_with_credential_store
# ---------------------------------------------------------------------------


class TestReconnectWithCredentialStore:
    def test_reconnect_with_credential_store_calls_retrieve(self) -> None:
        """reconnect_account() with a store must call store.retrieve(account_id)."""
        mock_session = _make_mock_session()
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        mock_store = MagicMock()
        mock_store.retrieve.return_value = {"api_key": "stored_key"}

        registry.reconnect_account("AB1234", credential_store=mock_store)
        mock_store.retrieve.assert_called_once_with("AB1234")

    def test_reconnect_with_credential_store_passes_retrieved_creds(self) -> None:
        """Credentials returned by store.retrieve must be passed to authenticate."""
        mock_session = _make_mock_session()
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        stored_creds: dict[str, str] = {"api_key": "stored_key", "totp": "111111"}
        mock_store = MagicMock()
        mock_store.retrieve.return_value = stored_creds

        registry.reconnect_account("AB1234", credential_store=mock_store)
        mock_session.authenticate.assert_called_with(stored_creds)

    def test_reconnect_credentials_takes_precedence_over_store(self) -> None:
        """When both credentials and store are given, credentials must be used."""
        mock_session = _make_mock_session()
        registry, _ = _registry_with_account("AB1234", mock_session=mock_session)

        direct_creds = {"api_key": "direct_key"}
        mock_store = MagicMock()
        mock_store.retrieve.return_value = {"api_key": "store_key"}

        registry.reconnect_account("AB1234", credentials=direct_creds, credential_store=mock_store)
        # store.retrieve must NOT be called when direct credentials are provided
        mock_store.retrieve.assert_not_called()
        mock_session.authenticate.assert_called_with(direct_creds)


# ---------------------------------------------------------------------------
# 15. thread_safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_thread_safety_concurrent_add_account(self) -> None:
        """Concurrent add_account() from 3 threads must all succeed without corruption."""
        account_ids = ["T001", "T002", "T003"]
        brokers = [_BROKER, _BROKER2, "angel"]
        registry = BrokerRegistry()
        errors: list[Exception] = []

        def add(account_id: str, broker: str) -> None:
            try:
                mock_session = _make_mock_session(account_id=account_id, broker=broker)
                with patch(_SESSION_PATCH, return_value=mock_session):
                    registry.add_account(account_id, broker, f"Label {account_id}", _CREDS)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=add, args=(aid, b))
            for aid, b in zip(account_ids, brokers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(registry.list_accounts()) == 3

    def test_thread_safety_all_accounts_retrievable_after_concurrent_add(self) -> None:
        """All concurrently-added accounts must be individually retrievable."""
        account_ids = ["T001", "T002", "T003"]
        brokers = [_BROKER, _BROKER2, "angel"]
        registry = BrokerRegistry()

        def add(account_id: str, broker: str) -> None:
            mock_session = _make_mock_session(account_id=account_id, broker=broker)
            with patch(_SESSION_PATCH, return_value=mock_session):
                registry.add_account(account_id, broker, f"Label {account_id}", _CREDS)

        threads = [
            threading.Thread(target=add, args=(aid, b))
            for aid, b in zip(account_ids, brokers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for account_id in account_ids:
            # Each session must be retrievable without error
            session = registry.get_session(account_id)
            assert session is not None

    def test_thread_safety_set_primary_concurrent(self) -> None:
        """Concurrent set_primary() calls must leave exactly one primary active."""
        mock_a = _make_mock_session(account_id="TA001")
        mock_b = _make_mock_session(account_id="TB002", broker=_BROKER2)
        registry = BrokerRegistry()
        with patch(_SESSION_PATCH, return_value=mock_a):
            registry.add_account("TA001", _BROKER, "A", _CREDS)
        with patch(_SESSION_PATCH, return_value=mock_b):
            registry.add_account("TB002", _BROKER2, "B", _CREDS)

        results: list[str] = []

        def set_primary(account_id: str) -> None:
            registry.set_primary(account_id)
            results.append(account_id)

        threads = [
            threading.Thread(target=set_primary, args=("TA001",)),
            threading.Thread(target=set_primary, args=("TB002",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one of the accounts must be primary (the last writer wins)
        accounts = {a.account_id: a for a in registry.list_accounts()}
        primary_count = sum(1 for a in accounts.values() if a.is_primary)
        assert primary_count == 1
