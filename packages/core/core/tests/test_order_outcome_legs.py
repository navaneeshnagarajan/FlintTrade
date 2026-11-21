"""Per-leg outcomes travel beside order_outcome on every labelled result."""

from __future__ import annotations

import pytest

from flinttrade_core.order_outcome import (
    annotate,
    cancel_acknowledgement,
    describe_tool_outcome,
    leg_outcomes,
    unknown_outcome,
)


def test_a_lost_single_leg_order_has_one_unknown_entry_leg() -> None:
    assert unknown_outcome()["leg_outcomes"] == {"entry": "unknown"}


@pytest.mark.parametrize(
    ("outcome", "entry"),
    [("unknown", "unknown"), ("rejected", "absent"), ("cancel_requested", "confirmed"), ("cancelled", "confirmed")],
)
def test_a_single_leg_order_maps_its_outcome_onto_the_entry_leg(outcome: str, entry: str) -> None:
    assert annotate({}, outcome=outcome, reason="r")["leg_outcomes"] == {"entry": entry}


def test_a_cancel_acknowledgement_keeps_the_entry_leg_confirmed() -> None:
    assert cancel_acknowledgement({})["leg_outcomes"] == {"entry": "confirmed"}
    assert cancel_acknowledgement({"status": "CANCELLED"})["leg_outcomes"] == {"entry": "confirmed"}


def test_each_leg_is_a_separate_value() -> None:
    legs = leg_outcomes(entry="confirmed", target="unknown", stop_loss="absent")
    assert legs == {"entry": "confirmed", "target": "unknown", "stop_loss": "absent"}


def test_a_leg_value_outside_the_three_states_is_refused() -> None:
    with pytest.raises(ValueError):
        leg_outcomes(entry="filled")


def test_tool_results_carry_leg_outcomes_beside_order_outcome() -> None:
    assert describe_tool_outcome(None, dropped=True)["leg_outcomes"] == {"entry": "unknown"}
    assert describe_tool_outcome({"status": "REJECTED"})["leg_outcomes"] == {"entry": "absent"}
    passed = describe_tool_outcome({"order_outcome": "cancel_requested"})
    assert passed["order_outcome"] == "cancel_requested"
    assert passed["leg_outcomes"] == {"entry": "confirmed"}
    bracket = describe_tool_outcome({
        "order_outcome": "cancel_requested",
        "leg_outcomes": {"entry": "confirmed", "target": "confirmed", "stop_loss": "absent"},
    })
    assert bracket["leg_outcomes"] == {"entry": "confirmed", "target": "confirmed", "stop_loss": "absent"}
