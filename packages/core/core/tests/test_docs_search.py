"""Tests for the in-app docs search index and routes.

Run with:
    python -m pytest packages/core/core/tests/test_docs_search.py -v --import-mode=importlib
"""
from __future__ import annotations


import pytest


# ---------------------------------------------------------------------------
# Unit tests: DocsIndex
# ---------------------------------------------------------------------------


class TestDocsIndex:
    """Unit tests for the DocsIndex class — tokeniser, build, and search."""

    def test_tokenise_strips_markdown_syntax(self):
        from flinttrade_core.docs_search_routes import _tokenise

        # Note: inline code (`market`) is intentionally stripped — test with unformatted words
        tokens = _tokenise("## Order Placement\n\nPlace orders via **OpenAlgo** REST API.")
        # Markdown noise stripped; meaningful words present
        assert "order" in tokens
        assert "placement" in tokens
        assert "openalgo" in tokens
        # Bold markers removed
        assert "**openalgo**" not in tokens

    def test_tokenise_removes_stop_words(self):
        from flinttrade_core.docs_search_routes import _tokenise

        tokens = _tokenise("This is a test of the tokeniser in the order module")
        assert "this" not in tokens
        assert "is" not in tokens
        assert "the" not in tokens
        assert "order" in tokens
        assert "module" in tokens

    def test_build_empty_dir(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        idx = DocsIndex()
        idx.build(tmp_path)
        assert idx.ready
        assert idx.doc_count == 0

    def test_build_nonexistent_dir(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        nonexistent = tmp_path / "does-not-exist"
        idx = DocsIndex()
        idx.build(nonexistent)
        assert idx.ready
        assert idx.doc_count == 0

    def test_build_indexes_markdown_files(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        (tmp_path / "guide.md").write_text("# Order Placement\n\nPlace orders via OpenAlgo.")
        (tmp_path / "concepts.md").write_text("# Backtesting\n\nRun simulations.")

        idx = DocsIndex()
        idx.build(tmp_path)
        assert idx.doc_count == 2

    def test_search_returns_relevant_results(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        (tmp_path / "order.md").write_text(
            "# Order Placement Guide\n\n"
            "FlintTrade supports market, limit, and stop orders via OpenAlgo API."
        )
        (tmp_path / "backtest.md").write_text(
            "# Backtesting Concepts\n\n"
            "Run vectorised historical simulations with the backtest engine."
        )

        idx = DocsIndex()
        idx.build(tmp_path)
        results = idx.search("order placement")
        assert len(results) >= 1
        assert results[0].path == "order.md"
        assert results[0].score > 0

    def test_search_empty_query_returns_empty(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        (tmp_path / "doc.md").write_text("# Test\n\nSome content.")
        idx = DocsIndex()
        idx.build(tmp_path)
        assert idx.search("") == []
        assert idx.search("   ") == []

    def test_search_respects_limit(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        for i in range(20):
            (tmp_path / f"doc{i}.md").write_text(
                f"# Document {i}\n\nThis document talks about orders and trading."
            )

        idx = DocsIndex()
        idx.build(tmp_path)
        results = idx.search("orders trading", limit=5)
        assert len(results) <= 5

    def test_search_no_match_returns_empty(self, tmp_path):
        from flinttrade_core.docs_search_routes import DocsIndex

        (tmp_path / "doc.md").write_text("# Guide\n\nSome generic content here.")
        idx = DocsIndex()
        idx.build(tmp_path)
        results = idx.search("xyzzynotfound")
        assert results == []


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestExtractTitle:
    def test_extracts_first_h1(self):
        from flinttrade_core.docs_search_routes import _extract_title
        assert _extract_title("# My Title\n\nSome text.") == "My Title"

    def test_extracts_h2_if_no_h1(self):
        from flinttrade_core.docs_search_routes import _extract_title
        assert _extract_title("## Section\n\nText.") == "Section"

    def test_returns_none_for_no_heading(self):
        from flinttrade_core.docs_search_routes import _extract_title
        assert _extract_title("Just a paragraph.") is None


class TestExtractSnippet:
    def test_prefers_line_with_most_query_terms(self):
        from flinttrade_core.docs_search_routes import _extract_snippet
        body = "This line has nothing.\nThis line mentions orders and trading.\nAnother line."
        snippet = _extract_snippet(body, ["orders", "trading"])
        assert "orders" in snippet.lower() or "trading" in snippet.lower()

    def test_truncates_long_lines(self):
        from flinttrade_core.docs_search_routes import _extract_snippet
        long_line = "order " * 50  # 300 chars
        snippet = _extract_snippet(long_line, ["order"])
        assert len(snippet) <= 165  # 160 + "…"


# ---------------------------------------------------------------------------
# Integration tests: routes
# ---------------------------------------------------------------------------


_TEST_DOCS_API_KEY = "test-docs-key"


def _auth() -> dict:
    return {"X-API-Key": _TEST_DOCS_API_KEY}


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def docs_app(tmp_path_factory, monkeypatch_module):
    """Flask app with docs_search blueprint + minimal test docs dir."""
    tmp_path = tmp_path_factory.mktemp("docs")
    (tmp_path / "order-guide.md").write_text(
        "# Order Placement Guide\n\n"
        "FlintTrade supports market and limit orders via the OpenAlgo REST API.\n"
        "Use the OrderPad widget to place orders interactively."
    )
    (tmp_path / "backtest.md").write_text(
        "# Backtesting\n\n"
        "Run vectorised simulations using the backtest engine.\n"
        "Supports walk-forward and Monte Carlo analysis."
    )

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_DOCS_API_KEY)
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True

    # Inject our test docs dir into the blueprint's index
    from flinttrade_core import docs_search_routes as dsr
    dsr._index = dsr.DocsIndex()
    dsr._index.build(tmp_path)
    dsr._built = True

    return app


@pytest.fixture()
def docs_client(docs_app):
    with docs_app.test_client() as c:
        yield c


class TestDocsSearchRoutes:
    def test_search_returns_results(self, docs_client):
        resp = docs_client.get("/v1/docs/search?q=order+placement", headers=_auth())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["query"] == "order placement"
        assert isinstance(data["results"], list)
        assert data["total"] >= 1

    def test_search_missing_query_returns_400(self, docs_client):
        resp = docs_client.get("/v1/docs/search", headers=_auth())
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"

    def test_search_no_results_returns_empty_list(self, docs_client):
        resp = docs_client.get("/v1/docs/search?q=xyzzynotfound", headers=_auth())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["results"] == []
        assert data["total"] == 0

    def test_search_limit_parameter(self, docs_client):
        resp = docs_client.get("/v1/docs/search?q=order&limit=1", headers=_auth())
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["results"]) <= 1

    def test_changelog_returns_content_or_404(self, docs_client):
        resp = docs_client.get("/v1/docs/changelog", headers=_auth())
        # Either 200 (file exists) or 404 (not at expected path in test env)
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            assert len(resp.data) > 0
