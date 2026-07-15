"""Tests for crawl4ai_client — all tests mock crawl4ai to avoid network calls.

crawl4ai is an optional dependency and may not be installed in CI.
Every test either patches sys.modules to simulate the library being absent, or
injects a full mock of the crawl4ai namespace so that the production code's
lazy imports succeed without the real package being installed.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flinttrade_ai.crawl4ai_client import Crawl4AIClient, ScrapeResult


# ---------------------------------------------------------------------------
# Helpers: fake crawl4ai module tree
# ---------------------------------------------------------------------------


def _make_crawl4ai_modules() -> dict[str, MagicMock]:
    """Return a dict of mock modules that stand in for crawl4ai and sub-modules.

    Injecting these into sys.modules lets the production code's `from crawl4ai
    import ...` succeed without the real package installed.
    """
    extraction_strategy_mod = MagicMock()
    extraction_strategy_mod.CssExtractionStrategy = MagicMock
    extraction_strategy_mod.LLMExtractionStrategy = MagicMock

    crawl4ai_mod = MagicMock()
    crawl4ai_mod.CacheMode = MagicMock()

    return {
        "crawl4ai": crawl4ai_mod,
        "crawl4ai.extraction_strategy": extraction_strategy_mod,
    }


@contextmanager
def _fake_crawl4ai(
    mock_crawler: MagicMock,
) -> Generator[dict[str, MagicMock], None, None]:
    """Context manager that injects a fake crawl4ai tree and wires AsyncWebCrawler.

    Args:
        mock_crawler: The mock object returned by ``AsyncWebCrawler()``.

    Yields the modules dict so callers can further configure mocks.
    """
    modules = _make_crawl4ai_modules()
    modules["crawl4ai"].AsyncWebCrawler = MagicMock(return_value=mock_crawler)

    with patch.dict(sys.modules, modules):
        # Ensure _check_availability returns True while the fake module is present
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=True,
        ):
            yield modules


def _make_mock_crawler(mock_result: MagicMock) -> AsyncMock:
    """Build an async context-manager mock that returns mock_result from arun."""
    crawler = AsyncMock()
    crawler.arun = AsyncMock(return_value=mock_result)
    crawler.__aenter__ = AsyncMock(return_value=crawler)
    crawler.__aexit__ = AsyncMock(return_value=False)
    return crawler


# ---------------------------------------------------------------------------
# ScrapeResult dataclass
# ---------------------------------------------------------------------------


class TestScrapeResult:
    """Unit tests for the ScrapeResult dataclass defaults."""

    def test_defaults(self) -> None:
        r = ScrapeResult(url="https://example.com")
        assert r.url == "https://example.com"
        assert r.markdown == ""
        assert r.html == ""
        assert r.success is True
        assert r.error is None
        assert r.extracted == {}

    def test_error_result(self) -> None:
        r = ScrapeResult(url="https://x.com", success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"

    def test_extracted_default_is_independent(self) -> None:
        """Each instance should have its own dict — not a shared default."""
        r1 = ScrapeResult(url="https://a.com")
        r2 = ScrapeResult(url="https://b.com")
        r1.extracted["key"] = "val"
        assert "key" not in r2.extracted

    def test_full_construction(self) -> None:
        r = ScrapeResult(
            url="https://screener.in",
            markdown="# Hello",
            html="<h1>Hello</h1>",
            extracted={"pe": "20"},
            success=True,
            error=None,
        )
        assert r.markdown == "# Hello"
        assert r.html == "<h1>Hello</h1>"
        assert r.extracted == {"pe": "20"}


# ---------------------------------------------------------------------------
# Availability detection
# ---------------------------------------------------------------------------


class TestCrawl4AIClientAvailability:
    """Tests for the crawl4ai import guard."""

    def test_available_when_installed(self) -> None:
        with patch.dict(sys.modules, {"crawl4ai": MagicMock()}):
            client = Crawl4AIClient()
            assert client.available is True

    def test_unavailable_when_not_installed(self) -> None:
        # Remove crawl4ai from sys.modules so ImportError is triggered
        filtered = {k: v for k, v in sys.modules.items() if not k.startswith("crawl4ai")}
        with patch.dict(sys.modules, filtered, clear=True):
            with patch(
                "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
                return_value=False,
            ):
                client = Crawl4AIClient()
                assert client.available is False

    @pytest.mark.asyncio
    async def test_scrape_returns_error_when_unavailable(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=False,
        ):
            client = Crawl4AIClient()
            result = await client.scrape("https://example.com")
            assert not result.success
            assert "not installed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_extract_css_returns_error_when_unavailable(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=False,
        ):
            client = Crawl4AIClient()
            result = await client.extract_css("https://example.com", {"title": "h1"})
            assert not result.success
            assert "not installed" in (result.error or "")

    @pytest.mark.asyncio
    async def test_extract_llm_returns_error_when_unavailable(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=False,
        ):
            client = Crawl4AIClient()
            result = await client.extract_llm("https://example.com", MagicMock())
            assert not result.success
            assert "not installed" in (result.error or "")


# ---------------------------------------------------------------------------
# scrape()
# ---------------------------------------------------------------------------


class TestCrawl4AIClientScrape:
    """Tests for the plain scrape() method."""

    @pytest.mark.asyncio
    async def test_scrape_success(self) -> None:
        mock_result = MagicMock()
        mock_result.markdown = "# Hello"
        mock_result.html = "<h1>Hello</h1>"
        mock_result.success = True

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.scrape("https://example.com")

        assert result.success
        assert result.markdown == "# Hello"
        assert result.html == "<h1>Hello</h1>"
        assert result.url == "https://example.com"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_scrape_returns_url(self) -> None:
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.html = ""
        mock_result.success = True

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.scrape("https://moneycontrol.com")

        assert result.url == "https://moneycontrol.com"

    @pytest.mark.asyncio
    async def test_scrape_handles_crawler_failure(self) -> None:
        """Crawler reports failure — error field should be set."""
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.html = ""
        mock_result.success = False

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.scrape("https://bad.example.com")

        assert not result.success
        assert result.error == "Crawl failed"

    @pytest.mark.asyncio
    async def test_scrape_handles_exception(self) -> None:
        """Unhandled exception from the crawler is caught and returned as error."""
        mock_crawler = _make_mock_crawler(MagicMock())
        mock_crawler.arun = AsyncMock(side_effect=RuntimeError("network"))

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.scrape("https://bad.com")

        assert not result.success
        assert "network" in (result.error or "")

    @pytest.mark.asyncio
    async def test_scrape_handles_none_markdown(self) -> None:
        """Crawler returning None for markdown should not raise."""
        mock_result = MagicMock()
        mock_result.markdown = None
        mock_result.html = None
        mock_result.success = True

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.scrape("https://example.com")

        assert result.markdown == ""
        assert result.html == ""


# ---------------------------------------------------------------------------
# extract_css()
# ---------------------------------------------------------------------------


class TestCrawl4AIClientCSS:
    """Tests for CSS-selector-based extraction."""

    @pytest.mark.asyncio
    async def test_extract_css_parses_list_result(self) -> None:
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = '[{"title": "FlintTrade", "pe": "20"}]'

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.extract_css(
                "https://screener.in/company/RELIANCE/",
                {"title": "h1", "pe": "span.pe"},
            )

        assert result.success
        assert result.extracted == {"title": "FlintTrade", "pe": "20"}

    @pytest.mark.asyncio
    async def test_extract_css_parses_dict_result(self) -> None:
        """When extracted_content is a plain dict (not a list), handle it."""
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = '{"name": "RELIANCE"}'

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.extract_css("https://example.com", {"name": "h1"})

        assert result.success
        assert result.extracted == {"name": "RELIANCE"}

    @pytest.mark.asyncio
    async def test_extract_css_empty_content(self) -> None:
        """None extracted_content should yield an empty dict, not an error."""
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = None

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.extract_css("https://example.com", {"title": "h1"})

        assert result.success
        assert result.extracted == {}

    @pytest.mark.asyncio
    async def test_extract_css_handles_exception(self) -> None:
        mock_crawler = _make_mock_crawler(MagicMock())
        mock_crawler.arun = AsyncMock(side_effect=ValueError("bad selector"))

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient()
            result = await client.extract_css("https://example.com", {"x": "y"})

        assert not result.success
        assert "bad selector" in (result.error or "")


# ---------------------------------------------------------------------------
# extract_llm()
# ---------------------------------------------------------------------------


class TestCrawl4AIClientLLM:
    """Tests for LLM-based structured extraction."""

    @pytest.mark.asyncio
    async def test_extract_llm_list_result(self) -> None:
        from flinttrade_core import ollama_runtime

        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = '[{"sentiment": "bullish", "score": 0.8}]'

        mock_crawler = _make_mock_crawler(mock_result)
        mock_schema = MagicMock()
        mock_schema.model_json_schema.return_value = {"type": "object"}

        admitted_models: list[str] = []

        @contextmanager
        def admitted(model: str) -> Generator[MagicMock, None, None]:
            admitted_models.append(model)
            yield MagicMock(base_url="http://127.0.0.1:49152")

        with patch.object(ollama_runtime, "managed_ollama_session", admitted):
            with _fake_crawl4ai(mock_crawler) as modules:
                strategy_factory = MagicMock()
                modules["crawl4ai.extraction_strategy"].LLMExtractionStrategy = strategy_factory
                client = Crawl4AIClient(llm_model="qwen3:8b")
                result = await client.extract_llm("https://news.example.com", mock_schema)

        assert result.success
        assert result.extracted["sentiment"] == "bullish"
        assert strategy_factory.call_args.kwargs["api_token"] == "local-runtime"
        assert strategy_factory.call_args.kwargs["base_url"] == "http://127.0.0.1:49152/v1"
        assert admitted_models == ["qwen3:8b"]

    @pytest.mark.asyncio
    async def test_extract_llm_dict_result(self) -> None:
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = '{"trend": "uptrend"}'

        mock_crawler = _make_mock_crawler(mock_result)
        mock_schema = MagicMock()
        mock_schema.model_json_schema.return_value = {"type": "object"}

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient(llm_base_url="https://models.example.invalid/v1", llm_model="qwen")
            result = await client.extract_llm("https://news.example.com", mock_schema)

        assert result.success
        assert result.extracted == {"trend": "uptrend"}

    @pytest.mark.asyncio
    async def test_extract_llm_no_model_json_schema(self) -> None:
        """Schema without model_json_schema (non-Pydantic) should not crash."""
        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = "[]"

        mock_crawler = _make_mock_crawler(mock_result)

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient(llm_base_url="https://models.example.invalid/v1", llm_model="qwen")
            result = await client.extract_llm("https://example.com", object())

        assert result.success
        assert result.extracted == {}

    @pytest.mark.asyncio
    async def test_extract_llm_handles_exception(self) -> None:
        mock_crawler = _make_mock_crawler(MagicMock())
        mock_crawler.arun = AsyncMock(side_effect=ConnectionError("refused"))

        with _fake_crawl4ai(mock_crawler):
            client = Crawl4AIClient(llm_base_url="https://models.example.invalid/v1", llm_model="qwen")
            result = await client.extract_llm("https://example.com", MagicMock())

        assert not result.success
        assert "refused" in (result.error or "")

    @pytest.mark.asyncio
    async def test_extract_llm_discards_output_when_managed_post_admission_fails(self) -> None:
        from flinttrade_core import ollama_runtime

        mock_result = MagicMock()
        mock_result.markdown = ""
        mock_result.success = True
        mock_result.extracted_content = '{"must": "not escape"}'
        mock_crawler = _make_mock_crawler(mock_result)

        @contextmanager
        def changed(_model: str) -> Generator[MagicMock, None, None]:
            yield MagicMock(base_url="http://127.0.0.1:49152")
            raise ollama_runtime.OllamaRuntimeError("loaded model digest changed")

        with patch.object(ollama_runtime, "managed_ollama_session", changed):
            with _fake_crawl4ai(mock_crawler):
                client = Crawl4AIClient(llm_model="qwen3:8b")
                result = await client.extract_llm("https://example.com", MagicMock())

        assert result.success is False
        assert result.extracted == {}


# ---------------------------------------------------------------------------
# __init__ configuration
# ---------------------------------------------------------------------------


class TestClientInit:
    """Tests for constructor arguments and stored configuration."""

    def test_defaults(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=True,
        ):
            client = Crawl4AIClient()

        assert client._lm_url == ""
        assert client._lm_model == ""
        assert client._timeout == 30

    def test_custom_openai_compatible_url(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=True,
        ):
            client = Crawl4AIClient(
                llm_base_url="http://custom:5000/v1",
                llm_model="qwen",
                timeout=60,
            )

        assert client._lm_url == "http://custom:5000/v1"
        assert client._lm_model == "qwen"
        assert client._timeout == 60

    def test_available_property_reflects_check(self) -> None:
        with patch(
            "flinttrade_ai.crawl4ai_client.Crawl4AIClient._check_availability",
            return_value=False,
        ):
            client = Crawl4AIClient()
            assert client.available is False
