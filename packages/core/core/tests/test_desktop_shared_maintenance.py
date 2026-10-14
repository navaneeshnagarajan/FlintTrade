"""Desktop's real retained release owner must respect shared borrower lifetimes."""
from __future__ import annotations

import threading
import time

import pytest
from flask import Flask

from flinttrade_core import desktop
from flinttrade_core.app import _install_runtime_request_tracking

pytestmark = pytest.mark.integration
KEYS = ("MODEL_RUN_SERVICES", "DATA_RUNTIME", "LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME",
        "SERVICE_TASK_DISPATCHER")


def quiet_external_owners(monkeypatch, events):
    monkeypatch.setattr(desktop, "_stop_backend_lease_watch", lambda *a, **k: True)
    monkeypatch.setattr(desktop, "_shutdown_rotation_scheduler", lambda app: None)
    monkeypatch.setattr(desktop, "shutdown_ditto_runtime", lambda *a, **k: True)
    monkeypatch.setattr("flinttrade_core.local_ai_routes.shutdown_local_ai_runtime", lambda *a, **k: True)
    monkeypatch.setattr("flinttrade_core.smart_order_routes.shutdown_smart_order_jobs", lambda **k: True)
    monkeypatch.setattr("flinttrade_core.agent_routes.shutdown_agent_runtime", lambda *a, **k: True)
    monkeypatch.setattr("flinttrade_engine.strategy_routes.shutdown_strategy_runtime", lambda app: None)
    monkeypatch.setattr(desktop, "retire_broker_dependencies", lambda app: events.append("broker") or True)


class CloseOwner:
    def __init__(self, key, events):
        self.key, self.events = key, events

    def close(self):
        self.events.append(self.key)


def test_desktop_actual_release_drains_requests_before_shared_borrowers(monkeypatch):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    tracker = _install_runtime_request_tracking(app)
    held = tracker.try_admit()
    assert held is not None
    entered_drain = threading.Event()
    wait = tracker.wait_for_idle

    def observe_drain(timeout):
        entered_drain.set()
        return wait(timeout)

    monkeypatch.setattr(tracker, "wait_for_idle", observe_drain)
    for key in KEYS:
        app.config[key] = CloseOwner(key, events)
    release = desktop._DesktopShutdownRecoveryOwner(app)
    outcome = []

    def run():
        try:
            release.release(deadline=time.monotonic() + 5)
            outcome.append("complete")
        except Exception as exc:
            outcome.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered_drain.wait(2)
        assert events == [], "shared source/model dependencies retired while a request still borrowed them"
    finally:
        held.release()
        worker.join(timeout=6)
    assert outcome == ["complete"]
    assert [event for event in events if event in KEYS] == list(KEYS)
    assert events.index("DATA_RUNTIME") < events.index("broker")
    assert events.index("MODEL_RUN_SERVICES") < events.index("KNOWLEDGE_RUNTIME")
    assert all(key not in app.config for key in KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_desktop_timeout_retains_exact_close_and_downstream_dependencies(monkeypatch, key):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)
    entered, finish = threading.Event(), threading.Event()

    class HeldClose(CloseOwner):
        def close(self):
            self.events.append(self.key)
            entered.set()
            assert finish.wait(5)

    for name in KEYS:
        app.config[name] = HeldClose(name, events) if name == key else CloseOwner(name, events)
    exact = app.config[key]
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    try:
        with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
            owner.release(deadline=time.monotonic() + 0.1)
        assert entered.is_set()
        assert app.config[key] is exact
        assert all(name in app.config for name in KEYS[KEYS.index(key):])
        assert events.count(key) == 1
        finish.set()
        owner.release(deadline=time.monotonic() + 5)
        assert events.count(key) == 1, "retry duplicated the still-owned close"
        assert all(name not in app.config for name in KEYS)
    finally:
        finish.set()


def test_desktop_replaced_close_cannot_become_completed_by_removing_replacement(monkeypatch):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)

    class SwappingClose:
        def close(self):
            app.config['DATA_RUNTIME'] = CloseOwner('replacement', events)

    app.config['DATA_RUNTIME'] = SwappingClose()
    app.config['KNOWLEDGE_RUNTIME'] = CloseOwner('KNOWLEDGE_RUNTIME', events)
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
        owner.release(deadline=time.monotonic() + 5)
    app.config.pop('DATA_RUNTIME')
    with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
        owner.release(deadline=time.monotonic() + 5)
    assert 'KNOWLEDGE_RUNTIME' in app.config


def test_incomplete_local_ai_worker_keeps_shared_dependencies_until_retry(monkeypatch):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)
    finished = threading.Event()

    def stop_local_ai(*args, **kwargs):
        return finished.is_set()

    monkeypatch.setattr("flinttrade_core.local_ai_routes.shutdown_local_ai_runtime", stop_local_ai)
    for key in KEYS:
        app.config[key] = CloseOwner(key, events)
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    with pytest.raises(desktop.DesktopBackendShutdownIncomplete):
        owner.release(deadline=time.monotonic() + 5)
    assert all(key in app.config for key in KEYS)
    assert events == []
    finished.set()
    owner.release(deadline=time.monotonic() + 5)
    assert all(key not in app.config for key in KEYS)


@pytest.mark.parametrize("key", KEYS)
def test_failed_shared_close_retains_owner_and_retries_same_instance(monkeypatch, key):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)

    class FailingClose(CloseOwner):
        failing = True

        def close(self):
            if self.failing:
                raise OSError("synthetic checkpoint failure")
            super().close()

    for name in KEYS:
        app.config[name] = FailingClose(name, events) if name == key else CloseOwner(name, events)
    exact = app.config[key]
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    with pytest.raises(desktop.DesktopBackendShutdownIncomplete) as failed:
        owner.release(deadline=time.monotonic() + 5)
    assert failed.value.recovery_owner is owner
    assert app.config[key] is exact
    assert all(name in app.config for name in KEYS[KEYS.index(key):])
    exact.failing = False
    owner.release(deadline=time.monotonic() + 5)
    assert events.count(key) == 1
    assert all(name not in app.config for name in KEYS)


@pytest.mark.parametrize("failed", [False, True])
def test_desktop_finalises_mounted_maintenance_only_after_managed_shutdown(monkeypatch, failed):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)
    for key in KEYS:
        app.config[key] = CloseOwner(key, events)

    class Boundary:
        failing = failed

        def runtime_stopped(self, *, timeout):
            assert timeout > 0
            events.append("maintenance-completion")
            if self.failing:
                raise RuntimeError("synthetic exact handoff remains pending")

        def close(self):
            events.append("maintenance-close")

    boundary = Boundary()
    app.extensions["flinttrade.maintenance"] = boundary
    owner = desktop._DesktopShutdownRecoveryOwner(app)
    if failed:
        with pytest.raises(desktop.DesktopBackendShutdownIncomplete) as caught:
            owner.release(deadline=time.monotonic() + 5)
        assert caught.value.recovery_owner is owner
        assert not owner._released
        assert "maintenance-close" not in events
        boundary.failing = False
    owner.release(deadline=time.monotonic() + 5)
    assert events.index("SERVICE_TASK_DISPATCHER") < events.index("maintenance-completion")
    assert events[-1] == "maintenance-close"
    assert owner._released


def test_post_factory_startup_failure_uses_shared_release_order(monkeypatch):
    events = []
    quiet_external_owners(monkeypatch, events)
    app = Flask(__name__)
    _install_runtime_request_tracking(app)
    for key in KEYS:
        app.config[key] = CloseOwner(key, events)
    recovery = desktop._DesktopStartupRollbackRecoveryOwner(
        app, client=None, audit=None, local_ai_attempted=False,
        smart_order_started=False, startup_error_context="SyntheticStartupFailure",
    )
    assert recovery.attempt_rollback(deadline=time.monotonic() + 5)
    assert [event for event in events if event in KEYS] == list(KEYS)
    assert events.index("MODEL_RUN_SERVICES") < events.index("broker")
    assert all(key not in app.config for key in KEYS)
