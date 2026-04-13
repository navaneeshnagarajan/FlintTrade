"""Dynamic lot size resolver for F&O instruments.

Fetches authoritative lot sizes from the OpenAlgo ``instruments`` endpoint
and caches them for 24 hours.  Falls back to a built-in table of common lot
sizes when the live fetch is unavailable.

The built-in table reflects current NSE/BSE/MCX/CDS contract specifications.
NIFTY is 75 as of the current NSE-mandated lot size.

Usage::

    resolver = LotSizeResolver(client)
    lot = await resolver.get_lot_size("NIFTY", "NFO")   # 75 (or live value)
    lot = await resolver.get_lot_size("UNKNOWN", "NFO")  # 1 (safe default)

    # Or use the convenience module-level function (uses shared instance):
    lot = get_lot_size_sync("BANKNIFTY", "NFO")  # synchronous fallback only
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.screener.lot_sizes")

# ---------------------------------------------------------------------------
# Built-in fallback table
# ---------------------------------------------------------------------------

# NSE F&O — Index options/futures
# NIFTY: 75 lots per contract (NSE mandate, last revised Nov 2024)
# BANKNIFTY: 30 (reduced from 15 in 2024 NSE revision)
FALLBACK_LOT_SIZES: dict[str, int] = {
    # NFO — Index derivatives
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 50,
    "NIFTYNXT50": 25,
    # BFO — BSE derivatives
    "SENSEX": 20,
    "BANKEX": 30,
    "SENSEX50": 25,
    # CDS — Currency derivatives (all per contract in INR notional units)
    "USDINR": 1_000,
    "EURINR": 1_000,
    "GBPINR": 1_000,
    "JPYINR": 1_000,
    "USDINR-SFX": 1_000,
    # MCX — Bullion
    "GOLD": 100,        # 100 grams
    "GOLDM": 10,        # 10 grams (Gold Mini)
    "GOLDPETAL": 1,     # 1 gram (Gold Petal)
    "SILVER": 30,       # 30 kg
    "SILVERM": 5,       # 5 kg (Silver Mini)
    "SILVERMIC": 1,     # 1 kg (Silver Micro)
    # MCX — Energy
    "CRUDEOIL": 100,    # 100 barrels
    "CRUDEOILM": 10,    # 10 barrels (Crude Mini)
    "NATURALGAS": 1_250,  # 1250 MMBtu
    # MCX — Base metals
    "COPPER": 2_500,    # 2.5 tonnes (kg)
    "COPPERM": 250,     # 250 kg (Copper Mini)
    "ZINC": 5_000,      # 5 tonnes (kg)
    "ZINCMINI": 1_000,  # 1 tonne (kg)
    "LEAD": 5_000,      # 5 tonnes (kg)
    "LEADMINI": 1_000,  # 1 tonne (kg)
    "NICKEL": 1_500,    # 1.5 tonnes (kg)
    "NICKELMINI": 100,  # 100 kg
    "ALUMINIUM": 5_000, # 5 tonnes (kg)
    "ALUMINI": 1_000,   # 1 tonne (kg)
    # MCX — Agri
    "MENTHAOIL": 360,   # 360 kg
    "COTTON": 25,       # 25 bales
}

# Cache TTL — lot sizes change infrequently; 24 hours is safe
_CACHE_TTL_SECONDS: int = 86_400  # 24 hours


def get_lot_size_sync(symbol: str, exchange: str = "") -> int:  # noqa: ARG001
    """Return the lot size for a symbol using the built-in fallback table only.

    This synchronous function never makes a network call.  Use
    ``LotSizeResolver.get_lot_size`` for the live-fetch variant.

    Args:
        symbol: Underlying or instrument symbol, e.g. ``"NIFTY"``.
        exchange: Exchange code (unused in sync fallback; reserved for future
            exchange-specific overrides).

    Returns:
        Lot size as an integer.  Returns ``1`` for unknown symbols.
    """
    return FALLBACK_LOT_SIZES.get(symbol.upper().strip(), 1)


# ---------------------------------------------------------------------------
# LotSizeResolver — live fetch with 24-hour cache
# ---------------------------------------------------------------------------


class LotSizeResolver:
    """Fetch and cache lot sizes from the OpenAlgo ``instruments`` endpoint.

    The resolver keeps an in-process cache keyed by ``(symbol, exchange)``
    with a configurable TTL (default 24 hours).  On cache miss it queries
    OpenAlgo; on network failure it falls back to the built-in table.

    Args:
        client: An ``OpenAlgoClient`` instance used for API calls.
        cache_ttl: Cache lifetime in seconds (default 86400 = 24 hours).

    Usage::

        resolver = LotSizeResolver(client)
        lot = resolver.get_lot_size("NIFTY", "NFO")
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        cache_ttl: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._cache_ttl = cache_ttl
        # Cache entries: (symbol_upper, exchange_upper) -> (lot_size, fetched_at)
        self._cache: dict[tuple[str, str], tuple[int, float]] = {}

    def _is_fresh(self, key: tuple[str, str]) -> bool:
        """Return True if the cache entry for *key* is still within TTL."""
        entry = self._cache.get(key)
        if entry is None:
            return False
        _, fetched_at = entry
        return (time.monotonic() - fetched_at) < self._cache_ttl

    def _fetch_from_openalgo(self, exchange: str) -> dict[str, int]:
        """Fetch all lot sizes for an exchange from OpenAlgo instruments endpoint.

        Returns a mapping of ``{symbol_upper: lot_size}`` or an empty dict on
        failure.

        Args:
            exchange: Exchange code, e.g. ``"NFO"``.

        Returns:
            Dict of symbol → lot size.  Empty on any error.
        """
        try:
            # OpenAlgo /api/v1/instruments returns a list of instrument dicts
            # with fields: symbol, exchange, lot_size (and others).
            instruments = self._client.instruments(exchange=exchange)
            if not isinstance(instruments, list):
                return {}
            result: dict[str, int] = {}
            for inst in instruments:
                sym = str(inst.get("symbol", "")).upper().strip()
                lot = inst.get("lot_size") or inst.get("lotsize") or inst.get("lot")
                if sym and lot is not None:
                    try:
                        result[sym] = int(lot)
                    except (ValueError, TypeError):
                        pass
            logger.debug(
                "Fetched %d lot sizes for exchange %s from OpenAlgo",
                len(result),
                exchange,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to fetch instruments from OpenAlgo for exchange %s: %s",
                exchange,
                exc,
            )
            return {}

    def get_lot_size(self, symbol: str, exchange: str) -> int:
        """Return the lot size for a symbol, fetching live data if needed.

        Lookup order:
        1. In-process cache (if within TTL).
        2. Live fetch from OpenAlgo ``/api/v1/instruments`` for the exchange.
        3. Built-in fallback table.
        4. Default of ``1`` for unknown symbols.

        Args:
            symbol: Underlying symbol, e.g. ``"NIFTY"`` or ``"BANKNIFTY"``.
            exchange: Exchange code, e.g. ``"NFO"``, ``"MCX"``.

        Returns:
            Lot size as an integer, always >= 1.
        """
        sym_key = symbol.upper().strip()
        exc_key = exchange.upper().strip()
        cache_key = (sym_key, exc_key)

        if self._is_fresh(cache_key):
            return self._cache[cache_key][0]

        # Fetch the full instrument list for this exchange and populate cache
        live_data = self._fetch_from_openalgo(exc_key)
        now = time.monotonic()
        for fetched_sym, lot in live_data.items():
            self._cache[(fetched_sym, exc_key)] = (lot, now)

        if cache_key in self._cache:
            return self._cache[cache_key][0]

        # Fall back to built-in table
        fallback = FALLBACK_LOT_SIZES.get(sym_key, 1)
        # Cache the fallback result with the same TTL to avoid repeated fetches
        self._cache[cache_key] = (fallback, now)
        return fallback

    def invalidate(self, symbol: str | None = None, exchange: str | None = None) -> None:
        """Invalidate cache entries.

        Args:
            symbol: If provided, only invalidate entries for this symbol.
            exchange: If provided, only invalidate entries for this exchange.
            When both are None, the entire cache is cleared.
        """
        if symbol is None and exchange is None:
            self._cache.clear()
            return
        keys_to_remove = [
            k for k in self._cache
            if (symbol is None or k[0] == symbol.upper().strip())
            and (exchange is None or k[1] == exchange.upper().strip())
        ]
        for k in keys_to_remove:
            del self._cache[k]

    @property
    def cache_size(self) -> int:
        """Return the number of entries currently in the cache."""
        return len(self._cache)
