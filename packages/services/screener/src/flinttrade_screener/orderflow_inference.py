"""Order flow inference — infers buy/sell aggression from tick data.

Pattern adapted from order-flow-chart repo:
- Compare LTP movement direction with volume delta tick-by-tick
- LTP up + volume increase → likely buy aggression
- LTP down + volume increase → likely sell aggression
- Aggregate into fixed-interval time buckets with price levels

Price levels are rounded to the nearest tick_size.
A bucket is sealed when the current wall-clock timestamp crosses the
next bucket boundary.  The caller drives time via process_tick() and
can optionally inject timestamps for deterministic testing.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger("flinttrade.screener.orderflow_inference")


@dataclass
class PriceLevel:
    """Buy and sell volume aggregated at a single price level within a bucket.

    Attributes:
        price: Price level (rounded to tick_size).
        buy_volume: Cumulative inferred buy volume at this level.
        sell_volume: Cumulative inferred sell volume at this level.
    """

    price: float
    buy_volume: int = 0
    sell_volume: int = 0

    @property
    def delta(self) -> int:
        """Buy volume minus sell volume at this level."""
        return self.buy_volume - self.sell_volume

    @property
    def total_volume(self) -> int:
        """Total traded volume at this level."""
        return self.buy_volume + self.sell_volume


@dataclass
class FlowBucket:
    """Aggregated order flow for one time interval.

    Attributes:
        start_time: Epoch seconds — bucket open time.
        end_time: Epoch seconds — bucket close time.
        levels: Price levels with buy/sell volumes, sorted ascending by price.
        total_buy: Total inferred buy volume across all levels.
        total_sell: Total inferred sell volume across all levels.
        delta: Net delta (total_buy - total_sell) for the bucket.
        ltp_open: LTP at the first tick of the bucket.
        ltp_close: LTP at the last tick of the bucket.
    """

    start_time: float
    end_time: float
    levels: list[PriceLevel] = field(default_factory=list)
    total_buy: int = 0
    total_sell: int = 0
    delta: int = 0
    ltp_open: float = 0.0
    ltp_close: float = 0.0

    @property
    def dominant_side(self) -> str:
        """BUY, SELL, or NEUTRAL based on net delta."""
        if self.delta > 0:
            return "BUY"
        if self.delta < 0:
            return "SELL"
        return "NEUTRAL"


def _round_to_tick(price: float, tick_size: float) -> float:
    """Round price down to the nearest tick_size boundary.

    Args:
        price: Raw price value.
        tick_size: Minimum price increment (e.g. 0.05 for NIFTY options).

    Returns:
        Price rounded to the nearest tick boundary (floor).
    """
    if tick_size <= 0:
        return price
    return math.floor(price / tick_size) * tick_size


class _ActiveBucket:
    """Mutable state for the bucket currently being filled.

    Not part of the public API — used internally by OrderFlowInference.
    """

    def __init__(self, start_time: float, bucket_interval_sec: int) -> None:
        self.start_time = start_time
        self.end_time = start_time + bucket_interval_sec
        self.ltp_open: float | None = None
        self.ltp_close: float = 0.0
        self._levels: dict[float, PriceLevel] = {}
        self.total_buy: int = 0
        self.total_sell: int = 0

    def record(self, price: float, buy_vol: int, sell_vol: int) -> None:
        """Accumulate volume at a price level."""
        if self.ltp_open is None:
            self.ltp_open = price
        self.ltp_close = price

        level = self._levels.setdefault(price, PriceLevel(price=price))
        level.buy_volume += buy_vol
        level.sell_volume += sell_vol
        self.total_buy += buy_vol
        self.total_sell += sell_vol

    def seal(self) -> FlowBucket:
        """Finalise and return the immutable FlowBucket."""
        levels = sorted(self._levels.values(), key=lambda lv: lv.price)
        return FlowBucket(
            start_time=self.start_time,
            end_time=self.end_time,
            levels=levels,
            total_buy=self.total_buy,
            total_sell=self.total_sell,
            delta=self.total_buy - self.total_sell,
            ltp_open=self.ltp_open or 0.0,
            ltp_close=self.ltp_close,
        )


class OrderFlowInference:
    """Infers buy/sell direction from tick data for order flow analysis.

    Each incoming tick is compared with the previous tick to classify
    aggression:

    - ``ltp > prev_ltp`` and ``volume > prev_volume``  → BUY aggression
    - ``ltp < prev_ltp`` and ``volume > prev_volume``  → SELL aggression
    - ``ltp == prev_ltp`` and ``volume > prev_volume`` → neutral; attributed
      to the last known direction (continuation heuristic)
    - ``volume <= prev_volume``                        → no new aggression
      this tick (exchange sometimes resends with same cumulative volume)

    Ticks are binned into time buckets of ``bucket_interval_sec`` seconds.
    When a tick's timestamp crosses a bucket boundary the current bucket is
    sealed, appended to ``_buckets``, and a fresh bucket is opened.

    Usage::

        inf = OrderFlowInference(tick_size=0.05, bucket_interval_sec=180)
        completed_bucket = inf.process_tick(ltp=24500.0, volume=12000, timestamp=1700000000.0)
        current = inf.get_current_bucket()
        last_20 = inf.get_recent_buckets(20)

    Args:
        tick_size: Minimum price increment for price-level rounding.
        bucket_interval_sec: Duration of each aggregation bucket in seconds.
    """

    def __init__(
        self,
        tick_size: float = 0.05,
        bucket_interval_sec: int = 180,
    ) -> None:
        if tick_size < 0:
            raise ValueError(f"tick_size must be non-negative, got {tick_size}")
        if bucket_interval_sec <= 0:
            raise ValueError(
                f"bucket_interval_sec must be positive, got {bucket_interval_sec}"
            )

        self.tick_size = tick_size
        self.bucket_interval_sec = bucket_interval_sec

        self._prev_ltp: float | None = None
        self._prev_volume: int = 0
        self._last_direction: str = "NEUTRAL"  # continuation heuristic
        self._active: _ActiveBucket | None = None
        self._buckets: list[FlowBucket] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_tick(
        self,
        ltp: float,
        volume: int,
        timestamp: float,
    ) -> FlowBucket | None:
        """Process a single market tick.

        Classifies aggression, accumulates into the active bucket, and seals
        the bucket if the timestamp has crossed the bucket boundary.

        Args:
            ltp: Last traded price for this tick.
            volume: Cumulative traded volume as reported by the exchange
                (monotonically increasing within a session; delta is derived
                internally by subtracting the previous cumulative volume).
            timestamp: Unix epoch seconds for this tick.

        Returns:
            A completed ``FlowBucket`` if this tick sealed one, otherwise
            ``None``.
        """
        # Initialise active bucket on very first tick
        if self._active is None:
            bucket_start = self._bucket_start(timestamp)
            self._active = _ActiveBucket(bucket_start, self.bucket_interval_sec)

        # Detect bucket boundary crossing — may produce multiple sealed buckets
        # if a gap in ticks spans more than one interval.
        sealed: FlowBucket | None = None
        while timestamp >= self._active.end_time:
            sealed = self._active.seal()
            self._buckets.append(sealed)
            logger.debug(
                "Bucket sealed [%.0f-%.0f] buy=%d sell=%d delta=%d",
                sealed.start_time, sealed.end_time,
                sealed.total_buy, sealed.total_sell, sealed.delta,
            )
            self._active = _ActiveBucket(
                self._active.end_time, self.bucket_interval_sec
            )

        # Derive volume delta (new volume traded since last tick)
        vol_delta = max(0, volume - self._prev_volume)

        # Classify aggression direction
        direction = self._classify(ltp, vol_delta)

        # Attribute to price level (rounded)
        if vol_delta > 0:
            rounded_price = _round_to_tick(ltp, self.tick_size)
            buy_vol = vol_delta if direction == "BUY" else 0
            sell_vol = vol_delta if direction == "SELL" else 0
            self._active.record(rounded_price, buy_vol, sell_vol)

        # Advance state
        self._prev_ltp = ltp
        self._prev_volume = volume

        return sealed

    def get_current_bucket(self) -> FlowBucket | None:
        """Return a snapshot of the in-progress (unsealed) bucket.

        Returns:
            A ``FlowBucket`` representing accumulated data so far in the
            current interval, or ``None`` if no ticks have been processed yet.
        """
        if self._active is None:
            return None
        return self._active.seal()

    def get_recent_buckets(self, n: int = 20) -> list[FlowBucket]:
        """Return the last *n* completed (sealed) buckets, most recent last.

        Args:
            n: Maximum number of completed buckets to return.

        Returns:
            Up to *n* ``FlowBucket`` objects in chronological order.
        """
        return list(self._buckets[-n:])

    def reset(self) -> None:
        """Clear all state — useful between trading sessions."""
        self._prev_ltp = None
        self._prev_volume = 0
        self._last_direction = "NEUTRAL"
        self._active = None
        self._buckets.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify(self, ltp: float, vol_delta: int) -> str:
        """Classify a tick as BUY, SELL, or NEUTRAL.

        Args:
            ltp: Last traded price of the current tick.
            vol_delta: New volume traded since the previous tick.

        Returns:
            ``"BUY"``, ``"SELL"``, or ``"NEUTRAL"``.
        """
        if vol_delta <= 0:
            return "NEUTRAL"

        if self._prev_ltp is None:
            # First tick — cannot determine direction yet
            return "NEUTRAL"

        if ltp > self._prev_ltp:
            self._last_direction = "BUY"
            return "BUY"

        if ltp < self._prev_ltp:
            self._last_direction = "SELL"
            return "SELL"

        # LTP unchanged — use continuation heuristic
        return self._last_direction

    def _bucket_start(self, timestamp: float) -> float:
        """Align timestamp to the start of the containing bucket interval.

        Args:
            timestamp: Arbitrary epoch timestamp.

        Returns:
            Start of the bucket interval that contains *timestamp*.
        """
        return (
            math.floor(timestamp / self.bucket_interval_sec)
            * self.bucket_interval_sec
        )
