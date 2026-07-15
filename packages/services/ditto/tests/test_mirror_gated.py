"""Tests for G6 (T9): safety-gated mirror dispatch through the BrokerRouter.

When a :class:`PositionMirror` is constructed with a ``broker_router`` injected,
each mirrored order must be dispatched through ``gate_order`` ->
``BrokerRouter.place_order`` (account-bound HMAC + ACL + one-shot consume)
rather than the transitional raw OpenAlgo ``httpx`` POST.

These tests assert:

1. ``execute(master_order)`` calls ``router.place_order`` exactly once per
   enabled slave account.
2. Each call supplies explicit ``adapter_id='openalgo'`` and the account's own
   ``account_id`` so no routing default can redirect the write.
3. The per-account allocated quantity is what reaches the router.
4. NO ``httpx`` client is constructed when a router is present (the httpx
   ``Client`` is monkeypatched to blow up, so any fallback POST would fail the
   test loudly).
5. A ``SafetyBypassError`` raised by the router is captured as
   ``result.error`` (a per-account failure) without crashing the whole mirror.

All tests are unit-level — no live OpenAlgo, no network, no real router.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Order
from flinttrade_ditto.account_manager import BrokerAccount
from flinttrade_ditto.mirror import AllocationMode, MirrorRiskError, PositionMirror
from flinttrade_engine.safety import set_safety_gate_secret
from flinttrade_gateway.log_safety import account_ref


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


@contextmanager
def _allow_complete_admission(_account_id: str, _order: Order):
    """Test-only admission stand-in for dispatch-focused unit tests."""
    lease = SimpleNamespace(
        reserve=lambda _candidate, _positions: object(),
        acknowledge=lambda _reservation, _result: None,
    )
    yield lease, []


def _make_gated_mirror(*args, **kwargs) -> PositionMirror:  # noqa: ANN002, ANN003
    kwargs.setdefault("admit_order", _allow_complete_admission)
    return PositionMirror(*args, **kwargs)


class _FakeRouter:
    """Records each ``place_order`` invocation; never touches a network.

    Mirrors the real :meth:`BrokerRouter.place_order` async signature closely
    enough for ``_place_via_router`` to await it: it accepts the positional
    ``request_ctx`` and the ``order`` / ``safety_ctx`` / explicit target keyword
    arguments that the mirror passes, records the salient bits, and returns a
    deterministic fake broker order id.
    """

    def __init__(self) -> None:
        # Each entry: (adapter_id, account_id, order.quantity)
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
        self.calls.append((adapter_id, account_id, order.quantity))
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
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="3"))

        # Exactly two router calls — one per enabled account.
        assert len(router.calls) == 2
        assert result.total_accounts == 2
        assert result.successful == 2
        assert result.failed == 0

    def test_non_live_operator_mode_fails_closed(self, _explode_httpx: None) -> None:
        """A Practice/Explore operator mode refuses the mirror — no router call.

        The gated dispatch targets a live OpenAlgo account directly (never the
        Practice SandboxEngine), so a non-live mode must not reach the router.
        """
        router = _FakeRouter()
        accounts = [_make_account("acc_a"), _make_account("acc_b")]
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router, trading_mode="practice"
        )

        result = mirror.execute(_make_order(qty="3"))

        assert router.calls == []  # nothing dispatched to a live broker
        assert result.successful == 0
        assert result.failed == 2
        assert all("not 'live'" in (r.error or "") for r in result.results)

    def test_explicit_target_is_openalgo_and_account_id(
        self, _explode_httpx: None
    ) -> None:
        """Every call carries an explicit adapter and account target."""
        router = _FakeRouter()
        accounts = [_make_account("acc_a"), _make_account("acc_b")]
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        mirror.execute(_make_order(qty="3"))

        adapters = {adapter for adapter, _acct, _qty in router.calls}
        accts = {acct for _adapter, acct, _qty in router.calls}
        assert adapters == {"openalgo"}
        assert accts == {"acc_a", "acc_b"}

    def test_uses_injected_account_loop_runner(self, _explode_httpx: None) -> None:
        """Each router coroutine runs through its target account's owner loop."""
        router = _FakeRouter()
        account_ids: list[str] = []

        def run_router_call(account_id: str, awaitable: object) -> object:
            account_ids.append(account_id)
            return asyncio.run(awaitable)  # type: ignore[arg-type]

        mirror = _make_gated_mirror(
            [_make_account("acc_a"), _make_account("acc_b")],
            mode=AllocationMode.EQUAL,
            broker_router=router,
            run_router_call=run_router_call,
        )

        result = mirror.execute(_make_order(qty="2"))

        assert result.successful == 2
        assert sorted(account_ids) == ["acc_a", "acc_b"]

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
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.WEIGHTED, broker_router=router
        )

        mirror.execute(_make_order(qty="4"))

        qty_by_acct = {acct: qty for _adapter, acct, qty in router.calls}
        assert qty_by_acct["acc_big"] == "3"
        assert qty_by_acct["acc_small"] == "1"
        # Preserve the Order model's canonical string representation.
        assert all(isinstance(q, str) for q in qty_by_acct.values())

    def test_request_context_carries_selector_and_agent_actor(
        self, _explode_httpx: None
    ) -> None:
        """The minted RequestContext binds the openalgo:<acct> selector as agent."""
        router = _FakeRouter()
        accounts = [_make_account("acc_a")]
        mirror = _make_gated_mirror(
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

    def test_authenticated_human_actor_is_preserved(self, _explode_httpx: None) -> None:
        """A runtime-starting human remains the signed mirror principal."""
        router = _FakeRouter()
        mirror = _make_gated_mirror(
            [_make_account("acc_a")],
            mode=AllocationMode.EQUAL,
            broker_router=router,
            actor_id="operator-1",
            actor_type="human",
        )

        result = mirror.execute(_make_order(qty="1"))

        assert result.successful == 1
        assert router.contexts[0].actor_type == "human"
        assert router.contexts[0].actor_id == "operator-1"

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
        mirror = _make_gated_mirror(
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
        mirror = _make_gated_mirror(
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

    def test_missing_complete_admission_fails_before_gate_and_router(
        self,
        _explode_httpx: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A router alone is insufficient: complete target state must be admitted."""
        from flinttrade_engine import safety as safety_module

        gate_calls: list[str] = []
        original_gate_order = safety_module.gate_order

        def recording_gate_order(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            gate_calls.append("minted")
            return original_gate_order(*args, **kwargs)

        monkeypatch.setattr(safety_module, "gate_order", recording_gate_order)
        router = _FakeRouter()
        mirror = PositionMirror(
            [_make_account("acc_a")],
            mode=AllocationMode.EQUAL,
            broker_router=router,
        )

        result = mirror.execute(_make_order(qty="1"))

        assert gate_calls == []
        assert router.calls == []
        assert result.failed == 1
        assert "admission" in (result.results[0].error or "").lower()

    def test_rejected_admission_fails_before_gate_and_redacts_detail(
        self,
        _explode_httpx: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unavailable target snapshot cannot mint or expose broker detail."""
        from flinttrade_engine import safety as safety_module

        gate_calls: list[str] = []
        original_gate_order = safety_module.gate_order

        def recording_gate_order(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            gate_calls.append("minted")
            return original_gate_order(*args, **kwargs)

        def reject_admission(_account_id: str, _order: Order) -> None:
            raise RuntimeError("raw broker response with private account detail")

        monkeypatch.setattr(safety_module, "gate_order", recording_gate_order)
        router = _FakeRouter()
        mirror = PositionMirror(
            [_make_account("acc_a")],
            mode=AllocationMode.EQUAL,
            broker_router=router,
            admit_order=reject_admission,
        )

        result = mirror.execute(_make_order(qty="1"))

        assert gate_calls == []
        assert router.calls == []
        assert result.failed == 1
        error = result.results[0].error or ""
        assert "admission" in error.lower()
        assert "private account detail" not in error

    def test_complete_admission_receives_allocated_order_before_gate(
        self,
        _explode_httpx: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Admission is target-scoped and evaluates the allocated child order."""
        from flinttrade_engine import safety as safety_module

        events: list[tuple[str, str, int]] = []
        original_gate_order = safety_module.gate_order

        @contextmanager
        def admit_order(account_id: str, order: Order):
            events.append(("admit", account_id, int(order.quantity)))
            with _allow_complete_admission(account_id, order) as admitted:
                yield admitted

        def recording_gate_order(order: Order, request_ctx, **kwargs):  # noqa: ANN001, ANN003, ANN202
            events.append(("gate", kwargs["account_id"], int(order.quantity)))
            return original_gate_order(order, request_ctx, **kwargs)

        monkeypatch.setattr(safety_module, "gate_order", recording_gate_order)
        router = _FakeRouter()
        mirror = PositionMirror(
            [_make_account("acc_a", weight=3), _make_account("acc_b", weight=1)],
            mode=AllocationMode.WEIGHTED,
            broker_router=router,
            admit_order=admit_order,
        )

        result = mirror.execute(_make_order(qty="4"))

        assert result.successful == 2
        for account_id, quantity in (("acc_a", 3), ("acc_b", 1)):
            assert events.index(("admit", account_id, quantity)) < events.index(
                ("gate", account_id, quantity)
            )

    def test_safety_bypass_becomes_account_error(
        self, _explode_httpx: None
    ) -> None:
        """SafetyBypassError becomes a generic per-account refusal."""
        router = _RefusingRouter()
        accounts = [_make_account("acc_a")]
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="2"))

        assert result.failed == 1
        assert result.successful == 0
        assert len(result.results) == 1
        assert "refused" in result.results[0].error.lower()
        assert "acl_denied" not in result.results[0].error

    def test_target_risk_refusal_is_explicit_and_never_reaches_gate(
        self, _explode_httpx: None
    ) -> None:
        router = _FakeRouter()

        @contextmanager
        def refuse_risk(_account_id: str, _order: Order):
            raise MirrorRiskError("private risk response")
            yield  # pragma: no cover

        mirror = PositionMirror(
            [_make_account("acc_a")],
            mode=AllocationMode.EQUAL,
            broker_router=router,
            admit_order=refuse_risk,
        )

        result = mirror.execute(_make_order(qty="2"))

        assert router.calls == []
        assert result.failed == 1
        assert result.results[0].failure_code == "risk_blocked"
        assert "risk" in result.results[0].error.lower()
        assert "private risk response" not in result.results[0].error

    def test_router_refusal_redacts_account_and_broker_detail_but_keeps_routing_id(
        self,
        _explode_httpx: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Logs and status errors are redacted without changing internal routing IDs."""
        private_account_id = "private-target-7491"
        private_detail = "broker secret rejection payload"

        class _SensitiveRouter(_FakeRouter):
            async def place_order(  # type: ignore[override]
                self,
                request_ctx,
                *,
                order,
                safety_ctx,
                adapter_id=None,
                account_id=None,
                **kwargs,
            ) -> str:
                del request_ctx, order, safety_ctx, adapter_id, kwargs
                raise SafetyBypassError(f"{private_detail}: {account_id}")

        caplog.set_level(logging.WARNING, logger="flinttrade.ditto.mirror")
        mirror = _make_gated_mirror(
            [_make_account(private_account_id)],
            mode=AllocationMode.EQUAL,
            broker_router=_SensitiveRouter(),
        )

        result = mirror.execute(_make_order(qty="1"))

        assert result.failed == 1
        assert result.results[0].account_id == private_account_id
        assert private_account_id not in result.results[0].error
        assert private_detail not in result.results[0].error
        assert private_account_id not in caplog.text
        assert private_detail not in caplog.text
        assert account_ref(private_account_id) in caplog.text

    def test_unexpected_worker_exception_is_redacted_from_result(
        self,
        _explode_httpx: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Executor failures expose neither broker payloads nor account IDs as error text."""
        private_account_id = "private-target-8624"
        private_detail = "unparsed broker response containing a secret"
        mirror = _make_gated_mirror(
            [_make_account(private_account_id)],
            mode=AllocationMode.EQUAL,
            broker_router=_FakeRouter(),
        )

        def fail_dispatch(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError(f"{private_detail}: {private_account_id}")

        monkeypatch.setattr(mirror, "_place_on_account", fail_dispatch)

        result = mirror.execute(_make_order(qty="1"))

        assert result.failed == 1
        assert result.results[0].account_id == private_account_id
        assert private_account_id not in result.results[0].error
        assert private_detail not in result.results[0].error
        assert result.results[0].success is False

    def test_one_account_refused_other_succeeds(
        self, _explode_httpx: None
    ) -> None:
        """A refusal on one account does not block dispatch to the others."""

        class _SelectiveRouter(_FakeRouter):
            async def place_order(  # type: ignore[override]
                self,
                request_ctx,
                *,
                order,
                safety_ctx,
                adapter_id=None,
                account_id=None,
                **kwargs,
            ) -> str:
                if account_id == "bad_acct":
                    raise SafetyBypassError("acl_denied: bad_acct")
                self.calls.append((adapter_id, account_id, order.quantity))
                return "FAKE-OK"

        router = _SelectiveRouter()
        accounts = [
            _make_account("good_acct"),
            _make_account("bad_acct"),
        ]
        mirror = _make_gated_mirror(
            accounts, mode=AllocationMode.EQUAL, broker_router=router
        )

        result = mirror.execute(_make_order(qty="2"))

        assert result.successful == 1
        assert result.failed == 1
        errored = {r.account_id for r in result.results if not r.success}
        succeeded = {r.account_id for r in result.results if r.success}
        assert errored == {"bad_acct"}
        assert succeeded == {"good_acct"}


class TestUngatedFallbackGuard:
    """No router → fail closed, always. The ungated path no longer exists."""

    def test_no_router_fails_closed(self, _explode_httpx: None) -> None:
        """Without a broker_router, no order is placed — ever.

        ``_explode_httpx`` would raise if any raw POST were reached; the guard
        returns first, so each account fails with the no-router message.
        """
        accounts = [_make_account("acc_a"), _make_account("acc_b")]
        mirror = PositionMirror(accounts, mode=AllocationMode.EQUAL)  # no router

        result = mirror.execute(_make_order(qty="2"))

        assert result.total_accounts == 2
        assert result.successful == 0
        assert result.failed == 2
        assert all("ungated" in (r.error or "").lower() for r in result.results)

    def test_ungated_optin_no_longer_exists(self) -> None:
        """The transitional ``allow_ungated_fallback`` escape hatch was retired
        (contract §8.1) — constructing with it must fail, so no caller can ever
        re-enable a raw, ungated OpenAlgo forward."""
        with pytest.raises(TypeError):
            PositionMirror(
                [_make_account("acc_a")],
                mode=AllocationMode.EQUAL,
                allow_ungated_fallback=True,  # type: ignore[call-arg]
            )
