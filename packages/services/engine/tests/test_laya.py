"""Admission contract for the decision engine.

Laya may allow or refuse a typed proposal. It does not place an order.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from flinttrade_engine.laya import DecisionStatus, Laya, Proposal, process_laya, reset_process_laya_for_tests

_MODULE = Path(__file__).resolve().parents[1] / "src" / "flinttrade_engine" / "laya.py"


def _proposal(**overrides: Any) -> Proposal:
    quantity = overrides.get("quantity", 1)
    price = overrides.get("price")
    return Proposal(
        symbol=str(overrides.get("symbol", "RELIANCE")),
        exchange=str(overrides.get("exchange", "NSE")),
        action=str(overrides.get("action", "BUY")),
        quantity=quantity if isinstance(quantity, int) else 1,
        mode=str(overrides.get("mode", "live")),
        order_type=str(overrides.get("order_type", "MARKET")),
        product=str(overrides.get("product", "MIS")),
        source=str(overrides.get("source", "operator")),
        price=float(price) if isinstance(price, (int, float)) else None,
    )


@pytest.mark.unit
def test_status_is_required_and_heartbeat_does_not_invent_ready() -> None:
    down = Laya(status=DecisionStatus.DOWN, max_quantity=10)
    assert down.status is DecisionStatus.DOWN
    assert down.note_heartbeat() is DecisionStatus.DOWN
    assert down.admit(_proposal(quantity=1)).allow is False
    ready = Laya(status=DecisionStatus.READY, max_quantity=10)
    assert ready.note_heartbeat() is DecisionStatus.READY
    degraded = Laya(status=DecisionStatus.DEGRADED, max_quantity=10, degraded_max_quantity=1)
    assert degraded.note_heartbeat() is DecisionStatus.DEGRADED


@pytest.mark.unit
def test_process_laya_starts_down_until_an_explicit_status() -> None:
    reset_process_laya_for_tests()
    engine = process_laya()
    assert engine.status is DecisionStatus.DOWN
    assert engine.note_heartbeat() is DecisionStatus.DOWN
    engine.set_status(DecisionStatus.READY)
    assert engine.note_heartbeat() is DecisionStatus.READY
    reset_process_laya_for_tests()


@pytest.mark.unit
def test_ready_operator_proposal_is_admitted_with_a_quantity_ceiling() -> None:
    verdict = Laya(status=DecisionStatus.READY, max_quantity=10).admit(_proposal(quantity=4))
    assert verdict.allow is True
    assert verdict.reason == ""
    assert verdict.limits.max_quantity == 10


@pytest.mark.unit
def test_quantity_above_the_ceiling_is_refused() -> None:
    verdict = Laya(status=DecisionStatus.READY, max_quantity=2).admit(_proposal(quantity=3))
    assert verdict.allow is False
    assert "2" in verdict.reason
    assert verdict.limits.max_quantity == 2


@pytest.mark.unit
def test_degraded_uses_the_tighter_ceiling_and_still_admits_inside_it() -> None:
    engine = Laya(status=DecisionStatus.DEGRADED, max_quantity=10, degraded_max_quantity=1)
    assert engine.admit(_proposal(quantity=1)).allow is True
    refused = engine.admit(_proposal(quantity=2))
    assert refused.allow is False
    assert refused.limits.max_quantity == 1


@pytest.mark.unit
def test_down_refuses_live_and_practice_with_no_model_fallback() -> None:
    engine = Laya(status=DecisionStatus.DOWN, max_quantity=10)
    live = engine.admit(_proposal(mode="live", source="automate"))
    practice = engine.admit(_proposal(mode="practice", source="operator"))
    assert live.allow is False
    assert practice.allow is False
    assert "Down" in live.reason
    assert "Live" in live.reason


@pytest.mark.unit
def test_explore_and_chat_sources_are_refused() -> None:
    engine = Laya(status=DecisionStatus.READY, max_quantity=10)
    explore = engine.admit(_proposal(mode="explore"))
    chat = engine.admit(_proposal(source="chat"))
    assert explore.allow is False
    assert "Explore" in explore.reason
    assert chat.allow is False
    assert chat.reason


@pytest.mark.unit
def test_limit_without_a_price_is_refused() -> None:
    verdict = Laya(status=DecisionStatus.READY, max_quantity=10).admit(_proposal(order_type="LIMIT", price=None))
    assert verdict.allow is False


@pytest.mark.unit
def test_module_does_not_import_a_broker_router_or_mint_a_write_ticket() -> None:
    source = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    banned = ("broker", "router", "gateway", "safety")
    assert imported == [] or all(not any(word in name.lower() for word in banned) for name in imported)
    assert "BrokerRouter" not in source
    assert "gate_order" not in source
    assert "SafetyContext" not in source


@pytest.mark.unit
def test_overlap_map_names_the_gaps_laya_does_not_close() -> None:
    source = _MODULE.read_text(encoding="utf-8")
    for needle in (
        "RiskAssessment",
        "SafetySystem",
        "orderGuards",
        "L2",
        "L5",
        "does not place",
    ):
        assert needle in source
