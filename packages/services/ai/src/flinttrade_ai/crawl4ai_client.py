"""Crawl4AI client — self-hosted web scraping for FlintTrade.

Replaces httpx+html.parser scrapers with Crawl4AI's async crawler.
Supports CSS extraction (free, no LLM tokens) and LLM extraction
through managed Ollama or any OpenAI-compatible endpoint.

Usage::

    from flinttrade_ai.crawl4ai_client import Crawl4AIClient

    client = Crawl4AIClient()
    result = await client.scrape("https://example.com")
    print(result.markdown)

    # CSS schema extraction (free, no LLM)
    data = await client.extract_css(
        "https://screener.in/company/RELIANCE/",
        schema={"name": "h1.company-name", "pe": "span.pe-ratio"},
    )

    # LLM extraction through managed Ollama
    structured = await client.extract_llm(
        "https://news.example.com",
        schema=MarketSummary,  # pydantic model
    )
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSRF protection — block private/internal networks
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|"
    r"172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|192\.168\.\d+\.\d+|"
    r"169\.254\.\d+\.\d+|0\.0\.0\.0|\[::1\])$"
)


def _validate_url(url: str) -> None:
    """Validate that a URL is safe to scrape (no SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    hostname = parsed.hostname or ""
    if _BLOCKED_HOSTS.match(hostname):
        raise ValueError(f"Blocked host (private/internal network): {hostname}")


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
        llm_base_url: Explicit OpenAI-compatible endpoint. When omitted, the
            FlintTrade-managed Ollama runtime is admitted dynamically.
        llm_model: Model identifier used for LLM extraction. When omitted on the
            managed path, the effective workspace model is used.
        timeout: Request timeout in seconds passed to the crawler.
    """

    def __init__(
        self,
        *,
        llm_base_url: str | None = None,
        llm_model: str = "",
        timeout: int = 30,
    ) -> None:
        self._lm_url = str(llm_base_url or "").strip().rstrip("/")
        self._lm_model = llm_model.strip()
        self._timeout = timeout
        self._crawl4ai_available = self._check_availability()

    def _managed_model(self) -> str:
        if self._lm_model:
            return self._lm_model
        try:
            from flinttrade_core.llm_config import read_effective_llm_config

            config = read_effective_llm_config()
        except Exception as exc:  # noqa: BLE001 - mapped to one bounded local-AI error
            raise RuntimeError("Managed local AI configuration is unavailable") from exc
        if str(config.get("provider") or "").strip().lower() != "ollama":
            raise RuntimeError("Managed Ollama is not the configured LLM provider")
        model = str(config.get("model") or "").strip()
        if not model:
            raise RuntimeError("Managed Ollama model is not configured")
        return model

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
        try:
            _validate_url(url)
        except ValueError as exc:
            return ScrapeResult(url=url, success=False, error=str(exc))

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
        try:
            _validate_url(url)
        except ValueError as exc:
            return ScrapeResult(url=url, success=False, error=str(exc))

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
        """Extract structured data using an OpenAI-compatible LLM.

        Args:
            url: Target URL.
            schema: Pydantic model class that defines the expected output shape.
                Must expose a ``model_json_schema()`` class method (Pydantic v2).
            instruction: Natural-language extraction instruction passed to the LLM.

        Returns:
            :class:`ScrapeResult` with ``extracted`` dict populated on success.
        """
        try:
            _validate_url(url)
        except ValueError as exc:
            return ScrapeResult(url=url, success=False, error=str(exc))

        if not self._crawl4ai_available:
            return ScrapeResult(url=url, success=False, error="crawl4ai not installed")

        managed_runtime = not self._lm_url
        try:
            from crawl4ai import AsyncWebCrawler, CacheMode  # type: ignore[import]
            from crawl4ai.extraction_strategy import LLMExtractionStrategy  # type: ignore[import]

            model = self._managed_model() if managed_runtime else self._lm_model
            if not model:
                raise ValueError("LLM model is required for extraction")
            if managed_runtime:
                from flinttrade_core.ollama_runtime import managed_ollama_session

                endpoint_context = managed_ollama_session(model)
            else:
                endpoint_context = nullcontext(self._lm_url)

            json_schema = (
                schema.model_json_schema()
                if hasattr(schema, "model_json_schema")
                else None
            )

            with endpoint_context as endpoint:
                base_url = (
                    str(endpoint).rstrip("/")
                    if isinstance(endpoint, str)
                    else f"{str(endpoint.base_url).rstrip('/')}/v1"
                )
                strategy = LLMExtractionStrategy(
                    provider=f"openai/{model}",
                    api_token="local-runtime",
                    base_url=base_url,
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

                    response = ScrapeResult(
                        url=url,
                        markdown=result.markdown or "",
                        extracted=extracted,
                        success=result.success,
                        error=None if result.success else "LLM extraction failed",
                    )
            return response
        except Exception as exc:
            logger.exception("LLM extraction failed for %s", url)
            error = "Managed local AI extraction failed" if managed_runtime else str(exc)
            return ScrapeResult(url=url, success=False, error=error)
