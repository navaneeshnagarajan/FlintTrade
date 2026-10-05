"""The supervisor observes the same real L5 before starting another cycle."""

from packages.core.core.tests.test_practice_agent_runtime import (
    _run_finished,
    _start,
    _supervisor,
    _wait_for,
)
from packages.core.core.tests.test_practice_agent_runtime import desk as desk


def test_latched_kill_stops_before_first_model_cycle(desk):
    desk.app.config["SAFETY"].l5_kill.activate("synthetic offline test")
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    run = _supervisor(desk).run
    assert not any(event["kind"] == "cycle_started" for event in desk.store.events(run.run_id))
    assert desk.reads == 0
    assert desk.sandbox.get_orders() == []


def test_kill_stops_hold_only_cycles_and_flattens_owned_exposure(desk):
    desk.signal = "BUY"
    assert _start(desk, cycle_interval_sec=1).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert len(desk.sandbox.get_positions()) == 1
    desk.signal = "HOLD"
    desk.app.config["SAFETY"].l5_kill.activate("synthetic after first cycle")
    _wait_for(lambda: _run_finished(desk))
    assert desk.sandbox.get_positions() == []
    assert len(desk.sandbox.get_trades()) == 2
    run = _supervisor(desk).run
    assert len([event for event in desk.store.events(run.run_id) if event["kind"] == "cycle_started"]) == 1


def test_missing_safety_stops_without_model_work(desk):
    desk.app.config.pop("SAFETY")
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    assert desk.reads == 0
    assert desk.sandbox.get_orders() == []
