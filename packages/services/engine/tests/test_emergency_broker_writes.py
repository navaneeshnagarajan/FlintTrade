"""Emergency broker writes stay inside the selector-bound gated router path."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    EmergencyBrokerTarget,
    EmergencyDispatchResult,
    EmergencyVerbOutcome,
    GatedEmergencyBrokerDispatcher,
    KillSwitch,
    L5_EMERGENCY_POLICY,
    SafetyGate,
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

    @staticmethod
    def _require_router(token: object | None) -> None:
        if token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write called without BrokerRouter token")

    async def cancel_all_orders(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, str]:
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        return {"status": "ok"}

    async def exit_all_positions(
        self,
        session: Session,
        *,
        _router_token: object | None = None,
    ) -> dict[str, str]:
        self._require_router(_router_token)
        self.calls.append("exit_all_positions")
        return {"status": "ok"}


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
    ) -> dict[str, str]:
        self._require_router(_router_token)
        self.calls.append("cancel_all_orders")
        self.entered.set()
        await asyncio.to_thread(self.release.wait)
        return {"status": "ok"}


def _router(adapter: Any, *, allowed_actor: str = "operator") -> BrokerRouter:
    gate = SafetyGate()
    return BrokerRouter(
        {"dhan": adapter},
        _session_provider(allowed_actor),
        consume_gate=gate.consume,
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
    assert provider_calls == 2, "each verb must resolve the current router generation"


def test_l5_policy_reaches_real_openalgo_bridge_sweep_methods() -> None:
    class _OpenAlgoClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

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
    assert client.calls == [
        ("cancel_all_orders", "Emergency"),
        ("close_position", "Emergency"),
    ]


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
                outcomes=tuple(
                    EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs
                ),
            )

    class _SecondDispatcher:
        def dispatch(self, policy, *, reason):
            second_dispatched.set()
            return EmergencyDispatchResult(
                policy=policy,
                outcomes=tuple(
                    EmergencyVerbOutcome(verb, succeeded=True) for verb in policy.verbs
                ),
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
