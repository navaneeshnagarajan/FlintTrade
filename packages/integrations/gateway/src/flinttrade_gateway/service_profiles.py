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


def _broker_capabilities(*, native: bool, connectable: bool, sandbox: bool) -> tuple[str, ...]:
    capabilities = list(_COMMON_BROKER_CAPABILITIES)
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
                ),
                exchanges=tuple(info.exchanges),
                auth_models=(info.auth_flow.value, *(f"method:{method.id}" for method in info.auth_methods)),
                connection_requirements=("static_ip",) if info.requires_static_ip else (),
                resource_requirements=(f"sdk:{info.sdk_pin}",) if info.sdk_pin is not None else (),
                activation_blockers=tuple(info.native_connect_blockers) if info.native else (),
                implemented=True,
            )
        )
    return tuple(descriptors)


# ---------------------------------------------------------------------------
# Order-entry profile: how each broker places a stop-loss and target
# ---------------------------------------------------------------------------

STOP_LOSS_TARGET_ATTACHED = "attached"
STOP_LOSS_TARGET_SEPARATE = "separate"

# A broker that attaches the stop-loss and target to the entry as one order.
# Every other broker, and Practice, places them as separate orders. Real
# placement of an attached order still goes through its own gated verb; this
# profile only describes the broker, it does not enable anything.
_ATTACHED_STOP_LOSS_TARGET_BROKERS = frozenset({"dhan", "practice", "sandbox"})


def stop_loss_target_placement(broker_id: str) -> str:
    """Return ``attached`` or ``separate`` for a broker id from the catalogue."""
    key = str(broker_id or "").strip().lower()
    return STOP_LOSS_TARGET_ATTACHED if key in _ATTACHED_STOP_LOSS_TARGET_BROKERS else STOP_LOSS_TARGET_SEPARATE


def broker_display_name(broker_id: str) -> str:
    """Catalogue display name, ``Practice`` for the sandbox, else the id."""
    key = str(broker_id or "").strip().lower()
    if key in {"practice", "sandbox"}:
        return "Practice"
    info = BROKER_CATALOG.get(key)
    return info.display_name if info is not None else key


def order_entry_profile(broker_id: str) -> dict[str, str]:
    """Facts the order rules need about one broker."""
    key = str(broker_id or "").strip().lower()
    rules_broker = "practice" if key in {"practice", "sandbox"} else key
    return {
        "broker": rules_broker,
        "broker_name": broker_display_name(key),
        "stop_loss_target_placement": stop_loss_target_placement(key),
    }
