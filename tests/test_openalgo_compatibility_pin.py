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
    assert f'"last_absorbed_commit": "{EXPECTED_OPENALGO_SHORT_SHA}"' in absorption
