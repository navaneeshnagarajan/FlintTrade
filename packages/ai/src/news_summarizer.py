"""AI-powered market news summarization for Indian markets.

Absorbs FinSights patterns. Fetches RSS feeds from MoneyControl, ET Markets,
LiveMint, extracts articles, and uses the configured LLM to generate
pre-market/post-market/sector summaries.

Uses the existing SentimentAnalyzer's feed parsing and the LLMClient for
summarization. Designed to wire into the News widget and /ai route.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .llm_client import LLMClient, LLMMessage
from .sentiment import DEFAULT_FEEDS

logger = logging.getLogger("flinttrade.ai.news_summarizer")

IST = timezone(timedelta(hours=5, minutes=30))

# RSS feeds for Indian financial news
PREMARKET_SOURCES: list[str] = list(DEFAULT_FEEDS)
POSTMARKET_SOURCES: list[str] = list(DEFAULT_FEEDS)

# Sector keywords for filtering
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "IT": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "IT", "software", "technology"],
    "Banking": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "banking", "bank", "RBI", "credit"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "pharma", "healthcare", "drug"],
    "Auto": ["TATAMOTORS", "MARUTI", "M&M", "BAJAJ-AUTO", "auto", "vehicle", "EV"],
    "Energy": ["RELIANCE", "NTPC", "POWERGRID", "ONGC", "energy", "oil", "gas", "power"],
    "Metal": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "metal", "steel", "mining"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "FMCG", "consumer"],
    "Realty": ["DLF", "GODREJPROP", "OBEROIRLTY", "realty", "real estate", "housing"],
    "Finance": ["BAJFINANCE", "BAJAJFINSV", "SBILIFE", "HDFCLIFE", "NBFC", "insurance", "fintech"],
}

# System prompts for different summary types
_PREMARKET_SYSTEM = (
    "You are a financial analyst generating a concise Indian market pre-market briefing. "
    "Summarize key overnight developments, global cues, and expected market impact. "
    "Focus on NIFTY, BANKNIFTY, key sectors, and any earnings/policy events. "
    "Output in clean markdown with bullet points. Keep it under 300 words."
)

_POSTMARKET_SYSTEM = (
    "You are a financial analyst generating a concise Indian market post-market summary. "
    "Summarize what happened today: index moves, top gainers/losers, sector performance, "
    "FII/DII flows, and key events. Include market data provided. "
    "Output in clean markdown with bullet points. Keep it under 300 words."
)

_SECTOR_SYSTEM = (
    "You are a sector analyst. Summarize the latest news for the {sector} sector in Indian markets. "
    "Focus on key company updates, regulatory changes, and sector outlook. "
    "Output in clean markdown with bullet points. Keep it under 200 words."
)


@dataclass
class NewsSummary:
    """A generated news summary."""

    summary_type: str = ""  # "premarket", "postmarket", "sector"
    content: str = ""
    article_count: int = 0
    generated_at: str = ""
    sector: str = ""  # Only set for sector summaries
    error: str = ""

    @property
    def success(self) -> bool:
        return bool(self.content) and not self.error


def _articles_to_text(articles: list[dict[str, str]], max_articles: int = 20) -> str:
    """Convert article dicts to a text block for LLM context."""
    lines: list[str] = []
    for i, article in enumerate(articles[:max_articles]):
        title = article.get("title", "")
        summary = article.get("summary", "")
        source = article.get("source", "")
        published = article.get("published", "")
        lines.append(f"{i + 1}. [{source}] {title}")
        if summary:
            lines.append(f"   {summary[:200]}")
        if published:
            lines.append(f"   Published: {published}")
        lines.append("")
    return "\n".join(lines)


class MarketNewsSummarizer:
    """Generate pre/post-market news summaries using LLM.

    Sources: MoneyControl, ET Markets, LiveMint RSS feeds.
    Uses configured LLM (local or cloud) for summarization.

    Usage::

        summarizer = MarketNewsSummarizer(llm_client)
        news = summarizer.fetch_news()
        premarket = summarizer.summarize_premarket(news)
        postmarket = summarizer.summarize_postmarket(news, market_data)
        sector = summarizer.summarize_sector("IT", news)
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()
        self._article_cache: list[dict[str, str]] = []

    def fetch_news(
        self,
        sources: list[str] | None = None,
        max_articles: int = 50,
    ) -> list[dict[str, str]]:
        """Fetch news articles from RSS feeds.

        Each article is a dict with keys: title, summary, link, published, source.
        Falls back gracefully if feedparser is not installed.

        Args:
            sources: RSS feed URLs (defaults to Indian financial feeds).
            max_articles: Maximum articles to return across all feeds.

        Returns:
            List of article dicts, sorted by published date (newest first).
        """
        feeds = sources or PREMARKET_SOURCES
        articles: list[dict[str, str]] = []

        try:
            import feedparser  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("feedparser not installed — returning empty news list")
            return articles

        for feed_url in feeds:
            try:
                parsed = feedparser.parse(feed_url)
                source_name = parsed.feed.get("title", feed_url)[:30]

                for entry in parsed.entries[:max_articles]:
                    article: dict[str, str] = {
                        "title": entry.get("title", ""),
                        "summary": entry.get("summary", entry.get("description", "")),
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": source_name,
                    }
                    # Deduplicate by title hash
                    title_hash = hashlib.md5(
                        article["title"].encode(), usedforsecurity=False,
                    ).hexdigest()
                    if not any(
                        hashlib.md5(a["title"].encode(), usedforsecurity=False).hexdigest() == title_hash
                        for a in articles
                    ):
                        articles.append(article)

                logger.info("Fetched %d articles from %s", len(parsed.entries), source_name)
            except Exception as exc:
                logger.warning("Failed to fetch feed %s: %s", feed_url, exc)

        # Sort newest first (best-effort parse of published dates)
        articles.sort(key=lambda a: a.get("published", ""), reverse=True)
        self._article_cache = articles[:max_articles]

        logger.info("Total articles fetched: %d", len(self._article_cache))
        return self._article_cache

    def summarize_premarket(self, news: list[dict[str, str]]) -> NewsSummary:
        """Generate a pre-market briefing from news articles.

        Args:
            news: List of article dicts (from fetch_news).

        Returns:
            NewsSummary with the pre-market briefing.
        """
        if not news:
            return NewsSummary(
                summary_type="premarket",
                error="No news articles provided",
                generated_at=datetime.now(IST).isoformat(),
            )

        articles_text = _articles_to_text(news)
        messages = [
            LLMMessage(role="system", content=_PREMARKET_SYSTEM),
            LLMMessage(
                role="user",
                content=f"Here are today's financial news articles:\n\n{articles_text}\n\nGenerate a pre-market briefing.",
            ),
        ]

        response = self.llm.chat(messages)
        return NewsSummary(
            summary_type="premarket",
            content=response.content if response.success else "",
            article_count=len(news),
            generated_at=datetime.now(IST).isoformat(),
            error=response.error if not response.success else "",
        )

    def summarize_postmarket(
        self,
        news: list[dict[str, str]],
        market_data: dict[str, Any] | None = None,
    ) -> NewsSummary:
        """Generate a post-market summary from news and market data.

        Args:
            news: List of article dicts (from fetch_news).
            market_data: Optional dict with keys like nifty_close, banknifty_close,
                         fii_net, dii_net, top_gainers, top_losers.

        Returns:
            NewsSummary with the post-market summary.
        """
        if not news:
            return NewsSummary(
                summary_type="postmarket",
                error="No news articles provided",
                generated_at=datetime.now(IST).isoformat(),
            )

        articles_text = _articles_to_text(news)

        market_context = ""
        if market_data:
            parts: list[str] = ["\nMarket Data:"]
            for key, val in market_data.items():
                parts.append(f"- {key}: {val}")
            market_context = "\n".join(parts)

        messages = [
            LLMMessage(role="system", content=_POSTMARKET_SYSTEM),
            LLMMessage(
                role="user",
                content=(
                    f"Here are today's financial news articles:\n\n{articles_text}"
                    f"{market_context}\n\nGenerate a post-market summary."
                ),
            ),
        ]

        response = self.llm.chat(messages)
        return NewsSummary(
            summary_type="postmarket",
            content=response.content if response.success else "",
            article_count=len(news),
            generated_at=datetime.now(IST).isoformat(),
            error=response.error if not response.success else "",
        )

    def summarize_sector(
        self,
        sector: str,
        news: list[dict[str, str]],
    ) -> NewsSummary:
        """Generate a sector-specific news summary.

        Args:
            sector: Sector name (e.g. "IT", "Banking", "Pharma").
            news: Full list of articles — will be filtered to sector.

        Returns:
            NewsSummary for the given sector.
        """
        keywords = SECTOR_KEYWORDS.get(sector, [sector.lower()])
        sector_news = self.get_stock_news_by_keywords(keywords, news)

        if not sector_news:
            return NewsSummary(
                summary_type="sector",
                sector=sector,
                content="",
                error=f"No news found for sector: {sector}",
                generated_at=datetime.now(IST).isoformat(),
            )

        articles_text = _articles_to_text(sector_news)
        system_prompt = _SECTOR_SYSTEM.format(sector=sector)

        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(
                role="user",
                content=f"Here are the latest {sector} sector news:\n\n{articles_text}\n\nSummarize.",
            ),
        ]

        response = self.llm.chat(messages)
        return NewsSummary(
            summary_type="sector",
            sector=sector,
            content=response.content if response.success else "",
            article_count=len(sector_news),
            generated_at=datetime.now(IST).isoformat(),
            error=response.error if not response.success else "",
        )

    def get_stock_news(
        self,
        symbol: str,
        news: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Filter news articles relevant to a specific stock symbol.

        Args:
            symbol: NSE symbol (e.g. "TCS", "RELIANCE").
            news: Full list of articles to search.

        Returns:
            Filtered list of articles mentioning the symbol.
        """
        return self.get_stock_news_by_keywords([symbol], news)

    def get_stock_news_by_keywords(
        self,
        keywords: list[str],
        news: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Filter articles by keyword match in title or summary.

        Args:
            keywords: List of keywords to match (case-insensitive).
            news: Full list of articles.

        Returns:
            Filtered list of matching articles.
        """
        lower_keywords = [k.lower() for k in keywords]
        matches: list[dict[str, str]] = []

        for article in news:
            text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
            if any(kw in text for kw in lower_keywords):
                matches.append(article)

        return matches
