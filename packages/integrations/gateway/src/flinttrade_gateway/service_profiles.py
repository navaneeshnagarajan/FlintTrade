"""Static, non-invoking projection of broker catalogue facts."""

from __future__ import annotations

from flinttrade_core.service_providers import ProviderDescriptor, ServiceKind

from .adapter import BROKER_CATALOG

_BROKER_SERVICE_KINDS = frozenset({ServiceKind.BROKER_EXECUTION, ServiceKind.MARKET_DATA_LIVE})
_COMMON_BROKER_CAPABILITIES = (
    "account.balances",
    "account.holdings",
    "account.positions",
    "broker.orders",
    "market.quote",
)


def _broker_capabilities(*, native: bool, connectable: bool, sandbox: bool, supports_streaming: bool) -> tuple[str, ...]:
    capabilities = list(_COMMON_BROKER_CAPABILITIES)
    if supports_streaming:
        capabilities.append("market.ticks")
    if native:
        capabilities.append("native")
    if native and connectable:
        capabilities.append("native_connectable")
    if sandbox:
        capabilities.append("practice_execution")
    return tuple(capabilities)


def broker_service_descriptors() -> tuple[ProviderDescriptor, ...]:
    """Project catalogue metadata without creating any broker connection or client."""
    descriptors = []
    for broker_id, info in BROKER_CATALOG.items():
        descriptors.append(
            ProviderDescriptor(
                provider_id=f"broker:{broker_id}",
                display_name=info.display_name,
                service_kinds=_BROKER_SERVICE_KINDS,
                capabilities=_broker_capabilities(
                    native=info.native,
                    connectable=info.connectable,
                    sandbox=info.is_sandbox,
                    supports_streaming=info.supports_streaming,
                ),
                exchanges=tuple(info.exchanges),
                auth_models=(info.auth_flow.value, *(f"method:{method.id}" for method in info.auth_methods)),
                connection_requirements=("static_ip",) if info.requires_static_ip else (),
                resource_requirements=(f"sdk:{info.sdk_pin}",) if info.sdk_pin is not None else (),
                activation_blockers=tuple(info.native_connect_blockers) if info.native else (),
                implemented=True,
            )
        )
    descriptors.append(
        ProviderDescriptor(
            provider_id="broker-bridge:openalgo",
            display_name="OpenAlgo broker bridge",
            service_kinds=_BROKER_SERVICE_KINDS,
            capabilities=(*_COMMON_BROKER_CAPABILITIES, "bridge"),
            auth_models=("api_key",),
            connection_requirements=("self_hosted_openalgo",),
            implemented=True,
        )
    )
    return tuple(descriptors)
