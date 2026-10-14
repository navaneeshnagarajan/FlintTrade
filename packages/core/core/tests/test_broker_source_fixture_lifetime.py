"""Fixture owners retain exclusion while live and release on both exits."""
from contextlib import contextmanager
from time import monotonic

import pytest
from filelock import Timeout

from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
from flinttrade_core.owner_file_lock import OwnerSafeFileLock
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack
from packages.core.core.tests.test_upstox_native_propagation import native_stack

pytestmark = pytest.mark.integration

@pytest.mark.parametrize('fixture_name', ['route', 'upstox'])
@pytest.mark.parametrize('body_fails', [False, True])
def test_source_qualification_fixture_retains_and_releases_owner(backend_lease_factory, monkeypatch, fixture_name, body_fails):
    app = None
    owner = None
    competing = None
    function = route_stack if fixture_name == 'route' else native_stack
    args = (backend_lease_factory,) if fixture_name == 'route' else (backend_lease_factory, monkeypatch)
    try:
        try:
            with contextmanager(function.__wrapped__)(*args) as stack:
                app = stack[0] if fixture_name == 'route' else stack.app
                owner = app.config['EXECUTION_SESSIONS']
                competing = OwnerSafeFileLock(str(owner.path / 'runtime.lock'), timeout=0, thread_local=False)
                assert owner.lease.is_locked and not owner.closed
                with pytest.raises(Timeout):
                    competing.acquire()
                if body_fails:
                    raise LookupError('synthetic body failure')
        except LookupError as error:
            assert body_fails and str(error) == 'synthetic body failure'
        assert owner is not None and competing is not None
        assert owner.closed
        assert not owner.lease.is_locked
        with competing:
            assert competing.is_locked
        assert not competing.is_locked
    finally:
        if app is not None:
            _DesktopShutdownRecoveryOwner(app).release(deadline=monotonic()+10)
