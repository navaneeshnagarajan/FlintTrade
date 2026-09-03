"""Tests for the static broker service-catalogue projection."""

from __future__ import annotations

from flinttrade_core.service_providers import ServiceKind
from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.service_profiles import broker_service_descriptors


def test_broker_projection_has_exact_catalogue_coverage_plus_trailing_bridge() -> None:
    """A missing or reordered broker cannot silently change catalogue coverage."""
    descriptors = broker_service_descriptors()

    assert tuple(item.provider_id for item in descriptors) == (
        *(f"broker:{broker_id}" for broker_id in BROKER_CATALOG),
        "broker-bridge:openalgo",
    )


def test_broker_projection_preserves_static_catalogue_facts() -> None:
    """A profile must reflect broker metadata without exposing mutable source lists."""
    by_id = {item.provider_id: item for item in broker_service_descriptors()}
    kotakneo = by_id["broker:kotakneo"]

    assert kotakneo.display_name == "Kotak Neo"
    assert kotakneo.exchanges == tuple(sorted(BROKER_CATALOG["kotakneo"].exchanges))
    assert kotakneo.auth_models == ("method:totp_mpin", "totp_form")
    assert kotakneo.connection_requirements == ("static_ip",)
    assert kotakneo.resource_requirements == ("sdk:neo-api-client",)
    assert kotakneo.activation_blockers == tuple(sorted(BROKER_CATALOG["kotakneo"].native_connect_blockers))
    assert kotakneo.service_kinds == frozenset({ServiceKind.BROKER_EXECUTION, ServiceKind.MARKET_DATA_LIVE})
    assert kotakneo.implemented is True


def test_broker_projection_classifies_native_connectability_without_health_claims() -> None:
    """Native promotion state must not be mistaken for health or readiness."""
    by_id = {item.provider_id: item for item in broker_service_descriptors()}

    assert {"native", "native_connectable"} <= set(by_id["broker:dhan"].capabilities)
    assert "native" in by_id["broker:kotakneo"].capabilities
    assert "native_connectable" not in by_id["broker:kotakneo"].capabilities
    assert by_id["broker:kotakneo"].activation_blockers
    assert all("verified" not in item.capabilities for item in by_id.values())


def test_broker_projection_withholds_ticks_until_a_runtime_path_is_routable() -> None:
    """Upstream stream support alone must not advertise a FlintTrade tick role."""
    by_id = {item.provider_id: item for item in broker_service_descriptors()}

    assert all("market.ticks" not in item.capabilities for item in by_id.values())
    assert "market.ticks" not in by_id["broker:zerodha"].capabilities
    assert "market.ticks" not in by_id["broker-bridge:openalgo"].capabilities
    assert "practice_execution" in by_id["broker:dhan_sandbox"].capabilities
    assert "practice_execution" not in by_id["broker:dhan"].capabilities


def test_openalgo_is_a_bridge_with_no_practice_execution_claim() -> None:
    """The bridge is a distinct provider, never a synthetic broker row."""
    bridge = broker_service_descriptors()[-1]

    assert "openalgo" not in BROKER_CATALOG
    assert bridge.provider_id == "broker-bridge:openalgo"
    assert bridge.auth_models == ("api_key",)
    assert bridge.connection_requirements == ("self_hosted_openalgo",)
    assert "bridge" in bridge.capabilities
    assert "practice_execution" not in bridge.capabilities
    assert bridge.implemented is True
