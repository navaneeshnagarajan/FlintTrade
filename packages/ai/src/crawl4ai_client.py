"""Crawl4AI client — self-hosted web scraping for FlintTrade.

Replaces httpx+html.parser scrapers with Crawl4AI's async crawler.
Supports CSS extraction (free, no LLM tokens) and LLM extraction
(via LM Studio or any OpenAI-compatible endpoint).

Usage::

    from packages.ai.src.crawl4ai_client import Crawl4AIClient

    client = Crawl4AIClient()
    result = await client.scrape("https://example.com")
    print(result.markdown)

    # CSS schema extraction (free, no LLM)
    data = await client.extract_css(
        "https://screener.in/company/RELIANCE/",
        schema={"name": "h1.company-name", "pe": "span.pe-ratio"},
    )

    # LLM extraction (uses LM Studio)
    structured = await client.extract_llm(
        "https://news.example.com",
        schema=MarketSummary,  # pydantic model
    )
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    """Result from a Crawl4AI scrape.

    Attributes:
        url: The URL that was scraped.
        markdown: Page content rendered as Markdown.
        html: Raw HTML of the page.
        extracted: Structured data from CSS or LLM extraction.
        success: Whether the scrape completed without error.
        error: Error message when success is False.
    """

    url: str
    markdown: str = ""
    html: str = ""
    extracted: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class Crawl4AIClient:
    """Thin async wrapper around Crawl4AI for FlintTrade scraping needs.

    Falls back gracefully when ``crawl4ai`` is not installed — every method
    returns a :class:`ScrapeResult` with ``success=False`` and an informative
    ``error`` message rather than raising.

    Args:
        lm_studio_url: Base URL of the LM Studio OpenAI-compatible endpoint.
        lm_studio_model: Model identifier used for LLM extraction.
        timeout: Request timeout in seconds passed to the crawler.
    """

    def __init__(
        self,
        *,
        lm_studio_url: str = "http://localhost:1234/v1",
        lm_studio_model: str = "local-model",
        timeout: int = 30,
    ) -> None:
        self._lm_url = lm_studio_url
        self._lm_model = lm_studio_model
        self._timeout = timeout
        self._crawl4ai_available = self._check_availability()

    @staticmethod
    def _check_availability() -> bool:
        """Return True if crawl4ai is importable."""
        try:
            import crawl4ai  # noqa: F401

            return True
        except ImportError:
            logger.warning(
                "crawl4ai not installed — scraping unavailable. "
                "Run: pip install crawl4ai"
            )
            return False

    @property
    def available(self) -> bool:
        """True when the crawl4ai library is installed and importable."""
        return self._crawl4ai_available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape(self, url: str, *, js_render: bool = False) -> ScrapeResult:
        """Scrape a URL and return markdown and raw HTML.

        Args:
            url: Target URL to scrape.
            js_render: When True, instruct the crawler to render JavaScript
                before capturing content (requires Playwright).

        Returns:
            :class:`ScrapeResult` with ``markdown`` and ``html`` populated on
            success, or ``success=False`` and an ``error`` message on failure.
        """
        if not self._crawl4ai_available:
            return ScrapeResult(url=url, success=False, error="crawl4ai not installed")

        try:
            from crawl4ai import AsyncWebCrawler, CacheMode  # type: ignore[import]

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=url,
                    cache_mode=CacheMode.BYPASS,
                )
                return ScrapeResult(
                    url=url,
                    markdown=result.markdown or "",
                    html=result.html or "",
                    success=result.success,
                    error=None if result.success else "Crawl failed",
                )
        except Exception as exc:
            logger.exception("Crawl4AI scrape failed for %s", url)
            return ScrapeResult(url=url, success=False, error=str(exc))

    async def extract_css(
        self,
        url: str,
        schema: dict[str, str],
    ) -> ScrapeResult:
        """Extract data using CSS selectors (free, no LLM tokens).

        Args:
            url: Target URL.
            schema: Mapping of ``field_name`` → CSS selector string.
                Example: ``{"pe_ratio": "span.pe-ratio", "name": "h1.company-name"}``

        Returns:
            :class:`ScrapeResult` with ``extracted`` dict populated on success.
        """
        if not self._crawl4ai_available:
            return ScrapeResult(url=url, success=False, error="crawl4ai not installed")

        try:
            from crawl4ai import AsyncWebCrawler, CacheMode  # type: ignore[import]
            from crawl4ai.extraction_strategy import CssExtractionStrategy  # type: ignore[import]

            strategy = CssExtractionStrategy(
                schema={
                    "fields": [
                        {"name": k, "selector": v, "type": "text"}
                        for k, v in schema.items()
                    ]
                },
            )

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=url,
                    cache_mode=CacheMode.BYPASS,
                    extraction_strategy=strategy,
                )
                extracted: dict[str, Any] = {}
                if result.extracted_content:
                    parsed = json.loads(result.extracted_content)
                    if isinstance(parsed, list) and parsed:
                        extracted = parsed[0]
                    elif isinstance(parsed, dict):
                        extracted = parsed

                return ScrapeResult(
                    url=url,
                    markdown=result.markdown or "",
                    extracted=extracted,
                    success=result.success,
                    error=None if result.success else "CSS extraction failed",
                )
        except Exception as exc:
            logger.exception("CSS extraction failed for %s", url)
            return ScrapeResult(url=url, success=False, error=str(exc))

    async def extract_llm(
        self,
        url: str,
        schema: type,
        *,
        instruction: str = "Extract the requested data from this page.",
    ) -> ScrapeResult:
        """Extract structured data using an LLM (via LM Studio).

        Args:
            url: Target URL.
            schema: Pydantic model class that defines the expected output shape.
                Must expose a ``model_json_schema()`` class method (Pydantic v2).
            instruction: Natural-language extraction instruction passed to the LLM.

        Returns:
            :class:`ScrapeResult` with ``extracted`` dict populated on success.
        """
        if not self._crawl4ai_available:
            return ScrapeResult(url=url, success=False, error="crawl4ai not installed")

        try:
            from crawl4ai import AsyncWebCrawler, CacheMode  # type: ignore[import]
            from crawl4ai.extraction_strategy import LLMExtractionStrategy  # type: ignore[import]

            json_schema = (
                schema.model_json_schema()
                if hasattr(schema, "model_json_schema")
                else None
            )

            strategy = LLMExtractionStrategy(
                provider=f"openai/{self._lm_model}",
                api_token="lm-studio",
                base_url=self._lm_url,
                schema=json_schema,
                instruction=instruction,
            )

            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=url,
                    cache_mode=CacheMode.BYPASS,
                    extraction_strategy=strategy,
                )
                extracted: dict[str, Any] = {}
                if result.extracted_content:
                    parsed = json.loads(result.extracted_content)
                    if isinstance(parsed, list) and parsed:
                        extracted = parsed[0]
                    elif isinstance(parsed, dict):
                        extracted = parsed

                return ScrapeResult(
                    url=url,
                    markdown=result.markdown or "",
                    extracted=extracted,
                    success=result.success,
                    error=None if result.success else "LLM extraction failed",
                )
        except Exception as exc:
            logger.exception("LLM extraction failed for %s", url)
            return ScrapeResult(url=url, success=False, error=str(exc))
