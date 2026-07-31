"""Tests for the AI1 skill-draft write path (drafts, approval, routes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify

from flinttrade_ai.skill_draft_routes import skill_draft_bp
from flinttrade_ai.skill_drafts import (
    approve_draft,
    draft_skill_from_reflection,
    drafts_dir,
    is_valid_slug,
    read_draft,
    reject_draft,
    skills_dir,
)
from flinttrade_ai.skill_system import SkillRegistry
from flinttrade_ai.trade_reflection import ReflectionResult

pytestmark = pytest.mark.unit


def _result(**overrides: Any) -> ReflectionResult:
    base: dict[str, Any] = {
        "trades_analysed": 4,
        "win_rate": 0.5,
        "avg_pnl": 1.2,
        "winning_patterns": ["Momentum entries after 10:00 worked"],
        "losing_patterns": ["Chasing gap-ups failed"],
        "recommendations": ["Wait for the first 30-minute range"],
        "market_insights": "Choppy expiry-day session.",
    }
    base.update(overrides)
    return ReflectionResult(**base)


# ---------------------------------------------------------------------------
# Draft rendering
# ---------------------------------------------------------------------------


def test_draft_renders_frontmatter_and_sections(tmp_path: Path) -> None:
    path = draft_skill_from_reflection(
        tmp_path, _result(), session_date="2026-07-19", symbols=["RELIANCE", "HDFCBANK"]
    )
    assert path is not None and path.parent == drafts_dir(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "status: draft" in text
    assert "name: session-lessons-2026-07-19" in text
    assert "RELIANCE, HDFCBANK" in text
    assert "## Recommendations" in text
    assert "## Winning patterns" in text
    assert "## Losing patterns" in text
    assert "Choppy expiry-day session." in text


def test_redrafting_the_same_date_overwrites(tmp_path: Path) -> None:
    draft_skill_from_reflection(tmp_path, _result(), session_date="2026-07-19", symbols=["X"])
    draft_skill_from_reflection(
        tmp_path,
        _result(recommendations=["Second pass"]),
        session_date="2026-07-19",
        symbols=["X"],
    )
    assert len(list(drafts_dir(tmp_path).glob("*.md"))) == 1
    assert "Second pass" in read_draft(tmp_path, "session-lessons-2026-07-19")


def test_empty_reflection_produces_no_draft(tmp_path: Path) -> None:
    empty = _result(winning_patterns=[], losing_patterns=[], recommendations=[])
    assert (
        draft_skill_from_reflection(tmp_path, empty, session_date="2026-07-19", symbols=[])
        is None
    )
    assert not drafts_dir(tmp_path).exists()


def test_slug_validation_blocks_traversal(tmp_path: Path) -> None:
    assert not is_valid_slug("../etc/passwd")
    assert not is_valid_slug("a/b")
    assert not is_valid_slug("")
    assert read_draft(tmp_path, "../secrets") is None
    assert reject_draft(tmp_path, "..") is False
    with pytest.raises(ValueError):
        approve_draft(tmp_path, "../x")


def test_slug_validation_rejects_a_trailing_newline(tmp_path: Path) -> None:
    """A ``$``-anchored match would have admitted "name\\n"; fullmatch does not."""
    draft_skill_from_reflection(tmp_path, _result(), session_date="2026-07-19", symbols=["X"])
    assert not is_valid_slug("session-lessons-2026-07-19\n")
    assert read_draft(tmp_path, "session-lessons-2026-07-19\n") is None
    assert reject_draft(tmp_path, "session-lessons-2026-07-19\n") is False
    with pytest.raises(ValueError):
        approve_draft(tmp_path, "session-lessons-2026-07-19\n")
    # The real draft is untouched.
    assert read_draft(tmp_path, "session-lessons-2026-07-19") is not None


# ---------------------------------------------------------------------------
# Approve / reject + registry visibility
# ---------------------------------------------------------------------------


def test_approve_moves_flips_status_and_registry_sees_only_approved(tmp_path: Path) -> None:
    draft_skill_from_reflection(tmp_path, _result(), session_date="2026-07-19", symbols=["X"])

    registry = SkillRegistry(skills_dir(tmp_path))
    # Drafts are invisible to the registry by construction.
    assert len(registry) == 0
    assert registry.get_system_prompt_section() == "" or "session-lessons" not in (
        registry.get_system_prompt_section()
    )

    approve_draft(tmp_path, "session-lessons-2026-07-19")
    assert not (drafts_dir(tmp_path) / "session-lessons-2026-07-19.md").exists()
    approved = (skills_dir(tmp_path) / "session-lessons-2026-07-19.md").read_text(encoding="utf-8")
    assert "status: approved" in approved
    assert "status: draft" not in approved

    registry.reload()
    assert "session-lessons-2026-07-19" in registry
    assert "session-lessons-2026-07-19" in registry.get_system_prompt_section()


def test_reject_deletes(tmp_path: Path) -> None:
    draft_skill_from_reflection(tmp_path, _result(), session_date="2026-07-19", symbols=["X"])
    assert reject_draft(tmp_path, "session-lessons-2026-07-19") is True
    assert reject_draft(tmp_path, "session-lessons-2026-07-19") is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    flask_app = Flask(__name__)
    flask_app.register_blueprint(skill_draft_bp)
    flask_app.config["WORKSPACE_DIR"] = tmp_path
    draft_skill_from_reflection(tmp_path, _result(), session_date="2026-07-19", symbols=["X"])
    return flask_app


def test_routes_list_and_read(app: Flask) -> None:
    client = app.test_client()
    listed = client.get("/api/v1/ai/skill-drafts")
    assert listed.status_code == 200
    rows = listed.get_json()["data"]
    assert rows and rows[0]["name"] == "session-lessons-2026-07-19"

    one = client.get("/api/v1/ai/skill-drafts/session-lessons-2026-07-19")
    assert one.status_code == 200
    assert "status: draft" in one.get_json()["data"]["content"]


def test_routes_approve_and_reject_are_guarded(app: Flask, tmp_path: Path) -> None:
    denials: list[bool] = []

    def guard() -> Any:
        denials.append(True)
        return jsonify({"status": "error", "message": "operator session required"}), 401

    app.config["BROKER_MGMT_WRITE_GUARD"] = guard
    client = app.test_client()
    assert client.post("/api/v1/ai/skill-drafts/session-lessons-2026-07-19/approve").status_code == 401
    assert client.delete("/api/v1/ai/skill-drafts/session-lessons-2026-07-19").status_code == 401
    assert len(denials) == 2

    # Guard passing: approve moves the file and reloads the registry.
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    registry = SkillRegistry(skills_dir(tmp_path))
    app.config["SKILL_REGISTRY"] = registry
    resp = client.post("/api/v1/ai/skill-drafts/session-lessons-2026-07-19/approve")
    assert resp.status_code == 200
    assert "session-lessons-2026-07-19" in registry

    # Approving again → 404; rejecting a missing draft → 404; bad slug → 400.
    assert client.post("/api/v1/ai/skill-drafts/session-lessons-2026-07-19/approve").status_code == 404
    assert client.delete("/api/v1/ai/skill-drafts/session-lessons-2026-07-19").status_code == 404
    assert client.post("/api/v1/ai/skill-drafts/BAD_NAME/approve").status_code == 400


def test_a_directory_named_like_a_draft_is_not_a_draft(tmp_path: Path) -> None:
    """A directory called ``<slug>.md`` must not be served as a draft.

    ``Path.glob`` yields directories as well as files, so selecting the draft
    out of a listing rather than joining a path drops the ``is_file`` guarantee
    unless it is restated. Reading one then raises ``IsADirectoryError`` on
    POSIX and ``PermissionError`` on Windows, and the routes catch neither - a
    documented 404 becomes an unhandled 500.
    """
    directory = drafts_dir(tmp_path)
    directory.mkdir(parents=True)
    (directory / "trap.md").mkdir()

    assert read_draft(tmp_path, "trap") is None
    assert reject_draft(tmp_path, "trap") is False
    with pytest.raises(FileNotFoundError):
        approve_draft(tmp_path, "trap")
