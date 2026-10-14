"""Durable Paper lease refusals preserve L5 policy and counted lifetimes."""

from __future__ import annotations

import threading

import pytest

from flinttrade_engine.emergency_intents import EmergencyIntentJournal
from flinttrade_engine.safety import KillSwitch, KillSwitchActiveError, SafetyBypassError

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("selector", ["paper:sandbox", "paper:run:one", "paper:run:two"])
def test_real_journal_accepts_canonical_paper_scopes_and_releases_lease(tmp_path, selector):
    kill = KillSwitch()
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill.bind_emergency_journal(journal)
    with kill.broker_write_admission(False, selector):
        assert kill._normal_writes_in_progress == 1
    assert kill._normal_writes_in_progress == 0
    assert journal.active_episodes() == ()


@pytest.mark.parametrize("selector", ["", "malformed", " paper:sandbox", "paper:run:one "])
def test_malformed_selector_remains_unavailable_not_active(tmp_path, selector):
    kill = KillSwitch()
    kill.bind_emergency_journal(EmergencyIntentJournal(tmp_path / "emergency.sqlite3"))
    with pytest.raises(SafetyBypassError) as raised, kill.broker_write_admission(False, selector):
        pytest.fail("Invalid selector admitted")
    assert type(raised.value) is SafetyBypassError
    assert isinstance(raised.value.__cause__, ValueError)
    assert not kill.is_active and kill._normal_writes_in_progress == 0


@pytest.mark.parametrize("selector", ["*", "paper:run:one"])
def test_typed_active_refusal_comes_from_durable_episode_not_text(tmp_path, selector):
    kill = KillSwitch()
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill.bind_emergency_journal(journal)
    journal.activate_episode(source="l5", selector=selector, session_key="manual", reason_hash="a" * 64)
    if selector != "*":
        with kill.broker_write_admission(False, "paper:run:two"):
            assert not kill.is_active
    with pytest.raises(KillSwitchActiveError), kill.broker_write_admission(False, "paper:run:one"):
        pytest.fail("Active durable episode admitted")
    # Existing global latch is intentionally not narrowed by the diagnostic type.
    with pytest.raises(KillSwitchActiveError), kill.broker_write_admission(False, "paper:run:two"):
        pytest.fail("Restored global latch was relaxed")
    assert kill._normal_writes_in_progress == 0


def test_journal_failure_message_cannot_impersonate_active_refusal(tmp_path, monkeypatch):
    kill = KillSwitch()
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill.bind_emergency_journal(journal)
    failure = OSError("kill switch is active; broker write refused")

    def unavailable(_selector):
        raise failure

    monkeypatch.setattr(journal, "blocking_sources", unavailable)
    with pytest.raises(SafetyBypassError) as raised, kill.broker_write_admission(False, "paper:sandbox"):
        pytest.fail("Unavailable journal admitted")
    assert type(raised.value) is SafetyBypassError and raised.value.__cause__ is failure
    assert not kill.is_active


def test_activation_waits_for_counted_write_and_late_write_is_refused(tmp_path, monkeypatch):
    kill = KillSwitch(normal_write_drain_timeout=5)
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill.bind_emergency_journal(journal)
    waiting, finished = threading.Event(), threading.Event()
    original = kill._condition.wait

    def observe_wait(timeout=None):
        waiting.set()
        return original(timeout)

    monkeypatch.setattr(kill._condition, "wait", observe_wait)
    result = []

    def activate():
        result.append(kill.activate("synthetic concurrent activation"))
        finished.set()

    thread = threading.Thread(target=activate)
    try:
        with kill.broker_write_admission(False, "paper:run:one"):
            thread.start()
            assert waiting.wait(3)
            assert kill.is_active and not finished.is_set()
            assert kill._normal_writes_in_progress == 1
            with pytest.raises(KillSwitchActiveError), kill.broker_write_admission(False, "paper:run:two"):
                pytest.fail("Late normal write admitted")
        assert finished.wait(3)
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(result) == 1 and kill._normal_writes_in_progress == 0
    assert journal.active_episodes("l5")[0].selector == "*"
