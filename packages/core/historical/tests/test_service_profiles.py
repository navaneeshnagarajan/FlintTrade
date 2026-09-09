"""Tests for static historical-data service catalogue contributions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from flinttrade_core.service_providers import PermissionState, ServiceKind
from flinttrade_historical.data_provider import ProviderRegistry
from flinttrade_historical.service_profiles import (
    HISTORICAL_PROVIDER_PROFILES,
    OPENALGO_PROFILE,
    OPENCHART_PROFILE,
    YFINANCE_PROFILE,
    historical_service_descriptors,
)


def test_static_profiles_expose_exact_runtime_coverage() -> None:
    assert HISTORICAL_PROVIDER_PROFILES == (
        OPENALGO_PROFILE,
        OPENCHART_PROFILE,
        YFINANCE_PROFILE,
    )
    assert tuple(profile.runtime_name for profile in HISTORICAL_PROVIDER_PROFILES) == (
        "openalgo",
        "openchart",
        "yfinance",
    )
    assert OPENALGO_PROFILE.exchanges == ("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX")
    assert OPENCHART_PROFILE.exchanges == ("NSE", "NFO")
    assert YFINANCE_PROFILE.exchanges == ("MCX",)
    assert OPENALGO_PROFILE.requires_configured_client is True
    assert OPENCHART_PROFILE.requires_configured_client is False
    assert YFINANCE_PROFILE.requires_configured_client is False
    assert OPENALGO_PROFILE.pricing_class == "unknown"
    assert OPENCHART_PROFILE.pricing_class == "free"
    assert YFINANCE_PROFILE.pricing_class == "free"


def test_static_descriptors_are_exact_and_fail_closed() -> None:
    descriptors = historical_service_descriptors()

    assert tuple(item.provider_id for item in descriptors) == (
        "market-data:openalgo-history",
        "market-data:openchart",
        "market-data:yfinance",
    )
    assert tuple(item.display_name for item in descriptors) == (
        "OpenAlgo historical data",
        "OpenChart historical data",
        "yfinance commodity proxies",
    )
    assert all(item.service_kinds == frozenset({ServiceKind.MARKET_DATA_HISTORICAL}) for item in descriptors)
    assert all(item.capabilities == ("market.history",) for item in descriptors)
    assert all(item.implemented is True for item in descriptors)
    assert tuple(item.connection_requirements for item in descriptors) == (("configured_client",), (), ())
    assert all(item.default_rights.rights.output_use is PermissionState.UNKNOWN for item in descriptors)
    assert tuple(item.provenance for item in descriptors) == tuple(
        profile.provenance for profile in HISTORICAL_PROVIDER_PROFILES
    )
    assert tuple(item.activation_blockers for item in descriptors) == tuple(
        profile.activation_blockers for profile in HISTORICAL_PROVIDER_PROFILES
    )
    assert any("international futures proxies" in item for item in YFINANCE_PROFILE.provenance)
    assert any("USDINR" in item and "83.0" in item for item in YFINANCE_PROFILE.provenance)


def test_static_descriptor_construction_does_not_construct_runtime_providers() -> None:
    with (
        patch("flinttrade_historical.data_provider.ProviderRegistry", side_effect=AssertionError("registry")),
        patch("flinttrade_historical.data_provider.OpenAlgoProvider", side_effect=AssertionError("openalgo")),
        patch("flinttrade_historical.data_provider.OpenChartProvider", side_effect=AssertionError("openchart")),
        patch("flinttrade_historical.data_provider.YFinanceProvider", side_effect=AssertionError("yfinance")),
    ):
        descriptors = historical_service_descriptors()

    assert descriptors


def test_runtime_registry_membership_matches_profiles_by_configuration() -> None:
    without_bridge = tuple(provider.name for provider in ProviderRegistry().providers)
    with_bridge = tuple(provider.name for provider in ProviderRegistry(MagicMock()).providers)

    assert without_bridge == ("openchart", "yfinance")
    assert with_bridge == tuple(profile.runtime_name for profile in HISTORICAL_PROVIDER_PROFILES)


def test_extra_providers_keep_the_existing_priority_slot() -> None:
    extra = MagicMock(name="extra_provider")
    extra.name = "fixture"

    assert tuple(provider.name for provider in ProviderRegistry(MagicMock(), [extra]).providers) == (
        "openalgo",
        "fixture",
        "openchart",
        "yfinance",
    )
