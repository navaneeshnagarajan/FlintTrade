"""Tests for G6 (T9): safety-gated mirror dispatch through the BrokerRouter.

When a :class:`PositionMirror` is constructed with a ``broker_router`` injected,
each mirrored order must be dispatched through ``gate_order`` ->
``BrokerRouter.place_order`` (account-bound HMAC + ACL + one-shot consume)
rather than the transitional raw OpenAlgo ``httpx`` POST.

These tests assert:

1. ``execute(master_order)`` calls ``router.place_order`` exactly once per
   enabled slave account.
2. Each call resolves to a ``RoutingHint`` with ``adapter_id='openalgo'`` and
   the account's own ``account_id``.
3. The per-account allocated quantity is what reaches the router.
4. NO ``httpx`` client is constructed when a router is present (the httpx
   ``Client`` is monkeypatched to blow up, so any fallback POST would fail the
   test loudly).
5. A ``SafetyBypassError`` raised by the router is captured as
   ``result.error`` (a per-account failure) without crashing the whole mirror.

All tests are unit-level — no live OpenAlgo, no network, no real router.
"""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Order
from flinttrade_ditto.account_manager import BrokerAccount
from flinttrade_ditto.mirror import AllocationMode, PositionMirror
from flinttrade_engine.safety import set_safety_gate_secret


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bind_safety_gate_secret() -> None:
    """Bind a >=32-byte safety-gate HMAC secret so ``gate_order`` can mint.

    Without this every ``SafetyContext.mint`` would raise because no
    process-wide secret is set. The value is a throwaway 32-byte key used only
    in tests (never production).
    """
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")


def _make_account(
    account_id: str = "acc1",
    name: str = "Test",
    host: str = "http://127.0.0.1:5001",
    api_key: str = "test_key",
    weight: float = 1.0,
    enabled: bool = True,
    is_master: bool = False,
) -> BrokerAccount:
    return BrokerAccount(
        account_id=account_id,
        name=name,
        openalgo_host=host,
        api_key=api_key,
        allocation_weight=weight,
        enabled=enabled,
        is_master=is_master,
    )


def _make_order(
    symbol: str = "NIFTY25APR20000CE",
    action: str = "BUY",
    qty: str = "2",
    exchange: str = "NFO",
) -> Order:
    return Order(symbol=symbol, action=action, quantity=qty, exchange=exchange)


class _FakeRouter:
    """Records each ``place_order`` invocation; never touches a network.

    Mirrors the real :meth:`BrokerRouter.place_order` async signature closely
    enough for ``_place_via_router`` to await it: it accepts the positional
    ``request_ctx`` and the ``order`` / ``safety_ctx`` / ``hint`` keyword
    arguments that the mirror passes, records the salient bits, and returns a
    deterministic fake broker order id.
    """

    def __init__(self) -> None:
        # Each entry: (hint.adapter_id, hint.account_id, order.quantity)
        self.calls: list[tuple[str, str, object]] = []
        self.contexts: list[object] = []
        self._counter = 0

    async def place_order(
        self,
        request_ctx,
        *,
        order,
        safety_ctx,
        adapter_id=None,
        account_id=None,
        hint=None,
        routing_key="execution",
    ) -> str:
        self.contexts.append(request_ctx)
        self.calls.append(
            (
                getattr(hint, "adapter_id", None),
                getattr(hint, "account_id", None),
                order.quantity,
            )
        )
        self._counter += 1
        return f"FAKE-BROKER-ORDER-{self._counter}"


class _RefusingRouter(_FakeRouter):
    """A router whose ``place_order`` always refuses with ``SafetyBypassError``."""

    async def place_order(self, request_ctx, **kwargs) -> str:  # type: ignore[override]
        raise SafetyBypassError("acl_denied: ditto not authorised for this selector")


@pytest.fixture
def _explode_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any ``httpx.Client`` construction in mirror.py blow up.

    Proves the gated path never falls back to the raw OpenAlgo POST while a
    router is present — if it did, this would surface as a loud RuntimeError
    rather than a silent network attempt.
    """

    def _boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError(
            "httpx.Client must NOT be used when a broker_router is injected"
        )

    monkeypatch.setattr("flinttrade_ditto.mirror.httpx.Client", _boom)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGatedMirrorDispatch:
    """PositionMirror routes through the safety-gated BrokerRouter (G6/T9)."""

    def test_routes_once_per_enabled_account(self, _explode_httpx: None) -> None:
        """One router call per enabled slave account, EQUAL allocation."""
        router = _FakeRouter()
        accounts = [_make_account("acc_a"), _make_account("acc_b")]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="3"))

        # Exactly two router calls — one per enabled account.
        assert len(router.calls) == 2
        assert result.total_accounts == 2
        assert result.successful == 2
        assert result.failed == 0

    def test_hint_resolves_openalgo_and_account_id(
        self, _explode_httpx: None
    ) -> None:
        """Every call carries hint adapter_id='openalgo' and the account's id."""
        router = _FakeRouter()
        accounts = [_make_account("acc_a"), _make_account("acc_b")]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        mirror.execute(_make_order(qty="3"))

        adapters = {adapter for adapter, _acct, _qty in router.calls}
        accts = {acct for _adapter, acct, _qty in router.calls}
        assert adapters == {"openalgo"}
        assert accts == {"acc_a", "acc_b"}

    def test_per_account_allocated_quantity_reaches_router(
        self, _explode_httpx: None
    ) -> None:
        """The WEIGHTED per-account quantity is exactly what the router sees."""
        router = _FakeRouter()
        # 3:1 weighting → from master qty 4: acc_big≈3, acc_small≈1.
        accounts = [
            _make_account("acc_big", weight=3.0),
            _make_account("acc_small", weight=1.0),
        ]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.WEIGHTED, broker_router=router
        )

        mirror.execute(_make_order(qty="4"))

        qty_by_acct = {acct: qty for _adapter, acct, qty in router.calls}
        assert qty_by_acct["acc_big"] == 3
        assert qty_by_acct["acc_small"] == 1
        # Quantity reaching the router is the per-account int, not the master str.
        assert all(isinstance(q, int) for q in qty_by_acct.values())

    def test_request_context_carries_selector_and_agent_actor(
        self, _explode_httpx: None
    ) -> None:
        """The minted RequestContext binds the openalgo:<acct> selector as agent."""
        router = _FakeRouter()
        accounts = [_make_account("acc_a")]
        mirror = PositionMirror(
            accounts,
            mode=AllocationMode.EQUAL,
            broker_router=router,
            actor_id="ditto",
        )

        mirror.execute(_make_order(qty="2"))

        assert len(router.contexts) == 1
        ctx = router.contexts[0]
        assert ctx.actor_type == "agent"
        assert ctx.actor_id == "ditto"
        assert ctx.selector == "openalgo:acc_a"

    def test_disabled_and_master_accounts_are_not_routed(
        self, _explode_httpx: None
    ) -> None:
        """Disabled accounts and the master are excluded from router dispatch."""
        router = _FakeRouter()
        accounts = [
            _make_account("live_slave", enabled=True),
            _make_account("off_slave", enabled=False),
            _make_account("the_master", is_master=True),
        ]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="2"))

        accts = {acct for _adapter, acct, _qty in router.calls}
        assert accts == {"live_slave"}
        assert result.total_accounts == 1

    def test_no_httpx_when_router_present(self, _explode_httpx: None) -> None:
        """A successful gated run never constructs an httpx client.

        ``_explode_httpx`` makes ``httpx.Client`` raise; reaching success here
        proves the fallback POST path was never taken.
        """
        router = _FakeRouter()
        accounts = [_make_account("acc_a")]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="1"))

        assert result.successful == 1
        assert len(router.calls) == 1
        # The result carries the fake broker order id the router returned.
        assert result.results[0].order_response is not None
        assert result.results[0].order_response.orderid == "FAKE-BROKER-ORDER-1"


class TestGatedMirrorFailureIsolation:
    """A router refusal becomes a per-account error, not a mirror crash."""

    def test_safety_bypass_becomes_account_error(
        self, _explode_httpx: None
    ) -> None:
        """SafetyBypassError from the router surfaces as result.error."""
        router = _RefusingRouter()
        accounts = [_make_account("acc_a")]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="2"))

        assert result.failed == 1
        assert result.successful == 0
        assert len(result.results) == 1
        assert "acl_denied" in result.results[0].error
        assert result.results[0].success is False

    def test_one_account_refused_other_succeeds(
        self, _explode_httpx: None
    ) -> None:
        """A refusal on one account does not block dispatch to the others."""

        class _SelectiveRouter(_FakeRouter):
            async def place_order(  # type: ignore[override]
                self, request_ctx, *, order, safety_ctx, hint=None, **kwargs
            ) -> str:
                if hint is not None and hint.account_id == "bad_acct":
                    raise SafetyBypassError("acl_denied: bad_acct")
                self.calls.append(
                    (hint.adapter_id, hint.account_id, order.quantity)
                )
                return "FAKE-OK"

        router = _SelectiveRouter()
        accounts = [
            _make_account("good_acct"),
            _make_account("bad_acct"),
        ]
        mirror = PositionMirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="2"))

        assert result.successful == 1
        assert result.failed == 1
        errored = {r.account_id for r in result.results if not r.success}
        succeeded = {r.account_id for r in result.results if r.success}
        assert errored == {"bad_acct"}
        assert succeeded == {"good_acct"}
