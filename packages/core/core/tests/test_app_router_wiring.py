"""T6 (gap G1): config-driven BrokerRouter assembled at app startup.

``build_broker_router`` parses workspace.json.brokers into a RoutingConfig,
wires the AuthenticatingSessionProvider over its account_acls and a one-shot
SafetyGate, and is strict (raises on a malformed config). The create_flask_app
wrapper is resilient (covered by the app construction suite): a bad config logs
and leaves BROKER_ROUTER unset rather than bricking the app.
"""

from __future__ import annotations

import pytest

from flinttrade_core.app import build_broker_router
from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingConfigError
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider


def test_build_broker_router_from_default_config() -> None:
    router = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert isinstance(router, BrokerRouter)
    assert isinstance(router._config, RoutingConfig)
    assert isinstance(router._session_provider, AuthenticatingSessionProvider)
    assert router._config.execution.default == "openalgo:default"


def test_build_broker_router_invalid_config_raises() -> None:
    bad = {**default_workspace_config()["brokers"], "execution": {"default": "dhan"}}  # no colon
    with pytest.raises(RoutingConfigError):
        build_broker_router(BrokerRegistry(), bad)


def test_build_broker_router_threads_account_acls() -> None:
    brokers = {
        "registered": ["dhan:personal"],
        "account_acls": {"dhan": {"personal": ["nava@flinttrade.local"]}},
        "execution": {"default": "dhan:personal"},
        "data": {
            "ticks": "dhan:personal",
            "historical": "dhan:personal",
            "option_chains": "dhan:personal",
            "quote": "dhan:personal",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }
    router = build_broker_router(BrokerRegistry(), brokers)
    assert router._session_provider._acls == {"dhan": {"personal": ["nava@flinttrade.local"]}}


def test_safety_gate_is_one_shot() -> None:
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("gate-abc") is True
    assert gate.consume("gate-abc") is False  # replay rejected
    assert gate.consume("gate-xyz") is True


def test_openalgo_client_registers_bridge_adapter_and_session() -> None:
    reg = BrokerRegistry()
    brokers = {
        **default_workspace_config()["brokers"],
        "account_acls": {"openalgo": {"default": ["me"]}},
    }
    router = build_broker_router(reg, brokers, openalgo_client=object())
    assert "openalgo" in router._adapters
    assert type(router._adapters["openalgo"]).__name__ == "OpenAlgoAdapter"
    # a Session is registered for the openalgo:default selector so the provider resolves it
    assert reg.get_session_for("openalgo", "default").adapter_id == "openalgo"


def test_no_openalgo_client_leaves_adapters_empty() -> None:
    # Back-compat: the create_flask_app path passes client=None in most tests.
    router = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert router._adapters == {}
