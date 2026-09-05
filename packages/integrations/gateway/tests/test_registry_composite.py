"""Exact session projections keep identity and liveness independent."""

import pytest
from flinttrade_core.broker_identity import BrokerSelector
from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
from flinttrade_gateway.brokers._base import Session

import importlib.util
from pathlib import Path

_fixture_spec = importlib.util.spec_from_file_location("_registry_fixtures", Path(__file__).resolve().parents[4] / "tests" / "registry_fixtures.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
RegistryFixture = _fixture_module.RegistryFixture

def test_composite_sessions_preserve_raw_account_and_exact_metadata(tmp_path):
    exact = RegistryFixture(tmp_path)
    try:
        exact.publish("dhan", "Case", Session("synthetic", 4102444800, "broker-id", "dhan"))
        exact.publish("upstox", "Other", Session("synthetic", 1, "broker-other", "upstox"))
        assert exact.session("dhan", "Case").account_id == "broker-id"
        states = exact.registry.list_exact_states()
        assert [(s.selector.adapter_id, s.status) for s in states] == [("dhan", "connected"), ("upstox", "expired")]
        assert exact.registry.is_connected()
        with pytest.raises(RegistrySessionUnavailable):
            exact.session("upstox", "Other")
        expected = exact.registry.snapshot_selector(BrokerSelector("dhan", "Case"))
        exact.owner.remove_session_for_exact(BrokerSelector("dhan", "Case"), expected_registry=expected)
        assert not exact.registry.is_connected()
        assert len(exact.registry.list_exact_states()) == 2
    finally:
        exact.close()
