"""Static historical-data provider facts shared with runtime routing."""

from __future__ import annotations

from dataclasses import dataclass

from flinttrade_core.service_providers import ProviderDescriptor, RightsResolution, ServiceKind, UsageRights


@dataclass(frozen=True, slots=True)
class HistoricalProviderProfile:
    """Static facts for one historical-data provider implementation."""

    runtime_name: str
    provider_id: str
    display_name: str
    exchanges: tuple[str, ...]
    pricing_class: str
    requires_configured_client: bool
    provenance: tuple[str, ...]
    activation_blockers: tuple[str, ...]


OPENALGO_PROFILE = HistoricalProviderProfile(
    runtime_name="openalgo",
    provider_id="market-data:openalgo-history",
    display_name="OpenAlgo historical data",
    exchanges=("NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX"),
    pricing_class="unknown",
    requires_configured_client=True,
    provenance=("Configured OpenAlgo client history endpoint.",),
    activation_blockers=("A configured OpenAlgo client is required.",),
)

OPENCHART_PROFILE = HistoricalProviderProfile(
    runtime_name="openchart",
    provider_id="market-data:openchart",
    display_name="OpenChart historical data",
    exchanges=("NSE", "NFO"),
    pricing_class="free",
    requires_configured_client=False,
    provenance=("OpenChart free historical NSE and NFO data.",),
    activation_blockers=(),
)

YFINANCE_PROFILE = HistoricalProviderProfile(
    runtime_name="yfinance",
    provider_id="market-data:yfinance",
    display_name="yfinance commodity proxies",
    exchanges=("MCX",),
    pricing_class="free",
    requires_configured_client=False,
    provenance=(
        "yfinance uses international futures proxies and approximate USDINR conversion, which can fall back to 83.0; it is not native MCX exchange data.",
    ),
    activation_blockers=(),
)

HISTORICAL_PROVIDER_PROFILES: tuple[HistoricalProviderProfile, ...] = (
    OPENALGO_PROFILE,
    OPENCHART_PROFILE,
    YFINANCE_PROFILE,
)


def _unknown_rights() -> RightsResolution:
    return RightsResolution(rights=UsageRights())


def _descriptor(profile: HistoricalProviderProfile) -> ProviderDescriptor:
    """Project one static profile to an immutable catalogue descriptor."""
    return ProviderDescriptor(
        provider_id=profile.provider_id,
        display_name=profile.display_name,
        service_kinds=frozenset({ServiceKind.MARKET_DATA_HISTORICAL}),
        capabilities=("market.history",),
        exchanges=profile.exchanges,
        pricing_class=profile.pricing_class,
        connection_requirements=("configured_client",) if profile.requires_configured_client else (),
        provenance=profile.provenance,
        activation_blockers=profile.activation_blockers,
        implemented=True,
        default_rights=_unknown_rights(),
    )


def historical_service_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Return static historical-data descriptors without constructing providers."""
    return tuple(_descriptor(profile) for profile in HISTORICAL_PROVIDER_PROFILES)
