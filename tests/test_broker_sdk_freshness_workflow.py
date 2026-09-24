"""Contract for the network-aware broker SDK freshness workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _ROOT / ".github" / "workflows" / "broker-sdk-freshness.yml"


@pytest.mark.unit
def test_broker_sdk_freshness_is_scheduled_and_manually_runnable() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in text
    assert "workflow_dispatch:" in text
    assert "python scripts/sync_broker_sdk_refs.py --fail-on-drift" in text
    assert "contents: read" in text
    assert "pull_request:" not in text
    assert "push:" not in text


@pytest.mark.unit
def test_broker_sdk_freshness_preserves_failure_evidence() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "if: always()" in text
    assert ".local/sdk-audit/manifest.json" in text
    assert ".local/sdk-audit/README.md" in text
    assert "retention-days: 30" in text
