"""Repository policy checks for broker SDK update monitoring."""

from __future__ import annotations

import json
import pathlib
import tomllib


REPO = pathlib.Path(__file__).resolve().parents[1]


def test_all_pinned_broker_sdks_are_in_manual_renovate_group() -> None:
    """Every activated broker SDK pin should need explicit founder review."""

    brokers = tomllib.loads((REPO / "brokers.lock").read_text(encoding="utf-8"))
    pinned = {
        str(entry["name"])
        for entry in brokers.get("broker", [])
        if isinstance(entry, dict) and str(entry.get("version", "")).strip()
    }

    renovate = json.loads((REPO / "renovate.json").read_text(encoding="utf-8"))
    manual_groups = [
        rule
        for rule in renovate.get("packageRules", [])
        if rule.get("groupName") == "python brokers (manual review only)"
    ]
    watched = {name for rule in manual_groups for name in rule.get("matchPackageNames", [])}

    assert pinned <= watched
    assert all(rule.get("automerge") is False for rule in manual_groups)
    assert all("needs-sandbox-smoke-test" in rule.get("labels", []) for rule in manual_groups)
