"""Unit tests for the Obsidian vault connector."""

from __future__ import annotations

import pytest

from flinttrade_ai.obsidian_bridge import ObsidianError, ObsidianVault

pytestmark = pytest.mark.unit


@pytest.fixture
def vault(tmp_path):
    (tmp_path / "Daily").mkdir()
    (tmp_path / "Daily" / "2026-06-05.md").write_text("NIFTY long thesis\n", encoding="utf-8")
    (tmp_path / "ideas.md").write_text("Iron condor on BANKNIFTY\n", encoding="utf-8")
    return ObsidianVault(tmp_path)


def test_available_and_list(vault):
    assert vault.available is True
    assert vault.list_notes() == ["Daily/2026-06-05.md", "ideas.md"]


def test_unavailable_vault(tmp_path):
    v = ObsidianVault(tmp_path / "nope")
    assert v.available is False
    assert v.list_notes() == []
    with pytest.raises(ObsidianError, match="not found"):
        v.read_note("anything")


def test_read_note(vault):
    assert "Iron condor" in vault.read_note("ideas.md")
    assert "NIFTY" in vault.read_note("Daily/2026-06-05.md")


def test_write_creates_dirs_and_appends_md(vault):
    rel = vault.write_note("Journal/today", "Closed the straddle at +2R")
    assert rel == "Journal/today.md"
    assert "+2R" in vault.read_note("Journal/today.md")


def test_append_note(vault):
    vault.append_note("ideas.md", "Add calendar spread")
    body = vault.read_note("ideas.md")
    assert "Iron condor" in body and "calendar spread" in body


def test_path_traversal_is_blocked(vault):
    with pytest.raises(ObsidianError, match="escapes the vault"):
        vault.read_note("../secret.md")
    with pytest.raises(ObsidianError, match="escapes the vault"):
        vault.write_note("../../evil", "x")


def test_missing_note_raises(vault):
    with pytest.raises(ObsidianError, match="not found"):
        vault.read_note("does-not-exist.md")


def test_search_matches_name_and_body(vault):
    by_body = vault.search("iron condor")
    assert any(h["path"] == "ideas.md" for h in by_body)
    by_name = vault.search("2026-06-05")
    assert any(h["path"] == "Daily/2026-06-05.md" for h in by_name)
    assert vault.search("   ") == []


def test_delete_note(vault):
    vault.delete_note("ideas.md")
    assert "ideas.md" not in vault.list_notes()
