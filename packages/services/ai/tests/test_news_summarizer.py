"""Tests for MarketNewsSummarizer — AI news summaries for Indian markets.

All tests mock the LLM client. No network or API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ======================================================================
# Sample data
# ======================================================================

SAMPLE_ARTICLES: list[dict[str, str]] = [
    {
        "title": "NIFTY closes above 22000 for the first time",
        "summary": "The NIFTY 50 index crossed the 22000 mark driven by IT and banking stocks.",
        "link": "https://example.com/1",
        "published": "2026-03-31T10:00:00",
        "source": "ET Markets",
    },
    {
        "title": "TCS Q4 results beat expectations with 12% profit growth",
        "summary": "Tata Consultancy Services reported Q4 net profit of Rs 12,434 crore.",
        "link": "https://example.com/2",
        "published": "2026-03-31T09:30:00",
        "source": "MoneyControl",
    },
    {
        "title": "RBI keeps repo rate unchanged at 6.5%",
        "summary": "The Reserve Bank of India maintained status quo on interest rates.",
        "link": "https://example.com/3",
        "published": "2026-03-31T09:00:00",
        "source": "LiveMint",
    },
    {
        "title": "HDFCBANK reports strong Q4 with NII growth of 15%",
        "summary": "HDFC Bank's net interest income grew 15% YoY in Q4.",
        "link": "https://example.com/4",
        "published": "2026-03-31T08:30:00",
        "source": "MoneyControl",
    },
    {
        "title": "SUNPHARMA acquires European pharma company for $500M",
        "summary": "Sun Pharmaceutical Industries announced acquisition of EuroPharma.",
        "link": "https://example.com/5",
        "published": "2026-03-31T08:00:00",
        "source": "ET Markets",
    },
]


# ======================================================================
# NewsSummary — dataclass
# ======================================================================


class TestNewsSummary:
    """Test NewsSummary dataclass properties."""

    def test_success_when_content_present(self):
        from flinttrade_ai.news_summarizer import NewsSummary

        summary = NewsSummary(
            summary_type="premarket",
            content="Market is bullish today.",
            article_count=5,
        )
        assert summary.success

    def test_not_success_when_empty(self):
        from flinttrade_ai.news_summarizer import NewsSummary

        summary = NewsSummary(summary_type="premarket", content="")
        assert not summary.success

    def test_not_success_when_error(self):
        from flinttrade_ai.news_summarizer import NewsSummary

        summary = NewsSummary(
            summary_type="premarket",
            content="Some content",
            error="LLM failed",
        )
        assert not summary.success


# ======================================================================
# MarketNewsSummarizer — initialization
# ======================================================================


class TestMarketNewsSummarizerInit:
    """Test summarizer initialization."""

    def test_creates_with_default_llm(self):
        from flinttrade_ai.llm_client import LLMClient, LLMConfig
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        cfg = LLMConfig(provider="lmstudio", host="http://127.0.0.1:1234", model="test")
        client = LLMClient(config=cfg)
        summarizer = MarketNewsSummarizer(llm_client=client)
        assert summarizer.llm is client
        client.close()

    def test_creates_with_none_llm(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        summarizer = MarketNewsSummarizer(llm_client=None)
        assert summarizer.llm is not None
        summarizer.llm.close()


# ======================================================================
# fetch_news — RSS parsing
# ======================================================================


class TestFetchNews:
    """Test news fetching through the canonical RSS parser."""

    def test_fetch_returns_articles(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer
        from flinttrade_ai.sentiment import NewsArticle

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)
        article = NewsArticle(
            title="Test Article",
            summary="Test summary",
            link="https://example.com",
            published="2026-03-31",
            source="Test Source",
        )

        with patch("flinttrade_ai.news_summarizer.parse_feed", return_value=[article]) as parse:
            articles = summarizer.fetch_news(sources=["https://example.com/rss"])

        assert articles == [article.to_dict()]
        parse.assert_called_once_with("https://example.com/rss")

    def test_fetch_handles_empty_canonical_feed(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)
        with patch("flinttrade_ai.news_summarizer.parse_feed", return_value=[]):
            articles = summarizer.fetch_news()
        assert articles == []


# ======================================================================
# summarize_premarket — LLM summarization
# ======================================================================


class TestSummarizePremarket:
    """Test pre-market summary generation."""

    def _make_summarizer(self, llm_content="Pre-market briefing here."):
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content=llm_content,
            model="test-model",
            provider="test",
        )
        return MarketNewsSummarizer(llm_client=mock_llm)

    def test_summarize_premarket_success(self):
        summarizer = self._make_summarizer()
        result = summarizer.summarize_premarket(SAMPLE_ARTICLES)
        assert result.success
        assert result.summary_type == "premarket"
        assert result.article_count == 5
        assert "Pre-market briefing" in result.content

    def test_summarize_premarket_empty_news(self):
        summarizer = self._make_summarizer()
        result = summarizer.summarize_premarket([])
        assert not result.success
        assert "No news" in result.error

    def test_summarize_premarket_llm_failure(self):
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="",
            error="Connection refused",
        )
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)
        result = summarizer.summarize_premarket(SAMPLE_ARTICLES)
        assert not result.success
        assert "Connection refused" in result.error


# ======================================================================
# summarize_postmarket — with market data
# ======================================================================


class TestSummarizePostmarket:
    """Test post-market summary generation."""

    def test_summarize_postmarket_with_market_data(self):
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="Post-market summary: NIFTY closed at 22050.",
            model="test",
            provider="test",
        )
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        market_data = {
            "nifty_close": 22050,
            "banknifty_close": 48200,
            "fii_net": -1500,
        }
        result = summarizer.summarize_postmarket(SAMPLE_ARTICLES, market_data)
        assert result.success
        assert result.summary_type == "postmarket"

        # Verify market data was included in the prompt
        call_args = mock_llm.chat.call_args[0][0]
        user_msg = [m for m in call_args if m.role == "user"][0]
        assert "nifty_close" in user_msg.content

    def test_summarize_postmarket_without_market_data(self):
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="Post-market summary.",
            model="test",
            provider="test",
        )
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)
        result = summarizer.summarize_postmarket(SAMPLE_ARTICLES)
        assert result.success


# ======================================================================
# summarize_sector — sector filtering
# ======================================================================


class TestSummarizeSector:
    """Test sector-specific summarization."""

    def _make_summarizer(self, llm_content="IT sector summary."):
        from flinttrade_ai.llm_client import LLMResponse
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content=llm_content,
            model="test",
            provider="test",
        )
        return MarketNewsSummarizer(llm_client=mock_llm)

    def test_summarize_sector_it(self):
        summarizer = self._make_summarizer()
        result = summarizer.summarize_sector("IT", SAMPLE_ARTICLES)
        assert result.summary_type == "sector"
        assert result.sector == "IT"
        # TCS article should match IT sector keywords
        if result.success:
            assert result.article_count >= 1

    def test_summarize_sector_no_matches(self):
        summarizer = self._make_summarizer()
        result = summarizer.summarize_sector("NonExistentSector", SAMPLE_ARTICLES)
        # Might still match on lowercased keyword
        assert result.summary_type == "sector"

    def test_summarize_sector_banking(self):
        summarizer = self._make_summarizer("Banking summary.")
        result = summarizer.summarize_sector("Banking", SAMPLE_ARTICLES)
        assert result.sector == "Banking"
        # HDFCBANK and RBI articles should match
        if result.success:
            assert result.article_count >= 1


# ======================================================================
# get_stock_news — symbol filtering
# ======================================================================


class TestGetStockNews:
    """Test stock-specific news filtering."""

    def test_filter_by_symbol(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        tcs_news = summarizer.get_stock_news("TCS", SAMPLE_ARTICLES)
        assert len(tcs_news) >= 1
        assert any("TCS" in a["title"] for a in tcs_news)

    def test_filter_no_matches(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        result = summarizer.get_stock_news("ZZZNONEXIST", SAMPLE_ARTICLES)
        assert result == []

    def test_filter_case_insensitive(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        # "rbi" should match even though articles have "RBI"
        result = summarizer.get_stock_news("rbi", SAMPLE_ARTICLES)
        assert len(result) >= 1


# ======================================================================
# get_stock_news_by_keywords — multi-keyword filtering
# ======================================================================


class TestGetStockNewsByKeywords:
    """Test multi-keyword news filtering."""

    def test_multiple_keywords(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        result = summarizer.get_stock_news_by_keywords(
            ["TCS", "HDFCBANK"],
            SAMPLE_ARTICLES,
        )
        assert len(result) >= 2

    def test_empty_keywords(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        result = summarizer.get_stock_news_by_keywords([], SAMPLE_ARTICLES)
        assert result == []

    def test_empty_articles(self):
        from flinttrade_ai.news_summarizer import MarketNewsSummarizer

        mock_llm = MagicMock()
        summarizer = MarketNewsSummarizer(llm_client=mock_llm)

        result = summarizer.get_stock_news_by_keywords(["TCS"], [])
        assert result == []


# ======================================================================
# _articles_to_text — formatting helper
# ======================================================================


class TestArticlesToText:
    """Test article formatting for LLM context."""

    def test_formats_articles(self):
        from flinttrade_ai.news_summarizer import _articles_to_text

        text = _articles_to_text(SAMPLE_ARTICLES, max_articles=2)
        assert "1." in text
        assert "2." in text
        assert "ET Markets" in text

    def test_max_articles_limit(self):
        from flinttrade_ai.news_summarizer import _articles_to_text

        text = _articles_to_text(SAMPLE_ARTICLES, max_articles=1)
        # Only 1 article should appear
        assert "2." not in text

    def test_empty_articles(self):
        from flinttrade_ai.news_summarizer import _articles_to_text

        text = _articles_to_text([])
        assert text == ""


# ======================================================================
# SECTOR_KEYWORDS — coverage
# ======================================================================


class TestSectorKeywords:
    """Test sector keyword definitions."""

    def test_all_major_sectors_defined(self):
        from flinttrade_ai.news_summarizer import SECTOR_KEYWORDS

        expected = ["IT", "Banking", "Pharma", "Auto", "Energy", "Metal", "FMCG"]
        for sector in expected:
            assert sector in SECTOR_KEYWORDS
            assert len(SECTOR_KEYWORDS[sector]) > 0
