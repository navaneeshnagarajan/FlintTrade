"""The static catalogue contains only built-in native broker adapters."""

from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers.native_factory import NATIVE_ADAPTER_SPECS


def test_native_catalogue_has_five_supported_brokers():
    assert len(BROKER_CATALOG) == 5
    assert set(BROKER_CATALOG) == set(NATIVE_ADAPTER_SPECS)
    assert all(info.native for info in BROKER_CATALOG.values())


def test_native_catalogue_has_valid_auth_metadata():
    for name, info in BROKER_CATALOG.items():
        assert info.name == name
        assert info.display_name
        assert info.exchanges
        assert info.auth_methods
        if info.connectable:
            assert not info.native_connect_blockers
