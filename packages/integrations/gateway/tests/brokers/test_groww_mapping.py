"""Focused contract tests for Groww response mapping."""

from __future__ import annotations

import pytest

from flinttrade_gateway.brokers import groww_mapping as mapping

pytestmark = pytest.mark.unit


def test_order_mapping_keeps_requested_and_filled_quantities_separate() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "OPEN",
            "quantity": 10,
            "filled_quantity": 4,
        }
    )

    assert mapped["quantity"] == 10
    assert mapped["filled_quantity"] == 4


def test_order_mapping_does_not_invent_requested_quantity_from_fills() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "EXECUTED",
            "filled_quantity": 4,
        }
    )

    assert "quantity" not in mapped
    assert mapped["filled_quantity"] == 4


def test_cancellation_requested_stays_non_terminal() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "CANCELLATION_REQUESTED",
            "quantity": 10,
            "filled_quantity": 4,
        }
    )

    assert mapped["status"] == "CANCEL_PENDING"
