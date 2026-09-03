"""Tests for the read-only service-provider catalogue API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import httpx
import pytest
from flinttrade_ai import llm_client, rag_pipeline, sentiment
from flinttrade_ai.agent_backends import registry as agent_backend_registry
from flinttrade_ai.service_profiles import ai_service_descriptors
from flinttrade_gateway import adapter, credentials, registry
from flinttrade_gateway.service_profiles import broker_service_descriptors
from flinttrade_historical import data_provider
from flinttrade_historical.service_profiles import historical_service_descriptors

from flinttrade_core.app import create_flask_app
from flinttrade_core.service_providers import DuplicateProviderIdError, ServiceProviderCatalogue


def test_catalogue_route_is_authenticated_read_only_and_generic_forecast_only(monkeypatch, tmp_path) -> None:
    """A caller can read static catalogue facts but cannot mutate providers."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "catalogue-test-key")
    app = create_flask_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        denied = client.get("/v1/services/providers")
        response = client.get(
            "/v1/services/providers",
            headers={"X-API-Key": "catalogue-test-key"},
        )
        mutation = client.post(
            "/v1/services/providers",
            json={},
            headers={"X-API-Key": "catalogue-test-key"},
        )

    assert denied.status_code == 401
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["data"]["count"] == 64
    ids = {item["provider_id"] for item in body["data"]["providers"]}
    assert {
        "broker:dhan",
        "market-data:openchart",
        "news:rss.moneycontrol",
        "llm:grok",
        "agent-runtime:hermes",
        "embedding:sentence-transformers",
        "forecast:external-json",
    } <= ids
    assert {provider_id for provider_id in ids if provider_id.startswith("forecast:")} == {
        "forecast:external-json"
    }
    assert mutation.status_code == 405


def test_catalogue_composition_preserves_contributor_order_and_static_payload(monkeypatch, tmp_path) -> None:
    """Composition keeps the three static contributor groups in their declared order."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    app = create_flask_app()

    catalogue = app.config["SERVICE_PROVIDER_CATALOGUE"]
    ids = tuple(provider.provider_id for provider in catalogue.list())
    assert len(ids) == 64
    assert ids[:23] == tuple(provider.provider_id for provider in ai_service_descriptors())
    assert ids[23:26] == (
        "market-data:openalgo-history",
        "market-data:openchart",
        "market-data:yfinance",
    )
    assert ids[-1] == "broker-bridge:openalgo"

    payload = catalogue.to_public_payload()
    forbidden = {"connection", "secret", "health", "readiness", "budget", "entitlement"}
    assert all(forbidden.isdisjoint(provider) for provider in payload["providers"])


def test_catalogue_composition_does_not_invoke_provider_transports(monkeypatch, tmp_path) -> None:
    """App construction only reads profiles and never calls an HTTP transport."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    with (
        patch("httpx.Client.get", side_effect=AssertionError("network I/O")),
        patch("httpx.Client.post", side_effect=AssertionError("network I/O")),
    ):
        app = create_flask_app()

    assert app.config["SERVICE_PROVIDER_CATALOGUE"].list()


def test_ai_contribution_reads_static_profiles_without_runtime_io() -> None:
    """AI metadata assembly cannot instantiate clients, probe binaries, or touch storage."""
    def poison_constructor(*args: object, **kwargs: object) -> None:
        raise AssertionError("embedding constructor or model download")

    sentence_transformers = ModuleType("sentence_transformers")
    sentence_transformers.SentenceTransformer = poison_constructor
    openai = ModuleType("openai")
    openai.OpenAI = poison_constructor
    huggingface_hub = ModuleType("huggingface_hub")
    huggingface_hub.snapshot_download = poison_constructor

    with (
        patch.dict(
            sys.modules,
            {
                "sentence_transformers": sentence_transformers,
                "openai": openai,
                "huggingface_hub": huggingface_hub,
            },
        ),
        patch.object(llm_client, "LLMClient", side_effect=AssertionError("LLM client")),
        patch.object(sentiment, "NewsScraper", side_effect=AssertionError("RSS scraper")),
        patch.object(rag_pipeline, "EmbeddingProvider", side_effect=AssertionError("embedding provider")),
        patch.object(agent_backend_registry, "detect_backend", side_effect=AssertionError("backend detection")),
        patch.object(subprocess, "Popen", side_effect=AssertionError("subprocess")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess")),
        patch.object(httpx, "get", side_effect=AssertionError("module HTTP")),
        patch.object(httpx, "post", side_effect=AssertionError("module HTTP")),
        patch.object(httpx.Client, "get", side_effect=AssertionError("client HTTP")),
        patch.object(httpx.Client, "post", side_effect=AssertionError("client HTTP")),
        patch.object(Path, "mkdir", side_effect=AssertionError("filesystem")),
        patch.object(Path, "read_text", side_effect=AssertionError("filesystem")),
        patch.object(Path, "write_text", side_effect=AssertionError("filesystem")),
    ):
        descriptors = ai_service_descriptors()

    assert len(descriptors) == 23


def test_historical_contribution_reads_static_profiles_without_runtime_io() -> None:
    """Historical metadata assembly never constructs registry or data-provider objects."""
    with (
        patch.object(data_provider, "ProviderRegistry", side_effect=AssertionError("registry")),
        patch.object(data_provider, "OpenAlgoProvider", side_effect=AssertionError("openalgo")),
        patch.object(data_provider, "OpenChartProvider", side_effect=AssertionError("openchart")),
        patch.object(data_provider, "YFinanceProvider", side_effect=AssertionError("yfinance")),
        patch.object(httpx, "get", side_effect=AssertionError("module HTTP")),
        patch.object(httpx.Client, "get", side_effect=AssertionError("client HTTP")),
        patch.object(Path, "mkdir", side_effect=AssertionError("filesystem")),
    ):
        descriptors = historical_service_descriptors()

    assert tuple(descriptor.provider_id for descriptor in descriptors) == (
        "market-data:openalgo-history",
        "market-data:openchart",
        "market-data:yfinance",
    )


def test_gateway_contribution_reads_catalogue_without_broker_or_credential_io() -> None:
    """Broker metadata projection never constructs a registry, adapter, or credential store."""
    with (
        patch.object(registry, "BrokerRegistry", side_effect=AssertionError("broker registry")),
        patch.object(adapter, "load_broker_adapter", side_effect=AssertionError("broker adapter")),
        patch.object(credentials, "CredentialStore", side_effect=AssertionError("credential store")),
        patch.object(httpx, "get", side_effect=AssertionError("module HTTP")),
        patch.object(httpx.Client, "get", side_effect=AssertionError("client HTTP")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess")),
        patch.object(Path, "mkdir", side_effect=AssertionError("filesystem")),
    ):
        descriptors = broker_service_descriptors()

    assert len(descriptors) == 38
    assert descriptors[-1].provider_id == "broker-bridge:openalgo"


def test_injected_catalogue_identity_is_preserved(monkeypatch, tmp_path) -> None:
    """An embedding host can supply the immutable catalogue it already owns."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    injected = ServiceProviderCatalogue(())

    app = create_flask_app(service_provider_catalogue=injected)

    assert app.config["SERVICE_PROVIDER_CATALOGUE"] is injected


def test_duplicate_contributor_ids_fail_before_catalogue_publication(monkeypatch, tmp_path) -> None:
    """A contributor collision is a deterministic startup defect, never a merge choice."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    from flinttrade_ai import service_profiles

    original = service_profiles.ai_service_descriptors
    monkeypatch.setattr(service_profiles, "ai_service_descriptors", lambda: (*original(), original()[0]))

    with pytest.raises(DuplicateProviderIdError):
        create_flask_app()
