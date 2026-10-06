"""Historical interval choices derived from native adapter capabilities."""

from __future__ import annotations

from flinttrade_gateway.brokers.native_factory import NATIVE_ADAPTER_SPECS


def _interval_choices() -> dict[str, list[str]]:
    choices = {}
    for broker, spec in NATIVE_ADAPTER_SPECS.items():
        capability = spec.capabilities
        minutes = sorted(set(capability.historical_intraday_intervals_minutes))
        intraday = [f"{minute // 60}h" if minute % 60 == 0 else f"{minute}m" for minute in minutes]
        calendar = [value.lower() for value in capability.historical_calendar_intervals]
        choices[broker] = list(dict.fromkeys(intraday + calendar))
    return choices


SUPPORTED_INTERVALS_PER_BROKER = _interval_choices()
ALL_KNOWN_INTERVALS = frozenset(value for values in SUPPORTED_INTERVALS_PER_BROKER.values() for value in values)


def get_intervals(broker: str) -> list[str]:
    """Return only intervals declared by the native adapter; unknown brokers have none."""
    return list(SUPPORTED_INTERVALS_PER_BROKER.get(broker.strip().lower(), ()))


def is_supported(broker: str, interval: str) -> bool:
    """Check the native adapter's declared historical support."""
    return interval in get_intervals(broker)


def get_common_intervals(brokers: list[str]) -> list[str]:
    """Preserve the first adapter's ordering while intersecting every declaration."""
    if not brokers:
        return []
    first = get_intervals(brokers[0])
    supported = [set(get_intervals(broker)) for broker in brokers[1:]]
    return [interval for interval in first if all(interval in values for values in supported)]


def list_brokers() -> list[str]:
    """List native adapters contributing historical capability facts."""
    return sorted(SUPPORTED_INTERVALS_PER_BROKER)
