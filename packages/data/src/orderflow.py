"""Order flow tick aggregator — converts raw ticks into footprint chart data.

Absorbs pattern from .local/reference/repos/tier2-ecosystem/order-flow-chart/app.py:
- Time-bucket quantization
- Price-level rounding
- LTP direction → BUY/SELL classification
- Volume delta tracking
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FootprintCell:
    """Buy/sell volume at a single price level within a time bucket."""

    buy_volume: int = 0
    sell_volume: int = 0

    @property
    def total_volume(self) -> int:
        """Total traded volume at this price level."""
        return self.buy_volume + self.sell_volume

    @property
    def delta(self) -> int:
        """Net delta: buy minus sell volume. Positive → buyer aggression."""
        return self.buy_volume - self.sell_volume


@dataclass
class FootprintBucket:
    """One time-interval's worth of footprint data.

    Cells are keyed by rounded price level. The POC is the price level
    with the highest total volume within this bucket.
    """

    time_label: str = ""
    cells: dict[float, FootprintCell] = field(default_factory=dict)
    poc_price: float = 0.0  # Point of Control — price with max total volume

    @property
    def total_volume(self) -> int:
        """Sum of all volume across all price levels in this bucket."""
        return sum(c.total_volume for c in self.cells.values())

    @property
    def total_delta(self) -> int:
        """Net delta across all price levels in this bucket."""
        return sum(c.delta for c in self.cells.values())

    @property
    def price_levels(self) -> list[float]:
        """All price levels present in this bucket, sorted ascending."""
        return sorted(self.cells.keys())


class OrderFlowAggregator:
    """Aggregates raw tick data into footprint chart buckets.

    Each bucket represents one time interval (default 5 minutes). Within a
    bucket, volume is distributed across price levels rounded to the nearest
    tick size. LTP direction determines whether volume is classified as buy
    or sell aggression.

    Usage::

        agg = OrderFlowAggregator(tick_size=50.0, interval_minutes=5)
        bucket_key = agg.process_tick(ltp=24050.0, volume=12500)
        buckets = agg.get_buckets()

    Args:
        tick_size: Price rounding granularity. For NIFTY futures, 50 is
            standard (each level covers a 50-point range).
        interval_minutes: Width of each time bucket in minutes.
    """

    def __init__(self, tick_size: float = 50.0, interval_minutes: int = 5) -> None:
        if tick_size <= 0:
            raise ValueError(f"tick_size must be positive, got {tick_size}")
        if interval_minutes <= 0:
            raise ValueError(f"interval_minutes must be positive, got {interval_minutes}")

        self.tick_size = tick_size
        self.interval_minutes = interval_minutes

        self._buckets: dict[str, FootprintBucket] = {}
        self._prev_ltp: float | None = None
        self._prev_volume: int | None = None  # None = no tick seen yet
        self._prev_direction: str = "BUY"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_tick(
        self,
        ltp: float,
        volume: int,
        timestamp: float | None = None,
    ) -> str:
        """Process a single tick and update the appropriate footprint bucket.

        Direction is derived from the LTP change relative to the previous tick:
        - LTP rose  → BUY  (market order lifted the ask)
        - LTP fell  → SELL (market order hit the bid)
        - LTP flat  → carries forward the last known direction

        Volume delta is calculated as the cumulative volume increment since the
        previous tick. On the very first tick the volume is treated as zero
        to avoid seeding the first bucket with a large baseline volume.

        Args:
            ltp: Last traded price for this tick.
            volume: Cumulative traded volume at the time of this tick.
            timestamp: Unix epoch seconds. Defaults to ``time.time()``.

        Returns:
            The bucket key (``"HH:MM"`` string) this tick was written into.
        """
        ts = timestamp if timestamp is not None else time.time()
        bucket_key = self._get_bucket_key(ts)
        price_level = self._round_to_tick(ltp)

        direction = self._classify_direction(ltp)
        trade_volume = self._volume_delta(volume)

        bucket = self._get_or_create_bucket(bucket_key)
        cell = self._get_or_create_cell(bucket, price_level)

        if direction == "BUY":
            cell.buy_volume += trade_volume
        else:
            cell.sell_volume += trade_volume

        self._update_poc(bucket)

        # Persist state for the next tick
        self._prev_ltp = ltp
        self._prev_volume = volume  # always record, even if volume==0
        self._prev_direction = direction

        return bucket_key

    def get_buckets(self) -> dict[str, FootprintBucket]:
        """Return a shallow copy of all accumulated buckets keyed by time label.

        Returns:
            Dictionary mapping ``"HH:MM"`` labels to ``FootprintBucket`` objects.
        """
        return dict(self._buckets)

    def get_bucket(self, key: str) -> FootprintBucket | None:
        """Return a single bucket by its time label, or ``None`` if not found.

        Args:
            key: Time label in ``"HH:MM"`` format.
        """
        return self._buckets.get(key)

    def reset(self) -> None:
        """Clear all accumulated state. Useful when switching trading sessions."""
        self._buckets.clear()
        self._prev_ltp = None
        self._prev_volume = None
        self._prev_direction = "BUY"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_bucket_key(self, timestamp: float) -> str:
        """Quantize a Unix timestamp into a ``"HH:MM"`` bucket label.

        Args:
            timestamp: Unix epoch seconds (float).
        """
        interval_seconds = self.interval_minutes * 60
        bucket_ts = int(timestamp // interval_seconds) * interval_seconds
        return time.strftime("%H:%M", time.localtime(bucket_ts))

    def _round_to_tick(self, price: float) -> float:
        """Round a price to the nearest tick size boundary.

        Args:
            price: Raw LTP value.
        """
        return round(price / self.tick_size) * self.tick_size

    def _classify_direction(self, ltp: float) -> str:
        """Determine trade aggression direction from the LTP change.

        Args:
            ltp: Current last traded price.

        Returns:
            ``"BUY"`` or ``"SELL"``.
        """
        if self._prev_ltp is None:
            return "BUY"
        if ltp > self._prev_ltp:
            return "BUY"
        if ltp < self._prev_ltp:
            return "SELL"
        # Price unchanged — carry forward last direction
        return self._prev_direction

    def _volume_delta(self, volume: int) -> int:
        """Compute the incremental volume since the previous tick.

        On the very first tick ``_prev_volume`` is ``None`` so the delta is 0,
        preventing an artificial spike from the cumulative baseline. Subsequent
        ticks produce a non-negative increment even when the previous baseline
        volume was 0.

        Args:
            volume: Cumulative volume from the current tick.

        Returns:
            Non-negative volume increment.
        """
        if self._prev_volume is None:
            return 0
        return max(0, volume - self._prev_volume)

    def _get_or_create_bucket(self, key: str) -> FootprintBucket:
        if key not in self._buckets:
            self._buckets[key] = FootprintBucket(time_label=key)
        return self._buckets[key]

    @staticmethod
    def _get_or_create_cell(bucket: FootprintBucket, price_level: float) -> FootprintCell:
        if price_level not in bucket.cells:
            bucket.cells[price_level] = FootprintCell()
        return bucket.cells[price_level]

    @staticmethod
    def _update_poc(bucket: FootprintBucket) -> None:
        """Recompute the Point of Control for the given bucket.

        The POC is the price level with the highest total (buy + sell) volume.
        """
        max_vol = -1
        poc = 0.0
        for price, cell in bucket.cells.items():
            total = cell.total_volume
            if total > max_vol:
                max_vol = total
                poc = price
        bucket.poc_price = poc
