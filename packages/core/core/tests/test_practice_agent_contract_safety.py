"""Practice derivative lot and shared L5 brakes use no broker write client."""

from __future__ import annotations

import hashlib
import json
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from flinttrade_core import order_routes
from flinttrade_core.models import Action, Product
from flinttrade_engine.laya import process_laya
from flinttrade_engine.safety import SafetyResult, SafetyVerdict
from packages.core.core.tests.test_practice_agent_adapter import _context, _order
from packages.core.core.tests.test_practice_agent_adapter import runtime as runtime

_SYMBOL = "NIFTY30SEP2625000CE"


def _receipt(context):
    canonical = json.dumps(
        context.market_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    context.receipt["input_digest"] = hashlib.sha256(canonical.encode()).hexdigest()
    return context


def _derivative(exchange="NFO", lot_size=65):
    context = _context(_SYMBOL, exchange)
    context.market_data["schema_version"] = 1
    provenance = {"selector": {"adapter_id": "dhan", "account_id": "Quotes"}, "requested_role": "quote"}
    context.market_data["quote"]["provenance"] = deepcopy(provenance)
    context.market_data["lot_size"] = {
        "request": {"exchange": exchange, "symbols": [_SYMBOL]},
        "value": {"symbol": _SYMBOL, "exchange": exchange, "lot_size": lot_size, "instrument_id": None},
        "provenance": provenance,
        "observed_at": datetime.now(UTC).isoformat(),
        "source_as_of": None,
    }
    return _receipt(context)


def _derivative_order(**kwargs):
    return _order(symbol=_SYMBOL, exchange="NFO", quantity="65", admission_note="Exit below the prior range.", **kwargs)


@pytest.mark.parametrize("quantity", [1, 64, 66, 99])
async def test_non_lot_quantity_refuses_before_laya(runtime, monkeypatch, quantity):
    runtime.context = _derivative()
    monkeypatch.setattr(process_laya(), "admit", lambda *_: pytest.fail("Invalid lot quantity reached Laya"))
    result = await runtime.create().place_order(
        symbol=_SYMBOL, exchange="NFO", product="NRML", action="BUY", quantity=quantity
    )
    assert result["code"] == "practice_lot_quantity_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_exact_lot_receipt_allows_canonical_sandbox_fill(runtime):
    runtime.context = _derivative()
    calls = []

    def market_open(exchange, *, symbol):
        calls.append((exchange, symbol))
        return True

    runtime.app.config["TIME_SCHEDULER"] = SimpleNamespace(is_market_open=market_open)
    result = await runtime.create().route_order(_derivative_order())
    assert result.passed, result.response
    assert runtime.sandbox.get_positions()[0]["net_qty"] == 65
    assert result.response["price_source"] == "ltp"
    assert calls == [("NFO", _SYMBOL)]


@pytest.mark.parametrize("session", ["missing", "closed", "unavailable"])
async def test_option_receipt_cannot_bypass_canonical_market_session(runtime, session):
    from flinttrade_data.practice_price import OPTION_PRICE_STALE

    runtime.context = _derivative()
    if session != "missing":

        def market_open(*_args, **_kwargs):
            if session == "unavailable":
                raise RuntimeError("synthetic scheduler failure")
            return False

        runtime.app.config["TIME_SCHEDULER"] = SimpleNamespace(is_market_open=market_open)
    adapter = runtime.create()
    result = await adapter.route_order(_derivative_order())
    assert not result.passed
    assert result.response["http_status"] == 400
    assert result.response["message"] == OPTION_PRICE_STALE
    assert not adapter.reconciliation_required
    assert runtime.sandbox.get_orders() == []


async def test_exact_option_reduction_retains_canonical_closed_session_refusal(runtime):
    from flinttrade_data.practice_price import OPTION_PRICE_STALE

    runtime.context = _derivative()
    runtime.app.config["TIME_SCHEDULER"] = SimpleNamespace(is_market_open=lambda *_args, **_kwargs: True)
    adapter = runtime.create()
    assert (await adapter.route_order(_derivative_order())).passed
    runtime.app.config["TIME_SCHEDULER"] = SimpleNamespace(is_market_open=lambda *_args, **_kwargs: False)
    runtime.app.config["SAFETY"].l5_kill.activate("synthetic closed-session reduction")

    result = await adapter.route_order(_derivative_order(action=Action.SELL))
    assert not result.passed
    assert result.response["message"] == OPTION_PRICE_STALE
    assert not adapter.reconciliation_required
    assert runtime.sandbox.get_positions()[0]["net_qty"] == 65
    assert len(runtime.sandbox.get_trades()) == 1


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "no_provenance",
        "different_provenance",
        "wrong_role",
        "wrong_symbol",
        "wrong_exchange",
        "wrong_request",
        "zero",
        "bool",
        "too_large",
        "stale",
        "future",
        "source_stale",
        "digest",
        "identity",
    ],
)
async def test_unrecognised_or_stale_lot_receipt_refuses_before_laya(runtime, monkeypatch, damage):
    context = _derivative()
    record = context.market_data["lot_size"]
    if damage == "missing":
        context.market_data.pop("lot_size")
    elif damage == "no_provenance":
        record["provenance"] = None
    elif damage == "different_provenance":
        record["provenance"]["selector"]["account_id"] = "Other"
    elif damage == "wrong_role":
        record["provenance"]["requested_role"] = "historical"
        context.market_data["quote"]["provenance"]["requested_role"] = "historical"
    elif damage == "wrong_symbol":
        record["value"]["symbol"] = "OTHER"
    elif damage == "wrong_exchange":
        record["value"]["exchange"] = "BFO"
    elif damage == "wrong_request":
        record["request"]["symbols"] = []
    elif damage in {"zero", "bool", "too_large"}:
        record["value"]["lot_size"] = {"zero": 0, "bool": True, "too_large": 1_000_001}[damage]
    elif damage in {"stale", "future", "source_stale"}:
        record["source_as_of" if damage == "source_stale" else "observed_at"] = (
            datetime.now(UTC) + timedelta(days=1 if damage == "future" else -1)
        ).isoformat()
    elif damage == "identity":
        context.market_data["quote"]["value"]["instrument"]["instrument_id"] = "contract-1"
        record["value"]["instrument_id"] = "contract-2"
    _receipt(context)
    if damage == "digest":
        record["value"]["lot_size"] = 1
    runtime.context = context
    monkeypatch.setattr(process_laya(), "admit", lambda *_: pytest.fail("Invalid lot receipt reached Laya"))
    result = await runtime.create().route_order(_derivative_order())
    assert not result.passed
    assert result.response["code"] == "practice_lot_data_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_dispatch_refreshes_lot_metadata_after_analysis(runtime):
    runtime.context = _derivative()
    adapter = runtime.create()
    await adapter.quotes(symbol=_SYMBOL, exchange="NFO")
    runtime.context = _derivative(lot_size=75)
    result = await adapter.route_order(_derivative_order())
    assert not result.passed
    assert result.response["code"] == "practice_lot_quantity_invalid"
    assert len(runtime.reads) == 2
    assert runtime.sandbox.get_orders() == []


async def test_lot_freshness_rechecked_after_slow_laya(runtime, monkeypatch):
    runtime.context = _derivative()
    original = order_routes._admit_place

    def delay_lot(*args, **kwargs):
        result = original(*args, **kwargs)
        # Move the adapter's clock only after canonical admission has completed.
        from flinttrade_core import practice_agent_adapter

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(seconds=31)

        monkeypatch.setattr(practice_agent_adapter, "datetime", Later)
        return result

    monkeypatch.setattr(order_routes, "_admit_place", delay_lot)
    result = await runtime.create().route_order(_derivative_order())
    assert not result.passed
    assert runtime.sandbox.get_orders() == []


async def test_active_shared_kill_blocks_entries_before_market_reads(runtime):
    runtime.app.config["SAFETY"].l5_kill.activate("synthetic offline test")
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_kill_switch_active"
    assert runtime.reads == []
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        object(),
        SimpleNamespace(passed=True),
        SafetyResult("PASS", "L5_KILL"),
        SafetyResult(SafetyVerdict.PASS, "L1_ORDER"),
        SafetyResult("INVALID", "L5_KILL"),
    ],
)
async def test_unrecognised_kill_verdict_fails_closed(runtime, monkeypatch, invalid):
    monkeypatch.setattr(runtime.app.config["SAFETY"].l5_kill, "validate", lambda: invalid)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_safety_unavailable"
    assert runtime.reads == []
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("failure", ["missing", "raises"])
async def test_missing_or_raising_kill_fails_closed(runtime, monkeypatch, failure):
    if failure == "missing":
        runtime.app.config.pop("SAFETY")
    else:

        def broken():
            raise RuntimeError("private failure")

        monkeypatch.setattr(runtime.app.config["SAFETY"].l5_kill, "validate", broken)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_safety_unavailable"
    assert runtime.sandbox.get_orders() == []


async def test_shared_kill_latched_during_laya_blocks_final_write(runtime, monkeypatch):
    original = order_routes._admit_place

    def activate(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.app.config["SAFETY"].l5_kill.activate("synthetic delayed admission")
        return result

    monkeypatch.setattr(order_routes, "_admit_place", activate)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_kill_switch_active"
    assert runtime.sandbox.get_orders() == []


async def test_price_resolution_holds_no_write_lease_and_kill_still_blocks_fill(runtime, monkeypatch):
    original = order_routes._resolve_practice_market_fill
    activated = threading.Event()

    def resolve_with_activation(*args, **kwargs):
        def activate():
            runtime.app.config["SAFETY"].l5_kill.activate("synthetic price resolution")
            activated.set()

        activation = threading.Thread(target=activate)
        activation.start()
        try:
            assert activated.wait(0.5), "Price resolution retained a sandbox write admission"
        finally:
            activation.join(timeout=2)
        return original(*args, **kwargs)

    monkeypatch.setattr(order_routes, "_resolve_practice_market_fill", resolve_with_activation)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_kill_switch_active"
    assert runtime.sandbox.get_orders() == []


async def test_quote_freshness_rechecked_after_canonical_price_resolution(runtime, monkeypatch):
    from flinttrade_core import practice_agent_adapter

    original = order_routes._resolve_practice_market_fill

    def resolve_after_quote_expires(*args, **kwargs):
        result = original(*args, **kwargs)

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(seconds=31)

        monkeypatch.setattr(practice_agent_adapter, "datetime", Later)
        return result

    monkeypatch.setattr(order_routes, "_resolve_practice_market_fill", resolve_after_quote_expires)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_market_data_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_shared_kill_allows_only_exact_reduction_with_valid_session(runtime):
    adapter = runtime.create()
    assert (await adapter.route_order(_order())).passed
    runtime.app.config["SAFETY"].l5_kill.activate("synthetic cleanup")
    assert not (await adapter.route_order(_order(action=Action.SELL, product=Product.CNC))).passed
    assert not (await adapter.route_order(_order(action=Action.SELL, quantity="2"))).passed
    assert (await adapter.route_order(_order(action=Action.SELL))).passed
    assert runtime.sandbox.get_positions() == []
    assert len(runtime.sandbox.get_trades()) == 2
    assert not (await adapter.route_order(_order(action=Action.SELL))).passed


async def test_kill_reduction_never_bypasses_revoked_session(runtime):
    adapter = runtime.create()
    assert (await adapter.route_order(_order())).passed
    runtime.app.config["SAFETY"].l5_kill.activate("synthetic cleanup")
    runtime.revoked.add("practice-session")
    result = await adapter.route_order(_order(action=Action.SELL))
    assert not result.passed
    assert result.response["code"] == "practice_session_invalid"
    assert len(runtime.sandbox.get_trades()) == 1


async def test_final_normal_write_owns_kill_admission_only_after_laya(runtime, monkeypatch):
    kill = runtime.app.config["SAFETY"].l5_kill
    activated = threading.Event()
    original_place = runtime.sandbox.place_order
    activation = None

    def place_with_activation(**kwargs):
        nonlocal activation

        def activate():
            kill.activate("synthetic concurrent admission")
            activated.set()

        activation = threading.Thread(target=activate)
        activation.start()
        for _ in range(100):
            if kill.is_active:
                break
            activated.wait(0.01)
        assert kill.is_active
        assert not activated.wait(0.05), "Activation failed to drain the admitted Practice write"
        return original_place(**kwargs)

    monkeypatch.setattr(runtime.sandbox, "place_order", place_with_activation)
    try:
        result = await runtime.create().route_order(_order())
        assert result.passed, result.response
    finally:
        if activation is not None:
            activation.join(timeout=2)
            assert not activation.is_alive()
    assert activated.is_set()


async def test_kill_drain_does_not_wait_for_post_fill_evidence(runtime):
    activated = threading.Event()
    activation = None

    def event(kind, _data):
        nonlocal activation
        if kind != "dispatch_result":
            return

        def activate():
            runtime.app.config["SAFETY"].l5_kill.activate("synthetic evidence boundary")
            activated.set()

        activation = threading.Thread(target=activate)
        activation.start()
        assert activated.wait(0.2), "Kill drain retained an admission after the sandbox write finished"

    try:
        result = await runtime.create(event_sink=event).route_order(_order())
        assert result.passed, result.response
    finally:
        if activation is not None:
            activation.join(timeout=2)
            assert not activation.is_alive()


async def test_sandbox_failure_after_write_is_never_misreported_as_known_kill_refusal(runtime, monkeypatch):
    from flinttrade_core.practice_agent_adapter import PracticeAgentError

    original = runtime.sandbox.place_order

    def uncertain(**kwargs):
        original(**kwargs)
        raise PracticeAgentError("practice_kill_switch_active")

    monkeypatch.setattr(runtime.sandbox, "place_order", uncertain)
    adapter = runtime.create()
    result = await adapter.route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_reconciliation_required"
    assert adapter.reconciliation_required
    assert len(runtime.sandbox.get_trades()) == 1
