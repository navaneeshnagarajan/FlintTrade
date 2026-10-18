"""Replay the original CI cases under their formerly implicit prerequisites."""
import asyncio
import inspect
import logging
from pathlib import Path
import stat

import pytest

from packages.core.core.tests import test_backend_instance as backend
from packages.core.core.tests import test_incident_review_regressions as incident
from packages.core.core.tests import test_listener_shutdown_retry as listener
from packages.core.core.tests.test_system_incidents import factory as factory
from packages.core.core.tests.test_normal_runtime_smoke import offline_startup as offline_startup

pytestmark = pytest.mark.integration


def test_post_acquisition_control_with_python312_path_dispatch(tmp_path, monkeypatch):
    # CPython 3.12's is_symlink goes through Path.stat(follow_symlinks=False).
    # Preserve actual kernel/stat behaviour; only restore this dispatch shape.
    def is_symlink(path):
        try:
            return stat.S_ISLNK(path.stat(follow_symlinks=False).st_mode)
        except FileNotFoundError:
            return False
    monkeypatch.setattr(Path, 'is_symlink', is_symlink)
    backend.test_post_acquisition_failure_releases_or_retains_exact_kernel_owner(
        tmp_path, monkeypatch, 'stat', False,
    )


def test_httpx_control_with_inherited_warning_threshold(factory, monkeypatch, capsys, caplog):
    logger = logging.getLogger('httpx')
    old = logger.level
    logger.setLevel(logging.WARNING)
    try:
        kwargs = {'caplog': caplog} if 'caplog' in inspect.signature(incident.test_real_httpx_telegram_redacts_before_every_log_sink).parameters else {}
        incident.test_real_httpx_telegram_redacts_before_every_log_sink(factory, monkeypatch, capsys, **kwargs)
    finally:
        logger.setLevel(old)


@pytest.mark.asyncio
async def test_listener_control_does_not_charge_startup_to_callback_budget(monkeypatch, offline_startup):
    # Deterministic boundary control: the callback completion wait must not be
    # submitted before the caller has entered actual runtime shutdown.
    from flinttrade_core import app as app_module
    entered = False
    stop = app_module.FlintTradeApp.stop
    to_thread = asyncio.to_thread

    async def observe_stop(runtime, *, timeout=None):
        nonlocal entered
        entered = True
        return await stop(runtime, timeout=timeout)

    async def observed_wait(func, *args, **kwargs):
        if getattr(func, '__name__', '') == 'wait' and args == (5,):
            assert entered, 'listener completion budget started before runtime shutdown'
        return await to_thread(func, *args, **kwargs)

    monkeypatch.setattr(app_module.FlintTradeApp, 'stop', observe_stop)
    monkeypatch.setattr(asyncio, 'to_thread', observed_wait)
    await listener.test_normal_listener_successful_callback_is_shared_with_a_shorter_caller(monkeypatch, offline_startup)
