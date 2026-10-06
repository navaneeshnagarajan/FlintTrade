"""Exact registry compatibility: catalogue, pure reads and refused legacy mutations."""

import threading

import pytest

from flinttrade_core.account_mutation_contracts import RegistryVersionConflict
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_gateway.registry import BrokerRegistry

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
    assert {"dhan", "upstox"} <= {broker.name for broker in brokers}
    assert all(not broker.is_sandbox for broker in brokers)










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
