"""Broker-SDK mocks + the default-mock authorisation gate (Identity H9).

The pytest default is MOCKED broker SDKs everywhere. Real brokers require BOTH:
  (a) FLINTTRADE_REAL_BROKERS=1 in the environment, AND
  (b) the current hostname listed in ~/.flinttrade/dev-machines.json

Either condition alone is insufficient. CI runners cannot satisfy (b) because they do
not carry dev-machines.json, so CI is guaranteed to mock regardless of any leaked env
var. Sub-spec §14.1-§14.2; acceptance gate #18; locked decision #22.

`install_broker_mocks()` performs the sys.modules swap. `real_brokers_authorised()` is
the two-factor check. Both are exported so the regression guard
(tests/test_real_brokers_off_by_default.py) can drive the mechanism deterministically.
"""

from __future__ import annotations

import json
import pathlib
import socket
import sys

from . import dhan_mock, kotak_neo_mock, upstox_mock

DEV_MACHINES_PATH = pathlib.Path.home() / ".flinttrade" / "dev-machines.json"

# real-import-name -> mock module
_MOCK_MODULES = {
    "dhanhq": dhan_mock,
    "upstox_python_sdk": upstox_mock,
    "neo_api_client": kotak_neo_mock,
}


def real_brokers_authorised() -> bool:
    """True only when explicit env opt-in AND host is in dev-machines.json."""
    import os

    if os.environ.get("FLINTTRADE_REAL_BROKERS") != "1":
        return False
    if not DEV_MACHINES_PATH.exists():
        return False
    try:
        allowed_hosts = set(
            json.loads(DEV_MACHINES_PATH.read_text(encoding="utf-8")).get("hostnames", [])
        )
    except (json.JSONDecodeError, OSError):
        return False
    return socket.gethostname() in allowed_hosts


def install_broker_mocks() -> None:
    """Swap every real broker SDK import name for its mock in sys.modules."""
    for real_name, mock_module in _MOCK_MODULES.items():
        sys.modules[real_name] = mock_module


__all__ = [
    "DEV_MACHINES_PATH",
    "dhan_mock",
    "upstox_mock",
    "kotak_neo_mock",
    "real_brokers_authorised",
    "install_broker_mocks",
]
