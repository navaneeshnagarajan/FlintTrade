"""Financial news sentiment analysis.

Adapts finnews-ai patterns. Parses RSS feeds, extracts entities (symbols),
scores sentiment via LLM, and aggregates per-symbol per-day scores.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator

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


@dataclass(frozen=True, init=False)
class NewsArticle:
    """A parsed news article."""

    title: str = ""
    summary: str = ""
    link: str = ""
    published: str = ""
    source: str = ""
    content_hash: str = ""
    _feed_title: str = field(default="", repr=False, compare=False)

    def __init__(self, *args: str, **kwargs: str) -> None:
        """Build a canonical article, adapting the legacy five-positional shape."""
        canonical_fields = ("title", "summary", "link", "published", "source", "content_hash")
        legacy_fields = ("title", "link", "summary", "published", "source")
        allowed = {*canonical_fields, "feed_title"}
        unknown = set(kwargs) - allowed
        if unknown:
            name = sorted(unknown)[0]
            raise TypeError(f"NewsArticle got an unexpected keyword argument {name!r}")
        if len(args) > len(canonical_fields):
            raise TypeError(f"NewsArticle expected at most 6 positional arguments, got {len(args)}")

        positional_fields = legacy_fields if len(args) == 5 else canonical_fields[: len(args)]
        values = dict.fromkeys(canonical_fields, "")
        assigned = set(positional_fields)
        values.update(zip(positional_fields, args, strict=True))
        for name in canonical_fields:
            if name in kwargs:
                if name in assigned:
                    raise TypeError(f"NewsArticle got multiple values for argument {name!r}")
                values[name] = kwargs[name]

        if not values["content_hash"]:
            digest = hashlib.sha256(f"{values['title']}{values['link']}".encode()).hexdigest()
            values["content_hash"] = digest[:12]
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_feed_title", kwargs.get("feed_title", ""))

    @property
    def feed_title(self) -> str:
        """Human feed name retained without changing the article API payload."""
        return self._feed_title

    def to_dict(self) -> dict[str, str]:
        """Return all article fields in JSON-ready form."""
        return {
            "title": self.title,
            "summary": self.summary,
            "link": self.link,
            "published": self.published,
            "source": self.source,
            "content_hash": self.content_hash,
        }


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
    articles, _success = _parse_rss_xml_result(xml_text, source_name)
    return articles


def _parse_rss_xml_result(xml_text: str, source_name: str) -> tuple[list[NewsArticle], bool]:
    """Parse RSS XML and distinguish valid empty feeds from malformed XML."""
    articles: list[NewsArticle] = []

    try:
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError as exc:
        logger.warning("XML parse error for %s: %s", source_name, exc)
        return articles, False

    root_name = root.tag.rsplit("}", 1)[-1].lower()
    if root_name not in {"rss", "rdf", "feed"}:
        logger.warning("Unexpected feed root for %s: %s", source_name, root_name)
        return articles, False

    atom_ns = ""
    if root.tag.startswith("{"):
        atom_ns = root.tag.split("}")[0] + "}"

    feed_container = root.find("channel")
    if feed_container is None:
        feed_container = root
    feed_title = _strip_html(_text(feed_container, "title", atom_ns) or "").strip()

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

        clean_title = _strip_html(title).strip()
        clean_summary = _strip_html(summary).strip()[:500]
        if clean_title or clean_summary:
            articles.append(
                NewsArticle(
                    title=clean_title or clean_summary[:120],
                    link=link.strip(),
                    summary=clean_summary,
                    published=published.strip(),
                    source=source_name,
                    feed_title=feed_title,
                )
            )

    return articles, True


def _text(element: ET.Element, tag: str, ns: str = "") -> str | None:
    """Find child text, trying namespaced and plain tags."""
    child = element.find(f"{ns}{tag}") if ns else None
    if child is None:
        child = element.find(tag)
    if child is None:
        return None
    text = "".join(child.itertext()).strip()
    return text or None


def _link(element: ET.Element, ns: str = "") -> str:
    """Extract an RSS text link or Atom href link."""
    candidates = list(element.findall("link"))
    if ns:
        candidates.extend(element.findall(f"{ns}link"))

    fallback = ""
    self_link = ""
    for link_element in candidates:
        value = (link_element.text or link_element.get("href", "")).strip()
        if not value:
            continue
        relation = link_element.get("rel", "alternate").lower()
        if relation == "alternate":
            return value
        if relation == "self" and not self_link:
            self_link = value
        elif not fallback:
            fallback = value
    return fallback or self_link


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
        self._cache_lock = threading.RLock()

    def fetch_headlines(self, source: str, limit: int | None = 20) -> list[NewsArticle]:
        """Fetch one named source or custom RSS URL, using the per-source cache."""
        url = RSS_SOURCES.get(source.lower())
        if url is None:
            if source.startswith("http"):
                url = source
            else:
                raise ValueError(f"Unknown source: {source!r}. Use one of {list(RSS_SOURCES)} or provide a URL.")

        articles = self._fetch_cached(source.lower(), url)
        return list(articles) if limit is None else articles[:limit]

    def search_news(self, query: str, limit: int = 20) -> list[NewsArticle]:
        """Search titles and summaries across all default RSS sources."""
        self._refresh_all()
        query_lower = query.lower()
        with self._cache_lock:
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
        with self._cache_lock:
            articles = [article for _timestamp, cached_articles in self._cache.values() for article in cached_articles]
        return self._deduplicate(articles)[:limit]

    def _refresh_all(self) -> None:
        for key, url in RSS_SOURCES.items():
            self._fetch_cached(key, url)

    def _fetch_cached(self, source_key: str, url: str) -> list[NewsArticle]:
        with self._cache_lock:
            now = time.monotonic()
            cached = self._cache.get(source_key)
            if cached is not None and now - cached[0] < self._cache_ttl:
                return list(cached[1])

            articles = self._fetch_rss(url, source_key)
            if articles is not None:
                self._cache[source_key] = (now, list(articles))
                return list(articles)
            return list(cached[1]) if cached is not None else []

    def _fetch_rss(self, url: str, source_name: str) -> list[NewsArticle] | None:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, follow_redirects=True)
                response.raise_for_status()
            articles, parsed = _parse_rss_xml_result(response.text, source_name)
            if not parsed:
                return None
            logger.info("Fetched %d articles from %s (%s)", len(articles), source_name, url)
            return articles
        except httpx.HTTPError as exc:
            logger.warning("HTTP error fetching %s: %s", url, exc)
        except Exception as exc:
            logger.warning("Unexpected error fetching %s: %s", url, exc)
        return None

    @staticmethod
    def _deduplicate(articles: list[NewsArticle]) -> list[NewsArticle]:
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for article in articles:
            if article.title not in seen:
                seen.add(article.title)
                unique.append(article)
        return unique


_DEFAULT_NEWS_SCRAPER = NewsScraper()


def parse_feed(feed_url: str) -> list[NewsArticle]:
    """Fetch and parse an RSS/Atom feed through the shared cached stdlib engine."""
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
        logger.info("LLM sentiment unavailable; using rule-based fallback: %s", response.error)
        return score_article_rule_based(article)

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

        data = json.loads(text)
        if not isinstance(data, dict) or "sentiment" not in data or "confidence" not in data:
            raise ValueError("sentiment response must contain sentiment and confidence")
        raw_sentiment = data["sentiment"]
        if not isinstance(raw_sentiment, str):
            raise TypeError("sentiment must be a string")
        sentiment = raw_sentiment.upper()
        if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
            raise ValueError("sentiment must be BULLISH, BEARISH, or NEUTRAL")
        raw_confidence = data["confidence"]
        if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
            raise TypeError("confidence must be a JSON number")
        confidence = float(raw_confidence)
        if not math.isfinite(confidence):
            raise ValueError("confidence must be finite")
        confidence = max(0.0, min(1.0, confidence))
        raw_reasoning = data.get("reasoning", "")
        if not isinstance(raw_reasoning, str):
            raise TypeError("reasoning must be a string")
        reasoning = raw_reasoning
    except (AttributeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.debug("Could not parse LLM sentiment response: %s", response.content[:100])
        return score_article_rule_based(article)

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


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SentimentLabel(StrEnum):
    """Categorical market sentiment labels (coarser than the numeric score)."""

    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"


class IndexSignal(StrEnum):
    """Directional signal for an index."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"


# ---------------------------------------------------------------------------
# JSON schema (passed directly to the LLM as a response-format constraint)
# ---------------------------------------------------------------------------

#: JSON schema for AI-generated structured market sentiment.
#: The ``type: "json_schema"`` envelope follows the OpenAI-compatible
#: structured-output convention used by LM Studio, Groq, OpenAI, etc.
MARKET_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "market_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "sentiment_score": {
                    "type": "number",
                    "minimum": -10,
                    "maximum": 10,
                    "description": (
                        "Overall market sentiment score. -10 = extremely bearish, 0 = neutral, +10 = extremely bullish."
                    ),
                },
                "market_sentiment": {
                    "type": "string",
                    "enum": [label.value for label in SentimentLabel],
                    "description": "Categorical market sentiment derived from sentiment_score.",
                },
                "indices": {
                    "type": "array",
                    "description": "Major Indian index snapshots (Nifty 50, Bank Nifty, Sensex, etc.).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Index name, e.g. NIFTY 50.",
                            },
                            "value": {
                                "type": "number",
                                "description": "Last traded value.",
                            },
                            "change_pct": {
                                "type": "number",
                                "description": "Percentage change from previous close.",
                            },
                            "signal": {
                                "type": "string",
                                "enum": [s.value for s in IndexSignal],
                                "description": "Short-term directional signal for the index.",
                            },
                        },
                        "required": ["name", "value", "change_pct", "signal"],
                        "additionalProperties": False,
                    },
                },
                "sectors": {
                    "type": "array",
                    "description": "Top and bottom performing sectors with outlook.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Sector name, e.g. IT, Banking, FMCG.",
                            },
                            "performance": {
                                "type": "string",
                                "description": (
                                    "Qualitative performance label: Outperforming / Underperforming / Neutral."
                                ),
                            },
                            "outlook": {
                                "type": "string",
                                "description": "One-sentence forward-looking note.",
                            },
                        },
                        "required": ["name", "performance", "outlook"],
                        "additionalProperties": False,
                    },
                },
                "key_points": {
                    "type": "array",
                    "description": "3 to 5 concise bullet points summarising today's market.",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 5,
                },
                "fii_dii_flow": {
                    "type": "object",
                    "description": "Foreign and domestic institutional activity.",
                    "properties": {
                        "fii_net": {
                            "type": "number",
                            "description": "FII net flow in crore INR (negative = outflow).",
                        },
                        "dii_net": {
                            "type": "number",
                            "description": "DII net flow in crore INR (negative = outflow).",
                        },
                        "interpretation": {
                            "type": "string",
                            "description": "One-sentence interpretation of the combined flow.",
                        },
                    },
                    "required": ["fii_net", "dii_net", "interpretation"],
                    "additionalProperties": False,
                },
                "risks": {
                    "type": "array",
                    "description": "Key downside risks to watch today.",
                    "items": {"type": "string"},
                },
                "opportunities": {
                    "type": "array",
                    "description": "Key upside opportunities or themes to watch today.",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "sentiment_score",
                "market_sentiment",
                "indices",
                "sectors",
                "key_points",
                "fii_dii_flow",
                "risks",
                "opportunities",
            ],
            "additionalProperties": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class IndexSnapshot(BaseModel):
    """Real-time or EOD snapshot for a single market index."""

    name: str = Field(..., description="Index name.")
    value: float = Field(..., description="Last traded value.")
    change_pct: float = Field(..., description="Percentage change from previous close.")
    signal: IndexSignal = Field(..., description="Directional signal.")


class SectorOutlook(BaseModel):
    """Sector-level performance and forward outlook."""

    name: str = Field(..., description="Sector name.")
    performance: str = Field(..., description="Qualitative performance label.")
    outlook: str = Field(..., description="One-sentence forward-looking note.")


class FiiDiiFlow(BaseModel):
    """Foreign and domestic institutional flow data."""

    fii_net: float = Field(..., description="FII net flow in crore INR.")
    dii_net: float = Field(..., description="DII net flow in crore INR.")
    interpretation: str = Field(..., description="Interpretation of combined flow.")


class _ProviderIndexSnapshot(BaseModel):
    """Trusted numeric index data supplied by the runtime provider."""

    name: str = Field(..., min_length=1)
    value: float = Field(..., allow_inf_nan=False)
    change_pct: float = Field(..., allow_inf_nan=False)
    signal: IndexSignal | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("index name must not be blank")
        return name


class _ProviderFiiDiiFlow(BaseModel):
    """Trusted institutional-flow numbers supplied by the runtime provider."""

    fii_net: float = Field(..., allow_inf_nan=False)
    dii_net: float = Field(..., allow_inf_nan=False)


class _ProviderMarketData(BaseModel):
    """Minimum provider payload required before rich generation can run."""

    indices: list[_ProviderIndexSnapshot] = Field(..., min_length=1)
    fii_dii_flow: _ProviderFiiDiiFlow

    @model_validator(mode="after")
    def _unique_index_names(self) -> _ProviderMarketData:
        names = [index.name.casefold() for index in self.indices]
        if len(names) != len(set(names)):
            raise ValueError("provider index names must be unique")
        return self


def prepare_market_summary_data(market_data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Snapshot and validate provider data before cache or LLM use."""
    if not isinstance(market_data, Mapping) or not market_data:
        return None
    try:
        snapshot = deepcopy(dict(market_data))
        _ProviderMarketData.model_validate(snapshot)
    except Exception as exc:
        logger.info("Rich market summary skipped: invalid provider snapshot (%s)", type(exc).__name__)
        return None
    return snapshot


class MarketSummary(BaseModel):
    """Structured AI-generated market sentiment summary.

    Validated against :data:`MARKET_SUMMARY_SCHEMA`. Returned by
    :func:`generate_market_summary`.
    """

    sentiment_score: float = Field(
        ...,
        description="Numeric sentiment score from -10 (strongly bearish) to +10 (strongly bullish).",
    )
    market_sentiment: SentimentLabel = Field(..., description="Categorical label derived from sentiment_score.")
    indices: list[IndexSnapshot] = Field(default_factory=list, description="Major index snapshots.")
    sectors: list[SectorOutlook] = Field(default_factory=list, description="Sector performance and outlook.")
    key_points: list[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3-5 concise bullet points.",
    )
    fii_dii_flow: FiiDiiFlow = Field(..., description="Institutional flow data.")
    risks: list[str] = Field(default_factory=list, description="Downside risks.")
    opportunities: list[str] = Field(default_factory=list, description="Upside opportunities.")

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def _clamp_score(cls, v: Any) -> float:
        """Clamp score to [-10, +10] in case the LLM drifts slightly.

        Runs before Pydantic type coercion so out-of-range values from the LLM
        are silently corrected rather than rejected with a ValidationError.
        """
        return max(-10.0, min(10.0, float(v)))

    @field_validator("market_sentiment", mode="before")
    @classmethod
    def _normalise_label(cls, v: Any) -> str:
        """Accept lowercase or mixed-case labels from the LLM."""
        if isinstance(v, str):
            return v.upper()
        return v

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def label_from_score(self) -> SentimentLabel:
        """Derive the categorical label purely from the numeric score.

        Useful for cross-checking the LLM's own categorisation.
        """
        score = self.sentiment_score
        if score >= 7:
            return SentimentLabel.STRONGLY_BULLISH
        if score >= 3:
            return SentimentLabel.BULLISH
        if score <= -7:
            return SentimentLabel.STRONGLY_BEARISH
        if score <= -3:
            return SentimentLabel.BEARISH
        return SentimentLabel.NEUTRAL

    @model_validator(mode="after")
    def _derive_label_from_score(self) -> MarketSummary:
        """Keep the categorical label consistent with the numeric score."""
        self.market_sentiment = self.label_from_score()
        return self

    def to_display_dict(self) -> dict[str, Any]:
        """Flat dict suitable for passing to the terminal API response."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert Indian equity markets analyst. Generate a structured JSON \
market summary for the current trading session. Base your analysis on the \
market data provided. Be factual, concise, and use Indian market conventions \
(crore INR for FII/DII flows, NSE index names). Never invent numeric index or \
FII/DII values; repeat only values present in the supplied market data. \
Return ONLY the JSON object — no prose, no markdown fences.\
"""

# Explicit field skeleton embedded in the prompt. Without response_format (which
# reasoning models on LM Studio do not honour — they return empty content),
# naming the exact keys is the only way to stop the model inventing its own
# structure (e.g. "flows"/"analyst_summary"). Keep these keys in sync with
# MARKET_SUMMARY_SCHEMA — a test walks the schema and asserts every required
# field and enum value (top-level AND nested) appears in this hint.
_SCHEMA_HINT = """\
Return ONLY a JSON object with EXACTLY these keys — no extra keys, no markdown:
{
  "sentiment_score": <number from -10 to 10>,
  "market_sentiment": "<STRONGLY_BULLISH|BULLISH|NEUTRAL|BEARISH|STRONGLY_BEARISH>",
  "indices": [{"name": "<index>", "value": <number>, "change_pct": <number>, "signal": "<BUY|SELL|HOLD|WATCH>"}],
  "sectors": [{"name": "<sector>", "performance": "<Outperforming|Underperforming|Neutral>", "outlook": "<one sentence>"}],
  "key_points": ["<point>", "<point>", "<point>"],
  "fii_dii_flow": {"fii_net": <crore INR>, "dii_net": <crore INR>, "interpretation": "<one sentence>"},
  "risks": ["<risk>"],
  "opportunities": ["<opportunity>"]
}\
"""

_USER_PROMPT_TEMPLATE = """\
Analyse the following Indian market data and generate a structured market \
sentiment summary:

{market_data}

{schema_hint}

Generate the JSON summary now, strictly following the schema above.\
"""


def _build_prompt(market_data: dict[str, Any]) -> str:
    """Serialise market_data to a clean string for the LLM prompt.

    Args:
        market_data: Raw market data from OpenAlgo or FlintTrade screener.

    Returns:
        Formatted string embedding all market data fields.
    """
    lines: list[str] = []
    for key, value in market_data.items():
        if isinstance(value, (dict, list)):
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_market_summary(
    llm_client: Any,
    market_data: dict[str, Any],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> MarketSummary | None:
    """Generate a structured market sentiment summary via the LLM.

    Calls the LLM with the market data and the :data:`MARKET_SUMMARY_SCHEMA`
    schema hint, then validates and returns a :class:`MarketSummary` Pydantic
    model. Returns ``None`` on any failure (LLM unavailable, parse error, etc.)
    so callers can gracefully degrade.

    Args:
        llm_client: A :class:`~flinttrade_ai.llm_client.LLMClient` instance.
            The function accepts ``Any`` so it can be tested with mocks without
            importing the client module.
        market_data: Dictionary of market inputs — indices, FII/DII flow, sector
            data, options PCR, etc. from OpenAlgo or the FlintTrade screener.
        temperature: LLM sampling temperature. Keep low (0.1–0.4) for structured
            output to reduce hallucinations.
        max_tokens: Maximum tokens the LLM may generate for the response.

    Returns:
        A validated :class:`MarketSummary` instance, or ``None`` on failure.

    Example::

        from flinttrade_ai.llm_client import LLMClient
        from flinttrade_ai.sentiment import generate_market_summary

        client = LLMClient()
        summary = generate_market_summary(client, {
            "indices": [
                {"name": "NIFTY 50", "value": 24350, "change_pct": -0.45},
            ],
            "fii_dii_flow": {"fii_net": -1240, "dii_net": 980},
        })
        if summary:
            print(summary.sentiment_score, summary.market_sentiment)
    """
    snapshot = prepare_market_summary_data(market_data)
    if snapshot is None:
        return None
    provider_data = _ProviderMarketData.model_validate(snapshot)

    try:
        from .llm_client import LLMMessage
    except ImportError:
        try:
            from llm_client import LLMMessage  # type: ignore[no-redef]
        except ImportError:
            logger.error("Cannot import LLMMessage — is the ai package on sys.path?")
            return None

    prompt_text = _build_prompt(snapshot)
    messages = [
        LLMMessage(role="system", content=_SYSTEM_PROMPT),
        LLMMessage(
            role="user", content=_USER_PROMPT_TEMPLATE.format(market_data=prompt_text, schema_hint=_SCHEMA_HINT)
        ),
    ]

    # Prompt-only structured output. We deliberately do NOT pass
    # ``MARKET_SUMMARY_SCHEMA`` as ``response_format`` here: LM Studio applies a
    # json_schema grammar to the visible-content channel, and reasoning models
    # (Qwen3, DeepSeek-R1, …) then emit their think block and stop without
    # producing the constrained JSON — yielding empty content. The system prompt
    # already constrains the model to return JSON, and the reasoning-aware client
    # gives it enough budget. Callers that know their model honours grammars can
    # still opt in via ``LLMClient.chat(response_format=...)``.
    response = None
    try:
        response = llm_client.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return None

    if not response or not response.success:
        logger.warning(
            "LLM returned unsuccessful response: %s",
            getattr(response, "error", "unknown"),
        )
        return None

    raw = response.content.strip()

    # Strip markdown code fences if the LLM included them despite the prompt.
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM JSON response: %s — raw: %.200s", exc, raw)
        return None

    try:
        summary = MarketSummary.model_validate(data)
    except Exception as exc:
        logger.error("MarketSummary validation failed: %s — data: %s", exc, data)
        return None

    generated_indices = {index.name.casefold(): index for index in summary.indices}
    trusted_indices = []
    for trusted in provider_data.indices:
        generated = generated_indices.get(trusted.name.casefold())
        signal = trusted.signal or (generated.signal if generated is not None else IndexSignal.HOLD)
        trusted_indices.append(
            IndexSnapshot(
                name=trusted.name,
                value=trusted.value,
                change_pct=trusted.change_pct,
                signal=signal,
            )
        )

    trusted_flow = FiiDiiFlow(
        fii_net=provider_data.fii_dii_flow.fii_net,
        dii_net=provider_data.fii_dii_flow.dii_net,
        interpretation=summary.fii_dii_flow.interpretation,
    )
    return summary.model_copy(update={"indices": trusted_indices, "fii_dii_flow": trusted_flow})


def sentiment_label_from_score(score: float) -> SentimentLabel:
    """Map a numeric sentiment score to its categorical label.

    This mirrors :meth:`MarketSummary.label_from_score` as a standalone
    utility for use without a full :class:`MarketSummary` instance.

    Args:
        score: Numeric score in the range [-10, +10].

    Returns:
        The corresponding :class:`SentimentLabel`.
    """
    score = max(-10.0, min(10.0, float(score)))
    if score >= 7:
        return SentimentLabel.STRONGLY_BULLISH
    if score >= 3:
        return SentimentLabel.BULLISH
    if score <= -7:
        return SentimentLabel.STRONGLY_BEARISH
    if score <= -3:
        return SentimentLabel.BEARISH
    return SentimentLabel.NEUTRAL
