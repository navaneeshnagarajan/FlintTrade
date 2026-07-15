"""Durable global safety-configuration contract."""

from __future__ import annotations

import json

import pytest

from flinttrade_core.safety_config import (
    load_workspace_safety_config,
    persist_workspace_safety_config,
)
from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
from flinttrade_engine.safety import SafetyConfig


def test_fresh_workspace_loads_complete_validated_defaults(tmp_path):
    config = load_workspace_safety_config(tmp_path)

    assert config == SafetyConfig()
    persisted = json.loads((tmp_path / "workspace.json").read_text(encoding="utf-8"))
    assert persisted["safety"] == config.to_mapping()


def test_current_version_missing_safety_section_fails_closed(tmp_path):
    (tmp_path / "workspace.json").write_text(
        json.dumps({"version": WORKSPACE_VERSION, "initialized": True}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing or invalid"):
        load_workspace_safety_config(tmp_path)


def test_persisted_config_survives_a_fresh_loader(tmp_path):
    load_workspace_safety_config(tmp_path)
    candidate = SafetyConfig(max_positions=12, pnl_pause_pct=4.0, pnl_kill_pct=9.0)

    persist_workspace_safety_config(tmp_path, candidate)

    assert load_workspace_safety_config(tmp_path) == candidate


def test_strict_loader_rejects_invalid_threshold_order(tmp_path):
    raw = {
        "version": WORKSPACE_VERSION,
        "initialized": True,
        "safety": SafetyConfig().to_mapping(),
    }
    raw["safety"]["pnl_kill_pct"] = 2.0
    (tmp_path / "workspace.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="greater than"):
        load_workspace_safety_config(tmp_path)
