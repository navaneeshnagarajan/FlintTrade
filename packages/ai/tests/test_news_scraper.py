"""Tests for the RSS-based news scraper (packages.ai.src.news_scraper).

Uses monkeypatched httpx responses to avoid hitting real RSS feeds.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from packages.ai.src.news_scraper import (
    NewsScraper,
    NewsArticle,
    RSS_SOURCES,
    _parse_rss_xml,
    _strip_html,
)

# ---------------------------------------------------------------------------
# Sample RSS XML payloads
# ---------------------------------------------------------------------------

_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>MoneyControl Markets</title>
    <item>
      <title>NIFTY closes above 22500 for first time</title>
      <link>https://example.com/nifty-22500</link>
      <description>NIFTY 50 &lt;b&gt;rallied&lt;/b&gt; 1.2% today on strong FII buying.</description>
      <pubDate>Tue, 08 Apr 2026 15:30:00 +0530</pubDate>
    </item>
    <item>
      <title>Reliance Q4 results beat estimates</title>
      <link>https://example.com/reliance-q4</link>
      <description>Reliance Industries reported strong Q4 earnings.</description>
      <pubDate>Tue, 08 Apr 2026 14:00:00 +0530</pubDate>
    </item>
    <item>
      <title>RBI holds rates steady in April policy</title>
      <link>https://example.com/rbi-rates</link>
      <description>Reserve Bank keeps repo rate unchanged at 6.5%.</description>
      <pubDate>Tue, 08 Apr 2026 12:00:00 +0530</pubDate>
    </item>
  </channel>
</rss>
"""

_ATOM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>LiveMint Markets</title>
  <entry>
    <title>BANKNIFTY surges 500 points</title>
    <link href="https://example.com/banknifty-surge"/>
    <summary>Banking index up sharply on credit growth data.</summary>
    <published>2026-04-08T16:00:00+05:30</published>
  </entry>
</feed>
"""

_EMPTY_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Empty</title></channel></rss>
"""

_MALFORMED_XML = "this is not xml at all <broken"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


# ---------------------------------------------------------------------------
# Tests: _parse_rss_xml
# ---------------------------------------------------------------------------


class TestParseRssXml:
    """Unit tests for the XML parser."""

    def test_parses_rss_items(self) -> None:
        articles = _parse_rss_xml(_RSS_XML, "test")
        assert len(articles) == 3
        assert articles[0].title == "NIFTY closes above 22500 for first time"
        assert articles[0].source == "test"
        assert articles[0].link == "https://example.com/nifty-22500"

    def test_parses_atom_entries(self) -> None:
        articles = _parse_rss_xml(_ATOM_XML, "livemint")
        assert len(articles) == 1
        assert articles[0].title == "BANKNIFTY surges 500 points"
        assert "https://example.com/banknifty-surge" in articles[0].link

    def test_empty_feed_returns_empty_list(self) -> None:
        articles = _parse_rss_xml(_EMPTY_RSS, "empty")
        assert articles == []

    def test_malformed_xml_returns_empty_list(self) -> None:
        articles = _parse_rss_xml(_MALFORMED_XML, "bad")
        assert articles == []

    def test_strips_html_from_description(self) -> None:
        articles = _parse_rss_xml(_RSS_XML, "test")
        # The <b>rallied</b> should be stripped
        assert "<b>" not in articles[0].summary
        assert "rallied" in articles[0].summary


# ---------------------------------------------------------------------------
# Tests: _strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_tags(self) -> None:
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_plain_text_unchanged(self) -> None:
        assert _strip_html("No tags here") == "No tags here"


# ---------------------------------------------------------------------------
# Tests: NewsScraper
# ---------------------------------------------------------------------------


class TestNewsScraper:
    """Integration tests for NewsScraper with mocked HTTP."""

    def _make_scraper(self) -> NewsScraper:
        return NewsScraper(timeout=5.0, cache_ttl=900.0)

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_fetch_headlines(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        articles = scraper.fetch_headlines("moneycontrol", limit=2)

        assert len(articles) == 2
        assert articles[0].title == "NIFTY closes above 22500 for first time"

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_fetch_headlines_unknown_source_raises(self, mock_client_cls: MagicMock) -> None:
        scraper = self._make_scraper()
        with pytest.raises(ValueError, match="Unknown source"):
            scraper.fetch_headlines("nonexistent")

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_fetch_headlines_with_url(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        articles = scraper.fetch_headlines("https://custom.example.com/rss")
        assert len(articles) == 3

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_search_news(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        results = scraper.search_news("NIFTY")

        assert len(results) >= 1
        assert any("NIFTY" in r.title for r in results)

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_get_latest(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        latest = scraper.get_latest(limit=5)

        assert len(latest) > 0
        assert all(isinstance(a, NewsArticle) for a in latest)

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_cache_prevents_refetch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        scraper.fetch_headlines("moneycontrol")
        scraper.fetch_headlines("moneycontrol")

        # httpx.Client should only be created once (cached second time)
        assert mock_client_cls.call_count == 1

    @patch("packages.ai.src.news_scraper.httpx.Client")
    def test_article_to_dict(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(_RSS_XML)
        mock_client_cls.return_value = mock_client

        scraper = self._make_scraper()
        articles = scraper.fetch_headlines("moneycontrol", limit=1)
        d = articles[0].to_dict()

        assert isinstance(d, dict)
        assert "title" in d
        assert "link" in d
        assert "summary" in d
        assert "published" in d
        assert "source" in d

    def test_rss_sources_defined(self) -> None:
        """Verify all three Indian financial RSS sources are configured."""
        assert "moneycontrol" in RSS_SOURCES
        assert "economictimes" in RSS_SOURCES
        assert "livemint" in RSS_SOURCES
        assert len(RSS_SOURCES) >= 3
