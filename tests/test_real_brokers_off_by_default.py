"""Regression guard for Identity H9: real-broker opt-in must remain explicit.

Drives the mock mechanism directly (rather than relying on the tests/mocks/ session
fixture, which only applies to tests collected under that directory) so the guarantee is
verified deterministically wherever this file runs. Acceptance gate #18.
"""

from __future__ import annotations

import sys

from tests.mocks import (
    dhan_mock,
    install_broker_mocks,
    kotak_neo_mock,
    real_brokers_authorised,
    upstox_mock,
)


def test_real_brokers_off_by_default(monkeypatch):
    # No opt-in env var → never authorised → the swap installs the safety mocks.
    monkeypatch.delenv("FLINTTRADE_REAL_BROKERS", raising=False)
    assert real_brokers_authorised() is False
    install_broker_mocks()
    assert sys.modules.get("dhanhq") is dhan_mock
    assert sys.modules.get("upstox_python_sdk") is upstox_mock
    assert sys.modules.get("neo_api_client") is kotak_neo_mock


def test_opt_in_alone_insufficient_without_dev_machines_file(monkeypatch, tmp_path):
    # Setting only the env var (no dev-machines.json on this host) must still refuse.
    monkeypatch.setenv("FLINTTRADE_REAL_BROKERS", "1")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)  # empty home; no dev-machines.json
    # re-evaluate the module-level path against the patched home
    import tests.mocks as mocks_pkg

    monkeypatch.setattr(mocks_pkg, "DEV_MACHINES_PATH", tmp_path / ".flinttrade" / "dev-machines.json")
    assert real_brokers_authorised() is False


def test_dev_machines_present_but_wrong_host_refuses(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_REAL_BROKERS", "1")
    dev_file = tmp_path / ".flinttrade" / "dev-machines.json"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text('{"hostnames": ["some-other-host-that-is-not-us"]}', encoding="utf-8")
    import tests.mocks as mocks_pkg

    monkeypatch.setattr(mocks_pkg, "DEV_MACHINES_PATH", dev_file)
    assert real_brokers_authorised() is False


def test_both_conditions_met_authorises(monkeypatch, tmp_path):
    import socket

    monkeypatch.setenv("FLINTTRADE_REAL_BROKERS", "1")
    dev_file = tmp_path / ".flinttrade" / "dev-machines.json"
    dev_file.parent.mkdir(parents=True, exist_ok=True)
    dev_file.write_text(
        '{"hostnames": ["' + socket.gethostname() + '"]}', encoding="utf-8"
    )
    import tests.mocks as mocks_pkg

    monkeypatch.setattr(mocks_pkg, "DEV_MACHINES_PATH", dev_file)
    assert real_brokers_authorised() is True
