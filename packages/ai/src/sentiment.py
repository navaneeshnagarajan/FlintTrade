"""Financial news sentiment analysis.

Absorbs finnews-ai patterns. Parses RSS feeds, extracts entities (symbols),
scores sentiment via LLM, and aggregates per-symbol per-day scores.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from typing import Any

from .llm_client import LLMClient, LLMMessage

logger = logging.getLogger("flinttrade.ai.sentiment")

IST = timezone(timedelta(hours=5, minutes=30))

# Default financial RSS feeds
DEFAULT_FEEDS: list[str] = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.livemint.com/rss/markets",
]

# Common NSE symbols for entity extraction
_SYMBOL_PATTERNS = [
    "NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
    "HDFC", "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "HCLTECH",
    "AXISBANK", "WIPRO", "MARUTI", "TATAMOTORS", "TATASTEEL",
    "ADANIENT", "ADANIPORTS", "BAJFINANCE", "BAJAJFINSV",
    "TITAN", "SUNPHARMA", "NESTLEIND", "POWERGRID", "NTPC",
    "GOLD", "SILVER", "CRUDEOIL", "NATURALGAS",
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


def parse_feed(feed_url: str) -> list[NewsArticle]:
    """Parse an RSS feed into a list of articles."""
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed — pip install feedparser")
        return []

    try:
        feed = feedparser.parse(feed_url)
    except Exception as exc:
        logger.error("Feed parse error for %s: %s", feed_url, exc)
        return []

    articles: list[NewsArticle] = []
    for entry in feed.entries:
        title = entry.get("title", "")
        summary = entry.get("summary", entry.get("description", ""))
        link = entry.get("link", "")
        published = entry.get("published", "")

        articles.append(NewsArticle(
            title=title,
            summary=summary[:500] if summary else "",
            link=link,
            published=published,
            source=feed_url,
            content_hash=hashlib.md5(f"{title}{link}".encode()).hexdigest()[:12],
        ))

    return articles


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

    response = llm.chat([
        LLMMessage(role="system", content="You are a financial sentiment analyst. Respond only with valid JSON."),
        LLMMessage(role="user", content=prompt),
    ], temperature=0.1, max_tokens=200)

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

    bullish_words = ["rally", "surge", "gain", "bullish", "breakout", "all-time high",
                     "upgrade", "buy", "strong", "growth", "profit", "outperform"]
    bearish_words = ["crash", "fall", "drop", "bearish", "breakdown", "sell",
                     "downgrade", "weak", "loss", "decline", "correction"]

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
        (1.0 if s.sentiment == "BULLISH" else -1.0 if s.sentiment == "BEARISH" else 0.0) * s.confidence
        for s in scores
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
                alerts.append({
                    "symbol": sym,
                    "shift": shift,
                    "direction": "BULLISH" if shift > 0 else "BEARISH",
                    "current_score": curr.net_score,
                    "previous_score": prev.net_score,
                })

        return sorted(alerts, key=lambda a: abs(a["shift"]), reverse=True)
