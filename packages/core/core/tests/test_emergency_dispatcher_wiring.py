"""Parent wiring for background emergency broker writes."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from flask import Flask

from flinttrade_core.app import FlintTradeApp, _bind_runtime_emergency_dispatcher
from flinttrade_engine.safety import (
    L5_EMERGENCY_POLICY,
    EmergencyBrokerWrite,
    EmergencyReductionPlan,
    EmergencyWritePolicy,
    SafetyBypassError,
    SafetySystem,
)


class _ClientLoopOwner:
    def __init__(self) -> None:
        self.calls = 0

    def run_sync(self, awaitable: Any) -> Any:
        self.calls += 1
        return asyncio.run(awaitable)


class _Router:
    default_selector = "openalgo:primary"

    def __init__(
        self,
        selectors: tuple[str, ...] = ("openalgo:primary",),
        authorised: tuple[str, ...] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.selectors = selectors
        self.authorised = selectors if authorised is None else authorised
        self.authorised_actor_ids: list[str] = []

    @property
    def registered_selectors(self) -> tuple[str, ...]:
        return self.selectors

    @property
    def configured_selectors(self) -> tuple[str, ...]:
        return self.selectors

    def authorised_selectors(self, actor_id: str) -> tuple[str, ...]:
        self.authorised_actor_ids.append(actor_id)
        return self.authorised

    async def plan_emergency_reduction(
        self,
        request_ctx: Any,
        *,
        policy: EmergencyWritePolicy,
        **_kwargs: Any,
    ) -> EmergencyReductionPlan:
        completed = {
            str(call["verb"])
            for call in self.calls
            if call["request_ctx"].selector == request_ctx.selector
        }
        pending = tuple(verb for verb in policy.verbs if verb not in completed)
        return EmergencyReductionPlan(
            writes=tuple(
                EmergencyBrokerWrite(
                    parent_verb=verb,
                    verb=verb,
                    payload={"_op": verb},
                )
                for verb in pending
            ),
            pending_verbs=frozenset(pending),
        )

    async def execute_gated(self, request_ctx: Any, **kwargs: Any) -> dict[str, bool]:
        self.calls.append({"request_ctx": request_ctx, **kwargs})
        return {"ok": True}


class _Safety:
    def __init__(self) -> None:
        self.dispatcher: Any = None

    def bind_emergency_dispatcher(self, dispatcher: Any) -> None:
        self.dispatcher = dispatcher


def test_runtime_dispatcher_binds_operator_principal_and_confirms_retry_by_readback(monkeypatch) -> None:
    from flinttrade_engine import safety as safety_module

    minted: list[tuple[str, dict[str, Any], Any, str, str]] = []

    def fake_gate(verb, payload, request_ctx, adapter_id, *, account_id):
        minted.append((verb, dict(payload), request_ctx, adapter_id, account_id))
        return object()

    monkeypatch.setattr(safety_module, "gate_broker_write", fake_gate)
    app = Flask("emergency-parent-wiring")
    router = _Router()
    app.config.update(
        BROKER_ROUTER=router,
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
    )
    safety = _Safety()
    telegram = SimpleNamespace(emergency_dispatcher=None)
    client = _ClientLoopOwner()

    dispatcher = _bind_runtime_emergency_dispatcher(app, safety, telegram, client)
    first = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator request")
    second = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator retry")

    assert first.complete is True
    assert second.complete is True
    assert safety.dispatcher is dispatcher
    assert telegram.emergency_dispatcher is dispatcher
    assert app.config["EMERGENCY_DISPATCHER"] is dispatcher
    assert [call[0] for call in minted] == [
        "cancel_all_orders",
        "exit_all_positions",
    ]
    assert all(call[2].actor_id == "operator" for call in minted)
    assert all(call[2].selector == "openalgo:primary" for call in minted)
    assert all(call[3:] == ("openalgo", "primary") for call in minted)
    assert minted[0][2].jti == minted[1][2].jti
    assert client.calls > len(router.calls)
    assert len(router.calls) == 2


def test_runtime_dispatcher_uses_the_app_owned_intent_journal() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    app = Flask("emergency-parent-journal")
    journal = InMemoryEmergencyIntentJournal()
    app.config.update(
        BROKER_ROUTER=_Router(),
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        EMERGENCY_INTENT_JOURNAL=journal,
    )

    dispatcher = _bind_runtime_emergency_dispatcher(
        app,
        _Safety(),
        SimpleNamespace(emergency_dispatcher=None),
        _ClientLoopOwner(),
    )

    assert dispatcher.durable_intent_journal is journal


def test_runtime_dispatcher_fails_closed_without_operator_profile() -> None:
    app = Flask("emergency-parent-no-profile")
    router = _Router()
    app.config["BROKER_ROUTER"] = router
    safety = _Safety()
    telegram = SimpleNamespace(emergency_dispatcher=None)

    dispatcher = _bind_runtime_emergency_dispatcher(
        app,
        safety,
        telegram,
        _ClientLoopOwner(),
    )
    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator request")

    assert result.complete is False
    assert result.failure_codes == ("target_unavailable", "target_unavailable")
    assert router.calls == []


def test_runtime_dispatcher_targets_every_registered_account_before_per_write_acl() -> None:
    app = Flask("emergency-parent-multi-account")
    router = _Router(
        ("openalgo:primary", "dhan:family"),
        authorised=("openalgo:primary",),
    )
    app.config.update(
        BROKER_ROUTER=router,
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
    )

    dispatcher = _bind_runtime_emergency_dispatcher(
        app,
        _Safety(),
        SimpleNamespace(emergency_dispatcher=None),
        _ClientLoopOwner(),
    )
    with dispatcher.authority() as targets:
        selectors = [target.request_ctx.selector for target in targets]

    assert selectors == ["openalgo:primary", "dhan:family"]
    assert router.authorised_actor_ids == []


def test_runtime_dispatcher_persists_unauthorised_registered_target_under_l5() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    class ACLRouter(_Router):
        async def plan_emergency_reduction(
            self,
            request_ctx: Any,
            *,
            policy: EmergencyWritePolicy,
            **kwargs: Any,
        ) -> EmergencyReductionPlan:
            if request_ctx.selector == "dhan:family":
                raise SafetyBypassError("selector ACL refused actor")
            return await super().plan_emergency_reduction(request_ctx, policy=policy, **kwargs)

    journal = InMemoryEmergencyIntentJournal()
    app = Flask("emergency-parent-global-l5")
    router = ACLRouter(("openalgo:primary", "dhan:family"), authorised=("openalgo:primary",))
    app.config.update(
        BROKER_ROUTER=router,
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        EMERGENCY_INTENT_JOURNAL=journal,
    )
    dispatcher = _bind_runtime_emergency_dispatcher(
        app,
        _Safety(),
        SimpleNamespace(emergency_dispatcher=None),
        _ClientLoopOwner(),
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="global L5")
    episode = journal.active_episode(source="l5", selector="*")

    assert result.complete is False
    assert episode is not None
    assert episode.affected_selectors == ("dhan:family", "openalgo:primary")
    assert all(call["request_ctx"].selector != "dhan:family" for call in router.calls)


def test_telegram_polling_starts_only_after_emergency_dispatcher_binding() -> None:
    source = inspect.getsource(FlintTradeApp._start_owned)

    assert source.index("_bind_runtime_emergency_dispatcher(") < source.index(
        "self.telegram.start_background()"
    )


def test_telegram_kill_preflight_failure_does_not_latch_l5_or_dispatch() -> None:
    """Missing operator profile is rejected before Telegram can activate L5."""
    from flinttrade_automation.telegram_bot import BotConfig, TelegramBot

    app = Flask("telegram-preflight")
    router = _Router()
    safety = SafetySystem()
    bot = TelegramBot(config=BotConfig(chat_id="1"), safety_system=safety)
    app.config.update(BROKER_ROUTER=router, AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {}))
    _bind_runtime_emergency_dispatcher(app, safety, bot, _ClientLoopOwner())

    result = bot.handle_command("/kill", chat_id="1")

    assert safety.l5_kill.is_active is False
    assert router.calls == []
    assert "NOT ACTIVATED" in result.response


def test_telegram_released_preflight_cannot_authorise_l5_activation() -> None:
    """Legacy preflight-only wiring is refused because its lease is already gone."""
    from flinttrade_automation.telegram_bot import BotConfig, TelegramBot

    safety = SafetySystem()
    bot = TelegramBot(config=BotConfig(chat_id="1"), safety_system=safety)
    preflight_called = False

    def released_preflight() -> tuple[()]:
        nonlocal preflight_called
        preflight_called = True
        return ()

    bot.emergency_preflight = released_preflight

    result = bot.handle_command("/kill", chat_id="1")

    assert preflight_called is False
    assert safety.l5_kill.is_active is False
    assert "NOT ACTIVATED" in result.response
    assert "authority is unavailable" in result.response


def test_telegram_kill_holds_one_generation_and_acl_authority_through_dispatch(monkeypatch) -> None:
    """A rebuild cannot invalidate Telegram's target between preflight and L5."""
    from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
    from flinttrade_engine import safety as safety_module

    monkeypatch.setattr(safety_module, "gate_broker_write", lambda *_args, **_kwargs: object())
    app = Flask("telegram-authority-transfer")
    rebuild_lock = threading.RLock()
    old_router = _Router(("dhan:family",))
    revoked_router = _Router(())
    safety = SafetySystem()
    bot = TelegramBot(config=BotConfig(chat_id="1"), safety_system=safety)
    app.config.update(
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=1.0,
    )
    _bind_runtime_emergency_dispatcher(app, safety, bot, _ClientLoopOwner())

    original_authority = bot.emergency_authority
    rebuild_started = threading.Event()
    rebuild_finished = threading.Event()

    def revoke_acl_generation() -> None:
        rebuild_started.set()
        with rebuild_lock:
            app.config["BROKER_ROUTER"] = revoked_router
        rebuild_finished.set()

    rebuild_thread: threading.Thread | None = None

    @contextmanager
    def authority_with_racing_rebuild():
        nonlocal rebuild_thread
        with original_authority() as prepared_targets:
            rebuild_thread = threading.Thread(target=revoke_acl_generation)
            rebuild_thread.start()
            assert rebuild_started.wait(1.0)
            assert not rebuild_finished.wait(0.05)
            yield prepared_targets
            assert [call["verb"] for call in old_router.calls] == list(L5_EMERGENCY_POLICY.verbs)
            assert not rebuild_finished.is_set()

    bot.emergency_authority = authority_with_racing_rebuild
    result = bot.handle_command("/kill", chat_id="1", username="operator")
    assert rebuild_thread is not None
    rebuild_thread.join(timeout=2.0)

    assert not rebuild_thread.is_alive()
    assert rebuild_finished.is_set()
    assert safety.l5_kill.is_active is True
    assert "KILL SWITCH ACTIVATED" in result.response
    assert [call["request_ctx"].selector for call in old_router.calls] == ["dhan:family", "dhan:family"]
    assert revoked_router.calls == []


def test_background_l5_scope_blocks_router_rebuild_until_every_verb_finishes(
    monkeypatch,
    tmp_path,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.workspace_migrations import default_workspace_config
    from flinttrade_engine import safety as safety_module
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    first_write_started = threading.Event()
    allow_writes_to_finish = threading.Event()
    rebuild_started = threading.Event()
    rebuild_finished = threading.Event()

    class BlockingRouter(_Router):
        def __init__(self) -> None:
            super().__init__()
            self.revoke_calls = 0

        async def execute_gated(self, request_ctx: Any, **kwargs: Any) -> dict[str, bool]:
            self.calls.append({"request_ctx": request_ctx, **kwargs})
            if len(self.calls) == 1:
                first_write_started.set()
                assert allow_writes_to_finish.wait(2.0)
            return {"ok": True}

        def revoke_and_drain(self, *, timeout: float) -> bool:
            self.revoke_calls += 1
            assert timeout == 1.0
            assert len(self.calls) == len(L5_EMERGENCY_POLICY.verbs)
            return True

    monkeypatch.setattr(safety_module, "gate_broker_write", lambda *_args, **_kwargs: object())
    app = Flask("emergency-parent-rebuild-race")
    old_router = BlockingRouter()
    candidate_router = _Router(("upstox:replacement",))
    safety = SafetySystem(reservation_db_path=tmp_path / "order-exposure-reservations.sqlite")
    journal = InMemoryEmergencyIntentJournal()
    safety.bind_emergency_journal(journal)
    app.config.update(
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        BROKER_ROUTER=old_router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=1.0,
        BROKER_ROUTER_REBUILD_LOCK=threading.RLock(),
        EMERGENCY_INTENT_JOURNAL=journal,
        EMERGENCY_INTENT_JOURNAL_READY=True,
        DAILY_PNL_STATE_STORE=object(),
        DAILY_PNL_STATE_READY=True,
        SAFETY_CONFIG_READY=True,
        SAFETY=safety,
    )
    _bind_runtime_emergency_dispatcher(
        app,
        safety,
        SimpleNamespace(emergency_dispatcher=None),
        _ClientLoopOwner(),
    )
    app.config["EMERGENCY_RUNTIME_READY"] = True
    monkeypatch.setattr(
        app_module,
        "_read_workspace_brokers",
        lambda: default_workspace_config()["brokers"],
    )
    monkeypatch.setattr(app_module, "_native_activation_checks", lambda _store: ({}, {}))
    monkeypatch.setattr(app_module, "_build_reconcile_targets_provider", lambda *_args: None)
    monkeypatch.setattr(app_module, "build_broker_router", lambda *_args, **_kwargs: candidate_router)
    monkeypatch.setattr(app_module, "_snapshot_brokers_bak", lambda _config: None)

    activation: dict[str, Any] = {}
    rebuild: dict[str, Any] = {}
    activation_thread = threading.Thread(
        target=lambda: activation.setdefault("result", safety.l5_kill.activate("background emergency"))
    )

    def rebuild_router() -> None:
        rebuild_started.set()
        rebuild["result"] = app_module.configure_broker_router(app, object(), object(), object())
        rebuild_finished.set()

    activation_thread.start()
    assert first_write_started.wait(1.0)
    rebuild_thread = threading.Thread(target=rebuild_router)
    rebuild_thread.start()
    assert rebuild_started.wait(1.0)
    assert rebuild_finished.wait(0.05) is False
    assert app.config["BROKER_ROUTER"] is old_router
    assert old_router.revoke_calls == 0

    allow_writes_to_finish.set()
    activation_thread.join(2.0)
    rebuild_thread.join(2.0)

    assert not activation_thread.is_alive()
    assert not rebuild_thread.is_alive()
    assert activation["result"].complete is True
    assert [call["verb"] for call in old_router.calls] == list(L5_EMERGENCY_POLICY.verbs)
    assert candidate_router.calls == []
    assert rebuild["result"] is True
    assert old_router.revoke_calls == 1
    assert app.config["BROKER_ROUTER"] is candidate_router


def test_background_l5_generation_lease_contention_fails_closed_within_timeout() -> None:
    app = Flask("emergency-parent-generation-timeout")
    router = _Router()
    safety = SafetySystem()
    rebuild_lock = threading.RLock()
    lock_held = threading.Event()
    release_lock = threading.Event()
    app.config.update(
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
        BROKER_ROUTER=router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.01,
        BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
    )
    _bind_runtime_emergency_dispatcher(
        app,
        safety,
        SimpleNamespace(emergency_dispatcher=None),
        _ClientLoopOwner(),
    )

    def hold_rebuild_lease() -> None:
        with rebuild_lock:
            lock_held.set()
            assert release_lock.wait(2.0)

    holder = threading.Thread(target=hold_rebuild_lease)
    holder.start()
    assert lock_held.wait(1.0)
    started_at = time.monotonic()
    try:
        result = safety.l5_kill.activate("bounded background emergency")
    finally:
        release_lock.set()
        holder.join(2.0)

    assert time.monotonic() - started_at < 1.0
    assert result.complete is False
    assert result.failure_codes == (
        "generation_lease_unavailable",
        "generation_lease_unavailable",
    )
    assert safety.l5_kill.is_active is True
    assert router.authorised_actor_ids == []
    assert router.calls == []
    assert not holder.is_alive()
