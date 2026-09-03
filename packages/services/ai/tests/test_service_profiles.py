"""Tests for static AI service-catalogue contributions."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import httpx
import pytest
from flinttrade_ai.agent_backends.profiles import AGENT_BACKEND_CATALOGUE
from flinttrade_ai.agent_backends import registry
from flinttrade_ai import llm_client, rag_pipeline, sentiment
from flinttrade_ai.llm_client import LLMProvider
from flinttrade_ai.service_profiles import DEFAULT_FEEDS, RSS_SOURCES, ai_service_descriptors


def test_ai_contribution_exactly_covers_current_surfaces() -> None:
    descriptors = ai_service_descriptors()
    ids = {item.provider_id for item in descriptors}

    assert {f"llm:{provider.value}" for provider in LLMProvider} <= ids
    assert {f"agent-runtime:{item.id}" for item in AGENT_BACKEND_CATALOGUE if item.requires_binary} <= ids
    assert {"embedding:sentence-transformers", "embedding:openai-compatible"} <= ids
    assert {"news:rss.moneycontrol", "news:rss.economictimes", "news:rss.livemint"} <= ids
    assert "forecast:external-json" in ids


def test_tracked_ai_catalogue_has_no_timesfm3_specific_integration() -> None:
    payload = repr([item.to_public_dict() for item in ai_service_descriptors()]).lower()

    assert "timesfm-3" not in payload
    assert "timesfm3" not in payload


def test_generic_forecast_protocol_is_declared_but_not_invokable() -> None:
    forecast = next(item for item in ai_service_descriptors() if item.provider_id == "forecast:external-json")

    assert forecast.implemented is False
    assert forecast.activation_blockers
    assert "forecast.run" not in forecast.capabilities
    assert "forecast.protocol" in forecast.capabilities


def test_rss_sources_have_one_canonical_market_feed_each() -> None:
    assert RSS_SOURCES == {
        "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
        "economictimes": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "livemint": "https://www.livemint.com/rss/markets",
    }
    assert DEFAULT_FEEDS == tuple(RSS_SOURCES.values())


def test_rss_sources_are_read_only_compatibility_data() -> None:
    original = RSS_SOURCES["moneycontrol"]
    try:
        with pytest.raises(TypeError):
            RSS_SOURCES["moneycontrol"] = "https://example.invalid/rss"
    finally:
        if RSS_SOURCES["moneycontrol"] != original:
            RSS_SOURCES["moneycontrol"] = original


def test_agent_and_embedding_descriptors_have_exact_static_metadata() -> None:
    descriptors = {item.provider_id: item for item in ai_service_descriptors()}

    for profile in AGENT_BACKEND_CATALOGUE:
        if profile.requires_binary:
            descriptor = descriptors[f"agent-runtime:{profile.id}"]
            assert descriptor.capabilities == ("agent.runtime",)
            assert descriptor.pricing_class == "unknown"

    assert descriptors["embedding:sentence-transformers"].capabilities == ("embedding.create",)
    assert descriptors["embedding:openai-compatible"].capabilities == ("embedding.create",)


def test_static_contribution_construction_has_no_provider_io() -> None:
    with (
        patch.object(llm_client, "LLMClient", side_effect=AssertionError("LLM client")),
        patch.object(sentiment, "NewsScraper", side_effect=AssertionError("RSS scraper")),
        patch.object(rag_pipeline, "EmbeddingProvider", side_effect=AssertionError("embedding client")),
        patch.object(registry, "detect_backend", side_effect=AssertionError("backend detection")),
        patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess")),
        patch.object(httpx, "get", side_effect=AssertionError("HTTP")),
        patch.object(httpx, "Client", side_effect=AssertionError("HTTP")),
    ):
        descriptors = ai_service_descriptors()

    assert descriptors
