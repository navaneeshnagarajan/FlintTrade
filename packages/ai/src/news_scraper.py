"""RSS-based financial news scraper for Indian markets.

Uses httpx for HTTP and stdlib xml.etree for RSS parsing — no external
feed-parsing library required.  Results are cached in memory for 15 minutes.

Sources:
    - MoneyControl RSS (market reports)
    - Economic Times RSS (markets)
    - LiveMint RSS (markets)

Usage::

    scraper = NewsScraper()
    headlines = scraper.fetch_headlines("moneycontrol")
    results  = scraper.search_news("NIFTY")
    latest   = scraper.get_latest(limit=10)
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import timedelta, timezone

import httpx

logger = logging.getLogger("flinttrade.ai.news_scraper")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# RSS feed registry
# ---------------------------------------------------------------------------

RSS_SOURCES: dict[str, str] = {
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    "economictimes": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
}

_CACHE_TTL_SECS: float = 900.0  # 15 minutes

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class NewsArticle:
    """A single news article parsed from an RSS feed."""

    title: str
    link: str
    summary: str
    published: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


# ---------------------------------------------------------------------------
# RSS XML parser (stdlib only)
# ---------------------------------------------------------------------------


def _parse_rss_xml(xml_text: str, source_name: str) -> list[NewsArticle]:
    """Parse RSS 2.0 / Atom XML into NewsArticle objects.

    Handles both ``<item>`` (RSS 2.0) and ``<entry>`` (Atom) elements.
    Strips CDATA and HTML tags from descriptions.

    Args:
        xml_text: Raw XML string from the feed.
        source_name: Human-readable source label.

    Returns:
        List of NewsArticle objects extracted from the feed.
    """
    articles: list[NewsArticle] = []

    try:
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("XML parse error for %s: %s", source_name, exc)
        return articles

    # Detect Atom namespace
    atom_ns = ""
    if root.tag.startswith("{"):
        atom_ns = root.tag.split("}")[0] + "}"

    # RSS 2.0 items
    items = root.findall(".//item")

    # Atom entries (if no RSS items found)
    if not items:
        items = root.findall(f".//{atom_ns}entry") if atom_ns else root.findall(".//entry")

    for item in items:
        title = _text(item, "title", atom_ns) or ""
        link = _link(item, atom_ns) or ""
        summary = (
            _text(item, "description", atom_ns)
            or _text(item, "summary", atom_ns)
            or _text(item, "content", atom_ns)
            or ""
        )
        published = (
            _text(item, "pubDate", atom_ns)
            or _text(item, "published", atom_ns)
            or _text(item, "updated", atom_ns)
            or ""
        )

        if title:
            articles.append(
                NewsArticle(
                    title=_strip_html(title).strip(),
                    link=link.strip(),
                    summary=_strip_html(summary).strip()[:500],
                    published=published.strip(),
                    source=source_name,
                )
            )

    return articles


def _text(element: ET.Element, tag: str, ns: str = "") -> str | None:
    """Find child element text, trying both namespaced and plain tags."""
    child = element.find(f"{ns}{tag}") if ns else None
    if child is None:
        child = element.find(tag)
    return child.text if child is not None and child.text else None


def _link(element: ET.Element, ns: str = "") -> str:
    """Extract link from RSS <link> text or Atom <link href='...'>."""
    # RSS 2.0: <link>https://...</link>
    link_el = element.find("link")
    if link_el is not None and link_el.text:
        return link_el.text

    # Atom: <link href="https://..." />
    if ns:
        link_el = element.find(f"{ns}link")
    if link_el is not None:
        href = link_el.get("href", "")
        if href:
            return href

    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags from a string (simple regex-free approach)."""
    result: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            result.append(ch)
    return "".join(result)


# ---------------------------------------------------------------------------
# NewsScraper
# ---------------------------------------------------------------------------


class NewsScraper:
    """Financial news scraper for Indian markets using RSS feeds.

    Fetches from MoneyControl, Economic Times, and LiveMint RSS feeds.
    Caches results for 15 minutes to avoid hammering the sources.

    Usage::

        scraper = NewsScraper()
        headlines = scraper.fetch_headlines("moneycontrol")
        results = scraper.search_news("Reliance")
        latest = scraper.get_latest(limit=10)
    """

    def __init__(
        self,
        timeout: float = 15.0,
        cache_ttl: float = _CACHE_TTL_SECS,
    ) -> None:
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        # Per-source cache: source_key -> (timestamp, articles)
        self._cache: dict[str, tuple[float, list[NewsArticle]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_headlines(
        self,
        source: str,
        limit: int = 20,
    ) -> list[NewsArticle]:
        """Fetch headlines from a specific RSS source.

        Args:
            source: Source key — one of ``moneycontrol``, ``economictimes``,
                ``livemint``, or a full URL.
            limit: Maximum number of articles to return.

        Returns:
            List of NewsArticle objects, newest first.

        Raises:
            ValueError: If *source* is not a recognised key and not a URL.
        """
        url = RSS_SOURCES.get(source.lower())
        if url is None:
            if source.startswith("http"):
                url = source
            else:
                raise ValueError(
                    f"Unknown source: {source!r}. "
                    f"Use one of {list(RSS_SOURCES)} or provide a URL."
                )

        source_key = source.lower()
        articles = self._fetch_cached(source_key, url)
        return articles[:limit]

    def search_news(
        self,
        query: str,
        limit: int = 20,
    ) -> list[NewsArticle]:
        """Search across all sources for articles matching a query.

        The search is case-insensitive and checks both title and summary.

        Args:
            query: Search string (e.g. ``"NIFTY"``, ``"Reliance"``).
            limit: Maximum number of results.

        Returns:
            Matching articles from all cached sources, newest first.
        """
        query_lower = query.lower()
        self._refresh_all()

        matches: list[NewsArticle] = []
        for _key, (_ts, articles) in self._cache.items():
            for article in articles:
                text = f"{article.title} {article.summary}".lower()
                if query_lower in text:
                    matches.append(article)

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique: list[NewsArticle] = []
        for art in matches:
            if art.title not in seen_titles:
                seen_titles.add(art.title)
                unique.append(art)

        return unique[:limit]

    def get_latest(
        self,
        limit: int = 20,
    ) -> list[NewsArticle]:
        """Get the latest headlines from all sources combined.

        Args:
            limit: Maximum number of articles to return.

        Returns:
            Combined articles from all sources, deduplicated by title.
        """
        self._refresh_all()

        all_articles: list[NewsArticle] = []
        for _key, (_ts, articles) in self._cache.items():
            all_articles.extend(articles)

        # Deduplicate by title
        seen_titles: set[str] = set()
        unique: list[NewsArticle] = []
        for art in all_articles:
            if art.title not in seen_titles:
                seen_titles.add(art.title)
                unique.append(art)

        return unique[:limit]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        """Ensure all default sources have been fetched (within cache TTL)."""
        for key, url in RSS_SOURCES.items():
            self._fetch_cached(key, url)

    def _fetch_cached(
        self,
        source_key: str,
        url: str,
    ) -> list[NewsArticle]:
        """Return articles for a source, fetching only if cache is stale."""
        now = time.monotonic()
        cached = self._cache.get(source_key)
        if cached is not None:
            ts, articles = cached
            if (now - ts) < self._cache_ttl:
                return articles

        articles = self._fetch_rss(url, source_key)
        self._cache[source_key] = (now, articles)
        return articles

    def _fetch_rss(self, url: str, source_name: str) -> list[NewsArticle]:
        """Download and parse an RSS feed.

        Args:
            url: RSS feed URL.
            source_name: Label for the source.

        Returns:
            Parsed articles, or an empty list on failure.
        """
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, follow_redirects=True)
                resp.raise_for_status()
                xml_text = resp.text

            articles = _parse_rss_xml(xml_text, source_name)
            logger.info(
                "Fetched %d articles from %s (%s)",
                len(articles),
                source_name,
                url,
            )
            return articles

        except httpx.HTTPError as exc:
            logger.warning("HTTP error fetching %s: %s", url, exc)
            return []
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", url, exc)
            return []
