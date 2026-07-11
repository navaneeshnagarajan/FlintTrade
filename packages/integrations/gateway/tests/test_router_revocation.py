"""BrokerRouter generation revocation and write-drain tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import gate_broker_write, gate_order, set_safety_gate_secret
from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _ROUTER_TOKEN
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


def _request_ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _session(_ctx: RequestContext, adapter_id: str, account_id: str) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id=account_id,
        adapter_id=adapter_id,
    )


def _order(quantity: str = "1") -> Order:
    return Order(symbol="RELIANCE", action="BUY", exchange="NSE", quantity=quantity)


class _RecordingAdapter:
    """Token-guarded adapter that records every write reaching dispatch."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    @staticmethod
    def _require_router(token: object | None) -> None:
        if token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")

    async def place_order(self, session: Session, order: Order, *, _router_token: object = None) -> str:
        self._require_router(_router_token)
        self.calls.append(("place", order))
        return "OID-1"

    async def modify_order(
        self,
        session: Session,
        order_id: str,
        changes: dict[str, Any],
        *,
        _router_token: object = None,
    ) -> None:
        self._require_router(_router_token)
        self.calls.append(("modify", order_id, changes))

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        _router_token: object = None,
    ) -> None:
        self._require_router(_router_token)
        self.calls.append(("cancel", order_id))

    async def cancel_all_orders(self, session: Session, *, _router_token: object = None) -> None:
        self._require_router(_router_token)
        self.calls.append(("cancel_all_orders",))


class _BlockingAdapter(_RecordingAdapter):
    """Holds one adapter dispatch open while another thread revokes the router."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def place_order(self, session: Session, order: Order, *, _router_token: object = None) -> str:
        self._require_router(_router_token)
        self.calls.append(("place", order))
        self.entered.set()
        await self.release.wait()
        return "OID-BLOCKED"


class _RaisingAdapter(_RecordingAdapter):
    """Raises from each adapter verb to exercise admission cleanup."""

    @staticmethod
    def _raise() -> None:
        raise RuntimeError("adapter failed")

    async def place_order(self, session: Session, order: Order, *, _router_token: object = None) -> str:
        self._require_router(_router_token)
        self._raise()

    async def modify_order(
        self,
        session: Session,
        order_id: str,
        changes: dict[str, Any],
        *,
        _router_token: object = None,
    ) -> None:
        self._require_router(_router_token)
        self._raise()

    async def cancel_order(
        self,
        session: Session,
        order_id: str,
        *,
        _router_token: object = None,
    ) -> None:
        self._require_router(_router_token)
        self._raise()

    async def cancel_all_orders(self, session: Session, *, _router_token: object = None) -> None:
        self._require_router(_router_token)
        self._raise()


def _router(adapter: object) -> BrokerRouter:
    return BrokerRouter({"dhan": adapter}, _session)


async def _place(router: BrokerRouter, order: Order) -> Any:
    return await router.place_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        safety_ctx=gate_order(order, _request_ctx(), "dhan", account_id="acct-1"),
    )


async def test_revoked_stale_router_fails_closed_before_adapter_dispatch() -> None:
    """A reference retained across router replacement cannot keep writing."""
    stale_adapter = _RecordingAdapter()
    stale_router = _router(stale_adapter)
    replacement_router = _router(_RecordingAdapter())

    assert stale_router.revoke_and_drain(timeout=0.1) is True
    assert replacement_router is not stale_router

    with pytest.raises(SafetyBypassError, match="revoked"):
        await _place(stale_router, _order())
    assert stale_adapter.calls == []


async def test_revoke_blocks_new_writes_and_boundedly_drains_an_admitted_write() -> None:
    adapter = _BlockingAdapter()
    router = _router(adapter)
    admitted_write = asyncio.create_task(_place(router, _order()))
    await adapter.entered.wait()

    # The adapter call is already admitted, so a zero-timeout revoke reports
    # that it did not drain while atomically closing admission to later calls.
    assert router.revoke_and_drain(timeout=0) is False
    with pytest.raises(SafetyBypassError, match="revoked"):
        await _place(router, _order("2"))

    waiter = asyncio.create_task(asyncio.to_thread(router.revoke_and_drain, timeout=1.0))
    await asyncio.sleep(0.02)
    assert waiter.done() is False

    adapter.release.set()
    assert await admitted_write == "OID-BLOCKED"
    assert await waiter is True
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("write_kind", ["place", "modify", "cancel", "extended"])
async def test_every_failed_write_releases_its_admission(write_kind: str) -> None:
    adapter = _RaisingAdapter()
    router = _router(adapter)
    request_ctx = _request_ctx()

    with pytest.raises(RuntimeError, match="adapter failed"):
        if write_kind == "place":
            order = _order()
            await router.place_order(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                order=order,
                safety_ctx=gate_order(order, request_ctx, "dhan", account_id="acct-1"),
            )
        elif write_kind == "modify":
            payload = {"_op": "modify", "order_id": "OID-1", "price": "101"}
            await router.modify_order(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                order=payload,
                order_id="OID-1",
                changes={"price": "101"},
                safety_ctx=gate_order(payload, request_ctx, "dhan", account_id="acct-1"),
            )
        elif write_kind == "cancel":
            payload = {"_op": "cancel", "order_id": "OID-1"}
            await router.cancel_order(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                order=payload,
                order_id="OID-1",
                safety_ctx=gate_order(payload, request_ctx, "dhan", account_id="acct-1"),
            )
        else:
            payload = {"_op": "cancel_all_orders"}
            await router.execute_gated(
                request_ctx,
                adapter_id="dhan",
                account_id="acct-1",
                verb="cancel_all_orders",
                payload=payload,
                safety_ctx=gate_broker_write(
                    "cancel_all_orders", payload, request_ctx, "dhan", account_id="acct-1"
                ),
            )

    assert router.revoke_and_drain(timeout=0) is True
