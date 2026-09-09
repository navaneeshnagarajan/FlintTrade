"""Exact registry compatibility: catalogue, pure reads and refused legacy mutations."""

import threading
from unittest.mock import Mock

import pytest

from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable, RegistryVersionConflict
from flinttrade_core.broker_account_cutover import BrokerAccountCutoverUnavailable
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_gateway.models import AccountStatus
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.session import BrokerSession

import importlib.util
from pathlib import Path

_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture

@pytest.fixture
def exact(tmp_path):
    value = RegistryFixture(tmp_path)
    yield value
    value.close()


def test_catalogue_keeps_live_brokers_and_excludes_sandbox():
    brokers = BrokerRegistry().get_supported_brokers()
    assert {"zerodha", "fyers"} <= {broker.name for broker in brokers}
    assert all(not broker.is_sandbox for broker in brokers)


@pytest.mark.parametrize("method,args", [
    ("add_account", ("Case", "zerodha", "Synthetic", {})),
    ("reconnect_account", ("Case",)), ("remove_account", ("Case",)),
    ("set_primary", ("Case",)), ("put_session", ("dhan", "Case", object())),
    ("remove_session_for", ("dhan", "Case")),
])
def test_legacy_mutation_never_allocates_or_authenticates(method, args, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("provider or payload allocation attempted")
    monkeypatch.setattr(BrokerSession, "authenticate", forbidden)
    monkeypatch.setattr(BrokerSession, "disconnect", forbidden)
    with pytest.raises(BrokerAccountCutoverUnavailable):
        getattr(BrokerRegistry(), method)(*args)
    with pytest.raises(RegistrySessionUnavailable):
        getattr(BrokerRegistry(mutation_admission=lambda: None), method)(*args)


@pytest.mark.parametrize("method,args,target_args", [
    ("get_positions", (), ()), ("get_orders", (), ()), ("get_trades", (), ()),
    ("get_holdings", (), ()), ("get_funds", (), ()),
    ("get_margin", ({},), ({},)), ("get_quotes", ("SYNTH", "NSE"), (["SYNTH"],)),
    ("get_depth", ("SYNTH",), ("SYNTH",)), ("get_history", ({},), ({},)),
    ("get_option_chain", ({},), ({},)), ("search_symbols", ("SYNTH",), ("SYNTH",)),
])
def test_legacy_delegated_reads_use_exact_unique_record(exact, monkeypatch, method, args, target_args):
    session = BrokerSession("broker-reported", "zerodha", "Raw label")
    reader = Mock(return_value={"synthetic": "result"})
    monkeypatch.setattr(session, method, reader)
    exact.publish("openalgo", "Logical", session, broker="zerodha")
    assert getattr(exact.registry, method)("Logical", *args) == {"synthetic": "result"}
    reader.assert_called_once_with(*target_args)
    assert exact.registry.list_accounts()[0].account_id == "Logical"


def test_primary_is_only_explicit_workspace_projection(exact):
    a = BrokerSession("raw-a", "zerodha", "A")
    b = BrokerSession("raw-b", "fyers", "B")
    exact.publish("openalgo", "A", a, broker="zerodha")
    exact.publish("openalgo", "B", b, broker="fyers")
    assert exact.registry.get_primary_account_id() is None
    with pytest.raises(RegistrySessionUnavailable):
        exact.registry.get_primary_session()
    exact.owner.set_execution_default_projection(BrokerSelector("openalgo", "B"),
                                                 workspace_version=exact.workspace.version)
    assert exact.registry.get_primary_session() is b
    assert exact.registry.get_primary_account_id() == "B"
    with pytest.raises(RegistryVersionConflict):
        exact.owner.set_execution_default_projection(BrokerSelector("openalgo", "A"),
                                                     workspace_version=exact.workspace.version)


def test_disconnected_legacy_is_present_without_canonical_metadata(exact):
    exact.publish("openalgo", "Case", BrokerSession("raw", "zerodha", "Synthetic"), broker="zerodha")
    state = exact.registry.snapshot_exact_state(BrokerSelector("openalgo", "Case"))
    assert state.status == "disconnected" and state.expires_at is None and state.read_only is None
    assert not exact.registry.is_connected()
    assert exact.registry.list_accounts()[0].status == AccountStatus.disconnected


def test_concurrent_remove_cas_has_one_winner(exact):
    selector = BrokerSelector("dhan", "Case")
    expected = exact.registry.snapshot_selector(selector)
    outcomes = []
    def remove():
        try:
            exact.owner.remove_session_for_exact(selector, expected_registry=expected)
            outcomes.append("won")
        except RegistryVersionConflict:
            outcomes.append("stale")
    threads = [threading.Thread(target=remove) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("won") == 1 and outcomes.count("stale") == 7
