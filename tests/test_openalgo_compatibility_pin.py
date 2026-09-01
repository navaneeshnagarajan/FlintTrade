"""Repository-level guard for the tested OpenAlgo compatibility pin."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OPENALGO_SHA = "ef1f6b9c2165607ae4c01edb9a3e189e26596d4d"
EXPECTED_OPENALGO_SHORT_SHA = "ef1f6b9c"
EXPECTED_OPENALGO_VERSION = "v2.0.2.2"
EXPECTED_OPENALGO_DATE = "2026-08-29"


def test_openalgo_test_dependency_and_compatibility_registry_use_v2_0_2_2() -> None:
    setup = (ROOT / "scripts" / "setup-test-deps.sh").read_text(encoding="utf-8")
    compatibility = (ROOT / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
    absorption = (ROOT / "scripts" / "check_absorption_drift.py").read_text(encoding="utf-8")

    assert EXPECTED_OPENALGO_SHA in setup
    assert (
        f"`{EXPECTED_OPENALGO_SHORT_SHA}` "
        f"({EXPECTED_OPENALGO_VERSION}, {EXPECTED_OPENALGO_DATE})"
    ) in compatibility
    assert f"| {EXPECTED_OPENALGO_VERSION} |" in compatibility
    assert f"**OpenAlgo minimum ({EXPECTED_OPENALGO_VERSION}):**" in compatibility
    assert f'"last_absorbed_commit": "{EXPECTED_OPENALGO_SHORT_SHA}"' in absorption


def test_openalgo_api_docs_preserve_broker_specific_modify_disclosure_contract() -> None:
    api = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")

    assert "Always forwards `trigger_price` and `disclosed_quantity`" not in api
    assert "full-replacement brokers" in api.lower()
    assert "partial-modify adapters" in api.lower()


def test_openalgo_option_chain_examples_put_apikey_in_json_body() -> None:
    api = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    section = api.split("### 7.4 Pull an option chain", maxsplit=1)[1].split(
        "### 7.5", maxsplit=1
    )[0]

    assert 'X-API-KEY' not in section
    assert '\\"apikey\\": \\"$OPENALGO_API_KEY\\"' in section
    assert "apikey = $env:OPENALGO_API_KEY" in section
    assert "fails closed before the request" not in section
    assert "FlintTrade's Python client and terminal helpers" in section
    assert "cross the network" in section
