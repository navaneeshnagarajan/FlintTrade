"""T6 (gap G1): config-driven BrokerRouter assembled at app startup.

``build_broker_router`` parses workspace.json.brokers into a RoutingConfig,
wires the AuthenticatingSessionProvider over its account_acls and a one-shot
SafetyGate, and is strict (raises on a malformed config). The create_flask_app
wrapper is resilient (covered by the app construction suite): a bad config logs
and leaves BROKER_ROUTER unset rather than bricking the app.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask
import pytest

from flinttrade_core.app import build_broker_router
from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingConfigError
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider


@pytest.mark.unit
def test_configure_broker_router_revokes_old_generation_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-swap")
    old_router = MagicMock()
    old_router.revoke_and_drain.side_effect = (
        lambda **_kwargs: app.config["BROKER_ROUTER"] is None
    )
    candidate = object()
    app.config["BROKER_ROUTER"] = old_router
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: ({}, {}))
    monkeypatch.setattr(app_module, "build_broker_router", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, object(), object(), object()) is True

    old_router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    assert app.config["BROKER_ROUTER"] is candidate


@pytest.mark.unit
def test_configure_broker_router_build_failure_revokes_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-build-failure")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = True
    app.config["BROKER_ROUTER"] = old_router
    monkeypatch.setattr(
        app_module,
        "build_broker_router",
        MagicMock(side_effect=ValueError("invalid routing")),
    )

    assert app_module.configure_broker_router(app, object(), object(), object()) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    assert app.config["BROKER_ROUTER"] is None


@pytest.mark.unit
def test_configure_broker_router_drain_timeout_never_publishes_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-drain-timeout")
    old_router = MagicMock()
    old_router.revoke_and_drain.return_value = False
    candidate = object()
    app.config.update(
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.25,
    )
    monkeypatch.setattr(app_module, "build_broker_router", lambda *_args, **_kwargs: candidate)

    assert app_module.configure_broker_router(app, object(), object(), object()) is False

    old_router.revoke_and_drain.assert_called_once_with(timeout=0.25)
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is old_router


@pytest.mark.unit
def test_configure_broker_router_retries_retained_generation_before_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-generation-drain-retry")
    old_router = MagicMock()
    old_router.revoke_and_drain.side_effect = [False, True]
    candidate = object()
    build = MagicMock(return_value=candidate)
    app.config.update(
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0,
    )
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: ({}, {}))
    monkeypatch.setattr(app_module, "build_broker_router", build)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    assert app_module.configure_broker_router(app, object(), object(), object()) is False
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is old_router

    assert app_module.configure_broker_router(app, object(), object(), object()) is True

    assert old_router.revoke_and_drain.call_count == 2
    assert app.config["BROKER_ROUTER_DRAINING"] is None
    assert app.config["BROKER_ROUTER"] is candidate


@pytest.mark.unit
def test_configure_broker_router_refuses_and_retires_during_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    app = Flask("router-rebuild-during-shutdown")
    router = MagicMock()
    router.revoke_and_drain.return_value = True
    build = MagicMock()
    app.config.update(
        BROKER_ROUTER=router,
        RUNTIME_ACCEPTING_REQUESTS=False,
    )
    monkeypatch.setattr(app_module, "build_broker_router", build)

    assert app_module.configure_broker_router(app, object(), object(), object()) is False

    router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    build.assert_not_called()
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is None


def test_build_broker_router_from_default_config() -> None:
    router = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert isinstance(router, BrokerRouter)
    assert isinstance(router._config, RoutingConfig)
    assert isinstance(router._session_provider, AuthenticatingSessionProvider)
    assert router._config.execution.default == "openalgo:default"
    # Public accessor mirrors the private config (used by order/bracket routes).
    assert router.default_selector == "openalgo:default"


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


def _all_native_brokers_cfg() -> dict:
    return {
        "registered": ["dhan:D1", "upstox:U1", "indmoney:I1", "kotakneo:K1", "groww:G1"],
        "account_acls": {
            "dhan": {"D1": ["me"]},
            "upstox": {"U1": ["me"]},
            "indmoney": {"I1": ["me"]},
            "kotakneo": {"K1": ["me"]},
            "groww": {"G1": ["me"]},
        },
        "execution": {"default": "dhan:D1"},
        "data": {
            "ticks": "dhan:D1", "historical": "dhan:D1",
            "option_chains": "dhan:D1", "quote": "dhan:D1",
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


def test_only_connectable_natives_activate_from_registered_selectors() -> None:
    """Boot activation follows the live-verified native set, not stale rows.

    Kotak Neo and Groww are built/catalogued but still ``connectable=false``
    until live login/read verification passes, so even attested+credentialled
    stale rows must remain dormant after restart. Capability metadata remains
    available via the recommendation/capability routes; this only guards runtime
    activation.
    """
    router = build_broker_router(
        BrokerRegistry(),
        _all_native_brokers_cfg(),
        native_attest_ok=lambda _b: True,
        native_has_credentials=lambda _b: True,
    )
    assert set(router._adapters) == {"dhan", "upstox", "indmoney"}
    assert "kotakneo" not in router._adapters
    assert "groww" not in router._adapters


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
    ``attest_ok`` now depends on the pinned SDK being INSTALLED (dhan/upstox/
    kotakneo/groww all carry real pins) — so its per-broker value is environment-
    dependent and not hard-asserted here. IndMoney is the exception: its SDK pin
    is ``None`` (REST-only), so it always attests. PLACEHOLDER-pin dormancy is
    covered against a fixture lock in ``test_broker_sdk_attest``.
    """
    from flinttrade_core.app import _native_activation_checks

    class _FakeVault:
        def list_accounts(self) -> list[dict]:
            return [{"account_id": "personal", "adapter_id": "dhan", "broker": "dhan"}]

    attest_ok, has_credentials = _native_activation_checks(_FakeVault())
    assert has_credentials("dhan") is True
    assert has_credentials("upstox") is False
    # REST-only native: no SDK to attest, so activation is gated by creds alone.
    assert attest_ok("indmoney") is True
    # A non-native id never attests.
    assert attest_ok("not-a-broker") is False


def test_native_activation_checks_no_vault_fails_closed() -> None:
    from flinttrade_core.app import _native_activation_checks

    _attest_ok, has_credentials = _native_activation_checks(None)
    # No vault → nothing is credentialled, so nothing activates even if attested.
    assert has_credentials("dhan") is False
    assert has_credentials("upstox") is False
    assert has_credentials("indmoney") is False


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
    # upstox is registered in config but the vault holds no upstox creds → dormant
    # (has_credentials gate), regardless of whether its SDK is installed.
    assert "upstox" not in router._adapters


@pytest.mark.unit
def test_native_adapter_kwargs_thread_local_state_provider() -> None:
    """The §14 wiring: adapter_kwargs reaches the native constructor, so the
    journal-backed ``local_state_provider`` lands on the adapter."""
    sentinel_provider = lambda _session: None  # noqa: E731 - shape only; never called

    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        native_attest_ok=lambda b: b == "dhan",
        native_has_credentials=lambda b: b == "dhan",
        native_adapter_kwargs=lambda _b: {"local_state_provider": sentinel_provider},
    )
    assert router._adapters["dhan"]._local_state_provider is sentinel_provider


@pytest.mark.unit
def test_native_adapter_kwargs_adds_cached_dhan_security_resolver(monkeypatch) -> None:
    """App-activated Dhan adapters must resolve symbols like the live probe.

    Dhan market-data and order-write calls require a security id. The app
    factory injects a lazy resolver only for Dhan, so the resolver works for
    reads/writes without making every native adapter accept Dhan-only kwargs.
    """
    from flinttrade_core.app import _native_adapter_kwargs_for

    csv_text = "\n".join(
        [
            "SEM_SMST_SECURITY_ID,SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SM_SYMBOL_NAME",
            "11536,NSE,E,RELIANCE,RELIANCE,RELIANCE",
        ]
    )
    downloads: list[str] = []

    def _fake_download(url: str) -> str:
        downloads.append(url)
        return csv_text

    monkeypatch.setattr("flinttrade_gateway.brokers.dhan._download_text", _fake_download)
    sentinel_provider = lambda _session: None  # noqa: E731 - shape only; never called

    kwargs_for = _native_adapter_kwargs_for(sentinel_provider)
    dhan_kwargs = kwargs_for("dhan")
    upstox_kwargs = kwargs_for("upstox")

    assert dhan_kwargs["local_state_provider"] is sentinel_provider
    assert upstox_kwargs == {"local_state_provider": sentinel_provider}
    resolve = dhan_kwargs["security_resolver"]
    assert resolve("RELIANCE", "NSE") == "11536"
    assert resolve("RELIANCE", "NSE") == "11536"
    assert len(downloads) == 1


@pytest.mark.unit
def test_on_native_activated_sink_receives_active_natives_only() -> None:
    """The sink sees exactly the ACTIVE native map — bridge excluded, injected
    natives included — so the reconciliation runner can enumerate them."""

    class _FakeNative:
        broker_id = "upstox"

    activated: dict[str, object] = {}
    router = build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        adapters={"upstox": _FakeNative()},
        openalgo_client=object(),
        native_attest_ok=lambda b: b == "dhan",
        native_has_credentials=lambda b: b == "dhan",
        on_native_activated=activated.update,
    )
    assert set(activated) == {"dhan", "upstox"}
    assert "openalgo" not in activated  # bridge never qualifies
    assert activated["dhan"] is router._adapters["dhan"]


@pytest.mark.unit
def test_on_native_activated_sink_empty_when_dormant() -> None:
    activated: dict[str, object] = {}
    build_broker_router(
        BrokerRegistry(),
        _native_brokers_cfg(),
        openalgo_client=object(),
        on_native_activated=activated.update,
    )
    assert activated == {}


@pytest.mark.unit
def test_reconcile_targets_provider_yields_only_live_native_sessions() -> None:
    """``_build_reconcile_targets_provider`` resolves at call time: a selector
    becomes a target only when its adapter is active AND a session exists."""
    from flinttrade_core.app import _build_reconcile_targets_provider

    class _FakeAdapter:
        broker_id = "dhan"

    reg = BrokerRegistry()
    adapter = _FakeAdapter()
    natives: dict[str, object] = {}
    targets = _build_reconcile_targets_provider(
        reg, natives, ["dhan:personal", "upstox:main", "not-a-selector"]
    )

    # Nothing active, nothing logged in → no targets.
    assert targets() == []

    # Adapter active but no session yet (pre-login) → still no targets.
    natives["dhan"] = adapter
    assert targets() == []

    # Session established (credential-replay login) → picked up next call.
    session = object()
    reg.put_session("dhan", "personal", session)
    assert targets() == [(adapter, session)]

    # A session for a DORMANT adapter never becomes a target.
    reg.put_session("upstox", "main", object())
    assert targets() == [(adapter, session)]


@pytest.mark.unit
def test_create_flask_app_defaults_reconcile_config_keys() -> None:
    """The factory always defines NATIVE_ADAPTERS / RECONCILE_TARGETS, and with
    the default config (no natives credentialled) the provider yields nothing."""
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    assert app.config["NATIVE_ADAPTERS"] == {}
    targets = app.config["RECONCILE_TARGETS"]
    assert callable(targets)
    assert targets() == []


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


def test_build_broker_router_builds_algo_tag_guard_from_config() -> None:
    """workspace brokers.algo_tags builds an engine AlgoTagGuard on the router
    (G10 — algo-id relay + per-exchange per-second ceiling for algo_tag_required
    natives). Without the block the router stays untagged (retail defaults)."""
    from flinttrade_engine.algo_tag_guard import AlgoTagGuard

    brokers = {
        **default_workspace_config()["brokers"],
        "algo_tags": {"dhan": {"algo_id": "ALGO-REG-1", "max_orders_per_sec": 8}},
    }
    router = build_broker_router(BrokerRegistry(), brokers)
    guard = router._algo_tag_guard
    assert isinstance(guard, AlgoTagGuard)
    assert guard.algo_id_for("dhan") == "ALGO-REG-1"

    untagged = build_broker_router(BrokerRegistry(), default_workspace_config()["brokers"])
    assert untagged._algo_tag_guard is None


@pytest.mark.unit
def test_build_broker_router_malformed_algo_tags_are_dropped_not_fatal() -> None:
    """A malformed algo_tags entry is DROPPED (loud error log), never raised —
    a bad compliance-config block must not brick broker reads/reconciliation/
    dispatch (audit finding: over-broad blast radius). The adapter/mapping
    retail default takes over, so no order dispatches in a broker-flagging
    state. A mix of valid + invalid keeps only the valid entry."""
    from flinttrade_engine.algo_tag_guard import AlgoTagGuard

    base = default_workspace_config()["brokers"]
    for bad in (
        {"dhan": {"algo_id": "", "max_orders_per_sec": 8}},
        {"dhan": {"algo_id": "A", "max_orders_per_sec": 0}},
        {"dhan": "not-an-object"},
        {"dhan": {"algo_id": "A", "max_orders_per_sec": "not-an-int"}},
    ):
        router = build_broker_router(BrokerRegistry(), {**base, "algo_tags": bad})
        assert isinstance(router, BrokerRouter)
        assert router._algo_tag_guard is None  # the only entry was dropped

    mixed = {"dhan": {"algo_id": "OK", "max_orders_per_sec": 5}, "indmoney": "bad"}
    router = build_broker_router(BrokerRegistry(), {**base, "algo_tags": mixed})
    assert isinstance(router._algo_tag_guard, AlgoTagGuard)
    assert router._algo_tag_guard.algo_id_for("dhan") == "OK"
    assert router._algo_tag_guard.algo_id_for("indmoney") is None
