"""Native copy metadata and deliberate live capability refusals."""

import pytest

from flinttrade_ditto.account_manager import AccountManager, BrokerAccount
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
