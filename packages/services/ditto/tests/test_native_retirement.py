"""Native copy metadata and deliberate live capability refusals."""

import pytest

from flinttrade_ditto.account_manager import AccountManager, AmbiguousCopyAccountError, BrokerAccount
from flinttrade_ditto.margin_calculator import MarginCalculator
from flinttrade_ditto.mirror import PositionWatcher
from flinttrade_ditto.runtime import DittoCapabilityUnavailable, DittoRouterOwner


def test_native_account_reference_has_no_transport_secrets(tmp_path):
    with AccountManager(str(tmp_path / "metadata.sqlite")) as manager:
        account = BrokerAccount(account_id="primary", adapter_id="dhan", name="Primary")
        manager.add_account(account)
        assert manager.get_account("primary") == account
        assert not hasattr(account, "api_key")
        assert not hasattr(account, "openalgo_host")
        assert manager.health_check(account).reachable is False


def test_copy_owner_refuses_before_any_router_or_client_exists():
    with pytest.raises(DittoCapabilityUnavailable, match="Native copy-trading"):
        DittoRouterOwner()


def test_margin_read_is_explicitly_unavailable():
    with pytest.raises(RuntimeError, match="unavailable"):
        MarginCalculator.get_margin_info(BrokerAccount("primary", "dhan"))


def test_position_reader_needs_native_account_bound_injection():
    account = BrokerAccount("primary", "dhan")
    with pytest.raises(RuntimeError, match="unavailable"):
        PositionWatcher(account).prime()
    assert PositionWatcher(account, snapshot_reader=lambda selected: {"status": "success", "data": []}).prime() == {}
    with pytest.raises(RuntimeError, match="incomplete"):
        PositionWatcher(account, snapshot_reader=lambda selected: {}).prime()


def test_retired_vault_constructor_arguments_are_rejected(tmp_path):
    with pytest.raises(TypeError):
        AccountManager(db_path=str(tmp_path / "accounts.sqlite"), credential_store=object())


def test_same_account_id_remains_independently_manageable_and_persisted(tmp_path):
    path = str(tmp_path / "metadata.sqlite")
    with AccountManager(path) as manager:
        dhan = BrokerAccount("primary", "dhan", name="Dhan")
        upstox = BrokerAccount("primary", "upstox", name="Upstox")
        manager.add_account(dhan)
        manager.add_account(upstox)
        assert manager.get_account("primary", adapter_id="dhan") == dhan
        assert manager.get_account("primary", adapter_id="upstox") == upstox
        manager.disable_account("primary", adapter_id="dhan")
        assert manager.get_account("primary", adapter_id="dhan").enabled is False
        assert manager.get_account("primary", adapter_id="upstox").enabled is True
        manager.disable_account("primary", adapter_id="upstox")
        manager.enable_account("primary", adapter_id="dhan")
        assert manager.get_account("primary", adapter_id="dhan").enabled is True
        assert manager.get_account("primary", adapter_id="upstox").enabled is False
    with AccountManager(path) as manager:
        assert manager.get_account("primary", adapter_id="dhan").enabled is True
        assert manager.get_account("primary", adapter_id="upstox").enabled is False
        manager.remove_account("primary", adapter_id="dhan")
        assert manager.get_account("primary", adapter_id="dhan") is None
        assert manager.get_account("primary", adapter_id="upstox").name == "Upstox"


@pytest.mark.parametrize("operation", ["get_account", "enable_account", "disable_account", "remove_account"])
def test_ambiguous_legacy_lookup_or_mutation_refuses_without_changing_either_row(operation):
    with AccountManager(":memory:") as manager:
        accounts = [BrokerAccount("primary", adapter) for adapter in ("dhan", "upstox")]
        for account in accounts:
            manager.add_account(account)
        with pytest.raises(AmbiguousCopyAccountError, match="adapter_id and account_id"):
            getattr(manager, operation)("primary")
        assert manager.list_accounts() == accounts


@pytest.mark.parametrize("operation", ["get_account", "enable_account", "disable_account", "remove_account"])
def test_explicit_missing_adapter_never_falls_back_to_another_broker(operation):
    with AccountManager(":memory:") as manager:
        account = BrokerAccount("primary", "dhan")
        manager.add_account(account)
        assert getattr(manager, operation)("primary", adapter_id="upstox") is None
        assert getattr(manager, operation)("primary", adapter_id="unknown") is None
        assert manager.list_accounts() == [account]


@pytest.mark.parametrize("account_id,adapter_id", [("primary", ""), ("primary", "DHAN"), ("bad/id", "dhan")])
def test_malformed_explicit_identity_refuses_without_mutating(account_id, adapter_id):
    from flinttrade_core.broker_identity import BrokerSelectorValidationError

    with AccountManager(":memory:") as manager:
        account = BrokerAccount("primary", "dhan")
        manager.add_account(account)
        with pytest.raises(BrokerSelectorValidationError):
            manager.disable_account(account_id, adapter_id=adapter_id)
        assert manager.list_accounts() == [account]
