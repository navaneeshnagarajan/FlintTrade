"""Tests for scripts/audit_repos.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_repos import (  # noqa: E402
    filter_repos,
    format_summary,
    format_table,
    load_status,
)


@pytest.fixture()
def sample_repos() -> dict[str, dict]:
    """Sample repo data for testing."""
    return {
        "openalgo": {
            "status": "integrated",
            "target_package": "gateway",
            "absorbed_patterns": ["REST API", "WebSocket"],
            "last_examined": "2026-03-24",
            "upstream_url": "https://github.com/marketcalls/openalgo",
            "notes": "Submodule. Adapter pattern.",
        },
        "FinRL": {
            "status": "unexamined",
            "target_package": "backtest-engine",
            "absorbed_patterns": [],
            "last_examined": None,
            "upstream_url": "https://github.com/AI4Finance-Foundation/FinRL",
            "notes": "Deep RL framework",
        },
        "openalgo-chatbot": {
            "status": "examined",
            "target_package": "ai",
            "absorbed_patterns": ["ChromaDB RAG"],
            "last_examined": "2026-03-22",
            "upstream_url": "https://github.com/marketcalls/openalgo-chatbot",
            "notes": "RAG patterns",
        },
    }


class TestFilterRepos:
    """Tests for filter_repos function."""

    def test_filter_by_status(self, sample_repos: dict) -> None:
        """Filter repos by status returns only matching repos."""
        result = filter_repos(sample_repos, status="integrated")
        assert len(result) == 1
        assert "openalgo" in result

    def test_filter_by_package(self, sample_repos: dict) -> None:
        """Filter repos by package returns only matching repos."""
        result = filter_repos(sample_repos, package="ai")
        assert len(result) == 1
        assert "openalgo-chatbot" in result

    def test_filter_no_match(self, sample_repos: dict) -> None:
        """Filter with no matches returns empty dict."""
        result = filter_repos(sample_repos, status="verified")
        assert len(result) == 0


class TestFormatTable:
    """Tests for format_table function."""

    def test_table_has_header(self, sample_repos: dict) -> None:
        """Table output includes header row."""
        output = format_table(sample_repos)
        assert "Repo" in output
        assert "Status" in output
        assert "Package" in output

    def test_table_has_all_repos(self, sample_repos: dict) -> None:
        """Table output includes all repo names."""
        output = format_table(sample_repos)
        assert "openalgo" in output
        assert "FinRL" in output
        assert "openalgo-chatbot" in output


class TestFormatSummary:
    """Tests for format_summary function."""

    def test_summary_counts(self, sample_repos: dict) -> None:
        """Summary shows correct counts per status."""
        output = format_summary(sample_repos, total_declared=222)
        assert "Tracked repos: 3" in output
        assert "Declared total: 222" in output
        assert "integrated: 1" in output
        assert "unexamined: 1" in output
        assert "examined: 1" in output


class TestLoadStatus:
    """Tests for load_status function."""

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """Loading a missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_status(tmp_path / "nonexistent.json")

    def test_load_valid_file(self, tmp_path: Path) -> None:
        """Loading a valid file returns parsed JSON."""
        data = {"version": "1.0", "repos": {"test": {"status": "examined"}}}
        target = tmp_path / "status.json"
        target.write_text(json.dumps(data), encoding="utf-8")
        result = load_status(target)
        assert result["version"] == "1.0"
        assert "test" in result["repos"]
