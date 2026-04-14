"""Crypto trading utilities for Delta Exchange via OpenAlgo.

Delta Exchange is the Indian crypto derivatives exchange supported by OpenAlgo.
This module provides symbol metadata, fee schedules, price formatting, and
order validation helpers that sit on top of the OpenAlgo REST/WebSocket layer.

All amounts are in USD or INR depending on the quote currency of the pair.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger("flinttrade.core.crypto_utils")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CryptoPairInfo:
    """Metadata for a single crypto trading pair on Delta Exchange.

    Attributes:
        base: Base currency (e.g. "BTC").
        quote: Quote currency (e.g. "USD" or "INR").
        lot_size: Minimum tradeable quantity increment.
        tick_size: Minimum price movement (price step).
        maker_fee: Maker rebate/fee as a fraction (negative = rebate).
        taker_fee: Taker fee as a fraction.
        description: Human-readable contract description.
    """

    base: str
    quote: str
    lot_size: float
    tick_size: float
    maker_fee: float
    taker_fee: float
    description: str = ""


# ---------------------------------------------------------------------------
# Pair catalogue
# ---------------------------------------------------------------------------

#: All supported Delta Exchange perpetual / spot pairs.
#: Fee schedule reflects Delta Exchange standard tier (updated 2026-04).
CRYPTO_PAIRS: Final[dict[str, CryptoPairInfo]] = {
    # ── USD-quoted pairs ────────────────────────────────────────────────
    "BTCUSD": CryptoPairInfo(
        base="BTC",
        quote="USD",
        lot_size=0.001,
        tick_size=0.5,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Bitcoin Perpetual (USD)",
    ),
    "ETHUSD": CryptoPairInfo(
        base="ETH",
        quote="USD",
        lot_size=0.01,
        tick_size=0.05,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Ethereum Perpetual (USD)",
    ),
    "SOLUSD": CryptoPairInfo(
        base="SOL",
        quote="USD",
        lot_size=0.1,
        tick_size=0.01,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Solana Perpetual (USD)",
    ),
    "BNBUSD": CryptoPairInfo(
        base="BNB",
        quote="USD",
        lot_size=0.01,
        tick_size=0.01,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="BNB Perpetual (USD)",
    ),
    "XRPUSD": CryptoPairInfo(
        base="XRP",
        quote="USD",
        lot_size=1.0,
        tick_size=0.0001,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="XRP Perpetual (USD)",
    ),
    "MATICUSD": CryptoPairInfo(
        base="MATIC",
        quote="USD",
        lot_size=1.0,
        tick_size=0.0001,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Polygon Perpetual (USD)",
    ),
    # ── INR-quoted pairs ─────────────────────────────────────────────────
    "BTCINR": CryptoPairInfo(
        base="BTC",
        quote="INR",
        lot_size=0.0001,
        tick_size=1.0,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Bitcoin Perpetual (INR)",
    ),
    "ETHINR": CryptoPairInfo(
        base="ETH",
        quote="INR",
        lot_size=0.001,
        tick_size=0.5,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Ethereum Perpetual (INR)",
    ),
    "SOLINR": CryptoPairInfo(
        base="SOL",
        quote="INR",
        lot_size=0.1,
        tick_size=0.1,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="Solana Perpetual (INR)",
    ),
    "XRPINR": CryptoPairInfo(
        base="XRP",
        quote="INR",
        lot_size=1.0,
        tick_size=0.01,
        maker_fee=0.0002,
        taker_fee=0.0005,
        description="XRP Perpetual (INR)",
    ),
}

#: Set of exchange identifiers that map to Delta Exchange.
DELTA_EXCHANGE_NAMES: Final[frozenset[str]] = frozenset(
    {"DELTA", "DELTAEXCHANGE", "CRYPTO"}
)

#: Number of decimal places used when displaying prices, keyed by quote currency.
_QUOTE_DECIMALS: Final[dict[str, int]] = {
    "USD": 2,
    "INR": 2,
    "USDT": 4,
    "BTC": 8,
    "ETH": 6,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class CryptoUtils:
    """Utility functions for crypto trading via Delta Exchange + OpenAlgo.

    All methods are static — this class is a pure namespace, not meant to be
    instantiated.

    Example::

        >>> CryptoUtils.is_crypto_exchange("DELTA")
        True
        >>> CryptoUtils.get_lot_size("BTCUSD")
        0.001
        >>> CryptoUtils.format_crypto_price(67432.5, "BTCUSD")
        '67432.50'
    """

    # ------------------------------------------------------------------
    # Exchange identification
    # ------------------------------------------------------------------

    @staticmethod
    def is_crypto_exchange(exchange: str) -> bool:
        """Return True if *exchange* refers to Delta Exchange.

        Args:
            exchange: Exchange identifier string (case-insensitive).

        Returns:
            True for "DELTA", "DELTAEXCHANGE", or "CRYPTO".

        Example::

            >>> CryptoUtils.is_crypto_exchange("delta")
            True
            >>> CryptoUtils.is_crypto_exchange("NSE")
            False
        """
        return exchange.upper() in DELTA_EXCHANGE_NAMES

    # ------------------------------------------------------------------
    # Symbol metadata
    # ------------------------------------------------------------------

    @staticmethod
    def is_crypto_pair(symbol: str) -> bool:
        """Return True if *symbol* is a known Delta Exchange trading pair.

        Args:
            symbol: Trading symbol (case-insensitive, e.g. "BTCUSD").

        Returns:
            True if the pair is in the catalogue.
        """
        return symbol.upper() in CRYPTO_PAIRS

    @staticmethod
    def get_pair_info(symbol: str) -> CryptoPairInfo | None:
        """Return the full :class:`CryptoPairInfo` for *symbol*.

        Args:
            symbol: Trading symbol (case-insensitive).

        Returns:
            ``CryptoPairInfo`` for the pair, or ``None`` if unknown.
        """
        return CRYPTO_PAIRS.get(symbol.upper())

    @staticmethod
    def get_lot_size(symbol: str) -> float:
        """Return the minimum lot size for *symbol*.

        Args:
            symbol: Trading symbol (case-insensitive).

        Returns:
            Lot size as a float.  Returns ``0.001`` (BTC default) when the
            symbol is not in the catalogue so callers always get a usable value.
        """
        info = CRYPTO_PAIRS.get(symbol.upper())
        return info.lot_size if info is not None else 0.001

    @staticmethod
    def get_tick_size(symbol: str) -> float:
        """Return the minimum price tick for *symbol*.

        Args:
            symbol: Trading symbol (case-insensitive).

        Returns:
            Tick size as a float.  Falls back to ``0.01`` for unknown pairs.
        """
        info = CRYPTO_PAIRS.get(symbol.upper())
        return info.tick_size if info is not None else 0.01

    # ------------------------------------------------------------------
    # Price formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_crypto_price(price: float, symbol: str) -> str:
        """Format *price* with the correct decimal precision for *symbol*.

        Decimal places are determined by the quote currency:

        * USD / INR  → 2 dp  (e.g. ``"67432.50"``)
        * USDT       → 4 dp
        * BTC        → 8 dp
        * ETH        → 6 dp
        * Unknown    → 2 dp (safe default)

        Args:
            price: Raw price value.
            symbol: Trading symbol used to look up the quote currency.

        Returns:
            Formatted price string with appropriate decimal places.

        Raises:
            ValueError: If *price* is negative.

        Example::

            >>> CryptoUtils.format_crypto_price(0.05123456, "ETHUSD")
            '0.05'
        """
        if price < 0:
            raise ValueError(f"Price cannot be negative: {price}")

        info = CRYPTO_PAIRS.get(symbol.upper())
        quote = info.quote if info is not None else "USD"
        dp = _QUOTE_DECIMALS.get(quote, 2)
        return f"{price:.{dp}f}"

    # ------------------------------------------------------------------
    # Fee schedule
    # ------------------------------------------------------------------

    @staticmethod
    def get_trading_fee(symbol: str) -> dict[str, float]:
        """Return maker and taker fee fractions for *symbol*.

        Delta Exchange charges fees as a fraction of the notional value.
        A negative maker fee indicates a rebate.

        Args:
            symbol: Trading symbol (case-insensitive).

        Returns:
            Dict with keys ``"maker"`` and ``"taker"``.  Falls back to the
            standard Delta tier (0.02 % maker / 0.05 % taker) for unknown pairs.

        Example::

            >>> CryptoUtils.get_trading_fee("BTCUSD")
            {'maker': 0.0002, 'taker': 0.0005}
        """
        info = CRYPTO_PAIRS.get(symbol.upper())
        if info is not None:
            return {"maker": info.maker_fee, "taker": info.taker_fee}
        # Standard Delta tier as safe default
        return {"maker": 0.0002, "taker": 0.0005}

    # ------------------------------------------------------------------
    # Order validation
    # ------------------------------------------------------------------

    @staticmethod
    def round_to_lot_size(quantity: float, symbol: str) -> float:
        """Round *quantity* down to the nearest valid lot increment.

        Prevents order rejection due to sub-lot quantities.

        Args:
            quantity: Requested quantity.
            symbol: Trading symbol used to look up lot size.

        Returns:
            Quantity rounded down to the nearest multiple of the lot size.

        Raises:
            ValueError: If *quantity* is not positive.

        Example::

            >>> CryptoUtils.round_to_lot_size(0.0037, "BTCUSD")
            0.003
        """
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive: {quantity}")

        lot = CryptoUtils.get_lot_size(symbol)
        # Avoid floating-point drift with integer arithmetic
        factor = round(1.0 / lot)
        return round(int(quantity * factor) / factor, 10)

    @staticmethod
    def round_to_tick_size(price: float, symbol: str) -> float:
        """Round *price* to the nearest valid tick increment.

        Prevents order rejection due to invalid price precision.

        Args:
            price: Raw price value.
            symbol: Trading symbol used to look up tick size.

        Returns:
            Price rounded to the nearest tick.

        Raises:
            ValueError: If *price* is not positive.
        """
        if price <= 0:
            raise ValueError(f"Price must be positive: {price}")

        tick = CryptoUtils.get_tick_size(symbol)
        factor = round(1.0 / tick)
        return round(round(price * factor) / factor, 10)

    # ------------------------------------------------------------------
    # Convenience lists
    # ------------------------------------------------------------------

    @staticmethod
    def all_pairs() -> list[str]:
        """Return all known crypto pair symbols in catalogue order.

        Returns:
            Sorted list of symbol strings (e.g. ``["BNBUSD", "BTCINR", ...]``).
        """
        return sorted(CRYPTO_PAIRS.keys())

    @staticmethod
    def usd_pairs() -> list[str]:
        """Return USD-quoted pairs only.

        Returns:
            Sorted list of USD-quoted pair symbols.
        """
        return sorted(s for s, info in CRYPTO_PAIRS.items() if info.quote == "USD")

    @staticmethod
    def inr_pairs() -> list[str]:
        """Return INR-quoted pairs only.

        Returns:
            Sorted list of INR-quoted pair symbols.
        """
        return sorted(s for s, info in CRYPTO_PAIRS.items() if info.quote == "INR")
