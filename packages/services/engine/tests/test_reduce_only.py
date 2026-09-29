"""Reduce-only classification. The place pipeline decides; a client flag is not an input."""

from __future__ import annotations

import pytest

from flinttrade_engine.reduce_only import classify_reduce_only, reset_reduce_only_for_tests


def _long() -> dict[str, object]:
    return {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": 10}


def _decision(**overrides: object):
    fields = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 10,
        "positions": [_long()],
        "our_orders": [],
        "broker_orders": [],
        "live": False,
    }
    fields.update(overrides)
    return classify_reduce_only(**fields)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_reservations() -> None:
    reset_reduce_only_for_tests()
    yield
    reset_reduce_only_for_tests()


@pytest.mark.unit
def test_same_contract_opposite_side_within_the_open_quantity_qualifies() -> None:
    decision = _decision(quantity=10)
    assert decision.qualifies is True
    assert decision.open_quantity == 10
    assert decision.cap == 10
    short = _decision(
        action="BUY",
        quantity=4,
        positions=[{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": -4}],
    )
    assert short.qualifies is True
    assert short.cap == 4


@pytest.mark.unit
def test_our_unfilled_opposite_order_reduces_the_cap() -> None:
    decision = _decision(
        quantity=7,
        our_orders=[{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 4,
            "filled_qty": 0,
            "status": "PENDING",
            "order_id": "ours-1",
        }],
    )
    assert decision.qualifies is False
    assert decision.pending_exits == 4
    assert decision.cap == 6
    inside = _decision(
        quantity=6,
        our_orders=[{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 4,
            "status": "PENDING",
        }],
    )
    assert inside.qualifies is True


@pytest.mark.unit
def test_adding_or_flipping_does_not_qualify() -> None:
    assert _decision(action="BUY", quantity=1).qualifies is False
    assert _decision(quantity=11).qualifies is False
    other = _decision(symbol="TCS", quantity=1)
    assert other.qualifies is False


@pytest.mark.unit
def test_live_broker_open_exit_reduces_the_cap_and_an_unreadable_book_does_not_qualify() -> None:
    broker_exit = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 4,
        "status": "OPEN",
        "order_id": "broker-1",
    }
    reduced = _decision(quantity=7, live=True, broker_orders=[broker_exit])
    assert reduced.qualifies is False
    assert reduced.pending_exits == 4
    assert reduced.cap == 6
    allowed = _decision(quantity=6, live=True, broker_orders=[broker_exit])
    assert allowed.qualifies is True

    unreadable = _decision(quantity=10, live=True, broker_orders=None)
    assert unreadable.qualifies is False
    assert unreadable.cap == 0

    duplicate = _decision(
        quantity=6,
        live=True,
        our_orders=[{**broker_exit, "status": "PENDING"}],
        broker_orders=[broker_exit],
    )
    assert duplicate.pending_exits == 4
    assert duplicate.qualifies is True
