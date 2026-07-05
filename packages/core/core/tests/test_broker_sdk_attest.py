"""Unit tests for broker SDK attestation."""

from __future__ import annotations

import textwrap

import pytest

from flinttrade_core.broker_sdk_attest import (
    STATUS_MISMATCH,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_SKIPPED,
    attest_all,
    attest_all_ok,
    load_pins,
    required_failures,
)

pytestmark = pytest.mark.unit

_LOCK = textwrap.dedent(
    """
    [[broker]]
    name = "dhanhq"
    version = "2.2.0"

    [[broker]]
    name = "upstox-python-sdk"
    version = "PLACEHOLDER"

    [[broker]]
    name = "neo-api-client"
    version = "1.0.0"
    """
)


@pytest.fixture
def lock_file(tmp_path):
    path = tmp_path / "brokers.lock"
    path.write_text(_LOCK, encoding="utf-8")
    return path


def test_ok_when_installed_matches_pin(lock_file):
    res = attest_all(
        lock_file,
        version_resolver=lambda d: {"dhanhq": "2.2.0", "neo-api-client": "1.0.0"}.get(d),
    )
    by = {r.broker: r for r in res}
    assert by["dhanhq"].status == STATUS_OK
    assert by["neo-api-client"].status == STATUS_OK
    # Placeholder pin → not yet live → skipped (not a failure).
    assert by["upstox-python-sdk"].status == STATUS_SKIPPED
    assert attest_all_ok(res) is True


def test_mismatch_and_missing_are_failures(lock_file):
    res = attest_all(lock_file, version_resolver=lambda d: {"dhanhq": "2.1.0"}.get(d))
    by = {r.broker: r for r in res}
    assert by["dhanhq"].status == STATUS_MISMATCH
    assert by["neo-api-client"].status == STATUS_MISSING
    assert {f.broker for f in required_failures(res)} == {"dhanhq", "neo-api-client"}
    assert attest_all_ok(res) is False


def test_loads_the_repo_brokers_lock():
    pins = load_pins()
    names = {p.get("name") for p in pins}
    assert "dhanhq" in names  # the repo's wave-1 pin
    assert "growwapi" in names


def test_missing_lock_returns_empty(tmp_path):
    assert attest_all(tmp_path / "nope.lock", version_resolver=lambda d: None) == []
