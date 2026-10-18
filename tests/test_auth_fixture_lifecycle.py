"""Process auth custody is distinct from factory lifetime and fails closed."""
from contextlib import contextmanager
import threading

import pytest

from tests.flask_app_lifecycle import (
    FactoryApps, ProcessAuthStateOwner, owned_auth_state, owned_flask_apps,
)
from flinttrade_core import auth_state

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("body_error", [False, True])
def test_process_auth_fixture_releases_exact_owner_on_every_exit(tmp_path, body_error):
    retained = []
    try:
        with contextmanager(owned_auth_state.__wrapped__)(tmp_path, FactoryApps()) as state:
            retained.append(state)
            state.revoke_jti("synthetic-revocation", 4102444800.0)
            with pytest.raises(RuntimeError, match="already has an owner"):
                ProcessAuthStateOwner(tmp_path / "other.sqlite")
            with pytest.raises(auth_state.AuthStateUnavailable, match="different path"):
                auth_state.get_auth_state(tmp_path / "other.sqlite")
            assert auth_state.get_auth_state() is state
            if body_error:
                raise ValueError("synthetic fixture body")
    except ValueError as error:
        assert body_error and str(error) == "synthetic fixture body"
    else:
        assert not body_error
    previous = retained[0]
    with pytest.raises(auth_state.AuthStateUnavailable, match="closed"):
        previous.is_jti_revoked("synthetic-revocation")
    successor = ProcessAuthStateOwner(tmp_path / "auth_state.sqlite")
    try:
        assert successor.state is not previous
        assert successor.state.is_jti_revoked("synthetic-revocation")
    finally:
        successor.close()


def test_default_owner_workspace_guard_survives_close_until_exact_release(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(first))
    owner = ProcessAuthStateOwner(None)
    try:
        owner.state.revoke_jti("synthetic-revocation", 4102444800.0)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(second))
        with pytest.raises(auth_state.AuthStateUnavailable, match="workspace changed"):
            auth_state.get_auth_state()
        owner.state.close()
        with pytest.raises(auth_state.AuthStateUnavailable, match="workspace changed"):
            auth_state.get_auth_state()
        assert auth_state._SINGLETON is owner.state
    finally:
        owner.close()
    successor = ProcessAuthStateOwner(None)
    try:
        assert successor.state is not owner.state
        assert successor.state._db_path == second / "auth_state.sqlite"
        assert not successor.state.is_jti_revoked("synthetic-revocation")
    finally:
        successor.close()
    retained = auth_state.AuthState(first / "auth_state.sqlite")
    try:
        assert retained.is_jti_revoked("synthetic-revocation")
    finally:
        retained.close()


def test_failed_auth_close_retains_exact_owner_and_refuses_reacquisition(tmp_path, monkeypatch):
    owner = ProcessAuthStateOwner(tmp_path / "auth_state.sqlite")
    real_close = owner.state.close

    def fail():
        raise RuntimeError("synthetic auth close failure")

    try:
        monkeypatch.setattr(owner.state, "close", fail)
        with pytest.raises(RuntimeError, match="synthetic auth close failure"):
            owner.close()
        assert auth_state.get_auth_state() is owner.state
        assert not owner.released
        with pytest.raises(RuntimeError, match="already has an owner"):
            ProcessAuthStateOwner(tmp_path / "other.sqlite")
    finally:
        monkeypatch.setattr(owner.state, "close", real_close)
        owner.close()
    successor = ProcessAuthStateOwner(tmp_path / "other.sqlite")
    try:
        assert successor.state is not owner.state
        assert owner.released
    finally:
        successor.close()


def test_auth_release_refuses_changed_custody_without_closing_unknown_owner(tmp_path, monkeypatch):
    owner = ProcessAuthStateOwner(tmp_path / "auth_state.sqlite")
    other = auth_state.AuthState(tmp_path / "other.sqlite")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(auth_state, "_SINGLETON", other)
            with pytest.raises(RuntimeError, match="custody changed"):
                owner.close()
            assert auth_state.get_auth_state() is other
            assert not other._closed and not owner.state._closed
    finally:
        other.close()
        owner.close()


def test_auth_fixture_drains_actual_request_before_closing_process_authority(tmp_path):
    from flinttrade_core.app import create_flask_app

    with pytest.MonkeyPatch.context() as patch:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "master_password").write_text("pytest-master-password", encoding="utf-8")
        patch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        patch.setenv("FLINTTRADE_API_KEY", "synthetic-held-request")
        with contextmanager(owned_flask_apps.__wrapped__)(patch) as apps:
            lifetime = contextmanager(owned_auth_state.__wrapped__)(tmp_path, apps)
            with lifetime as state:
                _exercise_held_auth_request(apps, lifetime, state, patch, tmp_path, create_flask_app)


def _exercise_held_auth_request(apps, lifetime, state, patch, tmp_path, create_flask_app):
    app = create_flask_app()
    tracker = app.config["RUNTIME_REQUEST_TRACKER"]
    entered, finish, draining = (threading.Event() for _ in range(3))
    events, errors = [], []
    real_wait, real_close = tracker.wait_for_idle, state.close

    def wait(timeout):
        draining.set()
        return real_wait(timeout)

    def close_auth():
        events.append("auth-close")
        real_close()

    patch.setattr(tracker, "wait_for_idle", wait)
    patch.setattr(state, "close", close_auth)

    @app.get("/synthetic-auth-borrower")
    def held():
        entered.set()
        assert finish.wait(5)
        assert auth_state.get_auth_state() is state
        assert not state.is_jti_revoked("synthetic-absent")
        events.append("request-finished")
        return {"ok": True}

    def request():
        try:
            with app.test_client().get("/synthetic-auth-borrower", headers={
                "X-API-Key": "synthetic-held-request",
            }) as response:
                assert response.status_code == 200
        except BaseException as error:
            errors.append(error)

    def cleanup():
        try:
            lifetime.__exit__(None, None, None)
        except BaseException as error:
            errors.append(error)

    caller, closer = threading.Thread(target=request), threading.Thread(target=cleanup)
    caller.start()
    try:
        assert entered.wait(5)
        closer.start()
        assert draining.wait(5)
        assert closer.is_alive()
        assert not state._closed
        assert auth_state.get_auth_state() is state
    finally:
        finish.set()
        caller.join(5)
        if closer.ident is not None:
            closer.join(10)
        else:
            lifetime.__exit__(None, None, None)
    assert not caller.is_alive() and not closer.is_alive()
    assert errors == []
    assert events == ["request-finished", "auth-close"]
    assert state._closed and auth_state._SINGLETON is None
    successor = ProcessAuthStateOwner(tmp_path / "auth_state.sqlite")
    try:
        assert successor.state is not state
    finally:
        successor.close()
