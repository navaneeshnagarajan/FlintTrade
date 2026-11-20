"""Regression checks for the public contributor guide."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETIRED_CODEX = re.compile(r"\bcodex\s+(?:is|was)\s+retired\b")
INTERNAL_PIPELINE = "build agents (codex or other supported agents)"


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _normalised(path: str) -> str:
    return " ".join(_text(path).casefold().split())


def test_contributor_guide_points_at_the_roadmap_and_reticle() -> None:
    """AGENTS.md is the contributor guide. CLAUDE.md points at it."""
    agents = _normalised("AGENTS.md")
    claude = _normalised("CLAUDE.md")
    ci = _normalised("docs/CI.md")

    assert "roadmap.md" in agents
    assert "reticle.md" in agents
    assert "agents.md" in claude
    assert "roadmap.md" in claude
    assert INTERNAL_PIPELINE not in agents
    assert INTERNAL_PIPELINE not in claude
    assert INTERNAL_PIPELINE not in ci
    assert RETIRED_CODEX.search(agents) is None
    assert RETIRED_CODEX.search(claude) is None


def test_agents_points_at_the_public_roadmap() -> None:
    """The contributor guide names the public roadmap and not a private queue."""
    guidance = _normalised("AGENTS.md")
    assert "roadmap.md" in guidance
    assert ".local/" not in _text("AGENTS.md")
    assert "phase tracker" not in guidance
    assert "ordered delivery/status/current work queue" not in guidance
