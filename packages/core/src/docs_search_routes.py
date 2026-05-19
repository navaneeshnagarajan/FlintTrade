"""In-app documentation search — full-text index over docs/ markdown files.

Builds a simple inverted index with TF-IDF ranking on startup. Rebuilt
automatically when the server restarts. The index is cached in memory for
the lifetime of the process.

Also serves CHANGELOG.md content for the in-app changelog viewer.

Blueprint prefix: /v1/docs

Endpoints:
    GET /v1/docs/search?q=<query>&limit=10   — full-text search
    GET /v1/docs/changelog                    — raw CHANGELOG.md content
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request, Response

logger = logging.getLogger("flinttrade.docs_search")

docs_search_bp = Blueprint("docs_search", __name__, url_prefix="/v1/docs")

# ---------------------------------------------------------------------------
# Repository root (3 levels above packages/core/src/)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCS_DIR = _REPO_ROOT / "docs"
_CHANGELOG_PATH = _REPO_ROOT / "CHANGELOG.md"

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search result with path, title, snippet, and relevance score."""

    path: str
    title: str
    snippet: str
    score: float


@dataclass
class _DocEntry:
    """Internal index entry for a single document."""

    path: str
    title: str
    body: str
    tokens: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------


def _tokenise(text: str) -> list[str]:
    """Lowercase + split on non-word characters, removing stop words.

    Args:
        text: Raw markdown or plain text.

    Returns:
        List of lowercase token strings.
    """
    _STOP = frozenset(
        {
            "a", "an", "and", "are", "as", "at", "be", "been", "but",
            "by", "for", "from", "has", "have", "i", "in", "is", "it",
            "its", "of", "on", "or", "that", "the", "this", "to", "was",
            "were", "will", "with",
        }
    )
    # Strip markdown syntax noise (headers, code fences, links)
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]+`", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"[#*_>~]", " ", cleaned)
    words = re.findall(r"\b[a-z][a-z0-9_-]{1,}\b", cleaned.lower())
    return [w for w in words if w not in _STOP]


# ---------------------------------------------------------------------------
# Index class
# ---------------------------------------------------------------------------


class DocsIndex:
    """Inverted index with TF-IDF ranking over markdown documents in docs/.

    Build once on startup, then search in O(|query terms| * |posting list|).

    Attributes:
        _docs: List of indexed document entries.
        _index: Inverted index mapping token → set of doc indices.
        _idf: IDF weight per token.
        _lock: Thread lock guarding all reads after build.
        _ready: True once build() has completed.
    """

    def __init__(self) -> None:
        self._docs: list[_DocEntry] = []
        self._index: dict[str, set[int]] = {}
        self._idf: dict[str, float] = {}
        self._lock = threading.RLock()
        self._ready = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, docs_dir: Path) -> None:
        """Scan docs_dir recursively and index all *.md files.

        Safe to call from any thread. Thread-safe write via lock.

        Args:
            docs_dir: Root directory to scan for markdown files.
        """
        if not docs_dir.exists():
            logger.warning("docs_dir does not exist: %s", docs_dir)
            with self._lock:
                self._ready = True
            return

        md_files = list(docs_dir.rglob("*.md"))
        logger.info("DocsIndex: indexing %d markdown files in %s", len(md_files), docs_dir)

        entries: list[_DocEntry] = []
        for md_path in md_files:
            try:
                body = md_path.read_text(encoding="utf-8", errors="replace")
                rel = str(md_path.relative_to(docs_dir))
                title = _extract_title(body) or md_path.stem.replace("-", " ").replace("_", " ").title()
                tokens = _tokenise(body)
                entries.append(_DocEntry(path=rel, title=title, body=body, tokens=tokens))
            except OSError as exc:
                logger.warning("Cannot read %s: %s", md_path, exc)

        # Build inverted index
        inv: dict[str, set[int]] = {}
        for i, entry in enumerate(entries):
            seen: set[str] = set()
            for tok in entry.tokens:
                if tok not in seen:
                    seen.add(tok)
                    inv.setdefault(tok, set()).add(i)

        # IDF
        n = len(entries) or 1
        idf = {tok: math.log((n + 1) / (len(docs) + 1)) for tok, docs in inv.items()}

        with self._lock:
            self._docs = entries
            self._index = inv
            self._idf = idf
            self._ready = True

        logger.info("DocsIndex: built index with %d tokens over %d docs", len(inv), len(entries))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Full-text search with TF-IDF ranking.

        Args:
            query: User query string (space-separated terms).
            limit: Maximum results to return.

        Returns:
            List of :class:`SearchResult` ordered by descending score.
        """
        if not query.strip():
            return []

        with self._lock:
            if not self._ready:
                return []
            docs = self._docs
            inv = self._index
            idf = self._idf

        query_tokens = _tokenise(query)
        if not query_tokens:
            return []

        # Candidate docs: union of posting lists
        candidate_ids: set[int] = set()
        for tok in query_tokens:
            candidate_ids.update(inv.get(tok, set()))

        if not candidate_ids:
            return []

        # Score each candidate
        scored: list[tuple[float, int]] = []
        for doc_id in candidate_ids:
            entry = docs[doc_id]
            n_tokens = len(entry.tokens) or 1
            score = 0.0
            for tok in query_tokens:
                tf = entry.tokens.count(tok) / n_tokens
                score += tf * idf.get(tok, 0.0)
            if score > 0:
                scored.append((score, doc_id))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[SearchResult] = []
        for score, doc_id in scored[:limit]:
            entry = docs[doc_id]
            snippet = _extract_snippet(entry.body, query_tokens)
            results.append(
                SearchResult(
                    path=entry.path,
                    title=entry.title,
                    snippet=snippet,
                    score=round(score, 4),
                )
            )

        return results

    @property
    def doc_count(self) -> int:
        """Number of documents currently in the index."""
        with self._lock:
            return len(self._docs)

    @property
    def ready(self) -> bool:
        """True once the index has been built."""
        with self._lock:
            return self._ready


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------


def _extract_title(body: str) -> str | None:
    """Extract the first # heading from markdown content.

    Args:
        body: Raw markdown text.

    Returns:
        Title string, or None if not found.
    """
    for line in body.splitlines():
        m = re.match(r"^#+\s+(.+)", line)
        if m:
            return m.group(1).strip()
    return None


def _extract_snippet(body: str, query_tokens: list[str], window: int = 160) -> str:
    """Find the best sentence-level snippet containing the most query terms.

    Args:
        body: Full document text.
        query_tokens: Tokenised query.
        window: Approximate character window for the snippet.

    Returns:
        Snippet string with leading/trailing ellipsis as needed.
    """
    # Split into sentences/lines
    lines = [line.strip() for line in re.split(r"[\n.!?]+", body) if line.strip()]
    best_line = ""
    best_hits = -1

    for line in lines:
        line_lower = line.lower()
        hits = sum(1 for tok in query_tokens if tok in line_lower)
        if hits > best_hits:
            best_hits = hits
            best_line = line

    if not best_line:
        # Fallback: first non-empty, non-heading line
        for line in lines:
            if not line.startswith("#"):
                best_line = line
                break

    # Trim to window size
    if len(best_line) > window:
        best_line = best_line[:window] + "…"

    return best_line or ""


# ---------------------------------------------------------------------------
# Module-level index singleton + background build
# ---------------------------------------------------------------------------

_index = DocsIndex()
_build_lock = threading.Lock()
_built = False


def _ensure_built() -> None:
    """Build the index once, in a background thread, on first access."""
    global _built  # noqa: PLW0603
    with _build_lock:
        if not _built:
            _built = True
            t = threading.Thread(
                target=_index.build,
                args=(_DOCS_DIR,),
                daemon=True,
                name="docs-index-build",
            )
            t.start()


def rebuild_index(docs_dir: Path | None = None) -> None:
    """Force a full rebuild of the docs index.

    Args:
        docs_dir: Directory to scan. Defaults to docs/ at the repo root.
    """
    global _built  # noqa: PLW0603
    with _build_lock:
        _built = True
    _index.build(docs_dir or _DOCS_DIR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@docs_search_bp.route("/search", methods=["GET"])
def search_docs() -> Any:
    """Search the docs index.

    Query parameters:
        q     — search query (required)
        limit — max results, 1-50 (default 10)

    Response::

        {
            "query": "order placement",
            "results": [
                {
                    "path": "guides/order-placement.md",
                    "title": "Order Placement Guide",
                    "snippet": "FlintTrade supports …",
                    "score": 0.042
                },
                ...
            ],
            "total": 3
        }

    Returns:
        JSON search response.

    Raises:
        400: If ``q`` parameter is missing.
    """
    _ensure_built()

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"status": "error", "message": "Missing 'q' query parameter"}), 400

    try:
        limit = max(1, min(50, int(request.args.get("limit", 10))))
    except (ValueError, TypeError):
        limit = 10

    results = _index.search(query, limit=limit)
    return jsonify(
        {
            "query": query,
            "results": [
                {
                    "path": r.path,
                    "title": r.title,
                    "snippet": r.snippet,
                    "score": r.score,
                }
                for r in results
            ],
            "total": len(results),
        }
    )


@docs_search_bp.route("/changelog", methods=["GET"])
def get_changelog() -> Any:
    """Serve the repo CHANGELOG.md as plain text.

    Used by the in-app ChangelogViewer component to render version history.

    Returns:
        Plain text response with CHANGELOG.md content, or 404 if not found.
    """
    if not _CHANGELOG_PATH.exists():
        return Response("", status=404, mimetype="text/plain")
    try:
        content = _CHANGELOG_PATH.read_text(encoding="utf-8")
        return Response(content, status=200, mimetype="text/plain")
    except OSError as exc:
        logger.error("Cannot read CHANGELOG.md: %s", exc)
        return Response("", status=500, mimetype="text/plain")
