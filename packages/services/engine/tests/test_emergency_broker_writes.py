"""Emergency broker writes stay inside the selector-bound gated router path."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    EmergencyBrokerTarget,
    EmergencyBrokerWrite,
    EmergencyDispatchResult,
    EmergencyReductionPlan,
    EmergencyVerbOutcome,
    EmergencyWritePolicy,
    GatedEmergencyBrokerDispatcher,
    IST,
    KillSwitch,
    KillSwitchResetAuthorisationError,
    L5_EMERGENCY_POLICY,
    MTM_EMERGENCY_POLICY,
    MTMCircuitBreaker,
    MTMCircuitBreakerConfig,
    SafetyGate,
    gate_broker_write,
    gate_order,
    set_safety_gate_secret,
)
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

_SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(_SECRET)


def _request_ctx(*, actor_id: str = "operator") -> RequestContext:
    return RequestContext(
        jti="emergency-jti",
        actor_type="human",
        actor_id=actor_id,
        mode="live",
        selector="dhan:acct-1",
    )


def _target(*, actor_id: str = "operator") -> EmergencyBrokerTarget:
    return EmergencyBrokerTarget(
        request_ctx=_request_ctx(actor_id=actor_id),
        adapter_id="dhan",
        account_id="acct-1",
    )


def _target_for(adapter_id: str, account_id: str, *, actor_id: str = "operator") -> EmergencyBrokerTarget:
    return EmergencyBrokerTarget(
        request_ctx=RequestContext(
            jti=f"emergency-jti-{adapter_id}-{account_id}",
            actor_type="human",
            actor_id=actor_id,
            mode="live",
            selector=f"{adapter_id}:{account_id}",
        ),
        adapter_id=adapter_id,
        account_id=account_id,
    )


def _mark_fake_adapter_invoked(kwargs: dict[str, Any]) -> None:
    callback = kwargs.get("on_adapter_invoke")
    if callable(callback):
        callback()


def _session_provider(allowed_actor: str = "operator"):
    def provide(ctx: RequestContext, adapter_id: str, account_id: str) -> Session:
        if ctx.actor_id != allowed_actor:
            raise SafetyBypassError("selector ACL refused actor")
        return Session(
            access_token="token",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
            account_id=account_id,
            adapter_id=adapter_id,
        )

    return provide


class _EmergencyAdapter:
    """Extended-write fake that proves dispatch arrived with the router token."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.completed_by_account: dict[str, set[str]] = {}

    async def plan_emergency_reduction(
        self,
        _session: Session,
        *,
        policy: EmergencyWritePolicy,
        **_kwargs: Any,
    ) -> EmergencyReductionPlan:
        """Model authoritative readback for the generic emergency adapter."""
        completed = self.completed_by_account.get(_session.account_id, set())
        writes: list[EmergencyBrokerWrite] = []
        pending: set[str] = set()
        for verb in policy.verbs:
            if verb in completed:
                continue
            pending.add(verb)
            writes.append(
                EmergencyBrokerWrite(
                    parent_verb=verb,
                    verb=verb,
                    payload={"_op": verb},
                )
            )
        return EmergencyReductionPlan(
            writes=tuple(writes),
            pending_verbs=frozenset(pending),
        )

    @staticmethod
    def _require_router(token: object | None) -> None:
        if token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write called without BrokerRouter token")

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, Any]:
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        self.completed_by_account.setdefault(session.account_id, set()).add("cancel_all_orders")
        return {"errors": [], "total": 1, "success": 1}

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        _router_token: object | None = None,
    ) -> None:
        self._require_router(_router_token)
        self.calls.append(f"cancel_order:{order_id}")

    async def cancel_forever(
        self,
        session: Session,
        order_id: str,
        *,
        _router_token: object | None = None,
    ) -> None:
        self._require_router(_router_token)
        self.calls.append(f"cancel_forever:{order_id}")

    async def exit_all_positions(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, Any]:
        self._require_router(_router_token)
        self.calls.append("exit_all_positions")
        self.completed_by_account.setdefault(session.account_id, set()).add("exit_all_positions")
        return {"errors": [], "total": 1, "success": 1}


class _BlockingEmergencyAdapter(_EmergencyAdapter):
    """Hold cancel-all open so the owning router can be retired concurrently."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, Any]:
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        self.completed_by_account.setdefault(session.account_id, set()).add("cancel_all_orders")
        self.entered.set()
        await asyncio.to_thread(self.release.wait)
        return {"errors": [], "total": 1, "success": 1}


class _PartialEmergencyAdapter(_EmergencyAdapter):
    async def plan_emergency_reduction(self, session, *, policy, **kwargs):
        plan = await super().plan_emergency_reduction(session, policy=policy, **kwargs)
        if "cancel_all_orders" not in policy.verbs:
            return plan
        writes = tuple(
            write for write in plan.writes if write.parent_verb != "cancel_all_orders"
        ) + (
            EmergencyBrokerWrite(
                parent_verb="cancel_all_orders",
                verb="cancel_all_orders",
                payload={"_op": "cancel_all_orders"},
            ),
        )
        return EmergencyReductionPlan(
            writes=writes,
            pending_verbs=plan.pending_verbs | {"cancel_all_orders"},
        )

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, Any]:
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        self.completed_by_account.setdefault(session.account_id, set()).add("cancel_all_orders")
        return {
            "order_ids": ["cancelled-one"],
            "errors": [{"order_id": "failed-one"}],
            "total": 2,
            "success": 1,
        }


class _BlockingNormalWriteAdapter(_EmergencyAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.normal_write_entered = threading.Event()
        self.release_normal_write = threading.Event()
        self.placed: list[Any] = []

    async def place_order(
        self,
        session: Session,
        order: Any,
        *,
        _router_token: object | None = None,
    ) -> str:
        self._require_router(_router_token)
        self.normal_write_entered.set()
        await asyncio.to_thread(self.release_normal_write.wait)
        self.placed.append(order)
        return "normal-order"


def _router(
    adapter: Any,
    *,
    allowed_actor: str = "operator",
    write_admission: Any = None,
    algo_tag_guard: Any = None,
) -> BrokerRouter:
    gate = SafetyGate()
    return BrokerRouter(
        {"dhan": adapter},
        _session_provider(allowed_actor),
        consume_gate=gate.consume,
        write_admission=write_admission,
        algo_tag_guard=algo_tag_guard,
    )


def _dispatcher(
    router_provider: Any,
    *,
    target_provider: Any = _target,
) -> GatedEmergencyBrokerDispatcher:
    return GatedEmergencyBrokerDispatcher(
        router_provider=router_provider,
        target_provider=target_provider,
        run_awaitable=asyncio.run,
    )


def test_l5_policy_mints_one_gate_per_verb_and_reaches_only_token_adapter() -> None:
    adapter = _EmergencyAdapter()
    router = _router(adapter)
    provider_calls = 0

    def current_router() -> BrokerRouter:
        nonlocal provider_calls
        provider_calls += 1
        return router

    result = _dispatcher(current_router).dispatch(
        L5_EMERGENCY_POLICY,
        reason="operator emergency",
    )

    assert result.complete
    assert result.succeeded("cancel_all_orders")
    assert result.succeeded("exit_all_positions")
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
    assert provider_calls == 6, "planner reads and concrete writes must observe the current router generation"


def test_l5_latch_time_journal_failure_degrades_to_dispatcher_fallback() -> None:
    """A dead durable journal at LATCH time must not veto the flatten.

    The kill switch previously returned ``intent_journal_unavailable`` without
    ever invoking the dispatcher when the durable ``activate_episode`` write
    failed — leaving the operator unable to flatten exactly when the journal
    volume died. It now records the episode in the dispatcher's process-local
    intent journal and dispatches the reducing writes; durable reset authority
    is untouched (reset still requires the durable journal).
    """
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    class DeadEpisodeJournal(InMemoryEmergencyIntentJournal):
        def activate_episode(self, **_kwargs):
            raise OSError("durable journal volume unavailable")

    adapter = _EmergencyAdapter()
    router = _router(adapter)
    safety = SafetySystem()
    safety.bind_emergency_journal(DeadEpisodeJournal())
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=4,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = safety.l5_kill.activate("latch during journal outage", emergency_dispatcher=dispatcher)

    assert safety.l5_kill.is_active
    assert result.complete, f"flatten was vetoed: {result.as_dict()}"
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
    assert "intent_journal_unavailable" not in str(result.as_dict())


def test_l5_latch_time_journal_failure_still_fails_closed_without_a_fallback() -> None:
    """No dispatcher fallback available → the pre-fix veto is preserved."""
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    class DeadEpisodeJournal(InMemoryEmergencyIntentJournal):
        def activate_episode(self, **_kwargs):
            raise OSError("durable journal volume unavailable")

    class NoFallbackDispatcher:
        """Duck-typed dispatcher without ensure_degraded_episode."""

        def dispatch(self, *_args, **_kwargs):  # pragma: no cover - must not run
            raise AssertionError("dispatch must not run when the episode was never recorded")

    safety = SafetySystem()
    safety.bind_emergency_journal(DeadEpisodeJournal())

    result = safety.l5_kill.activate("outage without fallback", emergency_dispatcher=NoFallbackDispatcher())

    assert safety.l5_kill.is_active
    assert not result.complete
    assert "intent_journal_unavailable" in str(result.as_dict())


def test_emergency_flatten_uses_process_fallback_when_journal_storage_fails() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    class FailingReserveJournal(InMemoryEmergencyIntentJournal):
        def reserve(self, **_kwargs):
            raise OSError("durable journal volume unavailable")

    adapter = _EmergencyAdapter()
    router = _router(adapter)
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=FailingReserveJournal(),
        planned_readback_attempts=4,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="journal outage")

    assert result.complete
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
    assert dispatcher.intent_journal_degraded is True


def test_emergency_intent_conflict_never_degrades_to_fallback() -> None:
    from flinttrade_engine.emergency_intents import (
        EmergencyIntentConflict,
        InMemoryEmergencyIntentJournal,
    )

    class ConflictingReserveJournal(InMemoryEmergencyIntentJournal):
        def reserve(self, **_kwargs):
            raise EmergencyIntentConflict("concurrent reservation changed")

    adapter = _EmergencyAdapter()
    router = _router(adapter)
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=ConflictingReserveJournal(),
        planned_readback_attempts=2,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="journal conflict")

    assert result.complete is False
    assert adapter.calls == []
    assert dispatcher.intent_journal_degraded is False


def test_dispatcher_generation_lease_spans_target_snapshot_and_every_write() -> None:
    events: list[str] = []

    class RecordingAdapter(_EmergencyAdapter):
        async def cancel_all_orders(self, session, *, _router_token=None):
            events.append("cancel")
            return await super().cancel_all_orders(session, _router_token=_router_token)

        async def exit_all_positions(self, session, *, _router_token=None):
            events.append("exit")
            return await super().exit_all_positions(session, _router_token=_router_token)

    @contextmanager
    def generation_lease():
        events.append("lease-enter")
        try:
            yield
        finally:
            events.append("lease-exit")

    adapter = RecordingAdapter()
    router = _router(adapter)
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: events.append("targets") or _target(),
        run_awaitable=asyncio.run,
        generation_lease_provider=generation_lease,
    )

    result = KillSwitch().activate("leased emergency", emergency_dispatcher=dispatcher)

    assert result.complete
    assert events == ["lease-enter", "targets", "cancel", "exit", "lease-exit"]


def test_l5_policy_sweeps_every_supplied_target_and_reports_each_selector() -> None:
    dhan = _EmergencyAdapter()
    upstox = _EmergencyAdapter()

    def session_provider(ctx: RequestContext, adapter_id: str, account_id: str) -> Session:
        assert ctx.actor_id == "operator"
        return Session(
            access_token="token",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
            account_id=account_id,
            adapter_id=adapter_id,
        )

    router = BrokerRouter(
        {"dhan": dhan, "upstox": upstox},
        session_provider,
        consume_gate=SafetyGate().consume,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        targets_provider=lambda: (
            _target_for("dhan", "primary"),
            _target_for("upstox", "secondary"),
        ),
        run_awaitable=asyncio.run,
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="all-account emergency")

    assert result.complete
    assert result.target_count == 2
    assert result.completed_target_count == 2
    assert dhan.calls == ["cancel_all_orders", "exit_all_positions"]
    assert upstox.calls == ["cancel_all_orders", "exit_all_positions"]
    payload = result.as_dict()
    assert [target["selector"] for target in payload["targets"]] == [
        "dhan:primary",
        "upstox:secondary",
    ]
    assert all(target["complete"] for target in payload["targets"])


def test_mtm_breaker_dispatches_only_the_breaching_account_selector() -> None:
    class AccountRecordingAdapter(_EmergencyAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.exited_accounts: list[str] = []

        async def exit_all_positions(
            self,
            session: Session,
            *,
            _router_token: object | None = None,
        ) -> dict[str, Any]:
            self._require_router(_router_token)
            self.calls.append("exit_all_positions")
            self.completed_by_account.setdefault(session.account_id, set()).add("exit_all_positions")
            self.exited_accounts.append(session.account_id)
            return {"errors": [], "total": 1, "success": 1}

    adapter = AccountRecordingAdapter()
    router = BrokerRouter(
        {"dhan": adapter},
        _session_provider(),
        consume_gate=SafetyGate().consume,
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        targets_provider=lambda: (
            _target_for("dhan", "primary"),
            _target_for("dhan", "family"),
        ),
        run_awaitable=asyncio.run,
    )
    breaker = MTMCircuitBreaker(
        MTMCircuitBreakerConfig(daily_loss_limit=-50_000),
        emergency_dispatcher=dispatcher,
    )

    fired = asyncio.run(
        breaker.check_and_act(
            -60_000,
            adapter_id="dhan",
            account_id="family",
        )
    )

    assert fired is True
    assert adapter.exited_accounts == ["family"]
    assert breaker.last_emergency_result is not None
    assert {outcome.selector for outcome in breaker.last_emergency_result.outcomes} == {"dhan:family"}

    second_account_fired = asyncio.run(
        breaker.check_and_act(
            -70_000,
            adapter_id="dhan",
            account_id="primary",
        )
    )

    assert second_account_fired is True
    assert adapter.exited_accounts == ["family", "primary"]
    assert breaker.last_emergency_result is not None
    assert {outcome.selector for outcome in breaker.last_emergency_result.outcomes} == {"dhan:primary"}


@pytest.mark.parametrize(
    ("returned_policy", "returned_selector"),
    (
        (L5_EMERGENCY_POLICY, "dhan:acct-1"),
        (MTM_EMERGENCY_POLICY, "dhan:other-account"),
    ),
)
def test_mtm_breaker_rejects_a_result_for_the_wrong_policy_or_account(
    returned_policy: EmergencyWritePolicy,
    returned_selector: str,
) -> None:
    class MismatchedDispatcher:
        def dispatch(self, _policy, *, reason, adapter_id, account_id):
            del reason, adapter_id, account_id
            return EmergencyDispatchResult(
                policy=returned_policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(verb, succeeded=True, selector=returned_selector)
                    for verb in returned_policy.verbs
                ),
            )

    breaker = MTMCircuitBreaker(
        MTMCircuitBreakerConfig(daily_loss_limit=-50_000),
        emergency_dispatcher=MismatchedDispatcher(),
    )

    assert asyncio.run(
        breaker.check_and_act(-60_000, adapter_id="dhan", account_id="acct-1")
    )
    assert breaker.is_triggered
    assert breaker.last_emergency_result is not None
    assert breaker.last_emergency_result.policy == MTM_EMERGENCY_POLICY
    assert set(breaker.last_emergency_result.failure_codes) == {"invalid_dispatch_result"}


def test_mtm_latch_blocks_later_normal_router_writes_for_the_breached_selector() -> None:
    from flinttrade_engine.safety import SafetySystem

    class CompleteDispatcher:
        def dispatch(self, policy, *, reason, adapter_id, account_id):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector=f"{adapter_id}:{account_id}",
                    )
                    for verb in policy.verbs
                ),
            )

    class PlacingAdapter(_EmergencyAdapter):
        async def place_order(self, session, order, *, _router_token=None):
            self._require_router(_router_token)
            self.calls.append("place_order")
            return "normal-order"

    safety = SafetySystem(emergency_dispatcher=CompleteDispatcher())
    assert asyncio.run(
        safety.mtm_circuit_breaker.check_and_act(
            -60_000,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )
    adapter = PlacingAdapter()
    router = _router(adapter, write_admission=safety.broker_write_admission)
    request_ctx = _request_ctx()
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(order, request_ctx, "dhan", account_id="acct-1")

    with pytest.raises(SafetyBypassError, match="MTM circuit breaker"):
        asyncio.run(
            router.place_order(
                request_ctx,
                order=order,
                safety_ctx=safety_ctx,
                adapter_id="dhan",
                account_id="acct-1",
            )
        )
    assert adapter.calls == []


def test_mtm_latch_does_not_block_a_different_account_selector() -> None:
    from flinttrade_engine.safety import SafetySystem

    class CompleteDispatcher:
        def dispatch(self, policy, *, reason, adapter_id, account_id):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector=f"{adapter_id}:{account_id}",
                    )
                    for verb in policy.verbs
                ),
            )

    class PlacingAdapter(_EmergencyAdapter):
        async def place_order(self, session, order, *, _router_token=None):
            self._require_router(_router_token)
            self.calls.append(session.account_id)
            return "normal-order"

    safety = SafetySystem(emergency_dispatcher=CompleteDispatcher())
    assert asyncio.run(
        safety.mtm_circuit_breaker.check_and_act(
            -60_000,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )
    adapter = PlacingAdapter()
    router = _router(adapter, write_admission=safety.broker_write_admission)
    request_ctx = _target_for("dhan", "acct-2").request_ctx
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(order, request_ctx, "dhan", account_id="acct-2")

    result = asyncio.run(
        router.place_order(
            request_ctx,
            order=order,
            safety_ctx=safety_ctx,
            adapter_id="dhan",
            account_id="acct-2",
        )
    )

    assert result == "normal-order"
    assert adapter.calls == ["acct-2"]


def test_mtm_breach_drains_an_admitted_account_write_before_flattening() -> None:
    from flinttrade_engine.safety import SafetySystem

    write_entered = threading.Event()
    release_write = threading.Event()
    emergency_dispatched = threading.Event()

    class CompleteDispatcher:
        def dispatch(self, policy, *, reason, adapter_id, account_id):
            emergency_dispatched.set()
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector=f"{adapter_id}:{account_id}",
                    )
                    for verb in policy.verbs
                ),
            )

    class BlockingAdapter(_EmergencyAdapter):
        async def place_order(self, session, order, *, _router_token=None):
            self._require_router(_router_token)
            write_entered.set()
            if not release_write.wait(timeout=2.0):
                raise TimeoutError("test did not release admitted broker write")
            self.calls.append("place_order")
            return "normal-order"

    safety = SafetySystem(emergency_dispatcher=CompleteDispatcher())
    adapter = BlockingAdapter()
    router = _router(adapter, write_admission=safety.broker_write_admission)
    request_ctx = _request_ctx()
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(order, request_ctx, "dhan", account_id="acct-1")
    write_errors: list[BaseException] = []
    breach_errors: list[BaseException] = []
    breach_results: list[bool] = []

    def place_normal_order() -> None:
        try:
            asyncio.run(
                router.place_order(
                    request_ctx,
                    order=order,
                    safety_ctx=safety_ctx,
                    adapter_id="dhan",
                    account_id="acct-1",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            write_errors.append(exc)

    def trigger_breach() -> None:
        try:
            breach_results.append(
                asyncio.run(
                    safety.mtm_circuit_breaker.check_and_act(
                        -60_000,
                        adapter_id="dhan",
                        account_id="acct-1",
                    )
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            breach_errors.append(exc)

    normal_thread = threading.Thread(target=place_normal_order)
    normal_thread.start()
    assert write_entered.wait(timeout=1.0)

    breach_thread = threading.Thread(target=trigger_breach)
    breach_thread.start()
    assert not emergency_dispatched.wait(timeout=0.05)
    assert breach_thread.is_alive()

    release_write.set()
    normal_thread.join(timeout=1.0)
    breach_thread.join(timeout=1.0)

    assert not normal_thread.is_alive()
    assert not breach_thread.is_alive()
    assert write_errors == []
    assert breach_errors == []
    assert breach_results == [True]
    assert emergency_dispatched.is_set()
    assert adapter.calls == ["place_order"]


def test_l5_episode_restores_after_restart_and_reset_closes_it(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    path = tmp_path / "restart-l5.sqlite"
    EmergencyIntentJournal(path).activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash="0" * 64,
    )
    safety = SafetySystem()
    safety.bind_emergency_journal(EmergencyIntentJournal(path))

    assert safety.l5_kill.is_active
    with pytest.raises(SafetyBypassError, match="kill switch"):
        with safety.broker_write_admission(False, "dhan:acct-1"):
            pytest.fail("durable L5 episode admitted a normal write")

    safety.l5_kill.reset()
    restarted = SafetySystem()
    restarted.bind_emergency_journal(EmergencyIntentJournal(path))
    assert not restarted.l5_kill.is_active
    with restarted.broker_write_admission(False, "dhan:acct-1"):
        pass


def test_restarted_l5_reset_authorises_persisted_affected_selectors(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    class QuietRouter:
        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())

    path = tmp_path / "restart-l5-authorisation.sqlite"
    journal = EmergencyIntentJournal(path)
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: QuietRouter(),
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=journal,
        planned_readback_attempts=1,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    first = KillSwitch(emergency_dispatcher=dispatcher)
    first.bind_emergency_journal(journal)
    assert first.activate("persist selector provenance").complete

    restarted = KillSwitch()
    restarted.bind_emergency_journal(EmergencyIntentJournal(path))
    observed: list[frozenset[str]] = []

    with pytest.raises(KillSwitchResetAuthorisationError, match="not authorised"):
        restarted.reset(authorise_selectors=lambda selectors: observed.append(selectors) or False)

    assert observed == [frozenset({"dhan:acct-1"})]
    assert restarted.is_active
    assert EmergencyIntentJournal(path).blocking_sources("dhan:acct-1") == frozenset({"l5"})

    restarted.reset(authorise_selectors=lambda selectors: selectors == {"dhan:acct-1"})
    assert not restarted.is_active


def test_mtm_episode_restores_only_its_account_after_restart(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    path = tmp_path / "restart-mtm.sqlite"
    EmergencyIntentJournal(path).activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key=datetime.now(IST).date().isoformat(),
        reason_hash="0" * 64,
    )
    safety = SafetySystem()
    safety.bind_emergency_journal(EmergencyIntentJournal(path))

    assert safety.mtm_circuit_breaker.is_triggered
    with pytest.raises(SafetyBypassError, match="MTM circuit breaker"):
        with safety.broker_write_admission(False, "dhan:acct-1"):
            pytest.fail("durable MTM episode admitted the breached account")
    with safety.broker_write_admission(False, "dhan:acct-2"):
        pass

    safety.mtm_circuit_breaker.reset_daily()
    restarted = SafetySystem()
    restarted.bind_emergency_journal(EmergencyIntentJournal(path))
    assert not restarted.mtm_circuit_breaker.is_triggered


def test_quiet_prior_day_mtm_episode_rolls_over_on_restart(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    path = tmp_path / "prior-day-mtm.sqlite"
    journal = EmergencyIntentJournal(path)
    journal.activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key="2000-01-01",
        reason_hash="0" * 64,
    )

    safety = SafetySystem()
    safety.bind_emergency_journal(journal)

    assert not safety.mtm_circuit_breaker.is_triggered
    assert journal.blocking_sources("dhan:acct-1") == frozenset()
    with safety.broker_write_admission(False, "dhan:acct-1"):
        pass


def test_stale_startup_rollover_cannot_deactivate_a_concurrently_renewed_mtm_episode(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    path = tmp_path / "startup-rollover-race.sqlite"
    base = EmergencyIntentJournal(path)
    base.activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key="2026-07-13",
        reason_hash="0" * 64,
    )

    class RenewBeforeDeactivate(EmergencyIntentJournal):
        def deactivate_episode(self, *, expected):
            EmergencyIntentJournal(path).activate_episode(
                source="mtm",
                selector="dhan:acct-1",
                session_key="2026-07-14",
                reason_hash="1" * 64,
            )
            return super().deactivate_episode(expected=expected)

    breaker = MTMCircuitBreaker(session_key_provider=lambda: "2026-07-14")
    breaker.bind_emergency_journal(RenewBeforeDeactivate(path))

    assert breaker.is_triggered
    episode = EmergencyIntentJournal(path).active_episode(source="mtm", selector="dhan:acct-1")
    assert episode is not None
    assert episode.session_key == "2026-07-14"
    with pytest.raises(SafetyBypassError, match="MTM circuit breaker"):
        with breaker.broker_write_admission(False, "dhan:acct-1"):
            pytest.fail("a concurrently renewed MTM episode admitted a normal write")


def test_unsettled_prior_day_mtm_episode_stays_blocked_and_renews_on_fresh_breach(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    path = tmp_path / "unsettled-prior-day-mtm.sqlite"
    journal = EmergencyIntentJournal(path)
    journal.activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key="2000-01-01",
        reason_hash="0" * 64,
    )
    journal.reserve(
        source="mtm",
        selector="dhan:acct-1",
        parent_verb="exit_all_positions",
        verb="place_reducing_order",
        payload_hash="1" * 64,
        scope="position:prior-day",
        exit_tag="FTE-PRIOR-DAY",
    )

    safety = SafetySystem()
    safety.bind_emergency_journal(journal)

    assert safety.mtm_circuit_breaker.is_triggered
    with pytest.raises(SafetyBypassError, match="MTM circuit breaker"):
        with safety.broker_write_admission(False, "dhan:acct-1"):
            pytest.fail("an unresolved prior-day MTM episode admitted a normal write")

    assert asyncio.run(
        safety.mtm_circuit_breaker.check_and_act(
            -60_000,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )
    episodes = journal.active_episodes("mtm")
    assert len(episodes) == 1
    assert episodes[0].session_key == datetime.now(IST).date().isoformat()


def test_prior_day_mtm_episode_created_after_bind_rolls_over_on_first_admission(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    journal = EmergencyIntentJournal(tmp_path / "late-prior-day-mtm.sqlite")
    breaker = MTMCircuitBreaker(session_key_provider=lambda: "2026-07-14")
    breaker.bind_emergency_journal(journal)
    journal.activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key="2026-07-13",
        reason_hash="0" * 64,
    )

    with breaker.broker_write_admission(False, "dhan:acct-1"):
        pass

    assert not breaker.is_triggered
    assert journal.blocking_sources("dhan:acct-1") == frozenset()


def test_stale_late_rollover_cannot_deactivate_a_concurrently_renewed_mtm_episode(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    path = tmp_path / "late-rollover-race.sqlite"

    class RenewBeforeDeactivate(EmergencyIntentJournal):
        def deactivate_episode(self, *, expected):
            EmergencyIntentJournal(path).activate_episode(
                source="mtm",
                selector="dhan:acct-1",
                session_key="2026-07-14",
                reason_hash="1" * 64,
            )
            return super().deactivate_episode(expected=expected)

    journal = RenewBeforeDeactivate(path)
    breaker = MTMCircuitBreaker(session_key_provider=lambda: "2026-07-14")
    breaker.bind_emergency_journal(journal)
    EmergencyIntentJournal(path).activate_episode(
        source="mtm",
        selector="dhan:acct-1",
        session_key="2026-07-13",
        reason_hash="0" * 64,
    )

    with pytest.raises(SafetyBypassError, match="MTM circuit breaker"):
        with breaker.broker_write_admission(False, "dhan:acct-1"):
            pytest.fail("a concurrently renewed late MTM episode admitted a normal write")

    episode = EmergencyIntentJournal(path).active_episode(source="mtm", selector="dhan:acct-1")
    assert episode is not None
    assert episode.session_key == "2026-07-14"


def test_l5_reset_keeps_the_latch_when_a_durable_intent_is_unsettled(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentConflict, EmergencyIntentJournal
    from flinttrade_engine.safety import SafetySystem

    path = tmp_path / "unsettled-l5.sqlite"
    journal = EmergencyIntentJournal(path)
    journal.activate_episode(
        source="l5",
        selector="*",
        session_key="manual",
        reason_hash="0" * 64,
    )
    journal.reserve(
        source="l5",
        selector="dhan:acct-1",
        parent_verb="exit_all_positions",
        verb="place_reducing_order",
        payload_hash="0" * 64,
        scope="position:abc",
        exit_tag="FTE-1",
    )
    safety = SafetySystem()
    safety.bind_emergency_journal(EmergencyIntentJournal(path))

    with pytest.raises(EmergencyIntentConflict, match="unsettled"):
        safety.l5_kill.reset()

    assert safety.l5_kill.is_active
    assert EmergencyIntentJournal(path).blocking_sources("dhan:acct-1") == frozenset({"l5"})


def test_l5_episode_is_durable_before_dispatcher_entry() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    journal = InMemoryEmergencyIntentJournal()

    class EpisodeAwareDispatcher:
        def dispatch(self, policy, *, reason):
            assert journal.blocking_sources("dhan:acct-1") == frozenset({"l5"})
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs),
            )

    kill_switch = KillSwitch(emergency_dispatcher=EpisodeAwareDispatcher())
    kill_switch.bind_emergency_journal(journal)

    result = kill_switch.activate("operator requested flatten")

    assert result.complete
    assert journal.blocking_sources("upstox:other") == frozenset({"l5"})
    kill_switch.reset()


def test_mtm_episode_is_durable_before_dispatcher_entry() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    journal = InMemoryEmergencyIntentJournal()

    class EpisodeAwareDispatcher:
        def dispatch(self, policy, *, reason, adapter_id, account_id):
            selector = f"{adapter_id}:{account_id}"
            assert journal.blocking_sources(selector) == frozenset({"mtm"})
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(verb, succeeded=True, selector=selector)
                    for verb in policy.verbs
                ),
            )

    breaker = MTMCircuitBreaker(emergency_dispatcher=EpisodeAwareDispatcher())
    breaker.bind_emergency_journal(journal)

    assert asyncio.run(
        breaker.check_and_act(
            -60_000,
            adapter_id="dhan",
            account_id="acct-1",
        )
    )
    assert journal.blocking_sources("dhan:acct-1") == frozenset({"mtm"})
    breaker.reset_daily()


def test_adapter_declared_partial_batch_is_not_reported_as_complete() -> None:
    adapter = _PartialEmergencyAdapter()
    router = _router(adapter)

    result = _dispatcher(lambda: router).dispatch(
        L5_EMERGENCY_POLICY,
        reason="partial broker sweep",
    )

    assert not result.complete
    assert result.failure_codes == ("partial_broker_result",)
    assert not result.succeeded("cancel_all_orders")
    assert result.succeeded("exit_all_positions")


def test_explicit_broker_error_status_is_not_reported_as_success() -> None:
    class ErrorStatusRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="exit_all_positions",
                        payload={"_op": "exit_all_positions"},
                    ),
                ),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            self.calls += 1
            return {
                "status": "error",
                "error": "broker refused the request",
                "errors": [],
                "total": 1,
                "success": 1,
            }

    router = ErrorStatusRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=2,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="status_error", verbs=("exit_all_positions",))

    result = dispatcher.dispatch(policy, reason="broker returned an error envelope")

    assert not result.complete
    assert result.failure_codes == ("broker_refused",)
    assert router.calls == 1


def test_gate_preparation_failure_does_not_reserve_an_emergency_intent(monkeypatch) -> None:
    import flinttrade_engine.safety as safety_module
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    class PlanningRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="exit_all_positions",
                        payload={"_op": "exit_all_positions"},
                    ),
                ),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            self.calls += 1
            return {"errors": [], "total": 1, "success": 1}

    journal = InMemoryEmergencyIntentJournal()
    router = PlanningRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=journal,
        planned_readback_attempts=2,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="pre_gate_failure", verbs=("exit_all_positions",))
    monkeypatch.setattr(safety_module, "_SAFETY_GATE_SECRET", None)

    result = dispatcher.dispatch(policy, reason="missing gate secret")

    assert not result.complete
    assert result.failure_codes == ("safety_refused",)
    assert router.calls == 0
    assert journal.unresolved("dhan:acct-1", policy.verbs, source="adhoc") == ()


def test_pre_adapter_refusal_releases_intent_for_a_later_retry() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    adapter = _EmergencyAdapter()
    provider_calls = 0

    def session_provider(_ctx, adapter_id, account_id):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 2:
            raise SafetyBypassError("selector ACL changed before adapter dispatch")
        return Session(
            access_token="token",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
            account_id=account_id,
            adapter_id=adapter_id,
        )

    router = BrokerRouter({"dhan": adapter}, session_provider)
    journal = InMemoryEmergencyIntentJournal()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=journal,
        planned_readback_attempts=3,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="retry_pre_adapter", verbs=("cancel_all_orders",))

    first = dispatcher.dispatch(policy, reason="transient pre-adapter refusal")
    second = dispatcher.dispatch(policy, reason="retry after refusal")

    assert not first.complete
    assert first.outcomes[0].attempted is False
    assert second.complete
    assert adapter.calls == ["cancel_all_orders"]
    assert journal.unresolved("dhan:acct-1", policy.verbs, source="adhoc") == ()


def test_planned_exit_accepts_complete_broker_summary_without_order_ids() -> None:
    class SummaryExitRouter:
        def __init__(self) -> None:
            self.pending = True
            self.exit_calls = 0

        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            if not self.pending:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="exit_all_positions",
                        payload={"_op": "exit_all_positions"},
                    ),
                ),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, *, verb, **_kwargs):
            assert verb == "exit_all_positions"
            self.exit_calls += 1
            self.pending = False
            return {"errors": [], "total": 2, "success": 2}

    router = SummaryExitRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=3,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="summary_exit", verbs=("exit_all_positions",))

    result = dispatcher.dispatch(policy, reason="verified Dhan-style summary")

    assert result.complete
    assert router.exit_calls == 1


def test_planned_partial_cancel_continues_through_later_bounded_batches() -> None:
    class PlanningRouter:
        def __init__(self) -> None:
            self.active = {f"O{index:02d}" for index in range(12)}
            self.cancel_calls: list[str] = []
            self.gate_ids: list[str] = []

        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            if not self.active:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
            writes = tuple(
                EmergencyBrokerWrite(
                    parent_verb="cancel_all_orders",
                    verb="cancel_order",
                    payload={"_op": "cancel_order", "order_id": order_id},
                )
                for order_id in sorted(self.active)[:10]
            )
            return EmergencyReductionPlan(
                writes=writes,
                pending_verbs=frozenset({"cancel_all_orders"}),
            )

        async def cancel_order(self, _request_ctx, *, order_id, safety_ctx, **_kwargs):
            _mark_fake_adapter_invoked(_kwargs)
            self.cancel_calls.append(order_id)
            self.gate_ids.append(safety_ctx.gate_id)
            if order_id == "O00":
                raise RuntimeError("deterministic refusal")
            self.active.remove(order_id)

    router = PlanningRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=8,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="bounded_cancel_batches", verbs=("cancel_all_orders",))

    result = dispatcher.dispatch(policy, reason="continue after one concrete refusal")

    assert result.failure_codes == ("partial_broker_result",)
    assert router.active == {"O00"}
    assert router.cancel_calls == [f"O{index:02d}" for index in range(12)]
    assert len(router.gate_ids) == 12
    assert len(set(router.gate_ids)) == 12


def test_successful_planned_cancellation_is_not_replayed_during_stale_readback() -> None:
    class StickyCancellationRouter:
        def __init__(self) -> None:
            self.cancel_calls: list[str] = []
            self.protected_snapshots: list[frozenset[str]] = []

        async def plan_emergency_reduction(
            self,
            _request_ctx,
            *,
            protected_order_ids,
            **_kwargs,
        ):
            self.protected_snapshots.append(protected_order_ids)
            writes = ()
            if "STICKY-1" not in protected_order_ids:
                writes = (
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_order",
                        payload={"_op": "cancel_order", "order_id": "STICKY-1"},
                    ),
                )
            return EmergencyReductionPlan(
                writes=writes,
                pending_verbs=frozenset({"cancel_all_orders"}),
            )

        async def cancel_order(self, _request_ctx, *, order_id, **_kwargs):
            self.cancel_calls.append(order_id)

    router = StickyCancellationRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=4,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="sticky_cancel", verbs=("cancel_all_orders",))

    result = dispatcher.dispatch(policy, reason="stale cancellation readback")

    assert not result.complete
    assert result.failure_codes == ("partial_broker_result",)
    assert router.cancel_calls == ["STICKY-1"]
    assert router.protected_snapshots[0] == frozenset()
    assert all(snapshot == frozenset({"STICKY-1"}) for snapshot in router.protected_snapshots[1:])


def test_newly_reserved_exit_tag_protects_lost_response_before_same_dispatch_replan() -> None:
    class LostTaggedExitRouter:
        def __init__(self) -> None:
            self.accepted = False
            self.cancelled = False
            self.protected_snapshots: list[frozenset[str]] = []

        async def plan_emergency_reduction(
            self,
            _request_ctx,
            *,
            protected_exit_tags,
            **_kwargs,
        ):
            self.protected_snapshots.append(protected_exit_tags)
            if not self.accepted:
                return EmergencyReductionPlan(
                    writes=(
                        EmergencyBrokerWrite(
                            parent_verb="exit_all_positions",
                            verb="place_reducing_order",
                            payload={
                                "_op": "place_reducing_order",
                                "symbol": "RELIANCE",
                                "exchange": "NSE",
                                "product": "D",
                                "quantity": 1,
                                "emergency_tag": "FTE-TAGGED-1",
                            },
                        ),
                    ),
                    pending_verbs=frozenset({"exit_all_positions"}),
                )
            if "FTE-TAGGED-1" not in protected_exit_tags:
                return EmergencyReductionPlan(
                    writes=(
                        EmergencyBrokerWrite(
                            parent_verb="exit_all_positions",
                            verb="cancel_order",
                            payload={"_op": "cancel_order", "order_id": "UNKNOWN-EXIT"},
                        ),
                    ),
                    pending_verbs=frozenset({"exit_all_positions"}),
                )
            return EmergencyReductionPlan(
                writes=(),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            _mark_fake_adapter_invoked(_kwargs)
            self.accepted = True
            raise TimeoutError("broker accepted the tagged exit and lost the response")

        async def cancel_order(self, _request_ctx, **_kwargs):
            self.cancelled = True

    router = LostTaggedExitRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=3,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="lost_tagged_exit", verbs=("exit_all_positions",))

    result = dispatcher.dispatch(policy, reason="lost tagged exit response")

    assert not result.complete
    assert router.cancelled is False
    assert router.protected_snapshots[0] == frozenset()
    assert all(
        snapshot == frozenset({"FTE-TAGGED-1"})
        for snapshot in router.protected_snapshots[1:]
    )


def test_unidentified_bulk_exit_blocks_cancellation_until_joint_readback_is_quiet() -> None:
    class LostBulkExitRouter:
        def __init__(self) -> None:
            self.accepted = False
            self.cancelled = False
            self.unidentified_snapshots: list[bool] = []

        async def plan_emergency_reduction(
            self,
            _request_ctx,
            *,
            unidentified_exit_inflight,
            **_kwargs,
        ):
            self.unidentified_snapshots.append(unidentified_exit_inflight)
            if not self.accepted:
                return EmergencyReductionPlan(
                    writes=(
                        EmergencyBrokerWrite(
                            parent_verb="exit_all_positions",
                            verb="exit_all_positions",
                            payload={"_op": "exit_all_positions"},
                        ),
                    ),
                    pending_verbs=frozenset({"exit_all_positions"}),
                )
            if not unidentified_exit_inflight:
                return EmergencyReductionPlan(
                    writes=(
                        EmergencyBrokerWrite(
                            parent_verb="exit_all_positions",
                            verb="cancel_order",
                            payload={"_op": "cancel_order", "order_id": "UNKNOWN-BULK-EXIT"},
                        ),
                    ),
                    pending_verbs=frozenset({"exit_all_positions"}),
                )
            return EmergencyReductionPlan(
                writes=(),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            _mark_fake_adapter_invoked(_kwargs)
            self.accepted = True
            raise TimeoutError("broker accepted an unidentified bulk exit")

        async def cancel_order(self, _request_ctx, **_kwargs):
            self.cancelled = True

    router = LostBulkExitRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=3,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="lost_bulk_exit", verbs=("exit_all_positions",))

    result = dispatcher.dispatch(policy, reason="lost unidentified bulk exit")

    assert not result.complete
    assert router.cancelled is False
    assert router.unidentified_snapshots == [False, True, True]


def test_fractional_batch_counts_are_an_invalid_broker_result() -> None:
    assert GatedEmergencyBrokerDispatcher._broker_result_failure(
        {"errors": [], "total": 1.9, "success": 1.2}
    ) == "invalid_broker_result"


@pytest.mark.parametrize("ambiguous_result", [None, {"status": "ok"}])
def test_bulk_write_requires_an_explicit_complete_summary(ambiguous_result) -> None:
    class AmbiguousBulkRouter:
        def __init__(self) -> None:
            self.pending = True

        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            if not self.pending:
                return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="cancel_all_orders",
                        verb="cancel_all_orders",
                        payload={"_op": "cancel_all_orders"},
                    ),
                ),
                pending_verbs=frozenset({"cancel_all_orders"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            return ambiguous_result

    router = AmbiguousBulkRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=2,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="ambiguous_bulk", verbs=("cancel_all_orders",))

    result = dispatcher.dispatch(policy, reason="ambiguous bulk acknowledgement")

    assert not result.complete
    assert result.failure_codes == ("invalid_broker_result",)


def test_exact_reduction_requires_exactly_one_broker_order_id() -> None:
    class MultipleIdRouter:
        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="place_reducing_order",
                        payload={
                            "_op": "place_reducing_order",
                            "symbol": "RELIANCE",
                            "exchange": "NSE",
                            "product": "D",
                            "quantity": 1,
                            "emergency_tag": "FTE-ONE-ID",
                        },
                    ),
                ),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, **_kwargs):
            return {"order_ids": ["EXIT-1", "EXIT-2"]}

    router = MultipleIdRouter()
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        planned_readback_attempts=2,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    policy = EmergencyWritePolicy(name="one_exact_exit", verbs=("exit_all_positions",))

    result = dispatcher.dispatch(policy, reason="multiple IDs for one exact exit")

    assert result.failure_codes == ("invalid_broker_result",)


def test_lost_exit_response_is_not_replayed_after_dispatcher_restart(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    state = {"quantity": 5, "calls": []}

    class ResidualExitRouter:
        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            quantity = state["quantity"]
            return EmergencyReductionPlan(
                writes=(
                    EmergencyBrokerWrite(
                        parent_verb="exit_all_positions",
                        verb="place_reducing_order",
                        payload={
                            "_op": "place_reducing_order",
                            "symbol": "RELIANCE",
                            "exchange": "NSE",
                            "product": "D",
                            "action": "SELL",
                            "quantity": quantity,
                            "expected_position_quantity": quantity,
                            "emergency_tag": f"FTE-{quantity}",
                        },
                    ),
                ),
                pending_verbs=frozenset({"exit_all_positions"}),
            )

        async def execute_gated(self, _request_ctx, *, payload, **_kwargs):
            _mark_fake_adapter_invoked(_kwargs)
            state["calls"].append(payload["quantity"])
            state["quantity"] = 3
            raise TimeoutError("broker accepted the exit but the response was lost")

    journal_path = tmp_path / "emergency-intents.sqlite"
    policy = EmergencyWritePolicy(name="durable_exit", verbs=("exit_all_positions",))
    router = ResidualExitRouter()

    first = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(journal_path),
        planned_readback_attempts=1,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    first_result = first.dispatch(policy, reason="first flatten attempt")

    second = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(journal_path),
        planned_readback_attempts=1,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )
    second_result = second.dispatch(policy, reason="process restarted")

    assert not first_result.complete
    assert not second_result.complete
    assert state["calls"] == [5]


def test_lost_legacy_sweep_response_is_not_replayed_after_dispatcher_restart(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    class LegacyRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute_gated(self, _request_ctx, **_kwargs):
            _mark_fake_adapter_invoked(_kwargs)
            self.calls += 1
            raise TimeoutError("broker accepted the sweep but the response was lost")

    journal_path = tmp_path / "legacy-emergency-intents.sqlite"
    policy = EmergencyWritePolicy(name="legacy_exit", verbs=("exit_all_positions",))
    router = LegacyRouter()

    first = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(journal_path),
    )
    second = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(journal_path),
    )

    first_result = first.dispatch(policy, reason="first legacy sweep")
    second_result = second.dispatch(policy, reason="process restarted")

    assert first_result.failure_codes == ("authoritative_readback_unavailable",)
    assert second_result.failure_codes == ("authoritative_readback_unavailable",)
    assert router.calls == 0


def test_acknowledged_legacy_sweep_is_not_replayed_without_readback(tmp_path) -> None:
    from flinttrade_engine.emergency_intents import EmergencyIntentJournal

    class LegacyRouter:
        def __init__(self) -> None:
            self.calls = 0

        async def execute_gated(self, _request_ctx, **_kwargs):
            self.calls += 1
            return {"errors": [], "total": 1, "success": 1}

    path = tmp_path / "acknowledged-legacy.sqlite"
    policy = EmergencyWritePolicy(name="legacy_cancel", verbs=("cancel_all_orders",))
    router = LegacyRouter()
    first = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(path),
    )
    second = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=EmergencyIntentJournal(path),
    )

    first_result = first.dispatch(policy, reason="broker acknowledged bulk cancel")
    retry = second.dispatch(policy, reason="transport response was retried")

    assert first_result.failure_codes == ("authoritative_readback_unavailable",)
    assert retry.failure_codes == ("authoritative_readback_unavailable",)
    assert router.calls == 0


def test_planned_settlement_conflict_fails_closed() -> None:
    from flinttrade_engine.emergency_intents import InMemoryEmergencyIntentJournal

    class ConflictingJournal(InMemoryEmergencyIntentJournal):
        def settle(self, *args, **kwargs):
            return False

    class QuietRouter:
        async def plan_emergency_reduction(self, _request_ctx, **_kwargs):
            return EmergencyReductionPlan(writes=(), pending_verbs=frozenset())

    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: QuietRouter(),
        target_provider=_target,
        run_awaitable=asyncio.run,
        intent_journal=ConflictingJournal(),
        planned_readback_attempts=1,
        planned_quiet_reads=1,
        planned_readback_delay_seconds=0,
    )

    result = dispatcher.dispatch(
        EmergencyWritePolicy(name="quiet_conflict", verbs=("cancel_all_orders",)),
        reason="concurrent reservation",
    )

    assert not result.complete
    assert result.failure_codes == ("intent_journal_conflict",)


def test_kill_activation_drains_admitted_normal_write_before_emergency_sweep() -> None:
    adapter = _BlockingNormalWriteAdapter()
    kill_switch = KillSwitch(normal_write_drain_timeout=1.0)
    router = _router(adapter, write_admission=kill_switch.broker_write_admission)
    request_ctx = _request_ctx()
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(
        order,
        request_ctx,
        "dhan",
        account_id="acct-1",
    )
    normal_errors: list[BaseException] = []

    def place_normal_order() -> None:
        try:
            asyncio.run(
                router.place_order(
                    request_ctx,
                    adapter_id="dhan",
                    account_id="acct-1",
                    order=order,
                    safety_ctx=safety_ctx,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            normal_errors.append(exc)

    normal_thread = threading.Thread(target=place_normal_order)
    normal_thread.start()
    assert adapter.normal_write_entered.wait(timeout=1.0)

    kill_results: list[EmergencyDispatchResult] = []
    kill_thread = threading.Thread(
        target=lambda: kill_results.append(
            kill_switch.activate(
                "race test",
                emergency_dispatcher=_dispatcher(lambda: router),
            )
        )
    )
    kill_thread.start()

    assert kill_switch.is_active
    assert kill_thread.is_alive(), "activation returned before an admitted write drained"
    assert adapter.calls == [], "emergency sweep ran before the admitted write completed"
    adapter.release_normal_write.set()
    normal_thread.join(timeout=1.0)
    kill_thread.join(timeout=1.0)

    assert normal_errors == []
    assert not normal_thread.is_alive()
    assert not kill_thread.is_alive()
    assert kill_results[0].complete
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]


def test_normal_context_minted_before_kill_cannot_dispatch_after_sweep() -> None:
    adapter = _BlockingNormalWriteAdapter()
    adapter.release_normal_write.set()
    kill_switch = KillSwitch()
    router = _router(adapter, write_admission=kill_switch.broker_write_admission)
    request_ctx = _request_ctx()
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(
        order,
        request_ctx,
        "dhan",
        account_id="acct-1",
    )

    emergency_result = kill_switch.activate(
        "block delayed normal order",
        emergency_dispatcher=_dispatcher(lambda: router),
    )

    assert emergency_result.complete
    with pytest.raises(SafetyBypassError, match="kill switch"):
        asyncio.run(
            router.place_order(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                order=order,
                safety_ctx=safety_ctx,
            )
        )
    assert adapter.placed == []


def test_l5_refuses_normal_write_before_session_and_generation_admission() -> None:
    adapter = _BlockingNormalWriteAdapter()
    adapter.release_normal_write.set()
    kill_switch = KillSwitch()
    session_calls: list[str] = []

    def session_provider(ctx: RequestContext, adapter_id: str, account_id: str) -> Session:
        session_calls.append(f"{adapter_id}:{account_id}")
        return _session_provider()(ctx, adapter_id, account_id)

    router = BrokerRouter(
        {"dhan": adapter},
        session_provider,
        consume_gate=SafetyGate().consume,
        write_admission=kill_switch.broker_write_admission,
    )
    request_ctx = _request_ctx()
    order = SimpleNamespace(symbol="RELIANCE", quantity=1, exchange="NSE")
    safety_ctx = gate_order(order, request_ctx, "dhan", account_id="acct-1")

    assert kill_switch.activate(
        "refuse delayed normal order",
        emergency_dispatcher=_dispatcher(lambda: router),
    ).complete
    session_calls.clear()
    adapter.calls.clear()

    with pytest.raises(SafetyBypassError, match="kill switch"):
        asyncio.run(
            router.place_order(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                order=order,
                safety_ctx=safety_ctx,
            )
        )

    assert session_calls == []
    assert adapter.placed == []


def test_normal_cancellations_cannot_remove_protective_orders_while_l5_is_latched() -> None:
    adapter = _EmergencyAdapter()
    kill_switch = KillSwitch()
    router = _router(adapter, write_admission=kill_switch.broker_write_admission)
    request_ctx = _request_ctx()

    assert kill_switch.activate(
        "permit exposure reduction",
        emergency_dispatcher=_dispatcher(lambda: router),
    ).complete
    adapter.calls.clear()

    cancel_fingerprint = {"_op": "cancel", "order_id": "OID-1"}
    cancel_ctx = gate_order(
        cancel_fingerprint,
        request_ctx,
        "dhan",
        account_id="acct-1",
    )
    with pytest.raises(SafetyBypassError, match="kill switch"):
        asyncio.run(
            router.cancel_order(
                request_ctx,
                order=cancel_fingerprint,
                order_id="OID-1",
                safety_ctx=cancel_ctx,
                adapter_id="dhan",
                account_id="acct-1",
            )
        )

    forever_payload = {"_op": "cancel_forever", "order_id": "GTT-1"}
    forever_ctx = gate_broker_write(
        "cancel_forever",
        forever_payload,
        request_ctx,
        "dhan",
        account_id="acct-1",
    )
    with pytest.raises(SafetyBypassError, match="kill switch"):
        asyncio.run(
            router.execute_gated(
                request_ctx,
                verb="cancel_forever",
                payload=forever_payload,
                safety_ctx=forever_ctx,
                adapter_id="dhan",
                account_id="acct-1",
            )
        )

    assert adapter.calls == []


def test_overlapping_selector_activations_share_one_inflight_flatten() -> None:
    adapter = _BlockingEmergencyAdapter()
    router = _router(adapter)
    dispatcher = _dispatcher(lambda: router)
    kill_switch = KillSwitch(normal_write_drain_timeout=1.0)
    results: list[EmergencyDispatchResult] = []

    first = threading.Thread(
        target=lambda: results.append(kill_switch.activate("first", emergency_dispatcher=dispatcher))
    )
    second = threading.Thread(
        target=lambda: results.append(kill_switch.activate("second", emergency_dispatcher=dispatcher))
    )
    first.start()
    assert adapter.entered.wait(timeout=1)
    second.start()
    try:
        time.sleep(0.05)
        assert adapter.calls == ["cancel_all_orders"]
    finally:
        adapter.release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(results) == 2
    assert all(result.complete for result in results)
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]


def test_partially_overlapping_activation_dispatches_free_selector_immediately() -> None:
    dhan = _BlockingEmergencyAdapter()
    upstox = _EmergencyAdapter()

    def session_provider(ctx: RequestContext, adapter_id: str, account_id: str) -> Session:
        return Session(
            access_token="token",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
            account_id=account_id,
            adapter_id=adapter_id,
        )

    router = BrokerRouter(
        {"dhan": dhan, "upstox": upstox},
        session_provider,
        consume_gate=SafetyGate().consume,
    )
    first_dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        targets_provider=lambda: (_target_for("dhan", "primary"),),
        run_awaitable=asyncio.run,
    )
    all_dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        targets_provider=lambda: (
            _target_for("dhan", "primary"),
            _target_for("upstox", "secondary"),
        ),
        run_awaitable=asyncio.run,
    )
    kill_switch = KillSwitch(normal_write_drain_timeout=1.0)
    results: list[EmergencyDispatchResult] = []
    first = threading.Thread(
        target=lambda: results.append(kill_switch.activate("dhan only", emergency_dispatcher=first_dispatcher))
    )
    second = threading.Thread(
        target=lambda: results.append(kill_switch.activate("all accounts", emergency_dispatcher=all_dispatcher))
    )

    first.start()
    assert dhan.entered.wait(timeout=1)
    second.start()
    try:
        deadline = time.monotonic() + 0.5
        while len(upstox.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert upstox.calls == ["cancel_all_orders", "exit_all_positions"]
        assert dhan.calls == ["cancel_all_orders"]
    finally:
        dhan.release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert all(result.complete for result in results)
    assert dhan.calls == ["cancel_all_orders", "exit_all_positions"]


def test_overlap_timeout_does_not_outrank_owners_later_success() -> None:
    adapter = _BlockingEmergencyAdapter()
    router = _router(adapter)
    dispatcher = _dispatcher(lambda: router)
    kill_switch = KillSwitch(normal_write_drain_timeout=0.01)
    owner_results: list[EmergencyDispatchResult] = []
    owner = threading.Thread(
        target=lambda: owner_results.append(kill_switch.activate("owner", emergency_dispatcher=dispatcher))
    )
    owner.start()
    assert adapter.entered.wait(timeout=1)

    waiter_result = kill_switch.activate("waiter", emergency_dispatcher=dispatcher)
    assert not waiter_result.complete
    adapter.release.set()
    owner.join(timeout=1)

    assert not owner.is_alive()
    assert owner_results[0].complete
    assert kill_switch.last_emergency_result is not None
    assert kill_switch.last_emergency_result.complete


def test_unexpected_dispatch_failure_retains_selector_reservation_until_merge() -> None:
    target = _target_for("dhan", "primary")

    class FailingPreparedDispatcher:
        def prepare_targets(self):
            return (target,)

        def dispatch_prepared(self, policy, *, reason, targets):
            raise RuntimeError("unexpected dispatcher failure")

    kill_switch = KillSwitch()
    result, owned_selectors, authoritative_selectors = kill_switch._dispatch_coordinated(
        FailingPreparedDispatcher(),
        "failure",
    )
    try:
        assert not result.complete
        assert result.failure_codes == ("dispatch_failed", "dispatch_failed")
        assert owned_selectors == {"dhan:primary"}
        assert authoritative_selectors == owned_selectors
        assert kill_switch._selectors_in_progress == owned_selectors
    finally:
        with kill_switch._condition:
            kill_switch._selectors_in_progress.difference_update(owned_selectors)


def test_malformed_dispatch_result_cannot_leak_selector_reservation() -> None:
    target = _target_for("dhan", "primary")

    class MalformedDispatcher:
        def prepare_targets(self):
            return (target,)

        def dispatch_prepared(self, policy, *, reason, targets):
            result = EmergencyDispatchResult.failed(policy, "malformed", selector=target.request_ctx.selector)
            object.__setattr__(result, "outcomes", (object(),))
            return result

    valid_calls: list[tuple[EmergencyBrokerTarget, ...]] = []

    class ValidDispatcher:
        def prepare_targets(self):
            return (target,)

        def dispatch_prepared(self, policy, *, reason, targets):
            valid_calls.append(targets)
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector=target.request_ctx.selector,
                    )
                    for verb in policy.verbs
                ),
            )

    kill_switch = KillSwitch(normal_write_drain_timeout=0.01)

    first = kill_switch.activate("malformed", emergency_dispatcher=MalformedDispatcher())
    second = kill_switch.activate("retry", emergency_dispatcher=ValidDispatcher())

    assert not first.complete
    assert second.complete
    assert valid_calls == [(target,)]
    assert kill_switch._selectors_in_progress == set()


def test_emergency_reductions_do_not_consume_or_hit_algo_placement_ceiling() -> None:
    from flinttrade_engine.algo_tag_guard import AlgoTagConfig, AlgoTagGuard

    adapter = _EmergencyAdapter()
    adapter.capabilities = SimpleNamespace(algo_tag_required=True)
    guard = AlgoTagGuard(
        {
            "dhan": AlgoTagConfig(algo_id="ALGO-1", max_orders_per_sec=1),
        }
    )
    router = _router(adapter, algo_tag_guard=guard)

    result = _dispatcher(lambda: router).dispatch(
        L5_EMERGENCY_POLICY,
        reason="emergency ceiling bypass",
    )

    assert result.complete
    assert adapter.calls == ["cancel_all_orders", "exit_all_positions"]
    assert guard.usage("dhan", "*") == 0


def test_targeted_retry_cannot_hide_another_selectors_failed_flatten() -> None:
    failed_selector = "dhan:primary"
    successful_selector = "upstox:secondary"

    class _AllTargetsDispatcher:
        def dispatch(self, policy, *, reason):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=selector == successful_selector,
                        failure_code="broker_refused" if selector == failed_selector else "",
                        selector=selector,
                    )
                    for selector in (failed_selector, successful_selector)
                    for verb in policy.verbs
                ),
            )

    class _SuccessfulRetryDispatcher:
        def dispatch(self, policy, *, reason):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector=successful_selector,
                    )
                    for verb in policy.verbs
                ),
            )

    kill_switch = KillSwitch()
    first = kill_switch.activate(
        "all-account flatten",
        emergency_dispatcher=_AllTargetsDispatcher(),
        replace_scope=True,
    )
    retry = kill_switch.activate(
        "retry successful account only",
        emergency_dispatcher=_SuccessfulRetryDispatcher(),
    )

    assert not first.complete
    assert not retry.complete
    assert retry.target_count == 2
    assert retry.completed_target_count == 1
    with pytest.raises(SafetyBypassError, match="incomplete"):
        kill_switch.reset(require_complete=True)
    assert kill_switch.is_active


def test_l5_policy_reaches_openalgo_through_authoritative_planned_writes() -> None:
    class _OpenAlgoClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.orders: list[dict[str, str]] = [
                {"orderid": "OPEN-1", "status": "open"}
            ]
            self.positions: list[dict[str, str]] = [
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "MIS",
                    "quantity": "3",
                }
            ]

        async def orderbook(self) -> list[dict[str, str]]:
            self.calls.append(("orderbook", ""))
            return list(self.orders)

        async def positionbook(self) -> list[dict[str, str]]:
            self.calls.append(("positionbook", ""))
            return list(self.positions)

        async def cancel_order(self, order_id: str, strategy: str = "Flint") -> Any:
            self.calls.append(("cancel_order", order_id))
            self.orders = []
            return SimpleNamespace(status="success", orderid=order_id)

        async def place_order(self, order: Any) -> Any:
            self.calls.append(("place_order", order.strategy))
            self.positions = []
            self.orders = [
                {
                    "orderid": "EXIT-1",
                    "status": "complete",
                }
            ]
            return SimpleNamespace(status="success", orderid="EXIT-1")

        async def cancel_all_orders(self, strategy: str = "Flint") -> Any:
            self.calls.append(("cancel_all_orders", strategy))
            return SimpleNamespace(status="success", message="cancelled")

        async def close_position(self, strategy: str = "Flint") -> Any:
            self.calls.append(("close_position", strategy))
            return SimpleNamespace(status="success", message="closed")

    client = _OpenAlgoClient()
    adapter = OpenAlgoAdapter(default_client=client)

    def session_provider(
        _ctx: RequestContext,
        adapter_id: str,
        account_id: str,
    ) -> Session:
        return Session(
            access_token="",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
            account_id=account_id,
            adapter_id=adapter_id,
            extra={"strategy": "Emergency"},
        )

    router = BrokerRouter(
        {"openalgo": adapter},
        session_provider,
        consume_gate=SafetyGate().consume,
    )
    request_ctx = RequestContext(
        jti="openalgo-emergency-jti",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="openalgo:dhan",
    )
    target = EmergencyBrokerTarget(
        request_ctx=request_ctx,
        adapter_id="openalgo",
        account_id="dhan",
    )

    result = _dispatcher(lambda: router, target_provider=lambda: target).dispatch(
        L5_EMERGENCY_POLICY,
        reason="OpenAlgo bridge emergency",
    )

    assert result.complete
    assert client.calls.count(("cancel_order", "OPEN-1")) == 1
    assert sum(call[0] == "place_order" for call in client.calls) == 1
    assert not {"cancel_all_orders", "close_position"}.intersection(call[0] for call in client.calls)


def test_selector_acl_refusal_never_reaches_adapter() -> None:
    adapter = _EmergencyAdapter()
    router = _router(adapter, allowed_actor="different-operator")

    result = _dispatcher(lambda: router).dispatch(
        L5_EMERGENCY_POLICY,
        reason="unauthorised emergency",
    )

    assert not result.complete
    assert result.failure_codes == ("safety_refused", "safety_refused")
    assert adapter.calls == []


def test_missing_target_fails_closed_without_router_or_default_fallback() -> None:
    router_calls = 0

    def current_router() -> None:
        nonlocal router_calls
        router_calls += 1
        return None

    def missing_target() -> EmergencyBrokerTarget:
        raise SafetyBypassError("no explicit emergency selector")

    result = _dispatcher(current_router, target_provider=missing_target).dispatch(
        L5_EMERGENCY_POLICY,
        reason="target missing",
    )

    assert not result.complete
    assert result.failure_codes == ("target_unavailable", "target_unavailable")
    assert router_calls == 0


def test_revoked_generation_fails_before_token_adapter_dispatch() -> None:
    adapter = _EmergencyAdapter()
    retired_router = _router(adapter)
    assert retired_router.revoke_and_drain(timeout=0.1)

    result = _dispatcher(lambda: retired_router).dispatch(
        L5_EMERGENCY_POLICY,
        reason="stale parent reference",
    )

    assert not result.complete
    assert result.failure_codes == ("safety_refused", "safety_refused")
    assert adapter.calls == []


def test_concurrent_retirement_moves_second_verb_to_current_generation() -> None:
    old_adapter = _BlockingEmergencyAdapter()
    old_router = _router(old_adapter)
    new_adapter = _EmergencyAdapter()
    new_router = _router(new_adapter)
    provider_lock = threading.Lock()
    current = old_router

    def current_router() -> BrokerRouter:
        with provider_lock:
            return current

    results: list[Any] = []
    worker = threading.Thread(
        target=lambda: results.append(
            _dispatcher(current_router).dispatch(
                L5_EMERGENCY_POLICY,
                reason="generation rotation",
            )
        )
    )
    worker.start()
    assert old_adapter.entered.wait(timeout=1.0)

    assert old_router.revoke_and_drain(timeout=0) is False
    with provider_lock:
        current = new_router
    new_adapter.completed_by_account["acct-1"] = {"cancel_all_orders"}
    old_adapter.release.set()

    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert old_router.revoke_and_drain(timeout=0.1) is True
    assert results[0].complete
    assert old_adapter.calls == ["cancel_all_orders"]
    assert new_adapter.calls == ["exit_all_positions"]


def test_concurrent_l5_activations_keep_distinct_parent_targets() -> None:
    """One account's in-flight emergency must not absorb another account's."""
    first_entered = threading.Event()
    release_first = threading.Event()
    second_dispatched = threading.Event()

    class _FirstDispatcher:
        def dispatch(self, policy, *, reason):
            first_entered.set()
            release_first.wait(timeout=1.0)
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs),
            )

    class _SecondDispatcher:
        def dispatch(self, policy, *, reason):
            second_dispatched.set()
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs),
            )

    kill_switch = KillSwitch()
    first = threading.Thread(
        target=lambda: kill_switch.activate(
            "account one",
            emergency_dispatcher=_FirstDispatcher(),
        )
    )
    second = threading.Thread(
        target=lambda: kill_switch.activate(
            "account two",
            emergency_dispatcher=_SecondDispatcher(),
        )
    )

    first.start()
    assert first_entered.wait(timeout=1.0)
    second.start()
    independent = second_dispatched.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert independent, "a concurrent account target was incorrectly coalesced"
    assert not first.is_alive()
    assert not second.is_alive()


def test_reset_rechecks_latest_result_after_inflight_activation_finishes() -> None:
    second_entered = threading.Event()
    release_second = threading.Event()

    class _CompleteDispatcher:
        def dispatch(self, policy, *, reason):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs),
            )

    class _IncompleteDispatcher:
        def dispatch(self, policy, *, reason):
            second_entered.set()
            release_second.wait(timeout=1.0)
            return EmergencyDispatchResult.failed(
                policy,
                "broker_refused",
                attempted=True,
            )

    kill_switch = KillSwitch()
    assert kill_switch.activate("first", emergency_dispatcher=_CompleteDispatcher()).complete
    activation = threading.Thread(
        target=lambda: kill_switch.activate("second", emergency_dispatcher=_IncompleteDispatcher())
    )
    activation.start()
    assert second_entered.wait(timeout=1.0)

    reset_errors: list[BaseException] = []

    def reset_after_dispatch() -> None:
        try:
            kill_switch.reset(require_complete=True)
        except BaseException as exc:  # pragma: no cover - asserted below
            reset_errors.append(exc)

    reset = threading.Thread(target=reset_after_dispatch)
    reset.start()
    assert reset.is_alive()
    release_second.set()
    activation.join(timeout=1.0)
    reset.join(timeout=1.0)

    assert len(reset_errors) == 1
    assert isinstance(reset_errors[0], SafetyBypassError)
    assert "incomplete" in str(reset_errors[0]).lower()
    assert kill_switch.is_active


def test_older_unscoped_failure_cannot_override_newer_full_scope_success() -> None:
    old_entered = threading.Event()
    release_old = threading.Event()

    class _OldFailure:
        def dispatch(self, policy, *, reason):
            old_entered.set()
            release_old.wait(timeout=1)
            return EmergencyDispatchResult.failed(policy, "dispatcher_unavailable")

    class _NewFullSuccess:
        def dispatch(self, policy, *, reason):
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector="dhan:primary",
                    )
                    for verb in policy.verbs
                ),
            )

    kill_switch = KillSwitch()
    old = threading.Thread(target=lambda: kill_switch.activate("old", emergency_dispatcher=_OldFailure()))
    old.start()
    assert old_entered.wait(timeout=1)

    latest = kill_switch.activate(
        "new full scope",
        emergency_dispatcher=_NewFullSuccess(),
        replace_scope=True,
    )
    assert latest.complete
    release_old.set()
    old.join(timeout=1)

    assert not old.is_alive()
    assert kill_switch.last_emergency_result is not None
    assert kill_switch.last_emergency_result.complete
    assert kill_switch.last_emergency_result.target_count == 1


def test_status_is_pending_while_a_new_emergency_dispatch_is_inflight() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _BlockingDispatcher:
        def dispatch(self, policy, *, reason):
            entered.set()
            release.wait(timeout=1)
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs),
            )

    kill_switch = KillSwitch()
    worker = threading.Thread(
        target=lambda: kill_switch.activate(
            "pending status",
            emergency_dispatcher=_BlockingDispatcher(),
        )
    )
    worker.start()
    assert entered.wait(timeout=1)

    pending = kill_switch.last_emergency_result
    assert pending is not None
    assert not pending.complete
    assert pending.failure_codes == ("dispatch_in_progress", "dispatch_in_progress")
    release.set()
    worker.join(timeout=1)


def test_reset_times_out_instead_of_waiting_forever_for_dispatch() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _BlockingDispatcher:
        def dispatch(self, policy, *, reason):
            entered.set()
            release.wait(timeout=1)
            return EmergencyDispatchResult.failed(policy, "broker_refused")

    kill_switch = KillSwitch()
    worker = threading.Thread(
        target=lambda: kill_switch.activate("stuck dispatch", emergency_dispatcher=_BlockingDispatcher())
    )
    worker.start()
    assert entered.wait(timeout=1)

    with pytest.raises(SafetyBypassError, match="still in progress"):
        kill_switch.reset(timeout=0.01)
    assert kill_switch.is_active
    release.set()
    worker.join(timeout=1)


def test_reset_authorises_final_selectors_after_inflight_dispatch_finishes() -> None:
    from flinttrade_engine.safety import KillSwitchResetAuthorisationError

    entered = threading.Event()
    release = threading.Event()

    class BlockingDispatcher:
        def dispatch(self, policy, *, reason):
            entered.set()
            release.wait(timeout=1)
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(
                        verb,
                        succeeded=True,
                        selector="upstox:secondary",
                    )
                    for verb in policy.verbs
                ),
            )

    kill_switch = KillSwitch()
    activation = threading.Thread(
        target=lambda: kill_switch.activate(
            "inflight selector",
            emergency_dispatcher=BlockingDispatcher(),
        )
    )
    activation.start()
    assert entered.wait(timeout=1)
    authorised: list[frozenset[str]] = []

    def authorise(selectors: frozenset[str]) -> bool:
        authorised.append(selectors)
        return False

    release.set()
    with pytest.raises(KillSwitchResetAuthorisationError):
        kill_switch.reset(authorise_selectors=authorise, timeout=1)
    activation.join(timeout=1)

    assert not activation.is_alive()
    assert authorised == [frozenset({"upstox:secondary"})]
    assert kill_switch.is_active
