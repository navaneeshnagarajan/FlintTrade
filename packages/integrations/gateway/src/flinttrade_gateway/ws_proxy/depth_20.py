"""20-Level Market Depth — parsing and aggregation utilities.

OpenAlgo v2 introduced WebSocket mode 4 which delivers up to 20 bid/ask
price levels per tick (mode 3 in v1 only delivered 5 levels).

This module provides:

- :class:`DepthLevel` — one price/quantity/orders level.
- :class:`Depth20Tick` — full 20-level depth snapshot.
- :func:`parse_depth_20_payload` — parse a raw OpenAlgo v2 depth dict into a
  :class:`Depth20Tick`.
- :class:`Depth20Aggregator` — collapse 20 levels to 5 and compute
  order-book imbalance.

OpenAlgo v2 depth payload format
---------------------------------
The raw ``data`` dict inside a ``market_data`` WebSocket message looks like::

    {
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "timestamp": 1714000000.123,
        "ltp": 22050.0,
        "bids": [[22045.0, 150, 3], [22040.0, 200, 5], ...],  # up to 20 entries
        "asks": [[22055.0, 100, 2], [22060.0, 180, 4], ...],  # up to 20 entries
        "total_buy_qty": 12500,
        "total_sell_qty": 9800
    }

Each inner list is ``[price, quantity, orders]``.  The ``bids`` list is
assumed to be sorted best-first (descending price) and ``asks`` ascending.

Usage::

    raw = {
        "symbol": "NIFTY", "exchange": "NSE_INDEX",
        "timestamp": 1714000000.0, "ltp": 22050.0,
        "bids": [[22045.0, 150, 3]],
        "asks": [[22055.0, 100, 2]],
        "total_buy_qty": 150,
        "total_sell_qty": 100,
    }
    tick = parse_depth_20_payload(raw)

    agg = Depth20Aggregator()
    top5 = agg.aggregate_to_5(tick)
    imbalance = agg.order_book_imbalance(tick)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("flinttrade.gateway.ws_proxy.depth_20")

# Maximum depth levels the protocol supports
_MAX_DEPTH_LEVELS: int = 20


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DepthLevel:
    """A single price level in the order book.

    Attributes:
        price: Price of this level.
        quantity: Total quantity available at this price.
        orders: Number of outstanding orders at this price.
    """

    price: float
    quantity: int
    orders: int


@dataclass
class Depth20Tick:
    """20-level market depth snapshot for one instrument.

    Attributes:
        symbol: Instrument symbol (e.g. ``"NIFTY"``).
        exchange: Exchange code (e.g. ``"NSE_INDEX"``).
        timestamp: Unix epoch seconds (float).
        bids: Up to 20 bid levels, best (highest price) first.
        asks: Up to 20 ask levels, best (lowest price) first.
        total_buy_qty: Aggregate quantity across all bid levels.
        total_sell_qty: Aggregate quantity across all ask levels.
        ltp: Last-traded price (optional, may be 0.0 if absent in payload).
    """

    symbol: str
    exchange: str
    timestamp: float
    bids: list[DepthLevel] = field(default_factory=list)
    asks: list[DepthLevel] = field(default_factory=list)
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    ltp: float = 0.0

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation.

        Returns:
            Dict with all fields; ``bids`` and ``asks`` as lists of dicts.
        """
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timestamp": self.timestamp,
            "ltp": self.ltp,
            "bids": [
                {"price": lvl.price, "qty": lvl.quantity, "orders": lvl.orders}
                for lvl in self.bids
            ],
            "asks": [
                {"price": lvl.price, "qty": lvl.quantity, "orders": lvl.orders}
                for lvl in self.asks
            ],
            "total_buy_qty": self.total_buy_qty,
            "total_sell_qty": self.total_sell_qty,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_depth_20_payload(raw: dict) -> Depth20Tick:
    """Parse an OpenAlgo v2 depth payload into a :class:`Depth20Tick`.

    Accepts two bid/ask formats:
    - **List-of-lists** (primary): ``[[price, qty, orders], ...]``
    - **List-of-dicts** (alternative): ``[{"price": …, "qty": …, "orders": …}, …]``

    Both are capped at :data:`_MAX_DEPTH_LEVELS` (20) entries.

    Args:
        raw: Raw dict from the OpenAlgo WebSocket ``data`` field.

    Returns:
        A populated :class:`Depth20Tick`.

    Raises:
        KeyError: If ``symbol`` or ``exchange`` is missing from ``raw``.
        ValueError: If a bid/ask entry has an unrecognised shape.
    """
    symbol: str = raw["symbol"]
    exchange: str = raw["exchange"]
    timestamp: float = float(raw.get("timestamp", time.time()))
    ltp: float = float(raw.get("ltp", 0.0))

    bids = _parse_levels(raw.get("bids", []), "bids")
    asks = _parse_levels(raw.get("asks", []), "asks")

    # Truncate to maximum depth
    bids = bids[:_MAX_DEPTH_LEVELS]
    asks = asks[:_MAX_DEPTH_LEVELS]

    # Use provided totals if present; otherwise sum from parsed levels
    total_buy_qty: int = int(raw.get("total_buy_qty") or sum(lvl.quantity for lvl in bids))
    total_sell_qty: int = int(raw.get("total_sell_qty") or sum(lvl.quantity for lvl in asks))

    return Depth20Tick(
        symbol=symbol,
        exchange=exchange,
        timestamp=timestamp,
        bids=bids,
        asks=asks,
        total_buy_qty=total_buy_qty,
        total_sell_qty=total_sell_qty,
        ltp=ltp,
    )


def _parse_levels(raw_levels: list, side: str) -> list[DepthLevel]:
    """Convert a list of raw level entries to :class:`DepthLevel` objects.

    Args:
        raw_levels: List of ``[price, qty, orders]`` or
            ``{"price": …, "qty": …, "orders": …}`` entries.
        side: ``"bids"`` or ``"asks"`` (used in error messages only).

    Returns:
        List of :class:`DepthLevel` objects.

    Raises:
        ValueError: If an entry has an unrecognised format.
    """
    levels: list[DepthLevel] = []
    for i, entry in enumerate(raw_levels):
        if isinstance(entry, (list, tuple)):
            if len(entry) < 3:
                raise ValueError(
                    f"Depth {side}[{i}]: expected [price, qty, orders], got {entry!r}"
                )
            levels.append(
                DepthLevel(
                    price=float(entry[0]),
                    quantity=int(entry[1]),
                    orders=int(entry[2]),
                )
            )
        elif isinstance(entry, dict):
            levels.append(
                DepthLevel(
                    price=float(entry.get("price", entry.get("p", 0.0))),
                    quantity=int(entry.get("qty", entry.get("quantity", entry.get("q", 0)))),
                    orders=int(entry.get("orders", entry.get("o", 0))),
                )
            )
        else:
            raise ValueError(
                f"Depth {side}[{i}]: unrecognised entry type {type(entry).__name__!r}"
            )
    return levels


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class Depth20Aggregator:
    """Aggregate 20-level depth data into 5-level views and compute metrics.

    All methods are stateless and reusable across ticks.

    Example::

        agg = Depth20Aggregator()
        top5 = agg.aggregate_to_5(tick)          # Depth20Tick with ≤5 levels
        imbalance = agg.order_book_imbalance(tick)  # float in [-1, 1]
    """

    def aggregate_to_5(self, tick: Depth20Tick) -> Depth20Tick:
        """Collapse a 20-level depth tick to a 5-level view.

        Takes the first 5 levels (best prices) from each side. Quantities are
        NOT aggregated — each of the top-5 levels retains its individual
        quantity and orders count.

        Args:
            tick: Source :class:`Depth20Tick` (any number of levels).

        Returns:
            A new :class:`Depth20Tick` with at most 5 bid and 5 ask levels,
            with ``total_buy_qty`` and ``total_sell_qty`` recalculated from
            the retained levels.
        """
        bids5 = tick.bids[:5]
        asks5 = tick.asks[:5]
        return Depth20Tick(
            symbol=tick.symbol,
            exchange=tick.exchange,
            timestamp=tick.timestamp,
            bids=list(bids5),
            asks=list(asks5),
            total_buy_qty=sum(lvl.quantity for lvl in bids5),
            total_sell_qty=sum(lvl.quantity for lvl in asks5),
            ltp=tick.ltp,
        )

    def order_book_imbalance(self, tick: Depth20Tick) -> float:
        """Compute the order-book imbalance from total quantities.

        Defined as::

            (buy_qty - sell_qty) / (buy_qty + sell_qty)

        where ``buy_qty = tick.total_buy_qty`` and
        ``sell_qty = tick.total_sell_qty``.

        Returns:
            A float in ``[-1.0, 1.0]``.  Returns ``0.0`` when both sides
            have zero quantity (empty book).

        Args:
            tick: The :class:`Depth20Tick` to analyse.
        """
        total = tick.total_buy_qty + tick.total_sell_qty
        if total == 0:
            return 0.0
        return (tick.total_buy_qty - tick.total_sell_qty) / total

    def weighted_mid_price(self, tick: Depth20Tick) -> float:
        """Compute the weighted mid-price from the best bid and ask.

        Uses the best bid and ask quantities as weights::

            (best_bid.price * best_ask.qty + best_ask.price * best_bid.qty)
            / (best_bid.qty + best_ask.qty)

        Falls back to a simple mid-price when weights sum to zero.

        Args:
            tick: The :class:`Depth20Tick` to analyse.

        Returns:
            Weighted mid-price, or ``0.0`` if the book is empty.
        """
        if not tick.bids or not tick.asks:
            return 0.0

        best_bid = tick.bids[0]
        best_ask = tick.asks[0]
        total_qty = best_bid.quantity + best_ask.quantity

        if total_qty == 0:
            return (best_bid.price + best_ask.price) / 2.0

        return (
            best_bid.price * best_ask.quantity + best_ask.price * best_bid.quantity
        ) / total_qty

    def spread(self, tick: Depth20Tick) -> float:
        """Return the best-bid/best-ask spread.

        Args:
            tick: The :class:`Depth20Tick` to analyse.

        Returns:
            ``best_ask.price - best_bid.price``, or ``0.0`` if either side
            is empty.
        """
        if not tick.bids or not tick.asks:
            return 0.0
        return tick.asks[0].price - tick.bids[0].price
