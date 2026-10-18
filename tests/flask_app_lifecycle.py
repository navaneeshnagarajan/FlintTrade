"""Function-scoped custody for tests using the normal Flask factory.

Keep exact apps and response iterators alive until bounded runtime cleanup has
finished. The production shutdown owner, not a second list of close methods,
remains the authority for dependency ordering and retained failures.
"""
from __future__ import annotations

from time import monotonic
import os

import pytest


class ProcessAuthStateOwner:
    """Own a test's process authority, separately from the Flask factory.

    This is a checked release of the actual owner, not a singleton reset before
    acquisition. Unknown incumbents and changed custody are always refused.
    """

    def __init__(self, path):
        from flinttrade_core import auth_state

        if auth_state._SINGLETON is not None:
            raise RuntimeError("process auth authority already has an owner")
        self.state = auth_state.get_auth_state(path)
        self.released = False

    def close(self):
        from flinttrade_core import auth_state

        with auth_state._SINGLETON_LOCK:
            if self.released:
                return
            if auth_state._SINGLETON is not self.state:
                raise RuntimeError("process auth authority custody changed")
            # Failed close retains both identities for explicit same-owner retry.
            self.state.close()
            auth_state._SINGLETON = None
            self.released = True


@pytest.fixture
def owned_auth_state(tmp_path, owned_flask_apps):
    owner = ProcessAuthStateOwner(tmp_path / "auth_state.sqlite")
    try:
        yield owner.state
    finally:
        # This owner is process-wide, not a factory config dependency. Drain
        # actual HTTP borrowers first; retain auth if runtime cleanup fails.
        owned_flask_apps.close()
        owner.close()


class FactoryApps:
    def __init__(self):
        self.apps = []
        self.responses = []
        self.owners = {}
        self.workspaces = {}

    def close(self):
        # A test client is the WSGI caller: it must close response iterators just
        # as a real server does, including an unread error or a failed test body.
        while self.responses:
            response = self.responses[-1]
            response.close()
            self.responses.pop()
        from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner

        for app, borrowed in reversed(self.apps):
            owner = self.owners.get(id(app))
            if owner is None:
                owner = app.extensions.get("flinttrade.factory_recovery")
                if owner is None:
                    owner = _DesktopShutdownRecoveryOwner(app, borrowed_keys=borrowed)
                self.owners[id(app)] = owner
            # Do not catch shutdown errors or drop a failed owner. A caller can
            # explicitly retry this exact collection after resolving its blocker.
            previous = os.environ.get("FLINTTRADE_WORKSPACE_DIR")
            workspace = self.workspaces[id(app)]
            try:
                if workspace is None:
                    os.environ.pop("FLINTTRADE_WORKSPACE_DIR", None)
                else:
                    os.environ["FLINTTRADE_WORKSPACE_DIR"] = workspace
                owner.release(deadline=monotonic() + 10)
            finally:
                if previous is None:
                    os.environ.pop("FLINTTRADE_WORKSPACE_DIR", None)
                else:
                    os.environ["FLINTTRADE_WORKSPACE_DIR"] = previous


@pytest.fixture
def owned_flask_apps(monkeypatch):
    """Own normal-factory apps even when construction or the fixture body fails."""
    from flask.testing import FlaskClient
    from flinttrade_core import app as module

    apps = FactoryApps()
    capture = module.capture_factory_app
    open_response = FlaskClient.open

    def capture_app(app, *, borrowed):
        capture(app, borrowed=borrowed)
        apps.apps.append((app, borrowed))
        apps.workspaces[id(app)] = os.environ.get("FLINTTRADE_WORKSPACE_DIR")

    def open_owned_response(client, *args, **kwargs):
        response = open_response(client, *args, **kwargs)
        if any(client.application is app for app, _ in apps.apps):
            apps.responses.append(response)
        return response

    monkeypatch.setattr(module, "capture_factory_app", capture_app)
    monkeypatch.setattr(FlaskClient, "open", open_owned_response)
    try:
        yield apps
    finally:
        # Restore test-only poisoned mappings and close methods before invoking
        # real teardown. The retained runtime's real failures still propagate.
        monkeypatch.undo()
        apps.close()
