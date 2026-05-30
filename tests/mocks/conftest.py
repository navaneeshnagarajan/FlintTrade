"""Default-mock broker SDKs for any test collected under tests/mocks/ (Identity H9).

Auto-mock broker SDKs unless explicitly opted out on a known dev machine. A startup
banner is emitted if real brokers are loaded inside pytest so the operator cannot miss
that they are running against live SDKs.

The mechanism (real_brokers_authorised + install_broker_mocks) lives in
tests/mocks/__init__.py so the regression guard at tests/ root can exercise it directly,
independent of fixture scope. Sub-spec §14.2.
"""

from __future__ import annotations

import socket
import warnings

import pytest

from tests.mocks import install_broker_mocks, real_brokers_authorised


@pytest.fixture(autouse=True, scope="session")
def _broker_sdk_mocking_default() -> None:
    if real_brokers_authorised():
        warnings.warn(
            "\n"
            "================================================================\n"
            "  flinttrade: REAL BROKER SDKs LOADED INSIDE pytest\n"
            "  hostname: " + socket.gethostname() + "\n"
            "  FLINTTRADE_REAL_BROKERS=1 + dev-machines.json present\n"
            "  Tests CAN place real orders if they hit credentialed code paths.\n"
            "================================================================\n",
            stacklevel=1,
        )
        return
    install_broker_mocks()
