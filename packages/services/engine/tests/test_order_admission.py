"""Selector-scoped live-order admission and unresolved exposure tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from flinttrade_core.models import Action, Exchange, Order, PriceType, Product
from flinttrade_engine.safety import SafetyBypassError, SafetySystem


def _order() -> Order:
    return Order(
        symbol="NIFTY30JUL2625000CE",
        exchange=Exchange.NFO,
        action=Action.BUY,
        product=Product.NRML,
        pricetype=PriceType.MARKET,
        quantity="50",
    )


@pytest.mark.asyncio
async def test_same_selector_admissions_are_serialised() -> None:
    safety = SafetySystem()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = asyncio.Event()

    async def first() -> None:
        async with safety.order_admission_async("dhan:primary"):
            first_entered.set()
            await release_first.wait()

    async def second() -> None:
        await first_entered.wait()
        async with safety.order_admission_async("dhan:primary"):
            second_entered.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_entered.wait()
    await asyncio.sleep(0)
    assert not second_entered.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_different_selector_admissions_can_progress_together() -> None:
    safety = SafetySystem()
    both_entered = asyncio.Event()
    entered: set[str] = set()

    async def acquire(selector: str) -> None:
        async with safety.order_admission_async(selector):
            entered.add(selector)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)

    await asyncio.gather(acquire("dhan:one"), acquire("dhan:two"))
    assert entered == {"dhan:one", "dhan:two"}


def test_dispatched_exposure_remains_reserved_until_reconciled() -> None:
    safety = SafetySystem()
    positions = [SimpleNamespace(symbol="NIFTY30JUL2625000CE", exchange="NFO", product="NRML", quantity="25")]

    with safety.order_admission("dhan:primary") as lease:
        reservation = lease.reserve(_order(), positions)
        lease.acknowledge(reservation, {"data": {"order_id": "OID-1"}})
        snapshot = lease.reservations
        assert len(snapshot) == 1
        assert snapshot[0].starting_quantity == 25
        assert snapshot[0].broker_order_id == "OID-1"

    with safety.order_admission("dhan:primary") as lease:
        assert [row.broker_order_id for row in lease.reservations] == ["OID-1"]
        lease.reconcile([lease.reservations[0].reservation_id])
        assert lease.reservations == ()


def test_missing_broker_order_id_fails_closed_and_keeps_reservation() -> None:
    safety = SafetySystem()

    with safety.order_admission("dhan:primary") as lease:
        reservation = lease.reserve(_order(), [])
        with pytest.raises(
            SafetyBypassError,
            match="broker placement acknowledgement lacks a canonical order id",
        ):
            lease.acknowledge(reservation, {"status": "success"})

        assert [row.reservation_id for row in lease.reservations] == [reservation.reservation_id]
        assert lease.reservations[0].broker_order_id == ""


def test_unresolved_reservation_survives_restart_until_reconciled(tmp_path) -> None:
    db_path = tmp_path / "order-exposure.sqlite"
    first = SafetySystem(reservation_db_path=db_path)

    with first.order_admission("dhan:primary") as lease:
        reservation = lease.reserve(_order(), [])
        lease.acknowledge(reservation, {"order_id": "OID-RESTART"})

    restarted = SafetySystem(reservation_db_path=db_path)
    with restarted.order_admission("dhan:primary") as lease:
        assert len(lease.reservations) == 1
        assert lease.reservations[0].reservation_id == reservation.reservation_id
        assert lease.reservations[0].broker_order_id == "OID-RESTART"
        lease.reconcile([reservation.reservation_id])

    final = SafetySystem(reservation_db_path=db_path)
    with final.order_admission("dhan:primary") as lease:
        assert lease.reservations == ()


def test_ambiguous_acknowledgement_remains_reserved_after_restart(tmp_path) -> None:
    db_path = tmp_path / "order-exposure.sqlite"
    first = SafetySystem(reservation_db_path=db_path)

    with first.order_admission("dhan:primary") as lease:
        reservation = lease.reserve(_order(), [])
        with pytest.raises(SafetyBypassError):
            lease.acknowledge(reservation, {"status": "success"})

    restarted = SafetySystem(reservation_db_path=db_path)
    with restarted.order_admission("dhan:primary") as lease:
        assert len(lease.reservations) == 1
        assert lease.reservations[0].reservation_id == reservation.reservation_id
        assert lease.reservations[0].broker_order_id == ""
