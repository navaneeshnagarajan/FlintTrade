"""BrokerRouter safety-enforcement tests (broker-adapter-contract §8).

The router must refuse to dispatch a broker write unless the presented
SafetyContext verifies against THIS order / mode / jti / actor / resolved
adapter (contract §8.0) and its one-shot gate has not already been consumed.
"""

from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.local_state_provider import (
    DISPATCH_OUTCOME_UNKNOWN,
    OrderLifecycleLedger,
)
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import (
    EMERGENCY_INTENT_SOURCE,
    SafetyContext,
    set_safety_gate_secret,
)
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


class _FakeAdapter:
    """Minimal adapter that only fires when handed the router token."""

    def __init__(self) -> None:
        self.placed: list[object] = []
        self.modified: list[tuple] = []
        self.cancelled: list[str] = []

    async def place_order(self, session, order, *, _router_token=None):
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.placed.append(order)
        return "BROKER-OID-1"

    async def modify_order(self, session, order_id, changes, *, _router_token=None):
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.modified.append((order_id, changes))
        return None

    async def cancel_order(self, session, order_id, *, _router_token=None):
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.cancelled.append(order_id)
        return None


class _SequencedAdapter(_FakeAdapter):
    def __init__(self, events: list[str], *, place_error: Exception | None = None) -> None:
        super().__init__()
        self._events = events
        self._place_error = place_error

    async def place_order(self, session, order, *, _router_token=None):
        self._events.append("adapter")
        if self._place_error is not None:
            raise self._place_error
        return await super().place_order(session, order, _router_token=_router_token)


class _CancellingAdapter(_FakeAdapter):
    """Raise task cancellation only after the router token reaches the adapter."""

    def __init__(self) -> None:
        super().__init__()
        self.started: list[str] = []

    async def _cancel(self, operation: str, router_token: object | None) -> None:
        if router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.started.append(operation)
        raise asyncio.CancelledError

    async def place_order(self, session, order, *, _router_token=None):
        await self._cancel("place_order", _router_token)

    async def modify_order(self, session, order_id, changes, *, _router_token=None):
        await self._cancel("modify_order", _router_token)

    async def cancel_order(self, session, order_id, *, _router_token=None):
        await self._cancel("cancel_order", _router_token)

    async def place_multi_order(self, session, orders, *, _router_token=None):
        await self._cancel("place_multi_order", _router_token)

    async def place_reducing_order(self, session, order, *, _router_token=None):
        await self._cancel("place_reducing_order", _router_token)

    async def modify_forever(self, session, order_id, changes, *, _router_token=None):
        await self._cancel("modify_forever", _router_token)


class _LifecycleStore:
    def __init__(
        self,
        events: list[str] | None = None,
        *,
        prepare_error: Exception | None = None,
        acknowledge_error: Exception | None = None,
    ) -> None:
        self.events = events if events is not None else []
        self.prepare_error = prepare_error
        self.acknowledge_error = acknowledge_error
        self.critical = False
        self.resolved_attempts: set[str] = set()

    def assert_write_ready(self) -> None:
        self.events.append("ready")
        if self.critical:
            raise RuntimeError("ledger requires reconciliation")

    def prepare_dispatch(self, **kwargs) -> str:
        self.events.append(f"prepare:{kwargs['operation']}")
        if self.prepare_error is not None:
            raise self.prepare_error
        return "ATTEMPT-1"

    def mark_invoked(self, attempt_id: str) -> None:
        assert attempt_id == "ATTEMPT-1"
        self.events.append("invoked")

    def acknowledge(self, attempt_id: str, result) -> None:
        assert attempt_id == "ATTEMPT-1"
        self.events.append(f"acknowledged:{result}")
        if self.acknowledge_error is not None:
            raise self.acknowledge_error

    def mark_failed_before_invoke(self, attempt_id: str, error_kind: str) -> None:
        assert attempt_id == "ATTEMPT-1"
        self.events.append(f"failed-before:{error_kind}")

    def mark_outcome_unknown(self, attempt_id: str, error_kind: str) -> None:
        assert attempt_id == "ATTEMPT-1"
        self.events.append(f"outcome-unknown:{error_kind}")
        self.critical = True

    def mark_health_critical(self, reason: str) -> None:
        self.events.append(f"critical:{reason}")
        self.critical = True

    def is_outcome_resolved(self, attempt_id: str) -> bool:
        return attempt_id in self.resolved_attempts

    def outcome_resolution_binding(self, attempt_id: str) -> dict[str, str] | None:
        if attempt_id not in self.resolved_attempts:
            return None
        return {
            "attempt_id": attempt_id,
            "resolution_id": "RESOLUTION-1",
            "selector": "dhan:acct-1",
            "status": "PENDING_ROUTER_CLEAR",
        }

class _BlockingLimiter:
    """Hold a write after verification so callers can mutate their objects."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def acquire(self, _broker_id: str, _kind: str) -> None:
        self.entered.set()
        await self.release.wait()


def _session(read_only: bool = False) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="dhan",
        read_only_until_at=(datetime.now(tz=timezone.utc).timestamp() + 3600) if read_only else None,
    )


def _order(symbol: str = "RELIANCE") -> object:
    return types.SimpleNamespace(symbol=symbol, quantity=10, side="BUY", exchange="NSE")


def _request_ctx(*, intent_source: str | None = None) -> RequestContext:
    return RequestContext(
        jti="jti-1",
        actor_type="human",
        actor_id="user-1",
        mode="live",
        intent_source=intent_source,
    )


def _router(
    adapter: _FakeAdapter,
    *,
    read_only: bool = False,
    consume_gate=None,
    rate_limiter=None,
    lifecycle_store=None,
) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: _session(read_only=read_only),
        consume_gate=consume_gate,
        rate_limiter=rate_limiter,
        lifecycle_store=lifecycle_store,
    )


def _mint(order, **over) -> SafetyContext:
    kwargs = dict(mode="live", user_jti="jti-1", adapter_id="dhan", account_id="acct-1", actor_type="human")
    kwargs.update(over)
    return SafetyContext.mint(order, **kwargs)


async def test_place_order_dispatches_with_valid_context() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter)
    order = _order()
    ctx = _mint(order)
    result = await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
    )
    assert result == "BROKER-OID-1"
    assert adapter.placed == [order]


async def test_place_order_records_exact_invocation_boundary_and_acknowledgement() -> None:
    events: list[str] = []
    lifecycle = _LifecycleStore(events)
    adapter = _SequencedAdapter(events)
    router = _router(adapter, lifecycle_store=lifecycle)
    order = _order()

    result = await router.place_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        safety_ctx=_mint(order),
    )

    assert result == "BROKER-OID-1"
    assert events == [
        "ready",
        "prepare:place_order",
        "invoked",
        "adapter",
        "acknowledged:BROKER-OID-1",
    ]


async def test_lifecycle_prepare_failure_prevents_adapter_invocation() -> None:
    events: list[str] = []
    lifecycle = _LifecycleStore(events, prepare_error=OSError("disk unavailable"))
    adapter = _SequencedAdapter(events)
    router = _router(adapter, lifecycle_store=lifecycle)
    order = _order()

    with pytest.raises(SafetyBypassError, match="lifecycle ledger"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )

    assert "adapter" not in events


async def test_adapter_exception_after_invocation_is_recorded_as_unknown_outcome() -> None:
    events: list[str] = []
    lifecycle = _LifecycleStore(events)
    adapter = _SequencedAdapter(events, place_error=TimeoutError("response lost"))
    router = _router(adapter, lifecycle_store=lifecycle)
    order = _order()

    with pytest.raises(TimeoutError, match="response lost"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )

    assert events[-1] == "outcome-unknown:TimeoutError"


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
async def test_direct_adapter_cancellation_is_durably_recorded_as_unknown_outcome(
    operation: str,
    tmp_path,
) -> None:
    adapter = _CancellingAdapter()
    lifecycle = OrderLifecycleLedger(ledger_path=tmp_path / "order-lifecycle.sqlite3")
    router = _router(adapter, lifecycle_store=lifecycle)

    if operation == "place_order":
        order = _order()
        dispatch = router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )
    elif operation == "modify_order":
        order = {"_op": "modify", "order_id": "OID-1", "price": "100"}
        dispatch = router.modify_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id="OID-1",
            changes={"price": "100"},
            safety_ctx=_mint(order),
        )
    else:
        order = {"_op": "cancel", "order_id": "OID-1"}
        dispatch = router.cancel_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id="OID-1",
            safety_ctx=_mint(order),
        )

    with pytest.raises(asyncio.CancelledError):
        await dispatch

    assert adapter.started == [operation]
    attempts = lifecycle.list_dispatch_attempts()
    assert len(attempts) == 1
    assert attempts[0]["dispatch_state"] == DISPATCH_OUTCOME_UNKNOWN
    assert attempts[0]["error_kind"] == "CancelledError"


@pytest.mark.parametrize(
    ("verb", "payload", "intent_source"),
    [
        (
            "place_multi_order",
            {"_op": "place_multi_order", "orders": [{"symbol": "RELIANCE", "quantity": 1}]},
            None,
        ),
        (
            "place_reducing_order",
            {"_op": "place_reducing_order", "symbol": "NIFTY", "quantity": 1},
            EMERGENCY_INTENT_SOURCE,
        ),
        (
            "modify_forever",
            {"_op": "modify_forever", "order_id": "GTT-1", "changes": {"price": "100"}},
            None,
        ),
    ],
)
async def test_extended_adapter_cancellation_is_durably_recorded_as_unknown_outcome(
    verb: str,
    payload: dict[str, object],
    intent_source: str | None,
    tmp_path,
) -> None:
    adapter = _CancellingAdapter()
    lifecycle = OrderLifecycleLedger(ledger_path=tmp_path / "order-lifecycle.sqlite3")
    router = _router(adapter, lifecycle_store=lifecycle)
    request_ctx = _request_ctx(intent_source=intent_source)

    with pytest.raises(asyncio.CancelledError):
        await router.execute_gated(
            request_ctx,
            verb=verb,
            payload=payload,
            safety_ctx=_mint(payload, intent_source=intent_source),
            adapter_id="dhan",
            account_id="acct-1",
        )

    assert adapter.started == [verb]
    attempts = lifecycle.list_dispatch_attempts()
    assert len(attempts) == 1
    assert attempts[0]["dispatch_state"] == DISPATCH_OUTCOME_UNKNOWN
    assert attempts[0]["error_kind"] == "CancelledError"


async def test_post_invocation_ledger_failure_returns_ack_but_blocks_next_normal_write() -> None:
    events: list[str] = []
    lifecycle = _LifecycleStore(events, acknowledge_error=OSError("disk full"))
    adapter = _SequencedAdapter(events)
    router = _router(adapter, lifecycle_store=lifecycle)
    order = _order()

    assert await router.place_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        safety_ctx=_mint(order),
    ) == "BROKER-OID-1"

    lifecycle.acknowledge_error = None
    with pytest.raises(SafetyBypassError, match="lifecycle ledger"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )
    assert events.count("adapter") == 1
    assert "outcome-unknown:OSError" in events
    assert "critical:OSError" not in events


async def test_router_clears_only_the_exact_durably_resolved_lifecycle_fault() -> None:
    events: list[str] = []
    lifecycle = _LifecycleStore(events)
    adapter = _SequencedAdapter(events, place_error=TimeoutError("response lost"))
    router = _router(adapter, lifecycle_store=lifecycle)
    order = _order()

    with pytest.raises(TimeoutError, match="response lost"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )

    lifecycle.critical = False
    lifecycle.resolved_attempts.add("ATTEMPT-1")
    with pytest.raises(SafetyBypassError, match="not durably resolved"):
        router.clear_lifecycle_fault(
            "DIFFERENT-ATTEMPT",
            resolution_id="RESOLUTION-1",
            selector="dhan:acct-1",
        )

    adapter._place_error = None
    with pytest.raises(SafetyBypassError, match="requires reconciliation"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order),
        )

    receipt = router.clear_lifecycle_fault(
        "ATTEMPT-1",
        resolution_id="RESOLUTION-1",
        selector="dhan:acct-1",
    )
    assert receipt is not None
    assert router.verify_lifecycle_fault_clear(
        receipt,
        resolution_id="RESOLUTION-1",
        attempt_id="ATTEMPT-1",
        selector="dhan:acct-1",
    )
    assert not router.verify_lifecycle_fault_clear(
        receipt,
        resolution_id="RESOLUTION-1",
        attempt_id="ATTEMPT-1",
        selector="dhan:other",
    )
    assert await router.place_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        safety_ctx=_mint(order),
    ) == "BROKER-OID-1"


async def test_place_order_dispatches_detached_snapshot_after_throttle() -> None:
    adapter = _FakeAdapter()
    limiter = _BlockingLimiter()
    router = _router(adapter, rate_limiter=limiter)
    order = types.SimpleNamespace(
        symbol="RELIANCE",
        quantity=10,
        side="BUY",
        exchange="NSE",
        metadata={"limits": {"price": "100"}},
    )
    ctx = _mint(order)

    dispatch = asyncio.create_task(
        router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=ctx,
        )
    )
    await limiter.entered.wait()
    order.symbol = "TAMPERED"
    order.metadata["limits"]["price"] = "999"
    limiter.release.set()

    assert await dispatch == "BROKER-OID-1"
    dispatched = adapter.placed[0]
    assert dispatched is not order
    assert dispatched.symbol == "RELIANCE"
    assert dispatched.metadata == {"limits": {"price": "100"}}


async def test_rate_limiter_throttle_runs_before_dispatch() -> None:
    """The router throttles BELOW the gate — acquire() runs after verify, before
    the broker call, and can only delay (never bypass) a dispatch."""
    class _SpyLimiter:
        def __init__(self) -> None:
            self.acquired: list[tuple[str, str]] = []

        async def acquire(self, broker_id: str, kind: str) -> None:
            self.acquired.append((broker_id, kind))

    adapter = _FakeAdapter()
    limiter = _SpyLimiter()
    router = BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: _session(),
        rate_limiter=limiter,
    )
    order = _order()
    ctx = _mint(order)
    await router.place_order(_request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx)
    assert limiter.acquired == [("dhan", "order")]
    assert adapter.placed == [order]  # throttle did not block the (gated) dispatch


async def test_place_order_rejects_adapter_mismatch() -> None:
    """A ctx minted for 'dhan' must not fire when the order resolves to 'upstox'."""
    adapter = _FakeAdapter()
    router = BrokerRouter(
        {"dhan": adapter, "upstox": adapter},
        lambda _ctx, _aid, _acct: _session(),
    )
    order = _order()
    ctx = _mint(order, adapter_id="dhan")
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.place_order(
            _request_ctx(), adapter_id="upstox", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_place_order_rejects_consumed_gate() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, consume_gate=lambda _gate_id: False)
    order = _order()
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_place_order_rejects_read_only_session() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, read_only=True)
    order = _order()
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="read-only"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == []


async def test_gate_consumed_exactly_once() -> None:
    """Second dispatch of the same gate_id must fail (one-shot)."""
    adapter = _FakeAdapter()
    consumed: set[str] = set()

    def consume(gate_id: str) -> bool:
        if gate_id in consumed:
            return False
        consumed.add(gate_id)
        return True

    router = _router(adapter, consume_gate=consume)
    order = _order()
    ctx = _mint(order)
    assert await router.place_order(
        _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
    ) == "BROKER-OID-1"
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.place_order(
            _request_ctx(), adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=ctx
        )
    assert adapter.placed == [order]


# ---------------------------------------------------------------------------
# modify_order / cancel_order — same verify-then-consume gate as place_order
# ---------------------------------------------------------------------------


async def test_modify_order_dispatches_with_valid_context() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter)
    order = {"_op": "modify", "order_id": "OID-1", "price": "100"}
    ctx = _mint(order)
    await router.modify_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        order_id="OID-1",
        changes={"price": "100"},
        safety_ctx=ctx,
    )
    assert adapter.modified == [("OID-1", {"price": "100"})]


async def test_modify_order_dispatches_only_signed_detached_values_after_throttle() -> None:
    adapter = _FakeAdapter()
    limiter = _BlockingLimiter()
    router = _router(adapter, rate_limiter=limiter)
    nested = {"levels": [{"price": "100"}]}
    order = {"_op": "modify", "order_id": "OID-1", "metadata": nested}
    changes = {"metadata": nested}
    ctx = _mint(order)

    dispatch = asyncio.create_task(
        router.modify_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id="OID-1",
            changes=changes,
            safety_ctx=ctx,
        )
    )
    await limiter.entered.wait()
    order["order_id"] = "TAMPERED"
    nested["levels"][0]["price"] = "999"
    changes["unsigned"] = True
    limiter.release.set()

    await dispatch
    assert adapter.modified == [
        ("OID-1", {"metadata": {"levels": [{"price": "100"}]}}),
    ]


@pytest.mark.parametrize(
    ("order", "order_id", "changes", "match"),
    [
        ({"_op": "cancel", "order_id": "OID-1", "price": "100"}, "OID-1", {"price": "100"}, "_op"),
        ({"_op": "modify", "order_id": "OID-1", "price": "100"}, "OID-2", {"price": "100"}, "order_id"),
        ({"_op": "modify", "order_id": "OID-1", "price": "100"}, "OID-1", {"price": "999"}, "changes"),
    ],
)
async def test_modify_order_rejects_unsigned_compatibility_values_before_gate_consumption(
    order: dict[str, object],
    order_id: str,
    changes: dict[str, object],
    match: str,
) -> None:
    consumed: list[str] = []
    adapter = _FakeAdapter()
    router = _router(adapter, consume_gate=lambda gate_id: consumed.append(gate_id) or True)
    ctx = _mint(order)

    with pytest.raises(SafetyBypassError, match=match):
        await router.modify_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id=order_id,
            changes=changes,
            safety_ctx=ctx,
        )

    assert consumed == []
    assert adapter.modified == []


async def test_modify_order_rejects_consumed_gate() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, consume_gate=lambda _gate_id: False)
    order = {"_op": "modify", "order_id": "OID-1"}
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="already consumed"):
        await router.modify_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id="OID-1",
            changes={},
            safety_ctx=ctx,
        )
    assert adapter.modified == []


async def test_cancel_order_dispatches_with_valid_context() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter)
    order = {"_op": "cancel", "order_id": "OID-9"}
    ctx = _mint(order)
    await router.cancel_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        order_id="OID-9",
        safety_ctx=ctx,
    )
    assert adapter.cancelled == ["OID-9"]


@pytest.mark.parametrize(
    ("order", "order_id", "match"),
    [
        ({"_op": "modify", "order_id": "OID-9"}, "OID-9", "_op"),
        ({"_op": "cancel", "order_id": "OID-9"}, "OID-8", "order_id"),
        ({"_op": "cancel"}, "", "order_id"),
        ({"_op": "cancel", "order_id": 9}, "9", "order_id"),
        ({"_op": "cancel", "order_id": " OID-9 "}, " OID-9 ", "order_id"),
        ({"_op": "cancel", "order_id": "OID 9"}, "OID 9", "order_id"),
        ({"_op": "cancel", "order_id": "OID\n9"}, "OID\n9", "order_id"),
    ],
)
async def test_cancel_order_rejects_invalid_signed_identity_before_gate_consumption(
    order: dict[str, object],
    order_id: str,
    match: str,
) -> None:
    consumed: list[str] = []
    adapter = _FakeAdapter()
    router = _router(adapter, consume_gate=lambda gate_id: consumed.append(gate_id) or True)
    ctx = _mint(order)

    with pytest.raises(SafetyBypassError, match=match):
        await router.cancel_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id=order_id,
            safety_ctx=ctx,
        )

    assert consumed == []
    assert adapter.cancelled == []


async def test_cancel_order_rejects_read_only_session() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, read_only=True)
    order = {"_op": "cancel", "order_id": "OID-9"}
    ctx = _mint(order)
    with pytest.raises(SafetyBypassError, match="read-only"):
        await router.cancel_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            order_id="OID-9",
            safety_ctx=ctx,
        )
    assert adapter.cancelled == []
