"""Regression checks for the repository's canonical agent governance."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PIPELINE = "build agents (codex or claude) → claude ultracode multi-agent review panels → maintainer"
RETIRED_CODEX = re.compile(r"\bcodex\s+(?:is|was)\s+retired\b")


def _normalised_guidance(path: str) -> str:
    return " ".join((ROOT / path).read_text(encoding="utf-8").casefold().split())


def test_tracked_agent_guidance_uses_one_canonical_review_pipeline() -> None:
    """Every tracked governance guide preserves build, ultracode review, then maintainer."""
    violations: dict[str, list[str]] = {}
    for path in ("AGENTS.md", "CLAUDE.md", "docs/CI.md"):
        guidance = _normalised_guidance(path)
        issues: list[str] = []
        if CANONICAL_PIPELINE not in guidance:
            issues.append("missing canonical build → review → maintainer pipeline")
        if RETIRED_CODEX.search(guidance):
            issues.append("contradicts canonical pipeline by retiring Codex")
        if issues:
            violations[path] = issues

    assert violations == {}


def test_agents_points_to_the_real_private_plan_structure() -> None:
    """The tracked pointer must name the private plan structure that exists."""
    guidance = _normalised_guidance("AGENTS.md")
    violations: list[str] = []
    if "ordered delivery/status/current work queue" not in guidance:
        violations.append("missing real ordered delivery/status/current work queue pointer")
    if "phase tracker" in guidance:
        violations.append("points to nonexistent phase tracker")

    assert violations == []
