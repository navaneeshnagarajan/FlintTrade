"""Dhan route fixtures retain exclusion while owned and drain on every exit."""
from __future__ import annotations

from contextlib import contextmanager
from time import monotonic

import pytest
from filelock import Timeout

from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from packages.core.core.tests.test_dhan_super_route_correspondence import route_stack

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("body_fails", [False, True])
def test_route_fixture_releases_factory_owner_even_when_body_fails(backend_lease_factory, body_fails: bool) -> None:
    app = None
    owner = None
    competing = None
    try:
        try:
            with contextmanager(route_stack.__wrapped__)(backend_lease_factory) as (app, _transport, _consumed):
                owner = app.config["EXECUTION_SESSIONS"]
                competing = OwnerSafeFileLock(str(owner.path / "runtime.lock"), timeout=0, thread_local=False)
                assert owner.lease.is_locked and not owner.closed
                with pytest.raises(Timeout):
                    competing.acquire()
                if body_fails:
                    raise LookupError("synthetic test body failure")
        except LookupError as error:
            assert body_fails and str(error) == "synthetic test body failure"
        # Keep the actual app/owner strongly referenced: GC is not cleanup.
        assert owner is not None and competing is not None
        assert owner.closed
        assert not owner.lease.is_locked
        with competing:
            assert competing.is_locked
        assert not competing.is_locked
    finally:
        # Preserve resource safety even when this regression detects old behaviour.
        if app is not None:
            _DesktopShutdownRecoveryOwner(app).release(deadline=monotonic() + 10)
