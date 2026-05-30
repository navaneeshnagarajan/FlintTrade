"""Interval support registry — per-broker interval lists and intersection helpers.

Provides a canonical view of which OHLCV intervals each broker supports via
OpenAlgo, enabling the UI to show only valid options and the downloader to
validate requests before hitting the API.

Example::

    from flinttrade_historical.intervals import get_intervals, is_supported

    intervals = get_intervals("zerodha")   # ["1m", "3m", "5m", ...]
    ok = is_supported("zerodha", "1m")     # True
    common = get_common_intervals(["zerodha", "angel"])  # intersection
"""

from __future__ import annotations

import logging

logger = logging.getLogger("flinttrade.historical.intervals")

# ---------------------------------------------------------------------------
# Per-broker interval registry
# ---------------------------------------------------------------------------

# Intervals listed in ascending granularity (finest → coarsest).
# Values match OpenAlgo /api/v1/intervals response format.
SUPPORTED_INTERVALS_PER_BROKER: dict[str, list[str]] = {
    "zerodha": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "angel": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "fyers": ["1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m", "1h", "1d"],
    "upstox": ["1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "icici": ["1m", "5m", "15m", "30m", "1h", "1d"],
    "hdfc": ["5m", "15m", "30m", "1h", "1d"],
    "kotak": ["1m", "5m", "15m", "30m", "1h", "1d"],
    "shoonya": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "aliceblue": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "dhan": ["1m", "5m", "15m", "30m", "1h", "1d"],
    "5paisa": ["5m", "15m", "30m", "1h", "1d"],
    "flattrade": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
    "mofsl": ["5m", "15m", "30m", "1h", "1d"],
    "paytm": ["1m", "5m", "15m", "30m", "1h", "1d"],
    "paper": ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"],
}

# Canonical set of all known intervals (union across all brokers)
ALL_KNOWN_INTERVALS: frozenset[str] = frozenset(
    iv for ivs in SUPPORTED_INTERVALS_PER_BROKER.values() for iv in ivs
)

# Default fallback used when broker is unknown
_DEFAULT_INTERVALS: list[str] = ["5m", "15m", "30m", "1h", "1d"]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_intervals(broker: str) -> list[str]:
    """Return the supported interval list for a broker.

    Args:
        broker: Broker identifier (lowercase), e.g. ``"zerodha"``.

    Returns:
        List of supported interval strings in ascending granularity order.
        Falls back to a sensible default list for unknown brokers.
    """
    key = broker.lower().strip()
    intervals = SUPPORTED_INTERVALS_PER_BROKER.get(key, _DEFAULT_INTERVALS)
    logger.debug("get_intervals(%r) → %s", broker, intervals)
    return list(intervals)


def is_supported(broker: str, interval: str) -> bool:
    """Check whether an interval is supported by a broker.

    Args:
        broker: Broker identifier (lowercase).
        interval: Interval string, e.g. ``"1m"``, ``"1d"``.

    Returns:
        ``True`` if the interval is in the broker's supported list.
    """
    return interval in get_intervals(broker)


def get_common_intervals(brokers: list[str]) -> list[str]:
    """Return intervals supported by *all* brokers in the list.

    Useful for multi-broker comparison scenarios where every broker must be
    able to supply data for the selected interval.

    Args:
        brokers: List of broker identifiers.

    Returns:
        Sorted list of intervals present in every broker's supported set.
        Returns the default list when *brokers* is empty.
    """
    if not brokers:
        logger.debug("get_common_intervals: empty broker list, returning defaults")
        return list(_DEFAULT_INTERVALS)

    sets = [frozenset(get_intervals(b)) for b in brokers]
    common: frozenset[str] = sets[0]
    for s in sets[1:]:
        common = common & s

    # Preserve ascending granularity order from the first broker's list
    first_order = get_intervals(brokers[0])
    result = [iv for iv in first_order if iv in common]
    logger.debug("get_common_intervals(%r) → %s", brokers, result)
    return result


def list_brokers() -> list[str]:
    """Return all broker identifiers in the registry.

    Returns:
        Sorted list of broker names.
    """
    return sorted(SUPPORTED_INTERVALS_PER_BROKER.keys())
