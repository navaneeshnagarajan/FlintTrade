"""Real-owner exclusion, exceptional cleanup and retry for factory fixtures."""
from contextlib import contextmanager
import threading

from filelock import Timeout
import pytest

from tests.flask_app_lifecycle import owned_flask_apps
from flinttrade_core import app as app_module
from flinttrade_core.desktop import DesktopBackendShutdownIncomplete
from flinttrade_core.system_incidents import IncidentTimeline

pytestmark = pytest.mark.integration


def exclusive(path):
    with pytest.raises(Timeout):
        IncidentTimeline(path)


def reacquired(path, previous):
    successor = IncidentTimeline(path)
    try:
        assert successor is not previous
        assert previous.closed
        assert previous._thread is None or not previous._thread.is_alive()
    finally:
        successor.close()


@pytest.mark.parametrize('failure', [None, 'body', 'startup'])
def test_real_factory_fixture_closes_held_owner_after_every_exit(tmp_path, failure):
    retained = []
    path = tmp_path / 'workspace/operational/incidents.sqlite'
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('FLINTTRADE_API_KEY', 'fixture-lifecycle-key')
        patch.setenv('FLINTTRADE_WORKSPACE_DIR', str(tmp_path / 'workspace'))
        from flinttrade_core import system_incidents
        install = system_incidents.install_incident_timeline

        def observed(app, root):
            result = install(app, root)
            retained.append(app.config['SYSTEM_INCIDENTS'])
            exclusive(path)
            if failure == 'startup':
                raise RuntimeError('synthetic startup failure')
            return result

        patch.setattr(system_incidents, 'install_incident_timeline', observed)
        try:
            with contextmanager(owned_flask_apps.__wrapped__)(patch) as custody:
                app = app_module.create_flask_app()
                assert custody.apps[0][0] is app
                exclusive(path)
                if failure == 'body':
                    raise RuntimeError('synthetic body failure')
        except RuntimeError as error:
            assert failure is not None
            assert str(error) == f'synthetic {failure} failure'
        else:
            assert failure is None
    assert len(retained) == 1
    reacquired(path, retained[0])


def test_failed_real_cleanup_retains_exact_owner_for_explicit_retry(tmp_path):
    path = tmp_path / 'workspace/operational/incidents.sqlite'
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('FLINTTRADE_API_KEY', 'fixture-lifecycle-key')
        patch.setenv('FLINTTRADE_WORKSPACE_DIR', str(tmp_path / 'workspace'))
        with contextmanager(owned_flask_apps.__wrapped__)(patch) as custody:
            app = app_module.create_flask_app()
            incident = app.config['SYSTEM_INCIDENTS']
            close = incident.close

            def fail_close():
                raise RuntimeError('synthetic close failure')

            patch.setattr(incident, 'close', fail_close)
            with pytest.raises(DesktopBackendShutdownIncomplete) as raised:
                custody.close()
            recovery = custody.owners[id(app)]
            assert raised.value.recovery_owner is recovery
            exclusive(path)
            assert not incident.closed
            patch.setattr(incident, 'close', close)
            custody.close()
            assert custody.owners[id(app)] is recovery
            reacquired(path, incident)


def test_fixture_drains_actual_held_request_before_releasing_incident_owner(tmp_path):
    path = tmp_path / 'workspace/operational/incidents.sqlite'
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('FLINTTRADE_API_KEY', 'fixture-lifecycle-key')
        patch.setenv('FLINTTRADE_WORKSPACE_DIR', str(tmp_path / 'workspace'))
        with contextmanager(owned_flask_apps.__wrapped__)(patch) as custody:
            app = app_module.create_flask_app()
            incident = app.config['SYSTEM_INCIDENTS']
            entered, finish, draining = (threading.Event() for _ in range(3))
            failures = []
            tracker = app.config['RUNTIME_REQUEST_TRACKER']
            real_wait = tracker.wait_for_idle

            def wait(timeout):
                draining.set()
                return real_wait(timeout)

            patch.setattr(tracker, 'wait_for_idle', wait)

            @app.get('/fixture-held')
            def held():
                entered.set()
                assert finish.wait(5)
                return {'ok': True}

            def request():
                try:
                    with app.test_client().get('/fixture-held', headers={'X-API-Key': 'fixture-lifecycle-key'}) as response:
                        assert response.status_code == 200
                except BaseException as error:
                    failures.append(error)

            def cleanup():
                try:
                    custody.close()
                except BaseException as error:
                    failures.append(error)

            caller = threading.Thread(target=request)
            closer = threading.Thread(target=cleanup)
            caller.start()
            try:
                assert entered.wait(5)
                closer.start()
                assert draining.wait(5)
                assert closer.is_alive()
                assert not incident.closed
                exclusive(path)
            finally:
                finish.set()
                caller.join(5)
                if closer.ident is not None:
                    closer.join(10)
            assert not caller.is_alive() and not closer.is_alive()
            assert failures == []
            reacquired(path, incident)
