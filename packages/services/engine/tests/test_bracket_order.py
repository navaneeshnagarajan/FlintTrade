"""Tests for ``flinttrade_engine.bracket_order`` — the gated-dispatcher contract.

The re-architected service holds NO broker/OpenAlgo client: every leg write
goes through injected ``place_leg``/``cancel_leg`` dispatchers bound to a
:class:`BracketPrincipal` (SafetySystem L1–L5 → ``gate_order`` →
``BrokerRouter`` in production). These tests use recording fakes for the
dispatchers, so no live broker is required, and they pin the fail-closed
behaviour: without a dispatcher or principal the service refuses honestly
instead of inventing simulated order ids.

OCO honesty is also pinned: a ``stoploss`` + ``target`` pair and
``trailing_sl`` are refused at placement because no fill monitor exists yet.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.models import Order, PriceType
from flinttrade_engine.bracket_order import (
    BracketOrderError,
    BracketOrderService,
    BracketPrincipal,
    build_gated_leg_dispatchers,
)
from flinttrade_engine.safety import SafetyConfig, SafetySystem

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Recording dispatcher fakes + helpers
# ---------------------------------------------------------------------------


PRINCIPAL = BracketPrincipal(actor_id="operator", jti="jti-001")


def test_gated_leg_refuses_unvalidated_safety_runtime_before_broker_reads() -> None:
    app = Flask("bracket-safety-readiness")
    app.config.update(
        BROKER_ROUTER=object(),
        SAFETY=SafetySystem(),
        SAFETY_CONFIG_READY=False,
    )
    place_leg, _cancel_leg = build_gated_leg_dispatchers(app)
    order = Order(
        symbol="RELIANCE",
        action="BUY",
        exchange="NSE",
        quantity="1",
    )

    with pytest.raises(BracketOrderError, match="safety configuration"):
        place_leg(order, PRINCIPAL)


def test_gated_leg_checks_prospective_greeks_before_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import l2_state

    class _BlockingSafety:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def check_order(self, _order: Order, **kwargs: object) -> list[object]:
            self.calls.append(kwargs)
            return [SimpleNamespace(
                passed=False,
                layer="L3_PORTFOLIO",
                reason="prospective delta exceeds limit",
            )]

    state = SimpleNamespace(
        positions=[],
        used_margin=0.0,
        total_balance=100000.0,
        daily_pnl=0.0,
        starting_capital=100000.0,
        net_delta=0.0,
        net_vega=0.0,
        ltp_for=lambda _order: None,
        admission_for=lambda _index: SimpleNamespace(
            positions=[],
            used_margin=0.0,
            net_delta=750.0,
            net_vega=12000.0,
        ),
    )

    async def _prospective_state(*_args: object, **_kwargs: object) -> object:
        return state

    monkeypatch.setattr(l2_state, "gather_safety_state", _prospective_state)
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    recorder = _BlockingSafety()
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    safety.check_order = recorder.check_order
    app = Flask("bracket-prospective-greeks")
    app.config.update(
        BROKER_ROUTER=router,
        SAFETY=safety,
        SAFETY_CONFIG_READY=True,
    )
    place_leg, _cancel_leg = build_gated_leg_dispatchers(app)
    order = Order(symbol="NIFTY", action="BUY", exchange="NFO", quantity="1")

    with pytest.raises(BracketOrderError, match="L3_PORTFOLIO"):
        place_leg(order, PRINCIPAL)

    assert recorder.calls[0]["net_delta"] == 750.0
    assert recorder.calls[0]["net_vega"] == 12000.0
    router.place_order.assert_not_called()


class RecordingPlaceLeg:
    """Fake gated placement dispatcher — records calls and returns order ids.

    Attributes:
        calls: Every ``(order, principal)`` pair the service dispatched.
    """

    def __init__(self, fail_on_call: set[int] | None = None) -> None:
        self.calls: list[tuple[Order, BracketPrincipal]] = []
        self._fail_on_call = fail_on_call or set()

    def __call__(self, order: Order, principal: BracketPrincipal) -> str:
        self.calls.append((order, principal))
        n = len(self.calls)
        if n in self._fail_on_call:
            raise BracketOrderError(f"leg {n} refused by the safety gate")
        return f"OID-{n}"


class RecordingCancelLeg:
    """Fake gated cancel dispatcher — records calls, optionally failing some ids.

    Attributes:
        calls: Every ``(order_id, principal)`` pair the service dispatched.
    """

    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.calls: list[tuple[str, BracketPrincipal]] = []
        self._fail_ids = fail_ids or set()

    def __call__(self, order_id: str, principal: BracketPrincipal) -> None:
        self.calls.append((order_id, principal))
        if order_id in self._fail_ids:
            raise BracketOrderError(f"cancel of {order_id} refused")


def _entry(
    symbol: str = "NIFTY25APRFUT",
    exchange: str = "NFO",
    action: str = "BUY",
    quantity: int = 50,
    price: float = 0,
) -> dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "quantity": quantity,
        "price": price,
    }


def _svc(
    fail_on_call: set[int] | None = None,
    fail_cancel_ids: set[str] | None = None,
) -> tuple[BracketOrderService, RecordingPlaceLeg, RecordingCancelLeg]:
    """Return a service wired with recording fakes for both gated dispatchers."""
    place_leg = RecordingPlaceLeg(fail_on_call=fail_on_call)
    cancel_leg = RecordingCancelLeg(fail_ids=fail_cancel_ids)
    return BracketOrderService(place_leg=place_leg, cancel_leg=cancel_leg), place_leg, cancel_leg


# ---------------------------------------------------------------------------
# Fail-closed refusals — no dispatcher / no principal
# ---------------------------------------------------------------------------


class TestFailClosed:
    """The service refuses honestly instead of simulating broker writes."""

    def test_place_without_dispatcher_refuses(self):
        """A bare service (pre-gate construction) must not place anything."""
        svc = BracketOrderService()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert not result.success
        assert result.bracket is None
        assert "gated order path" in result.message
        assert "dispatcher" in result.error

    def test_place_without_principal_refuses(self):
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0)
        assert not result.success
        assert result.bracket is None
        assert "principal" in result.message
        assert place_leg.calls == []

    def test_dispatcher_refusal_precedes_validation(self):
        """Even an invalid entry gets the dispatcher refusal first — nothing leaks."""
        svc = BracketOrderService()
        result = svc.place_bracket(entry={"symbol": ""}, stoploss=22000.0, principal=PRINCIPAL)
        assert not result.success
        assert result.bracket is None
        assert "dispatcher" in result.error

    def test_result_to_dict_on_refusal(self):
        """BracketResult serialises with a None bracket on refusal."""
        svc = BracketOrderService()
        d = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).to_dict()
        assert d["success"] is False
        assert d["bracket"] is None
        assert d["message"]
        assert d["error"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Parameter validation rejects malformed inputs before any order is sent."""

    def test_missing_symbol_fails(self):
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "symbol": ""}, stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "symbol" in result.error
        assert place_leg.calls == []

    def test_missing_exchange_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "exchange": ""}, stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "exchange" in result.error

    def test_invalid_action_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "action": "HOLD"}, stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "BUY or SELL" in result.error

    def test_zero_quantity_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "quantity": 0}, stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "quantity" in result.error

    def test_non_integer_quantity_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "quantity": "fifty"}, stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "quantity" in result.error

    def test_zero_stoploss_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=0.0, principal=PRINCIPAL)
        assert not result.success
        assert "stoploss" in result.error

    def test_zero_target_fails(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), target=0.0, principal=PRINCIPAL)
        assert not result.success
        assert "target" in result.error

    def test_stoploss_and_target_together_refused(self):
        """A true OCO pair is refused — no fill monitor to cancel the sibling leg."""
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "OCO" in result.error
        assert place_leg.calls == []

    def test_no_exit_leg_refused(self):
        """A bracket needs exactly one protective exit leg."""
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), principal=PRINCIPAL)
        assert not result.success
        assert "exactly one" in result.error

    def test_trailing_sl_refused(self):
        """trailing_sl is refused at placement — nothing exists to trail the stop."""
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, trailing_sl=25.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "trailing_sl" in result.error
        assert place_leg.calls == []

    def test_negative_trailing_sl_refused(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, trailing_sl=-10.0, principal=PRINCIPAL
        )
        assert not result.success
        assert "trailing_sl" in result.error

    def test_validation_failure_dispatches_nothing(self):
        svc, place_leg, cancel_leg = _svc()
        svc.place_bracket(entry={**_entry(), "action": "HOLD"}, stoploss=1.0, principal=PRINCIPAL)
        assert place_leg.calls == []
        assert cancel_leg.calls == []


# ---------------------------------------------------------------------------
# Placement through the gated dispatcher
# ---------------------------------------------------------------------------


class TestPlaceBracket:
    """place_bracket dispatches every leg through the injected gated callable."""

    def test_success_returns_bracket(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.success
        assert result.bracket is not None

    def test_bracket_id_is_set(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.bracket_id  # non-empty UUID string

    def test_both_legs_dispatched_with_principal(self):
        svc, place_leg, _ = _svc()
        svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert len(place_leg.calls) == 2
        assert all(principal is PRINCIPAL for _, principal in place_leg.calls)

    def test_entry_leg_order_fields(self):
        svc, place_leg, _ = _svc()
        svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        entry_order, _ = place_leg.calls[0]
        assert entry_order.symbol == "NIFTY25APRFUT"
        assert entry_order.action == "BUY"
        assert entry_order.exchange == "NFO"
        assert entry_order.pricetype == PriceType.MARKET  # price 0 → MARKET
        assert entry_order.quantity == "50"

    def test_stoploss_exit_leg_is_sl_order(self):
        """The SL exit leg is an SL-type order at the stop price, opposite side."""
        svc, place_leg, _ = _svc()
        svc.place_bracket(entry=_entry(action="BUY"), stoploss=22000.0, principal=PRINCIPAL)
        exit_order, _ = place_leg.calls[1]
        assert exit_order.action == "SELL"
        assert exit_order.pricetype == PriceType.SL
        assert exit_order.price == "22000.0"
        assert exit_order.trigger_price == "22000.0"

    def test_target_exit_leg_is_limit_order(self):
        svc, place_leg, _ = _svc()
        svc.place_bracket(entry=_entry(action="BUY"), target=22500.0, principal=PRINCIPAL)
        exit_order, _ = place_leg.calls[1]
        assert exit_order.action == "SELL"
        assert exit_order.pricetype == PriceType.LIMIT
        assert exit_order.price == "22500.0"

    def test_sell_entry_produces_buy_exit_leg(self):
        """SELL entry should produce a BUY protective exit leg."""
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(entry=_entry(action="SELL"), stoploss=22600.0, principal=PRINCIPAL)
        assert result.success
        assert result.bracket.action == "SELL"
        exit_order, _ = place_leg.calls[1]
        assert exit_order.action == "BUY"

    def test_stoploss_bracket_order_ids(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        b = result.bracket
        assert b.entry_order_id == "OID-1"
        assert b.sl_order_id == "OID-2"
        assert b.target_order_id is None
        assert b.stoploss == 22000.0
        assert b.target is None

    def test_target_bracket_order_ids(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), target=22500.0, principal=PRINCIPAL)
        b = result.bracket
        assert b.entry_order_id == "OID-1"
        assert b.target_order_id == "OID-2"
        assert b.sl_order_id is None
        assert b.target == 22500.0
        assert b.stoploss is None

    def test_bracket_status_active_when_both_legs_placed(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.status == "active"

    def test_bracket_is_in_active_list(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        active = svc.get_active_brackets()
        assert result.bracket.bracket_id in [b.bracket_id for b in active]

    def test_trailing_sl_always_none_on_bracket(self):
        """A placed bracket never carries a trailing stop (refused at placement)."""
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.trailing_sl is None

    def test_limit_entry_recorded_as_limit(self):
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL)
        entry_order, _ = place_leg.calls[0]
        assert entry_order.pricetype == PriceType.LIMIT
        assert result.bracket.entry_pricetype == "LIMIT"
        assert result.bracket.entry_price == 22100.0

    def test_broker_target_recorded_from_principal(self):
        """The bracket remembers the selector its legs were placed on."""
        svc, _, _ = _svc()
        principal = BracketPrincipal(
            actor_id="operator", jti="jti-9", adapter_id="dhan", account_id="acct-1"
        )
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=principal)
        assert result.bracket.adapter_id == "dhan"
        assert result.bracket.account_id == "acct-1"

    def test_strategy_and_product_defaults(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.strategy == "Flint"
        assert result.bracket.product == "MIS"

    def test_strategy_and_product_overrides(self):
        svc, place_leg, _ = _svc()
        entry = {**_entry(), "strategy": "Wheel", "product": "NRML"}
        result = svc.place_bracket(entry=entry, stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.strategy == "Wheel"
        assert result.bracket.product == "NRML"
        entry_order, _ = place_leg.calls[0]
        assert entry_order.strategy == "Wheel"


# ---------------------------------------------------------------------------
# Entry-leg failures
# ---------------------------------------------------------------------------


class TestEntryLegFailure:
    """A failed entry leg leaves NOTHING registered — no phantom brackets."""

    def test_entry_dispatch_failure_returns_error(self):
        svc, place_leg, _ = _svc(fail_on_call={1})
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert not result.success
        assert result.bracket is None
        assert result.message == "Entry order placement failed"
        assert "refused by the safety gate" in result.error
        assert len(place_leg.calls) == 1  # exit leg never attempted

    def test_entry_dispatch_failure_registers_nothing(self):
        svc, _, _ = _svc(fail_on_call={1})
        svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert svc.get_active_brackets() == []

    def test_entry_model_build_failure_dispatches_nothing(self):
        """An unknown exchange fails the Order model build before any dispatch."""
        svc, place_leg, _ = _svc()
        result = svc.place_bracket(
            entry=_entry(exchange="NARNIA"), stoploss=22000.0, principal=PRINCIPAL
        )
        assert not result.success
        assert result.bracket is None
        assert result.message == "Failed to build entry order model"
        assert place_leg.calls == []


# ---------------------------------------------------------------------------
# Exit-leg failures — partial brackets stay visible
# ---------------------------------------------------------------------------


class TestExitLegFailure:
    """A failed exit leg yields an honest FAILURE with a visible partial bracket."""

    def test_exit_failure_is_reported_as_failure(self):
        svc, _, _ = _svc(fail_on_call={2})
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert not result.success
        assert "UNPROTECTED" in result.message
        assert "refused by the safety gate" in result.error

    def test_exit_failure_registers_partial_bracket(self):
        svc, _, _ = _svc(fail_on_call={2})
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        b = result.bracket
        assert b is not None
        assert b.status == "partial"
        assert b.entry_order_id == "OID-1"
        assert b.sl_order_id is None
        assert b.target_order_id is None

    def test_partial_bracket_stays_in_active_list(self):
        """The unprotected position must remain visible for operator action."""
        svc, _, _ = _svc(fail_on_call={2})
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        assert result.bracket.bracket_id in [b.bracket_id for b in svc.get_active_brackets()]


# ---------------------------------------------------------------------------
# Modify bracket — refused until a gated modify verb exists
# ---------------------------------------------------------------------------


class TestModifyBracket:
    """modify_bracket refuses totally — a local-only update would lie to the UI."""

    def test_modify_sl_refused(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        result = svc.modify_bracket(bid, new_sl=21900.0)
        assert not result.success
        assert "not supported" in result.message
        assert svc.get_bracket(bid).stoploss == 22000.0  # registry untouched

    def test_modify_target_refused(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), target=22500.0, principal=PRINCIPAL).bracket.bracket_id
        result = svc.modify_bracket(bid, new_target=22700.0)
        assert not result.success
        assert svc.get_bracket(bid).target == 22500.0

    def test_modify_returns_existing_bracket_state(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        result = svc.modify_bracket(bid, new_sl=21900.0)
        assert result.bracket is not None
        assert result.bracket.bracket_id == bid

    def test_modify_unknown_bracket_fails(self):
        svc, _, _ = _svc()
        result = svc.modify_bracket("nonexistent-id", new_sl=21000.0)
        assert not result.success
        assert "not found" in result.message.lower()

    def test_modify_cancelled_bracket_fails(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        svc.cancel_bracket(bid, principal=PRINCIPAL)
        result = svc.modify_bracket(bid, new_sl=21000.0)
        assert not result.success

    def test_modify_with_no_fields_fails(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        result = svc.modify_bracket(bid)
        assert not result.success


# ---------------------------------------------------------------------------
# Cancel bracket — gated cancel verb, best-effort per leg
# ---------------------------------------------------------------------------


class TestCancelBracket:
    def test_cancel_active_bracket(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert svc.get_bracket(bid).status == "cancelled"

    def test_market_entry_leg_is_not_broker_cancelled(self):
        """A MARKET entry filled at placement — only the exit leg is swept."""
        svc, _, cancel_leg = _svc()
        bid = svc.place_bracket(entry=_entry(price=0), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert [order_id for order_id, _ in cancel_leg.calls] == ["OID-2"]

    def test_limit_entry_leg_is_swept_on_cancel(self):
        """A resting LIMIT entry is cancelled alongside the exit leg."""
        svc, _, cancel_leg = _svc()
        bid = svc.place_bracket(
            entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL
        ).bracket.bracket_id
        svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert [order_id for order_id, _ in cancel_leg.calls] == ["OID-1", "OID-2"]

    def test_cancel_rebinds_principal_to_placement_selector(self):
        """Cancel targets the selector the legs live on, never the caller's target."""
        svc, _, cancel_leg = _svc()
        placement = BracketPrincipal(
            actor_id="operator", jti="jti-1", adapter_id="dhan", account_id="acct-1"
        )
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=placement).bracket.bracket_id
        caller = BracketPrincipal(
            actor_id="operator", jti="jti-2", adapter_id="openalgo", account_id="default"
        )
        svc.cancel_bracket(bid, principal=caller)
        _, bound = cancel_leg.calls[0]
        assert bound.adapter_id == "dhan"
        assert bound.account_id == "acct-1"
        assert bound.actor_id == "operator"
        assert bound.jti == "jti-2"

    def test_cancelled_bracket_not_in_active_list(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert bid not in [b.bracket_id for b in svc.get_active_brackets()]

    def test_cancel_unknown_bracket_returns_false(self):
        svc, _, cancel_leg = _svc()
        assert not svc.cancel_bracket("does-not-exist", principal=PRINCIPAL)
        assert cancel_leg.calls == []

    def test_cancel_already_cancelled_returns_false(self):
        svc, _, cancel_leg = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        svc.cancel_bracket(bid, principal=PRINCIPAL)
        first_sweep = len(cancel_leg.calls)
        assert not svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert len(cancel_leg.calls) == first_sweep  # no re-dispatch

    def test_cancel_without_dispatcher_fails_closed(self):
        """Legs resting at the broker + no gated cancel path → refuse loudly."""
        place_leg = RecordingPlaceLeg()
        svc = BracketOrderService(place_leg=place_leg, cancel_leg=None)
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        with pytest.raises(BracketOrderError):
            svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert svc.get_bracket(bid).status == "active"  # never lies about cancelled

    def test_cancel_without_principal_fails_closed(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        with pytest.raises(BracketOrderError):
            svc.cancel_bracket(bid)
        assert svc.get_bracket(bid).status == "active"

    def test_cancel_is_best_effort_per_leg(self):
        """A leg that fails to cancel is logged; the remaining legs are still swept."""
        svc, _, cancel_leg = _svc(fail_cancel_ids={"OID-1"})
        bid = svc.place_bracket(
            entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL
        ).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert [order_id for order_id, _ in cancel_leg.calls] == ["OID-1", "OID-2"]
        assert svc.get_bracket(bid).status == "cancelled"

    def test_cancel_partial_market_bracket_needs_no_dispatcher(self):
        """A partial bracket with a MARKET entry has no resting legs to sweep."""
        place_leg = RecordingPlaceLeg(fail_on_call={2})
        svc = BracketOrderService(place_leg=place_leg, cancel_leg=None)
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=None)
        assert svc.get_bracket(bid).status == "cancelled"

    def test_cancel_fails_closed_when_every_leg_cancel_fails(self):
        """All-legs-failed is indistinguishable from a broker/transport outage.

        The registry must NOT claim "cancelled" — the legs may all still rest
        live at the broker. Fail closed and leave the bracket tracked.
        """
        svc, _, cancel_leg = _svc(fail_cancel_ids={"OID-1", "OID-2"})
        bid = svc.place_bracket(
            entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL
        ).bracket.bracket_id
        with pytest.raises(BracketOrderError, match="NOT cancelled"):
            svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert svc.get_bracket(bid).status == "active"
        assert bid in [b.bracket_id for b in svc.get_active_brackets()]
        # Both legs were attempted before the refusal.
        assert [order_id for order_id, _ in cancel_leg.calls] == ["OID-1", "OID-2"]

    def test_partial_leg_failure_records_honest_warning(self):
        """A mixed sweep cancels, but the unconfirmed leg is called out."""
        svc, _, _ = _svc(fail_cancel_ids={"OID-1"})
        bid = svc.place_bracket(
            entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL
        ).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=PRINCIPAL)
        bracket = svc.get_bracket(bid)
        assert any("could not be confirmed cancelled" in w for w in bracket.cancel_warnings)
        assert "cancel_warnings" in bracket.to_dict()

    def test_cancel_market_entry_warns_position_remains_open(self):
        """Cancelling never closes a filled MARKET entry — say so, honestly."""
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(price=0), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=PRINCIPAL)
        warnings = svc.get_bracket(bid).cancel_warnings
        assert any("remains open" in w for w in warnings)

    def test_cancel_limit_entry_has_no_position_warning(self):
        """A swept LIMIT entry never filled — no open-position caveat."""
        svc, _, _ = _svc()
        bid = svc.place_bracket(
            entry=_entry(price=22100.0), stoploss=22000.0, principal=PRINCIPAL
        ).bracket.bracket_id
        assert svc.cancel_bracket(bid, principal=PRINCIPAL)
        assert svc.get_bracket(bid).cancel_warnings == []


# ---------------------------------------------------------------------------
# mark_completed
# ---------------------------------------------------------------------------


class TestMarkCompleted:
    def test_mark_completed(self):
        svc, _, _ = _svc()
        bid = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).bracket.bracket_id
        assert svc.mark_completed(bid)
        assert svc.get_bracket(bid).status == "completed"
        assert bid not in [b.bracket_id for b in svc.get_active_brackets()]

    def test_mark_completed_unknown_returns_false(self):
        svc, _, _ = _svc()
        assert not svc.mark_completed("does-not-exist")


# ---------------------------------------------------------------------------
# to_dict serialisation
# ---------------------------------------------------------------------------


class TestBracketDict:
    def test_to_dict_has_required_keys(self):
        svc, _, _ = _svc()
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL)
        d = result.bracket.to_dict()
        for key in (
            "bracket_id", "entry_order_id", "sl_order_id", "target_order_id",
            "symbol", "exchange", "action", "quantity",
            "entry_price", "stoploss", "target", "trailing_sl",
            "strategy", "product", "broker", "status",
            "created_at", "updated_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_broker_key_reflects_adapter(self):
        svc, _, _ = _svc()
        principal = BracketPrincipal(
            actor_id="operator", jti="jti-1", adapter_id="upstox", account_id="a1"
        )
        result = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=principal)
        assert result.bracket.to_dict()["broker"] == "upstox"

    def test_result_to_dict_on_success(self):
        svc, _, _ = _svc()
        d = svc.place_bracket(entry=_entry(), stoploss=22000.0, principal=PRINCIPAL).to_dict()
        assert d["success"] is True
        assert d["bracket"]["status"] == "active"
        assert d["error"] == ""
