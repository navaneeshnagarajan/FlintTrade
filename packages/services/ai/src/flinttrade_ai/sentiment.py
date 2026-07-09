"""Financial news sentiment analysis.

Adapts finnews-ai patterns. Parses RSS feeds, extracts entities (symbols),
scores sentiment via LLM, and aggregates per-symbol per-day scores.
"""

from __future__ import annotations

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import timedelta, timezone
from typing import Any

import httpx

from .llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.sentiment")

IST = timezone(timedelta(hours=5, minutes=30))

# Default financial RSS feeds, keyed for NewsScraper callers.
RSS_SOURCES: dict[str, str] = {
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    "economictimes": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "livemint": "https://www.livemint.com/rss/markets",
}
DEFAULT_FEEDS: list[str] = [
    RSS_SOURCES["economictimes"],
    RSS_SOURCES["moneycontrol"],
    RSS_SOURCES["livemint"],
]
_CACHE_TTL_SECS = 900.0

# Common NSE symbols for entity extraction
_SYMBOL_PATTERNS = [
    "NIFTY",
    "BANKNIFTY",
    "SENSEX",
    "FINNIFTY",
    "MIDCPNIFTY",
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "HDFC",
    "BHARTIARTL",
    "ITC",
    "KOTAKBANK",
    "LT",
    "HCLTECH",
    "AXISBANK",
    "WIPRO",
    "MARUTI",
    "TATAMOTORS",
    "TATASTEEL",
    "ADANIENT",
    "ADANIPORTS",
    "BAJFINANCE",
    "BAJAJFINSV",
    "TITAN",
    "SUNPHARMA",
    "NESTLEIND",
    "POWERGRID",
    "NTPC",
    "GOLD",
    "SILVER",
    "CRUDEOIL",
    "NATURALGAS",
]


@dataclass
class NewsArticle:
    """A parsed news article."""

    title: str = ""
    summary: str = ""
    link: str = ""
    published: str = ""
    source: str = ""
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            digest = hashlib.sha256(f"{self.title}{self.link}".encode()).hexdigest()
            self.content_hash = digest[:12]

    def to_dict(self) -> dict[str, str]:
        """Return all article fields in JSON-ready form."""
        return asdict(self)


@dataclass
class SentimentScore:
    """Sentiment analysis result for a single article."""

    article_title: str = ""
    sentiment: str = ""  # "BULLISH", "BEARISH", "NEUTRAL"
    confidence: float = 0.0  # 0.0 to 1.0
    symbols: list[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: str = ""


@dataclass
class AggregatedSentiment:
    """Aggregated sentiment for a symbol over a period."""

    symbol: str = ""
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    avg_confidence: float = 0.0
    net_score: float = 0.0  # -1.0 (very bearish) to +1.0 (very bullish)
    article_count: int = 0

    @property
    def dominant_sentiment(self) -> str:
        if self.net_score > 0.2:
            return "BULLISH"
        if self.net_score < -0.2:
            return "BEARISH"
        return "NEUTRAL"


# ---------------------------------------------------------------------------
# RSS feed parsing
# ---------------------------------------------------------------------------


def _parse_rss_xml(xml_text: str, source_name: str) -> list[NewsArticle]:
    """Parse RSS 2.0 or Atom XML with the standard library."""
    articles: list[NewsArticle] = []

    try:
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("XML parse error for %s: %s", source_name, exc)
        return articles

    atom_ns = ""
    if root.tag.startswith("{"):
        atom_ns = root.tag.split("}")[0] + "}"

    items = root.findall(".//item")
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
    """Find child text, trying namespaced and plain tags."""
    child = element.find(f"{ns}{tag}") if ns else None
    if child is None:
        child = element.find(tag)
    return child.text if child is not None and child.text else None


def _link(element: ET.Element, ns: str = "") -> str:
    """Extract an RSS text link or Atom href link."""
    link_element = element.find("link")
    if link_element is not None and link_element.text:
        return link_element.text

    if ns:
        link_element = element.find(f"{ns}link")
    if link_element is not None:
        return link_element.get("href", "")
    return ""


def _strip_html(text: str) -> str:
    """Remove HTML tags without an additional parser dependency."""
    result: list[str] = []
    in_tag = False
    for character in text:
        if character == "<":
            in_tag = True
        elif character == ">":
            in_tag = False
        elif not in_tag:
            result.append(character)
    return "".join(result)


class NewsScraper:
    """Cached RSS news client for the configured Indian-market sources."""

    def __init__(self, timeout: float = 15.0, cache_ttl: float = _CACHE_TTL_SECS) -> None:
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, list[NewsArticle]]] = {}

    def fetch_headlines(self, source: str, limit: int | None = 20) -> list[NewsArticle]:
        """Fetch one named source or custom RSS URL, using the per-source cache."""
        url = RSS_SOURCES.get(source.lower())
        if url is None:
            if source.startswith("http"):
                url = source
            else:
                raise ValueError(f"Unknown source: {source!r}. Use one of {list(RSS_SOURCES)} or provide a URL.")

        articles = self._fetch_cached(source.lower(), url)
        return articles if limit is None else articles[:limit]

    def search_news(self, query: str, limit: int = 20) -> list[NewsArticle]:
        """Search titles and summaries across all default RSS sources."""
        self._refresh_all()
        query_lower = query.lower()
        matches = [
            article
            for _timestamp, articles in self._cache.values()
            for article in articles
            if query_lower in f"{article.title} {article.summary}".lower()
        ]
        return self._deduplicate(matches)[:limit]

    def get_latest(self, limit: int = 20) -> list[NewsArticle]:
        """Return combined headlines from all default sources."""
        self._refresh_all()
        articles = [article for _timestamp, cached_articles in self._cache.values() for article in cached_articles]
        return self._deduplicate(articles)[:limit]

    def _refresh_all(self) -> None:
        for key, url in RSS_SOURCES.items():
            self._fetch_cached(key, url)

    def _fetch_cached(self, source_key: str, url: str) -> list[NewsArticle]:
        now = time.monotonic()
        cached = self._cache.get(source_key)
        if cached is not None and now - cached[0] < self._cache_ttl:
            return cached[1]

        articles = self._fetch_rss(url, source_key)
        self._cache[source_key] = (now, articles)
        return articles

    def _fetch_rss(self, url: str, source_name: str) -> list[NewsArticle]:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, follow_redirects=True)
                response.raise_for_status()
            articles = _parse_rss_xml(response.text, source_name)
            logger.info("Fetched %d articles from %s (%s)", len(articles), source_name, url)
            return articles
        except httpx.HTTPError as exc:
            logger.warning("HTTP error fetching %s: %s", url, exc)
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", url, exc)
        return []

    @staticmethod
    def _deduplicate(articles: list[NewsArticle]) -> list[NewsArticle]:
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for article in articles:
            if article.title not in seen:
                seen.add(article.title)
                unique.append(article)
        return unique


_DEFAULT_NEWS_SCRAPER: NewsScraper | None = None


def parse_feed(feed_url: str) -> list[NewsArticle]:
    """Fetch and parse an RSS/Atom feed through the shared cached stdlib engine."""
    global _DEFAULT_NEWS_SCRAPER
    if _DEFAULT_NEWS_SCRAPER is None:
        _DEFAULT_NEWS_SCRAPER = NewsScraper()
    return _DEFAULT_NEWS_SCRAPER.fetch_headlines(feed_url, limit=None)


def extract_symbols(text: str) -> list[str]:
    """Extract stock/index symbols mentioned in text."""
    text_upper = text.upper()
    found: list[str] = []
    for sym in _SYMBOL_PATTERNS:
        if sym in text_upper:
            found.append(sym)
    return found


# ---------------------------------------------------------------------------
# LLM-based sentiment scoring
# ---------------------------------------------------------------------------

_SENTIMENT_PROMPT = """Analyse the following financial news headline and summary for market sentiment.
Respond with EXACTLY this JSON format (no other text):
{{"sentiment": "BULLISH" or "BEARISH" or "NEUTRAL", "confidence": 0.0 to 1.0, "reasoning": "brief reason"}}

Headline: {title}
Summary: {summary}"""


def score_article_with_llm(
    article: NewsArticle,
    llm: LLMClient,
) -> SentimentScore:
    """Score a single article's sentiment using the LLM."""
    prompt = _SENTIMENT_PROMPT.format(
        title=article.title,
        summary=article.summary[:300],
    )

    response = llm.chat(
        [
            LLMMessage(role="system", content="You are a financial sentiment analyst. Respond only with valid JSON."),
            LLMMessage(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=200,
    )

    if not response.success:
        return SentimentScore(
            article_title=article.title,
            sentiment="NEUTRAL",
            confidence=0.0,
            symbols=extract_symbols(article.title + " " + article.summary),
            timestamp=article.published,
        )

    # Parse JSON response
    sentiment = "NEUTRAL"
    confidence = 0.5
    reasoning = ""

    try:
        # Extract JSON from response (may have markdown wrapping)
        text = response.content.strip()
        if "```" in text:
            text = text.split("```")[1].strip()
            if text.startswith("json"):
                text = text[4:].strip()

        import json

        data = json.loads(text)
        sentiment = data.get("sentiment", "NEUTRAL").upper()
        if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
            sentiment = "NEUTRAL"
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        reasoning = data.get("reasoning", "")
    except (json.JSONDecodeError, ValueError, KeyError):
        logger.debug("Could not parse LLM sentiment response: %s", response.content[:100])

    return SentimentScore(
        article_title=article.title,
        sentiment=sentiment,
        confidence=confidence,
        symbols=extract_symbols(article.title + " " + article.summary),
        reasoning=reasoning,
        timestamp=article.published,
    )


def score_article_rule_based(article: NewsArticle) -> SentimentScore:
    """Simple rule-based sentiment (fallback when LLM unavailable)."""
    text = (article.title + " " + article.summary).lower()

    bullish_words = [
        "rally",
        "surge",
        "gain",
        "bullish",
        "breakout",
        "all-time high",
        "upgrade",
        "buy",
        "strong",
        "growth",
        "profit",
        "outperform",
    ]
    bearish_words = [
        "crash",
        "fall",
        "drop",
        "bearish",
        "breakdown",
        "sell",
        "downgrade",
        "weak",
        "loss",
        "decline",
        "correction",
    ]

    bull = sum(1 for w in bullish_words if w in text)
    bear = sum(1 for w in bearish_words if w in text)

    if bull > bear:
        sentiment = "BULLISH"
        confidence = min(0.9, 0.5 + bull * 0.1)
    elif bear > bull:
        sentiment = "BEARISH"
        confidence = min(0.9, 0.5 + bear * 0.1)
    else:
        sentiment = "NEUTRAL"
        confidence = 0.5

    return SentimentScore(
        article_title=article.title,
        sentiment=sentiment,
        confidence=confidence,
        symbols=extract_symbols(article.title + " " + article.summary),
        timestamp=article.published,
    )


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_sentiment(
    scores: list[SentimentScore],
    symbol: str | None = None,
) -> AggregatedSentiment:
    """Aggregate multiple sentiment scores, optionally filtered by symbol."""
    if symbol:
        scores = [s for s in scores if symbol in s.symbols]

    if not scores:
        return AggregatedSentiment(symbol=symbol or "")

    bullish = sum(1 for s in scores if s.sentiment == "BULLISH")
    bearish = sum(1 for s in scores if s.sentiment == "BEARISH")
    neutral = sum(1 for s in scores if s.sentiment == "NEUTRAL")
    avg_conf = sum(s.confidence for s in scores) / len(scores)

    # Net score: +1 for bullish, -1 for bearish, weighted by confidence
    net = sum(
        (1.0 if s.sentiment == "BULLISH" else -1.0 if s.sentiment == "BEARISH" else 0.0) * s.confidence for s in scores
    ) / len(scores)

    return AggregatedSentiment(
        symbol=symbol or "",
        bullish_count=bullish,
        bearish_count=bearish,
        neutral_count=neutral,
        avg_confidence=avg_conf,
        net_score=net,
        article_count=len(scores),
    )


# ---------------------------------------------------------------------------
# SentimentAnalyzer
# ---------------------------------------------------------------------------


class SentimentAnalyzer:
    """Financial news sentiment analyzer.

    Usage::

        analyzer = SentimentAnalyzer(llm_client=llm)
        scores = analyzer.analyze_feeds()
        nifty_sentiment = analyzer.get_symbol_sentiment(scores, "NIFTY")
        alerts = analyzer.detect_shifts(current_scores, previous_scores)
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        feeds: list[str] | None = None,
    ) -> None:
        self._llm = llm_client
        self._feeds = feeds or DEFAULT_FEEDS
        self._seen_hashes: set[str] = set()

    def fetch_articles(self) -> list[NewsArticle]:
        """Fetch articles from all configured RSS feeds."""
        all_articles: list[NewsArticle] = []
        for feed_url in self._feeds:
            articles = parse_feed(feed_url)
            # Deduplicate
            for a in articles:
                if a.content_hash not in self._seen_hashes:
                    self._seen_hashes.add(a.content_hash)
                    all_articles.append(a)

        logger.info("Fetched %d new articles from %d feeds", len(all_articles), len(self._feeds))
        return all_articles

    def score_articles(self, articles: list[NewsArticle]) -> list[SentimentScore]:
        """Score sentiment for a list of articles."""
        scores: list[SentimentScore] = []
        for article in articles:
            if self._llm:
                score = score_article_with_llm(article, self._llm)
            else:
                score = score_article_rule_based(article)
            scores.append(score)
        return scores

    def analyze_feeds(self) -> list[SentimentScore]:
        """Fetch + score all feeds in one call."""
        articles = self.fetch_articles()
        return self.score_articles(articles)

    def get_symbol_sentiment(
        self,
        scores: list[SentimentScore],
        symbol: str,
    ) -> AggregatedSentiment:
        """Get aggregated sentiment for a specific symbol."""
        return aggregate_sentiment(scores, symbol)

    @staticmethod
    def detect_shifts(
        current: list[SentimentScore],
        previous: list[SentimentScore],
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Detect extreme sentiment shifts between two analysis periods.

        Returns alerts when a symbol's net score changes by more than threshold.
        """
        # Get unique symbols across both periods
        all_symbols: set[str] = set()
        for s in current + previous:
            all_symbols.update(s.symbols)

        alerts: list[dict[str, Any]] = []
        for sym in all_symbols:
            curr = aggregate_sentiment(current, sym)
            prev = aggregate_sentiment(previous, sym)

            shift = curr.net_score - prev.net_score
            if abs(shift) >= threshold:
                alerts.append(
                    {
                        "symbol": sym,
                        "shift": shift,
                        "direction": "BULLISH" if shift > 0 else "BEARISH",
                        "current_score": curr.net_score,
                        "previous_score": prev.net_score,
                    }
                )

        return sorted(alerts, key=lambda a: abs(a["shift"]), reverse=True)
