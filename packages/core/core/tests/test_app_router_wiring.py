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


def test_safety_gate_reconsume_allowed_after_ttl_expiry() -> None:
    """L4: once the consumed marker expires, the slot re-opens.

    ``ttl_seconds=0`` makes the marker expire immediately, so a second consume
    returns True. This never widens the real replay window because
    SafetyContext.verify independently enforces the order's own ~10s expiry — a
    gate old enough to be re-consumable is already expired at verify time.
    """
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("g0", ttl_seconds=0) is True
    assert gate.consume("g0", ttl_seconds=0) is True  # expired marker re-opens


def test_safety_gate_prune_does_not_evict_live_marker() -> None:
    """L4: the >256 opportunistic prune drops expired markers but keeps live ones."""
    from flinttrade_engine.safety import SafetyGate

    gate = SafetyGate()
    assert gate.consume("live", ttl_seconds=60.0) is True
    # Overflow the prune threshold with already-expired markers.
    for i in range(300):
        gate.consume(f"expired-{i}", ttl_seconds=0)
    # The live marker survived the prune, so its replay is still rejected.
    assert gate.consume("live") is False


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


def _native_brokers_cfg() -> dict:
    return {
        "registered": ["dhan:personal", "upstox:main"],
        "account_acls": {"dhan": {"personal": ["me"]}, "upstox": {"main": ["me"]}},
        "execution": {"default": "dhan:personal"},
        "data": {
            "ticks": "dhan:personal", "historical": "dhan:personal",
            "option_chains": "dhan:personal", "quote": "dhan:personal",
        },
        "failover": {"enabled": False, "order": []},
        "cost_aware": {"enabled": False, "tasks": []},
    }


def test_natives_stay_dormant_without_activation_checks() -> None:
    # Default: no native_* callables → no native adapter constructed.
    router = build_broker_router(BrokerRegistry(), _native_brokers_cfg())
    assert router._adapters == {}


def test_native_activates_only_when_attested_and_credentialled() -> None:
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda b: b in {"dhan", "upstox"},
        native_has_credentials=lambda b: b == "dhan",  # only dhan has creds
    )
    # dhan passes both gates; upstox is attested but has no creds → dormant.
    assert set(router._adapters) == {"dhan"}
    assert type(router._adapters["dhan"]).__name__ == "DhanAdapter"


def test_native_activation_gates_fail_closed() -> None:
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda _b: False,
        native_has_credentials=lambda _b: True,
    )
    assert router._adapters == {}


def test_injected_adapter_wins_over_factory() -> None:
    sentinel = object()
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        adapters={"dhan": sentinel},
        native_attest_ok=lambda _b: True,
        native_has_credentials=lambda _b: True,
    )
    # Explicit injection takes precedence; the factory does not overwrite it.
    assert router._adapters["dhan"] is sentinel


def test_native_activation_checks_credential_presence() -> None:
    """``_native_activation_checks`` reflects what the vault holds.

    ``has_credentials`` must mirror the vault's ``list_accounts`` adapter ids.
    ``attest_ok`` is real: brokers whose ``brokers.lock`` pin is still PLACEHOLDER
    (upstox / kotakneo) are ``skipped`` and so never attested — environment-
    independent. (Dhan's pin is real, so its attest_ok depends on whether dhanhq
    is installed — not asserted here.)
    """
    from flinttrade_core.app import _native_activation_checks

    class _FakeVault:
        def list_accounts(self) -> list[dict]:
            return [{"account_id": "personal", "adapter_id": "dhan", "broker": "dhan"}]

    attest_ok, has_credentials = _native_activation_checks(_FakeVault())
    assert has_credentials("dhan") is True
    assert has_credentials("upstox") is False
    # PLACEHOLDER-pinned brokers are never attested, regardless of environment.
    assert attest_ok("upstox") is False
    assert attest_ok("kotakneo") is False


def test_native_activation_checks_no_vault_fails_closed() -> None:
    from flinttrade_core.app import _native_activation_checks

    attest_ok, has_credentials = _native_activation_checks(None)
    assert has_credentials("dhan") is False
    # No vault → nothing is credentialled, so nothing activates even if attested.
    assert attest_ok("upstox") is False


def test_dhan_activates_end_to_end_when_sdk_present() -> None:
    """Real bridge: with dhanhq installed (pin match) + creds in the vault, the
    router registers a live DhanAdapter via the activation factory.

    Skipped where dhanhq is not installed (the PLACEHOLDER-pinned natives can
    never reach this state, so this only exercises the one real pin).
    """
    pytest.importorskip("dhanhq")
    from flinttrade_core.app import _native_activation_checks, build_broker_router

    class _FakeVault:
        def list_accounts(self) -> list[dict]:
            return [{"account_id": "personal", "adapter_id": "dhan", "broker": "dhan"}]

    attest_ok, has_credentials = _native_activation_checks(_FakeVault())
    if not attest_ok("dhan"):  # dhanhq present but version != pin → nothing to prove
        pytest.skip("dhanhq installed but version does not match brokers.lock pin")

    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=attest_ok,
        native_has_credentials=has_credentials,
    )
    assert "dhan" in router._adapters
    assert type(router._adapters["dhan"]).__name__ == "DhanAdapter"
    # upstox is registered in config but its pin is PLACEHOLDER → stays dormant.
    assert "upstox" not in router._adapters


def test_authorise_default_actor_trust_on_first_use() -> None:
    """A freshly authenticated operator claims the default execution selector once."""
    from flinttrade_engine.request_context import RequestContext

    reg = BrokerRegistry()
    router = build_broker_router(reg, default_workspace_config()["brokers"], openalgo_client=object())
    # Default execution selector is openalgo:default with an empty ACL.
    assert router._config.execution.default == "openalgo:default"

    claimed = router.authorise_default_actor("nava")
    assert claimed == ("openalgo", "default")
    # The provider now authorises that actor for the gated path (no SafetyBypassError).
    ctx = RequestContext(jti="x", actor_type="human", actor_id="nava", mode="live")
    assert router._session_provider(ctx, "openalgo", "default") is not None
    # A second, different actor is NOT auto-claimed (TOFU is one-shot per selector).
    assert router.authorise_default_actor("someone-else") is None
