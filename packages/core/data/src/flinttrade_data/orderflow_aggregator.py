"""Per-symbol order flow tick aggregator with IST-aligned time bins.

This module provides :class:`OrderFlowAggregator`, a stateful aggregator that
accumulates raw tick events — each carrying a price, volume, and aggressor side
— into footprint buckets keyed by IST-aligned time bins.

It is distinct from :mod:`orderflow` (which derives tick direction automatically
from LTP change). This aggregator accepts an explicit ``side`` parameter
(``"BUY"`` or ``"SELL"``) coming from exchange-level trade-by-trade data, and
maintains per-symbol state so a single aggregator instance can handle multiple
instruments simultaneously.

Key additions over the base :mod:`orderflow` module:
- Per-symbol state isolation
- IST-aligned bins anchored to market open (09:15 AM)
- Cumulative delta computation (resets at market open)
- Point of Control detection across an arbitrary bin list

Usage::

    from flinttrade_data.orderflow_aggregator import OrderFlowAggregator

    agg = OrderFlowAggregator(time_bin_seconds=60, tick_size=0.05)

    # Feed ticks (e.g. from a trade stream)
    agg.add_tick("NIFTY", 24500.0, 150, "BUY",  timestamp=1743055500.0)
    agg.add_tick("NIFTY", 24495.0, 200, "SELL", timestamp=1743055510.0)

    bins = agg.get_footprint("NIFTY", n_bins=10)
    cd   = agg.cumulative_delta(bins)
    poc  = agg.detect_poc(bins)
"""

from __future__ import annotations

import logging
import math
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time as dt_time
from itertools import islice
from threading import RLock
from typing import Any, Literal

from ._tick_contracts import MAX_SOURCE_CLOCK_SKEW_SECONDS

logger = logging.getLogger("flinttrade.data.orderflow_aggregator")

# ---------------------------------------------------------------------------
# IST market open constant
# ---------------------------------------------------------------------------

_MARKET_OPEN_DEFAULT = "09:15"
_MARKET_OPEN_HOUR = 9
_MARKET_OPEN_MINUTE = 15
_SECONDS_PER_DAY = 24 * 60 * 60

# A shared live aggregator must retain the finest tick used by any supported
# segment. Instrument-specific display grids are applied losslessly by the API.
LIVE_MARKET_INGESTION_INTERVAL_SECONDS = 60
LIVE_MARKET_INGESTION_TICK_SIZE = 0.0001
LIVE_TICK_FRESHNESS_SECONDS = 120.0
DEFAULT_RESTORE_MAX_TICKS = 10_000
MAX_RESTORE_TICKS = 100_000
_MAX_COUNTER_EPOCHS = 8
_MAX_PERSISTED_VOLUME = 2**63 - 1
_MAX_SAFE_VOLUME = 2**53 - 1
_MAX_SAFE_TICK_GRID_UNITS = float(2**53 - 1)
_MAX_SYNTHETIC_TICK_SPAN = 4096.0
_TICK_SIZE_REFERENCE_PRICE = 100_000.0
ORDERFLOW_STATE_VERSION = 1
_MAX_STATE_PRICE_LEVELS = 1_000_000

# Attempt to import zoneinfo (3.9+) then fall back to pytz.
try:
    from zoneinfo import ZoneInfo as _ZoneInfo

    _IST = _ZoneInfo("Asia/Kolkata")
    _HAS_TZ = True
except Exception:
    try:
        import pytz as _pytz  # type: ignore[import-untyped]

        _IST = _pytz.timezone("Asia/Kolkata")
        _HAS_TZ = True
    except Exception:
        _IST = None  # type: ignore[assignment]
        _HAS_TZ = False

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

Side = Literal["BUY", "SELL"]
DataQuality = Literal["exact", "estimated"]
DataProvenance = Literal["trade_tick", "cumulative_quote_delta", "mixed"]
_InstrumentIdentity = tuple[str, str]


def _instrument_identity(symbol: str, exchange: str) -> _InstrumentIdentity:
    """Return the canonical identity for an instrument stream."""
    return exchange.strip().upper(), symbol.strip().upper()


def _ist_session_date(timestamp: int | float) -> date:
    """Return the IST calendar date represented by one bin timestamp."""
    if _HAS_TZ and _IST is not None:
        return datetime.fromtimestamp(timestamp, tz=_IST).date()  # type: ignore[arg-type]
    return datetime.fromtimestamp(timestamp).date()


def _persisted_timestamp(value: Any) -> float | None:
    """Coerce a persisted UTC timestamp to epoch seconds."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, datetime):
            timestamp = value.replace(tzinfo=UTC).timestamp() if value.tzinfo is None else value.timestamp()
        elif isinstance(value, (int, float)):
            timestamp = float(value)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            timestamp = parsed.replace(tzinfo=UTC).timestamp() if parsed.tzinfo is None else parsed.timestamp()
        else:
            return None
    except (OverflowError, TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) else None


def _persisted_number(value: Any, *, positive: bool = False) -> float | None:
    """Return one finite persisted numeric field, rejecting booleans."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or (positive and number <= 0):
        return None
    return number


def _persisted_volume(value: Any) -> int | None:
    """Return a non-negative integral cumulative volume."""
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, int):
            volume = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                return None
            volume = int(value)
        elif isinstance(value, str):
            volume = int(value.strip(), 10)
        else:
            volume = int(value)
            if value != volume:
                return None
    except (OverflowError, TypeError, ValueError):
        return None
    return volume if 0 <= volume <= _MAX_PERSISTED_VOLUME else None


def _persisted_session(value: Any, timestamp: float) -> date | None:
    """Parse an ISO date only when it agrees with the source timestamp."""
    if not isinstance(value, str):
        return None
    try:
        session = date.fromisoformat(value)
        return session if session == _ist_session_date(timestamp) else None
    except (OSError, OverflowError, ValueError):
        return None


def _exact_trade_volume(value: Any) -> int | None:
    """Return an exactly represented, JSON-safe trade volume."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        volume = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        volume = int(value)
    else:
        return None
    return volume if 0 <= volume <= _MAX_SAFE_VOLUME else None


def is_arithmetic_safe_tick_size(value: Any) -> bool:
    """Return whether a tick size is finite and safe for float grid arithmetic."""
    if isinstance(value, bool):
        return False
    try:
        tick_size = float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    if not math.isfinite(tick_size) or tick_size <= 0:
        return False
    return (
        math.isfinite(tick_size * _MAX_SYNTHETIC_TICK_SPAN)
        and _TICK_SIZE_REFERENCE_PRICE / tick_size <= _MAX_SAFE_TICK_GRID_UNITS
    )


@dataclass
class FootprintBucket:
    """Aggregated order-flow data for one time bin at one price level.

    This dataclass intentionally re-exposes only the fields relevant to
    external consumers of :class:`OrderFlowAggregator`. It is a lightweight
    view — not related to :class:`~flinttrade_data.orderflow.FootprintBucket`
    which organises the data as a nested ``cells`` dict.

    Attributes:
        price_level: Price rounded to the nearest tick size.
        buy_volume: Aggressor buy volume at this level during the bin.
        sell_volume: Aggressor sell volume at this level during the bin.
        delta: ``buy_volume - sell_volume`` (positive → buyer aggression).
        timestamp_bin: Unix epoch seconds of the bin start (IST-aligned).
        quality: ``"exact"`` for explicit trade ticks or ``"estimated"`` for
            cumulative quote deltas and mixed-source bins.
        provenance: Source method used to build the bucket.
    """

    price_level: float
    buy_volume: int
    sell_volume: int
    delta: int
    timestamp_bin: int
    quality: DataQuality = "exact"
    provenance: DataProvenance = "trade_tick"

    @property
    def total_volume(self) -> int:
        """Total volume at this price level (buy + sell)."""
        return self.buy_volume + self.sell_volume


# ---------------------------------------------------------------------------
# Internal state structures
# ---------------------------------------------------------------------------


@dataclass
class _BinState:
    """Mutable accumulator for one time bin (one symbol).

    Stores buy/sell volume per rounded price level. Used internally by
    :class:`OrderFlowAggregator`; not exported.
    """

    bin_start: int  # Unix epoch seconds of bin start
    # price_level → (buy_vol, sell_vol)
    levels: dict[float, list[int]] = field(default_factory=dict)
    provenances: set[DataProvenance] = field(default_factory=set)

    def add(
        self,
        price_level: float,
        side: Side,
        volume: int,
        provenance: DataProvenance,
    ) -> None:
        """Accumulate ``volume`` into ``price_level`` for ``side``.

        Args:
            price_level: Rounded price level.
            side: ``"BUY"`` or ``"SELL"``.
            volume: Volume to add (must be non-negative).
        """
        current = self.levels.get(price_level, [0, 0])
        side_index = 0 if side == "BUY" else 1
        updated = current[side_index] + volume
        if updated > _MAX_SAFE_VOLUME:
            raise ValueError("volume accumulation exceeds the safe integer range")
        if price_level not in self.levels:
            self.levels[price_level] = current
        self.levels[price_level][side_index] = updated
        self.provenances.add(provenance)

    def to_buckets(self) -> list[FootprintBucket]:
        """Convert accumulated levels into a list of :class:`FootprintBucket`.

        Returns:
            List sorted by ``price_level`` ascending.
        """
        provenance: DataProvenance
        if len(self.provenances) == 1:
            provenance = next(iter(self.provenances))
        else:
            provenance = "mixed"
        quality: DataQuality = "exact" if provenance == "trade_tick" else "estimated"

        result: list[FootprintBucket] = []
        for price_level in sorted(self.levels):
            buy_vol, sell_vol = self.levels[price_level]
            result.append(
                FootprintBucket(
                    price_level=price_level,
                    buy_volume=buy_vol,
                    sell_volume=sell_vol,
                    delta=buy_vol - sell_vol,
                    timestamp_bin=self.bin_start,
                    quality=quality,
                    provenance=provenance,
                )
            )
        return result


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class OrderFlowAggregator:
    """Per-symbol footprint chart aggregator with IST-aligned time bins.

    State is maintained per symbol so a single instance can aggregate ticks
    for all instruments in a trading session.

    Args:
        time_bin_seconds: Width of each time bin in seconds. Default ``60``
            (1 minute), allowing exact aggregation to 3-minute and 5-minute
            response intervals without fabricating finer data.
        tick_size: Price rounding granularity. Default ``0.05`` (suitable for
            USDINR and many equity instruments). Use ``50.0`` for NIFTY
            futures, ``0.25`` for Bank NIFTY options, etc.
        max_retained_sessions: Maximum IST trading dates retained per
            instrument. Default ``2``.
        max_bins_per_session: Maximum bins retained per instrument and IST
            date. Defaults to enough bins for a full 24-hour day at the source
            interval.
        max_instruments: Maximum instrument identities retained globally.
            Least-recently-used identities are evicted together with all of
            their bins and cumulative-volume state. Default ``512``.

    Example::

        agg = OrderFlowAggregator(time_bin_seconds=300, tick_size=50.0)
        agg.add_tick("NIFTY", 24500.0, 150, "BUY",  timestamp=1743055500.0)
        agg.add_tick("NIFTY", 24450.0, 200, "SELL", timestamp=1743055560.0)
        bins  = agg.get_footprint("NIFTY", n_bins=50)
        delta = agg.cumulative_delta(bins)
        poc   = agg.detect_poc(bins)
    """

    def __init__(
        self,
        time_bin_seconds: int = 60,
        tick_size: float = 0.05,
        max_retained_sessions: int = 2,
        max_bins_per_session: int | None = None,
        max_instruments: int = 512,
    ) -> None:
        if time_bin_seconds <= 0:
            raise ValueError(f"time_bin_seconds must be positive, got {time_bin_seconds}")
        if not is_arithmetic_safe_tick_size(tick_size):
            raise ValueError("tick_size must be a finite arithmetic-safe number")
        if max_retained_sessions <= 0:
            raise ValueError(f"max_retained_sessions must be positive, got {max_retained_sessions}")
        if max_bins_per_session is not None and max_bins_per_session <= 0:
            raise ValueError(f"max_bins_per_session must be positive, got {max_bins_per_session}")
        if max_instruments <= 0:
            raise ValueError(f"max_instruments must be positive, got {max_instruments}")

        self.time_bin_seconds = time_bin_seconds
        self.tick_size = float(tick_size)
        self.max_retained_sessions = max_retained_sessions
        self.max_bins_per_session = max_bins_per_session or (
            (_SECONDS_PER_DAY + time_bin_seconds - 1) // time_bin_seconds + 1
        )
        self.max_instruments = max_instruments

        # (exchange, symbol) → {bin_start → _BinState}
        self._state: dict[_InstrumentIdentity, dict[int, _BinState]] = {}
        # Per-instrument baseline for deriving incremental volume + aggressor
        # side from raw market ticks (which carry cumulative volume and no side).
        self._last_tick: dict[_InstrumentIdentity, tuple[float, int, date, float]] = {}
        # Raw cumulative counters can reset and later recover to an earlier
        # namespace. Keep a monotonic logical total plus a bounded set of
        # observed namespace offsets so recovery cannot count volume twice.
        self._normalised_volume: dict[_InstrumentIdentity, int] = {}
        self._counter_offsets: dict[_InstrumentIdentity, tuple[int, ...]] = {}
        self._counter_high_watermarks: dict[_InstrumentIdentity, dict[int, int]] = {}
        # A lower intraday cumulative counter needs a second monotonic sample
        # before it can replace the last trusted baseline.
        self._pending_volume_reset: dict[_InstrumentIdentity, tuple[float, int, date, float]] = {}
        self._last_side: dict[_InstrumentIdentity, Side] = {}
        # Freshness describes returned footprint data, not transport activity.
        # (session, source timestamp, provenance) advances only after a positive
        # volume is successfully represented in a retained bucket.
        self._last_data_tick: dict[_InstrumentIdentity, tuple[date, float, DataProvenance]] = {}
        self._identity_recency: OrderedDict[_InstrumentIdentity, None] = OrderedDict()
        self._price_level_count = 0
        # feed_market_tick nests classification and recording under one state
        # transaction, so this must permit re-entry.
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_tick(
        self,
        symbol: str,
        price: float,
        volume: int,
        side: Side,
        timestamp: float | None = None,
        *,
        exchange: str = "",
    ) -> int:
        """Accumulate a single tick into the appropriate time bin.

        Args:
            symbol: Instrument symbol.
            price: Trade price for this tick.
            volume: Trade volume for this tick (not cumulative — this is the
                size of the individual trade, as provided by a trade stream).
            side: Trade aggressor side: ``"BUY"`` or ``"SELL"``.
            timestamp: Unix epoch seconds. Defaults to ``time.time()``.
            exchange: Exchange for state isolation. Defaults to the empty
                exchange for compatibility with direct analytics callers.

        Returns:
            The ``bin_start`` (Unix epoch seconds) of the bin this tick was
            accumulated into.

        Raises:
            ValueError: If ``side`` is not ``"BUY"`` or ``"SELL"``.
        """
        return self._accumulate_tick(
            symbol,
            price,
            volume,
            side,
            timestamp=timestamp,
            exchange=exchange,
            provenance="trade_tick",
        )

    def _accumulate_tick(
        self,
        symbol: str,
        price: float,
        volume: int,
        side: Side,
        *,
        timestamp: float | None,
        exchange: str,
        provenance: DataProvenance,
    ) -> int:
        """Record one exact or estimated increment with explicit provenance."""
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got '{side}'")

        import time as _time

        ts = timestamp if timestamp is not None else _time.time()
        bin_start = self.calculate_aligned_time_bin(ts, self.time_bin_seconds, _MARKET_OPEN_DEFAULT)
        price_level = self._round_to_tick(price)
        exact_volume = _exact_trade_volume(volume)
        if exact_volume is None:
            raise ValueError("volume must be a non-negative safe integer")
        if exact_volume == 0:
            return bin_start

        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            symbol_state = self._state.get(identity, {})
            current_bin = symbol_state.get(bin_start)
            if current_bin is None and not self._would_retain_bin_locked(identity, bin_start):
                return bin_start
            current_level = None if current_bin is None else current_bin.levels.get(price_level)
            if current_level is not None:
                side_index = 0 if side == "BUY" else 1
                if current_level[side_index] > _MAX_SAFE_VOLUME - exact_volume:
                    raise ValueError("volume accumulation exceeds the safe integer range")
            adds_price_level = current_bin is None or price_level not in current_bin.levels
            if adds_price_level:
                identity_evictions = self._identity_evictions_for_touch_locked(identity)
                reclaimed_levels = sum(
                    self._identity_price_level_count_locked(evicted_identity) for evicted_identity in identity_evictions
                )
                retained_new_level = True
                if current_bin is None:
                    bin_evictions = self._bin_evictions_after_insert_locked(
                        symbol_state,
                        bin_start,
                    )
                    retained_new_level = bin_start not in bin_evictions
                    if identity not in identity_evictions:
                        reclaimed_levels += sum(
                            len(symbol_state[evicted_bin].levels)
                            for evicted_bin in bin_evictions
                            if evicted_bin in symbol_state
                        )
                projected_levels = self._price_level_count - reclaimed_levels + int(retained_new_level)
                if projected_levels > _MAX_STATE_PRICE_LEVELS:
                    raise ValueError("order-flow state contains too many price levels")
            self._touch_identity_locked(identity)
            if identity not in self._state:
                self._state[identity] = {}
            symbol_state = self._state[identity]

            if bin_start not in symbol_state:
                symbol_state[bin_start] = _BinState(bin_start=bin_start)
                self._evict_retained_state_locked(symbol_state)

            bin_state = symbol_state.get(bin_start)
            if bin_state is not None:
                bin_state.add(price_level, side, exact_volume, provenance)
                if adds_price_level:
                    self._price_level_count += 1
                self._record_data_tick_locked(identity, float(ts), provenance)
        logger.debug(
            "add_tick: exchange=%s symbol=%s price=%.4f vol=%d side=%s bin=%d provenance=%s",
            identity[0],
            identity[1],
            price_level,
            exact_volume,
            side,
            bin_start,
            provenance,
        )
        return bin_start

    def _classify_side(
        self, symbol: str, ltp: float, prev_ltp: float, bid: float | None, ask: float | None, *, exchange: str = ""
    ) -> Side:
        """Return an aggressor side via the quote rule or the tick rule.

        Lee-Ready style: a trade at or above the ask is buyer-initiated; at or
        below the bid is seller-initiated; otherwise (or with no quote) the tick
        rule — up-trade = buy, down-trade = sell, unchanged = carry the previous
        side. The caller publishes the returned side only after accumulation
        succeeds, keeping cumulative-tick application transactional.
        """
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            if bid is not None and ask is not None and ask >= bid > 0:
                if ltp >= ask:
                    return "BUY"
                if ltp <= bid:
                    return "SELL"
            if ltp > prev_ltp:
                side: Side = "BUY"
            elif ltp < prev_ltp:
                side = "SELL"
            else:
                side = self._last_side.get(identity, "BUY")
            return side

    def feed_market_tick(
        self,
        symbol: str,
        ltp: float,
        cumulative_volume: int,
        *,
        exchange: str = "",
        bid: float | None = None,
        ask: float | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Feed a raw market tick (LTP + cumulative day volume, no aggressor).

        Estimates incremental volume from changes in the cumulative counter and
        estimates one side/price for that whole interval (see
        :meth:`_classify_side`). The resulting buckets remain useful order-flow
        estimates but are not exact trade-by-trade exchange prints. A first
        snapshot establishes only a baseline.
        """
        import time as _time

        try:
            if isinstance(cumulative_volume, bool):
                return
            ltp = float(ltp)
        except (OverflowError, TypeError, ValueError):
            return
        if not math.isfinite(ltp) or ltp <= 0:
            return

        tick_timestamp = timestamp if timestamp is not None else _time.time()
        session_date = _ist_session_date(tick_timestamp)
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            current_volume = int(cumulative_volume)
            prev = self._last_tick.get(identity)
            if current_volume < 0:
                return
            if prev is not None:
                if tick_timestamp < prev[3]:
                    return
                if tick_timestamp == prev[3] and current_volume < prev[1]:
                    return
                if tick_timestamp == prev[3] and current_volume == prev[1]:
                    return
            if prev is None or prev[2] != session_date:
                bin_start = self.calculate_aligned_time_bin(
                    tick_timestamp,
                    self.time_bin_seconds,
                    _MARKET_OPEN_DEFAULT,
                )
                if not self._would_retain_bin_locked(identity, bin_start):
                    return
                self._touch_identity_locked(identity)
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._normalised_volume[identity] = current_volume
                self._counter_offsets[identity] = (0,)
                self._counter_high_watermarks[identity] = {0: current_volume}
                self._pending_volume_reset.pop(identity, None)
                self._last_side.pop(identity, None)
                return
            prev_ltp, prev_vol, _, _ = prev
            previous_normalised = self._normalised_volume.get(identity, prev_vol)
            offsets = self._counter_offsets.get(
                identity,
                (previous_normalised - prev_vol,),
            )
            high_watermarks = self._counter_high_watermarks.get(
                identity,
                {offsets[0]: prev_vol},
            )
            if current_volume < prev_vol:
                pending = self._pending_volume_reset.get(identity)
                if pending is None or pending[2] != session_date:
                    self._touch_identity_locked(identity)
                    self._pending_volume_reset[identity] = (
                        ltp,
                        current_volume,
                        session_date,
                        tick_timestamp,
                    )
                    return

                pending_ltp, pending_volume, _, pending_timestamp = pending
                if tick_timestamp <= pending_timestamp:
                    return
                if current_volume < pending_volume:
                    self._touch_identity_locked(identity)
                    self._pending_volume_reset[identity] = (
                        ltp,
                        current_volume,
                        session_date,
                        tick_timestamp,
                    )
                    return
                if current_volume == pending_volume:
                    self._touch_identity_locked(identity)
                    self._pending_volume_reset[identity] = (
                        ltp,
                        current_volume,
                        session_date,
                        tick_timestamp,
                    )
                    return

                new_offset = previous_normalised - pending_volume
                high_watermarks = dict(high_watermarks)
                high_watermarks[new_offset] = current_volume
                normalised, offsets, high_watermarks = self._select_counter_namespace(
                    current_volume,
                    previous_normalised,
                    (new_offset, *offsets),
                    high_watermarks,
                )
                if normalised is None:
                    self._touch_identity_locked(identity)
                    self._pending_volume_reset.pop(identity, None)
                    self._counter_offsets[identity] = offsets
                    self._counter_high_watermarks[identity] = high_watermarks
                    return
                inc_volume = normalised - previous_normalised
                if inc_volume <= 0:
                    self._touch_identity_locked(identity)
                    self._pending_volume_reset.pop(identity, None)
                    self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                    self._normalised_volume[identity] = normalised
                    self._counter_offsets[identity] = offsets
                    self._counter_high_watermarks[identity] = high_watermarks
                    return
                side = self._classify_side(
                    symbol,
                    ltp,
                    pending_ltp,
                    bid,
                    ask,
                    exchange=exchange,
                )
                self._accumulate_tick(
                    symbol,
                    ltp,
                    inc_volume,
                    side,
                    timestamp=tick_timestamp,
                    exchange=exchange,
                    provenance="cumulative_quote_delta",
                )
                self._pending_volume_reset.pop(identity, None)
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._normalised_volume[identity] = normalised
                self._counter_offsets[identity] = offsets
                self._counter_high_watermarks[identity] = high_watermarks
                self._last_side[identity] = side
                return
            normalised, offsets, high_watermarks = self._select_counter_namespace(
                current_volume,
                previous_normalised,
                offsets,
                high_watermarks,
            )
            if normalised is None:
                self._touch_identity_locked(identity)
                self._pending_volume_reset.pop(identity, None)
                self._counter_offsets[identity] = offsets
                self._counter_high_watermarks[identity] = high_watermarks
                return

            inc_volume = normalised - previous_normalised
            if inc_volume <= 0:
                self._touch_identity_locked(identity)
                self._pending_volume_reset.pop(identity, None)
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._normalised_volume[identity] = normalised
                self._counter_offsets[identity] = offsets
                self._counter_high_watermarks[identity] = high_watermarks
                return
            side = self._classify_side(symbol, ltp, prev_ltp, bid, ask, exchange=exchange)
            self._accumulate_tick(
                symbol,
                ltp,
                inc_volume,
                side,
                timestamp=tick_timestamp,
                exchange=exchange,
                provenance="cumulative_quote_delta",
            )
            self._pending_volume_reset.pop(identity, None)
            self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
            self._normalised_volume[identity] = normalised
            self._counter_offsets[identity] = offsets
            self._counter_high_watermarks[identity] = high_watermarks
            self._last_side[identity] = side

    @staticmethod
    def _select_counter_namespace(
        raw_volume: int,
        previous_normalised: int,
        offsets: tuple[int, ...],
        high_watermarks: dict[int, int],
    ) -> tuple[int | None, tuple[int, ...], dict[int, int]]:
        """Choose the least non-decreasing interpretation of a raw counter.

        A confirmed reset introduces another ``raw + offset`` namespace. While
        an older namespace is still below the trusted total, no increment is
        knowable. Once multiple namespaces exceed it, retire to the smallest
        translated value: that is the conservative lower bound under every
        valid interpretation and prevents an ambiguity from freezing forever.
        """
        unique_offsets = tuple(dict.fromkeys(offsets))[:_MAX_COUNTER_EPOCHS] or (0,)
        selected_offset = unique_offsets[0]
        retained_high_watermarks = {offset: high_watermarks.get(offset, -1) for offset in unique_offsets}
        candidates: list[tuple[int, int, int]] = []
        catching_up: list[int] = []
        for index, offset in enumerate(unique_offsets):
            if raw_volume < retained_high_watermarks[offset]:
                continue
            translated = raw_volume + offset
            if translated < previous_normalised:
                catching_up.append(offset)
            else:
                candidates.append((translated, index, offset))

        exact = next(
            (candidate for candidate in candidates if candidate[0] == previous_normalised),
            None,
        )
        if exact is not None:
            _, _, exact_offset = exact
            if exact_offset != selected_offset:
                return previous_normalised, (exact_offset,), {exact_offset: raw_volume}
            retained_high_watermarks[exact_offset] = raw_volume
            return previous_normalised, unique_offsets, retained_high_watermarks

        if catching_up:
            for offset in catching_up:
                retained_high_watermarks[offset] = raw_volume
            return None, unique_offsets, retained_high_watermarks
        if candidates:
            normalised, _, selected_offset = min(candidates)
        else:
            return None, unique_offsets, retained_high_watermarks
        if len(candidates) > 1:
            return normalised, (selected_offset,), {selected_offset: raw_volume}
        retained_high_watermarks[selected_offset] = raw_volume
        reordered = (selected_offset, *(offset for offset in unique_offsets if offset != selected_offset))
        reordered = reordered[:_MAX_COUNTER_EPOCHS]
        return (
            normalised,
            reordered,
            {offset: retained_high_watermarks[offset] for offset in reordered},
        )

    def get_market_freshness(
        self,
        symbol: str,
        *,
        exchange: str = "",
        now: float | None = None,
    ) -> dict[str, str | float | bool | None]:
        """Return recency for the newest source event represented in returned data."""
        import time as _time

        now_timestamp = _time.time() if now is None else float(now)
        current_session = _ist_session_date(now_timestamp)
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            last_data_tick = self._last_data_tick.get(identity)

        if last_data_tick is None:
            return {
                "state": "unavailable",
                "is_fresh": False,
                "last_tick_timestamp": None,
                "last_tick_session": None,
                "current_session": current_session.isoformat(),
                "age_seconds": None,
                "provenance": None,
            }

        last_session, last_timestamp, provenance = last_data_tick
        age_seconds = now_timestamp - last_timestamp
        if last_session != current_session:
            state = "stale"
        elif age_seconds < -MAX_SOURCE_CLOCK_SKEW_SECONDS or age_seconds > LIVE_TICK_FRESHNESS_SECONDS:
            state = "delayed"
        else:
            state = "live"
        return {
            "state": state,
            "is_fresh": state == "live",
            "last_tick_timestamp": last_timestamp,
            "last_tick_session": last_session.isoformat(),
            "current_session": current_session.isoformat(),
            "age_seconds": age_seconds,
            "provenance": provenance,
        }

    def export_state(self) -> dict[str, Any]:
        """Export a versioned, JSON-safe restart checkpoint.

        The checkpoint includes retained buckets and their provenance together
        with every cumulative-counter namespace needed to interpret a bounded
        replay tail without manufacturing volume.
        """
        with self._lock:
            identities: list[dict[str, Any]] = []
            ordered_identities = list(self._identity_recency)
            known_identities = (
                set(self._state)
                | set(self._last_tick)
                | set(self._normalised_volume)
                | set(self._counter_offsets)
                | set(self._counter_high_watermarks)
                | set(self._pending_volume_reset)
                | set(self._last_side)
                | set(self._last_data_tick)
            )
            ordered_identities.extend(sorted(known_identities - set(ordered_identities)))
            for exchange, symbol in ordered_identities:
                identity = (exchange, symbol)
                bins = []
                for bin_start, bin_state in sorted(self._state.get(identity, {}).items()):
                    bins.append(
                        {
                            "timestamp_bin": bin_start,
                            "levels": [
                                {
                                    "price_level": price_level,
                                    "buy_volume": volumes[0],
                                    "sell_volume": volumes[1],
                                }
                                for price_level, volumes in sorted(bin_state.levels.items())
                            ],
                            "provenances": sorted(bin_state.provenances),
                        }
                    )

                last_tick = self._last_tick.get(identity)
                pending_reset = self._pending_volume_reset.get(identity)
                last_data_tick = self._last_data_tick.get(identity)
                offsets = self._counter_offsets.get(identity, ())
                high_watermarks = self._counter_high_watermarks.get(identity, {})
                identities.append(
                    {
                        "exchange": exchange,
                        "symbol": symbol,
                        "bins": bins,
                        "last_tick": (
                            {
                                "ltp": last_tick[0],
                                "volume": last_tick[1],
                                "session": last_tick[2].isoformat(),
                                "timestamp": last_tick[3],
                            }
                            if last_tick is not None
                            else None
                        ),
                        "normalised_volume": self._normalised_volume.get(identity),
                        "counter_offsets": list(offsets),
                        "counter_high_watermarks": [
                            {"offset": offset, "volume": high_watermarks[offset]}
                            for offset in offsets
                            if offset in high_watermarks
                        ],
                        "pending_volume_reset": (
                            {
                                "ltp": pending_reset[0],
                                "volume": pending_reset[1],
                                "session": pending_reset[2].isoformat(),
                                "timestamp": pending_reset[3],
                            }
                            if pending_reset is not None
                            else None
                        ),
                        "last_side": self._last_side.get(identity),
                        "last_data_tick": (
                            {
                                "session": last_data_tick[0].isoformat(),
                                "timestamp": last_data_tick[1],
                                "provenance": last_data_tick[2],
                            }
                            if last_data_tick is not None
                            else None
                        ),
                    }
                )

        return {
            "version": ORDERFLOW_STATE_VERSION,
            "config": self._checkpoint_config(),
            "identities": identities,
        }

    def restore_state(
        self,
        checkpoint: Mapping[str, Any],
        *,
        now: float | datetime | None = None,
    ) -> dict[str, int]:
        """Atomically restore a checkpoint exported by :meth:`export_state`.

        All structure, bounds, source timestamps, counter namespaces, and
        represented-data freshness links are validated on a scratch instance
        before the live state is replaced.
        """
        import time as _time

        restore_timestamp = _time.time() if now is None else _persisted_timestamp(now)
        if restore_timestamp is None:
            raise ValueError("now must be a finite timestamp or datetime")
        if not isinstance(checkpoint, Mapping):
            raise ValueError("checkpoint must be a mapping")
        if checkpoint.get("version") != ORDERFLOW_STATE_VERSION:
            raise ValueError("unsupported order-flow checkpoint version")
        if checkpoint.get("config") != self._checkpoint_config():
            raise ValueError("checkpoint configuration does not match the aggregator")
        identity_rows = checkpoint.get("identities")
        if not isinstance(identity_rows, list):
            raise ValueError("checkpoint identities must be a list")
        if len(identity_rows) > self.max_instruments:
            raise ValueError("checkpoint exceeds max_instruments")

        scratch = OrderFlowAggregator(**self._checkpoint_config())
        identities_seen: set[_InstrumentIdentity] = set()
        bin_count = 0
        price_level_count = 0
        for identity_row in identity_rows:
            identity, identity_bins, identity_levels = scratch._restore_checkpoint_identity(
                identity_row,
                now=restore_timestamp,
            )
            if identity in identities_seen:
                raise ValueError("checkpoint contains a duplicate identity")
            identities_seen.add(identity)
            scratch._identity_recency[identity] = None
            bin_count += identity_bins
            price_level_count += identity_levels
            if price_level_count > _MAX_STATE_PRICE_LEVELS:
                raise ValueError("checkpoint contains too many price levels")

        with self._lock:
            self._replace_all_state_locked(scratch)
        return {
            "identities": len(identities_seen),
            "bins": bin_count,
            "price_levels": price_level_count,
        }

    def replay_current_session_tail(
        self,
        ticks: Iterable[Mapping[str, Any]],
        *,
        now: float | datetime | None = None,
        max_ticks: int = DEFAULT_RESTORE_MAX_TICKS,
        history_complete: bool = False,
    ) -> dict[str, int]:
        """Atomically apply a bounded retained-session tail after ``restore_state``.

        Source rows older than the checkpoint watermark are naturally ignored
        by :meth:`feed_market_tick`. A tail filling the entire caller-provided
        bound is rejected unless ``history_complete`` attests that the caller
        queried beyond the bound and proved no omitted rows remain.
        """
        if not isinstance(history_complete, bool):
            raise ValueError("history_complete must be a boolean")
        bounded_ticks, prepared = self._prepare_replay_ticks(
            ticks,
            now=now,
            max_ticks=max_ticks,
            reject_full_window=not history_complete,
            current_session_only=False,
        )
        identities = {_instrument_identity(symbol, exchange) for _, _, symbol, exchange, _, _, _, _ in prepared}
        if not prepared:
            return {
                "input_ticks": len(bounded_ticks),
                "restored_ticks": 0,
                "skipped_ticks": len(bounded_ticks),
                "identities": 0,
            }

        with self._lock:
            checkpoint = self.export_state()
            scratch = OrderFlowAggregator(**self._checkpoint_config())
            scratch.restore_state(checkpoint, now=now)
            for timestamp, _, symbol, exchange, ltp, volume, bid, ask in prepared:
                scratch.feed_market_tick(
                    symbol,
                    ltp,
                    volume,
                    exchange=exchange,
                    bid=bid,
                    ask=ask,
                    timestamp=timestamp,
                )
            self._replace_all_state_locked(scratch)

        return {
            "input_ticks": len(bounded_ticks),
            "restored_ticks": len(prepared),
            "skipped_ticks": len(bounded_ticks) - len(prepared),
            "identities": len(identities),
        }

    def restore_current_session(
        self,
        ticks: Iterable[Mapping[str, Any]],
        *,
        now: float | datetime | None = None,
        max_ticks: int = DEFAULT_RESTORE_MAX_TICKS,
        history_complete: bool = False,
    ) -> dict[str, int]:
        """Replace represented identities with replayed current-session ticks.

        Persisted rows must use the ``StorageManager.get_ticks`` field names.
        Naive datetimes are interpreted as UTC, matching the DuckDB schema.
        Input is materialised only up to ``max_ticks + 1``. A full or
        overflowing window fails closed because the caller has not proved that
        the session prefix (including any counter resets) is present. Invalid
        and non-current-session rows are skipped. Replay occurs on a scratch
        aggregator, then swaps into this instance under one lock so a failed
        replay cannot leave partial state.

        Call this before starting live ingestion. Repeating the same restore is
        idempotent because represented identities are replaced, not appended.
        Set ``history_complete`` only after querying beyond ``max_ticks`` and
        proving that the supplied session prefix is complete.
        """
        if not isinstance(history_complete, bool):
            raise ValueError("history_complete must be a boolean")
        bounded_ticks, prepared = self._prepare_replay_ticks(
            ticks,
            now=now,
            max_ticks=max_ticks,
            reject_full_window=not history_complete,
            current_session_only=True,
        )

        identities = {_instrument_identity(symbol, exchange) for _, _, symbol, exchange, _, _, _, _ in prepared}
        if len(identities) > self.max_instruments:
            raise ValueError(
                f"restore contains {len(identities)} identities, exceeding max_instruments={self.max_instruments}"
            )

        if prepared:
            with self._lock:
                scratch = OrderFlowAggregator(
                    time_bin_seconds=self.time_bin_seconds,
                    tick_size=self.tick_size,
                    max_retained_sessions=self.max_retained_sessions,
                    max_bins_per_session=self.max_bins_per_session,
                    max_instruments=self.max_instruments,
                )
                for timestamp, _, symbol, exchange, ltp, volume, bid, ask in prepared:
                    scratch.feed_market_tick(
                        symbol,
                        ltp,
                        volume,
                        exchange=exchange,
                        bid=bid,
                        ask=ask,
                        timestamp=timestamp,
                    )

                ordered_identities = tuple(sorted(identities))
                replaced_levels = sum(
                    self._identity_price_level_count_locked(identity) for identity in ordered_identities
                )
                replacement_levels = sum(
                    scratch._identity_price_level_count_locked(identity) for identity in ordered_identities
                )
                identity_evictions = self._identity_evictions_after_replacement_locked(ordered_identities)
                evicted_levels = sum(
                    self._identity_price_level_count_locked(identity) for identity in identity_evictions
                )
                if (
                    self._price_level_count - replaced_levels - evicted_levels + replacement_levels
                    > _MAX_STATE_PRICE_LEVELS
                ):
                    raise ValueError("order-flow state contains too many price levels")

                for identity in ordered_identities:
                    self._drop_identity_locked(identity)
                    for target, source in (
                        (self._state, scratch._state),
                        (self._last_tick, scratch._last_tick),
                        (self._normalised_volume, scratch._normalised_volume),
                        (self._counter_offsets, scratch._counter_offsets),
                        (self._counter_high_watermarks, scratch._counter_high_watermarks),
                        (self._pending_volume_reset, scratch._pending_volume_reset),
                        (self._last_side, scratch._last_side),
                        (self._last_data_tick, scratch._last_data_tick),
                    ):
                        if identity in source:
                            target[identity] = source[identity]
                    self._price_level_count += self._identity_price_level_count_locked(identity)
                    self._touch_identity_locked(identity)

        return {
            "input_ticks": len(bounded_ticks),
            "restored_ticks": len(prepared),
            "skipped_ticks": len(bounded_ticks) - len(prepared),
            "identities": len(identities),
        }

    def retain_identities(self, identities: set[_InstrumentIdentity]) -> None:
        """Discard every identity no longer present in the recorder watchlist."""
        allowed = {(str(exchange).strip().upper(), str(symbol).strip().upper()) for exchange, symbol in identities}
        with self._lock:
            known = (
                set(self._state)
                | set(self._last_tick)
                | set(self._normalised_volume)
                | set(self._counter_offsets)
                | set(self._counter_high_watermarks)
                | set(self._pending_volume_reset)
                | set(self._last_side)
                | set(self._last_data_tick)
                | set(self._identity_recency)
            )
            for identity in known - allowed:
                self._drop_identity_locked(identity)

    def get_footprint(
        self,
        symbol: str,
        n_bins: int = 50,
        *,
        exchange: str = "",
    ) -> list[FootprintBucket]:
        """Return aggregated footprint data for the most recent ``n_bins`` bins.

        The bins are sorted chronologically (oldest first) and limited to the
        most recent ``n_bins`` bins. Within each bin, price levels are sorted
        ascending, so the caller receives a flat list ordered first by time
        then by price.

        Args:
            symbol: Instrument symbol.
            n_bins: Maximum number of bins to return. Default ``50``.
            exchange: Exchange to retrieve. Defaults to the empty exchange for
                compatibility with direct analytics callers.

        Returns:
            List of :class:`FootprintBucket` instances, sorted by
            ``timestamp_bin`` ascending then ``price_level`` ascending.
            Returns an empty list if no data has been accumulated for
            ``symbol``.
        """
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            symbol_state = self._state.get(identity)
            if not symbol_state:
                return []

            # Select the n_bins most recent bin keys and materialise a stable
            # view before another thread can mutate the nested dictionaries.
            all_bins = sorted(symbol_state)
            latest_session = _ist_session_date(all_bins[-1])
            active_tick = self._last_tick.get(identity)
            if active_tick is not None and active_tick[2] > latest_session:
                latest_session = active_tick[2]
            session_bins = [bin_start for bin_start in all_bins if _ist_session_date(bin_start) == latest_session]
            recent_bins = session_bins[-n_bins:] if len(session_bins) > n_bins else session_bins

            result: list[FootprintBucket] = []
            for bin_start in recent_bins:
                result.extend(symbol_state[bin_start].to_buckets())
            return result

    def reset(self, symbol: str | None = None, *, exchange: str = "") -> None:
        """Clear accumulated state.

        Args:
            symbol: If given, clear only that instrument. If ``None``, clear
                all instruments.
            exchange: Exchange to clear when ``symbol`` is given. Defaults to
                the empty exchange for compatibility with direct callers.
        """
        with self._lock:
            if symbol is None:
                self._state.clear()
                self._last_tick.clear()
                self._normalised_volume.clear()
                self._counter_offsets.clear()
                self._counter_high_watermarks.clear()
                self._pending_volume_reset.clear()
                self._last_side.clear()
                self._last_data_tick.clear()
                self._identity_recency.clear()
                self._price_level_count = 0
                return

            identity = _instrument_identity(symbol, exchange)
            self._drop_identity_locked(identity)

    # ------------------------------------------------------------------
    # Static / class-level analytics
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_aligned_time_bin(
        timestamp: float,
        bin_seconds: int,
        market_open: str = "09:15",
    ) -> int:
        """Return the IST-aligned bin start for a Unix timestamp.

        Bins are anchored to the market open time (default 09:15 IST). Each
        bin covers exactly ``bin_seconds`` seconds. Timestamps before market
        open on the same calendar day are aligned to the plain floor of the
        Unix timestamp (not anchored to market open, since pre-market data is
        unusual but should still be bucketed cleanly).

        Args:
            timestamp: Unix epoch seconds (float).
            bin_seconds: Bin width in seconds. Must be positive.
            market_open: Market open time as ``"HH:MM"`` string (IST).
                Default ``"09:15"``.

        Returns:
            Unix epoch seconds of the bin start (integer).
        """
        if _HAS_TZ:
            try:
                dt = datetime.fromtimestamp(timestamp, tz=_IST)  # type: ignore[arg-type]
            except Exception:
                dt = datetime.fromtimestamp(timestamp)
        else:
            dt = datetime.fromtimestamp(timestamp)

        # Parse market open time
        try:
            open_h, open_m = (int(p) for p in market_open.split(":"))
        except Exception:
            open_h, open_m = _MARKET_OPEN_HOUR, _MARKET_OPEN_MINUTE

        market_open_naive = datetime.combine(dt.date(), dt_time(open_h, open_m, 0))

        if _HAS_TZ and _IST is not None:
            if hasattr(_IST, "localize"):
                # pytz path
                try:
                    market_open_dt = _IST.localize(market_open_naive)  # type: ignore[attr-defined]
                except Exception:
                    market_open_dt = market_open_naive
            else:
                # zoneinfo path
                market_open_dt = market_open_naive.replace(tzinfo=_IST)
        else:
            market_open_dt = market_open_naive

        market_open_ts = int(market_open_dt.timestamp())
        ts_int = int(timestamp)

        if ts_int < market_open_ts:
            # Pre-market: plain floor alignment
            return (ts_int // bin_seconds) * bin_seconds

        seconds_since_open = ts_int - market_open_ts
        candle_period = seconds_since_open // bin_seconds
        return market_open_ts + candle_period * bin_seconds

    @staticmethod
    def cumulative_delta(bins: list[FootprintBucket]) -> list[float]:
        """Compute running cumulative delta across a list of footprint buckets.

        The cumulative delta resets at each new trading day (i.e. whenever the
        ``timestamp_bin`` crosses into a new calendar date in IST). Within the
        same day it accumulates monotonically.

        Args:
            bins: List of :class:`FootprintBucket` instances, ordered
                chronologically (oldest first). Typically the output of
                :meth:`get_footprint`.

        Returns:
            List of cumulative delta floats, one per input bucket, in the same
            order as ``bins``. Empty list if ``bins`` is empty.
        """
        if not bins:
            return []

        running: float = 0.0
        result: list[float] = []
        prev_date: datetime | None = None

        for bucket in bins:
            # Determine calendar date for this bin
            try:
                if _HAS_TZ and _IST is not None:
                    bin_dt = datetime.fromtimestamp(bucket.timestamp_bin, tz=_IST)  # type: ignore[arg-type]
                else:
                    bin_dt = datetime.fromtimestamp(bucket.timestamp_bin)
            except Exception:
                bin_dt = datetime.fromtimestamp(bucket.timestamp_bin)

            current_date = bin_dt.date()

            if prev_date is not None and current_date != prev_date:
                # New trading day — reset accumulator
                running = 0.0

            running += bucket.delta
            result.append(running)
            prev_date = current_date

        return result

    @staticmethod
    def detect_poc(bins: list[FootprintBucket]) -> float:
        """Detect the Point of Control — price level with the highest total volume.

        The POC is computed across all supplied bins (the entire session or any
        window the caller chooses to pass). If multiple price levels share the
        same maximum volume, the lowest price level is returned (deterministic
        tie-breaking).

        Args:
            bins: List of :class:`FootprintBucket` instances. May span multiple
                time bins — volumes at the same price level across bins are
                summed before comparison.

        Returns:
            Price level (float) of the Point of Control, or ``0.0`` if
            ``bins`` is empty.
        """
        if not bins:
            return 0.0

        # Aggregate total volume per price level across all bins
        volume_by_level: dict[float, int] = {}
        for bucket in bins:
            level = bucket.price_level
            volume_by_level[level] = volume_by_level.get(level, 0) + bucket.total_volume

        if not volume_by_level:
            return 0.0

        # Find the price level with the highest total volume.
        # Tie-break: lowest price level (deterministic).
        poc = min(
            volume_by_level,
            key=lambda p: (-volume_by_level[p], p),
        )
        return poc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _checkpoint_config(self) -> dict[str, int | float]:
        """Return constructor settings that define checkpoint compatibility."""
        return {
            "time_bin_seconds": self.time_bin_seconds,
            "tick_size": self.tick_size,
            "max_retained_sessions": self.max_retained_sessions,
            "max_bins_per_session": self.max_bins_per_session,
            "max_instruments": self.max_instruments,
        }

    def _restore_checkpoint_identity(
        self,
        row: Any,
        *,
        now: float,
    ) -> tuple[_InstrumentIdentity, int, int]:
        """Validate and load one identity into a scratch aggregator."""
        if not isinstance(row, Mapping):
            raise ValueError("checkpoint identity must be a mapping")
        exchange = row.get("exchange")
        symbol = row.get("symbol")
        if not isinstance(exchange, str) or not exchange.strip():
            raise ValueError("checkpoint identity exchange is invalid")
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("checkpoint identity symbol is invalid")
        identity = _instrument_identity(symbol, exchange)

        bin_rows = row.get("bins")
        if not isinstance(bin_rows, list):
            raise ValueError("checkpoint bins must be a list")
        max_bins = self.max_retained_sessions * self.max_bins_per_session
        if len(bin_rows) > max_bins:
            raise ValueError("checkpoint identity exceeds retained bin bounds")

        symbol_state: dict[int, _BinState] = {}
        bins_by_session: dict[date, int] = {}
        positive_bins: set[int] = set()
        price_level_count = 0
        for bin_row in bin_rows:
            if not isinstance(bin_row, Mapping):
                raise ValueError("checkpoint bin must be a mapping")
            timestamp = _persisted_timestamp(bin_row.get("timestamp_bin"))
            if timestamp is None or not timestamp.is_integer():
                raise ValueError("checkpoint bin timestamp is invalid")
            if timestamp > now + MAX_SOURCE_CLOCK_SKEW_SECONDS:
                raise ValueError("checkpoint contains a future source timestamp")
            bin_start = int(timestamp)
            try:
                if self.calculate_aligned_time_bin(bin_start, self.time_bin_seconds) != bin_start:
                    raise ValueError("checkpoint bin is not aligned to the aggregator interval")
                session = _ist_session_date(bin_start)
            except (OSError, OverflowError, ValueError) as exc:
                raise ValueError("checkpoint bin timestamp is invalid") from exc
            if bin_start in symbol_state:
                raise ValueError("checkpoint contains a duplicate bin")
            bins_by_session[session] = bins_by_session.get(session, 0) + 1
            if bins_by_session[session] > self.max_bins_per_session:
                raise ValueError("checkpoint session exceeds retained bin bounds")
            if len(bins_by_session) > self.max_retained_sessions:
                raise ValueError("checkpoint exceeds retained session bounds")

            provenance_rows = bin_row.get("provenances")
            if not isinstance(provenance_rows, list) or any(
                provenance not in {"trade_tick", "cumulative_quote_delta", "mixed"} for provenance in provenance_rows
            ):
                raise ValueError("checkpoint bin provenance is invalid")
            provenances = set(provenance_rows)
            level_rows = bin_row.get("levels")
            if not isinstance(level_rows, list):
                raise ValueError("checkpoint levels must be a list")
            if level_rows and not provenances:
                raise ValueError("checkpoint levels are missing provenance")

            levels: dict[float, list[int]] = {}
            for level_row in level_rows:
                if not isinstance(level_row, Mapping):
                    raise ValueError("checkpoint price level must be a mapping")
                price_level = _persisted_number(level_row.get("price_level"), positive=True)
                buy_volume = _exact_trade_volume(level_row.get("buy_volume"))
                sell_volume = _exact_trade_volume(level_row.get("sell_volume"))
                if (
                    price_level is None
                    or buy_volume is None
                    or sell_volume is None
                    or not math.isfinite(price_level / self.tick_size)
                    or self._round_to_tick(price_level) != price_level
                ):
                    raise ValueError("checkpoint price level is invalid")
                if price_level in levels:
                    raise ValueError("checkpoint contains a duplicate price level")
                levels[price_level] = [buy_volume, sell_volume]
                if buy_volume > 0 or sell_volume > 0:
                    positive_bins.add(bin_start)
            price_level_count += len(levels)
            if price_level_count > _MAX_STATE_PRICE_LEVELS:
                raise ValueError("checkpoint contains too many price levels")
            symbol_state[bin_start] = _BinState(
                bin_start=bin_start,
                levels=levels,
                provenances=provenances,
            )

        if symbol_state:
            self._state[identity] = symbol_state

        last_tick_row = row.get("last_tick")
        normalised_volume = row.get("normalised_volume")
        offset_rows = row.get("counter_offsets")
        high_watermark_rows = row.get("counter_high_watermarks")
        if last_tick_row is None:
            if normalised_volume is not None or offset_rows or high_watermark_rows:
                raise ValueError("checkpoint counter state is incomplete")
        else:
            if not isinstance(last_tick_row, Mapping):
                raise ValueError("checkpoint last_tick must be a mapping")
            ltp = _persisted_number(last_tick_row.get("ltp"), positive=True)
            raw_volume = _persisted_volume(last_tick_row.get("volume"))
            timestamp = _persisted_timestamp(last_tick_row.get("timestamp"))
            if ltp is None or raw_volume is None or timestamp is None:
                raise ValueError("checkpoint last_tick is invalid")
            if timestamp > now + MAX_SOURCE_CLOCK_SKEW_SECONDS:
                raise ValueError("checkpoint contains a future source timestamp")
            session = _persisted_session(last_tick_row.get("session"), timestamp)
            normalised = _persisted_volume(normalised_volume)
            if session is None or normalised is None or normalised < raw_volume:
                raise ValueError("checkpoint normalised counter is invalid")
            if not isinstance(offset_rows, list) or not 0 < len(offset_rows) <= _MAX_COUNTER_EPOCHS:
                raise ValueError("checkpoint counter offsets are invalid")
            offsets = tuple(_persisted_volume(offset) for offset in offset_rows)
            if any(offset is None for offset in offsets) or len(set(offsets)) != len(offsets):
                raise ValueError("checkpoint counter offsets are invalid")
            parsed_offsets = tuple(int(offset) for offset in offsets if offset is not None)
            if not isinstance(high_watermark_rows, list):
                raise ValueError("checkpoint counter high-water marks are invalid")
            high_watermarks: dict[int, int] = {}
            for high_watermark_row in high_watermark_rows:
                if not isinstance(high_watermark_row, Mapping):
                    raise ValueError("checkpoint counter high-water mark is invalid")
                offset = _persisted_volume(high_watermark_row.get("offset"))
                volume = _persisted_volume(high_watermark_row.get("volume"))
                if offset is None or volume is None or offset in high_watermarks:
                    raise ValueError("checkpoint counter high-water mark is invalid")
                high_watermarks[offset] = volume
            if set(high_watermarks) != set(parsed_offsets):
                raise ValueError("checkpoint counter high-water marks do not match offsets")
            self._last_tick[identity] = (ltp, raw_volume, session, timestamp)
            self._normalised_volume[identity] = normalised
            self._counter_offsets[identity] = parsed_offsets
            self._counter_high_watermarks[identity] = high_watermarks

        pending_row = row.get("pending_volume_reset")
        if pending_row is not None:
            if last_tick_row is None or not isinstance(pending_row, Mapping):
                raise ValueError("checkpoint pending reset is invalid")
            pending_ltp = _persisted_number(pending_row.get("ltp"), positive=True)
            pending_volume = _persisted_volume(pending_row.get("volume"))
            pending_timestamp = _persisted_timestamp(pending_row.get("timestamp"))
            if pending_ltp is None or pending_volume is None or pending_timestamp is None:
                raise ValueError("checkpoint pending reset is invalid")
            pending_session = _persisted_session(pending_row.get("session"), pending_timestamp)
            last_timestamp = self._last_tick[identity][3]
            if (
                pending_session is None
                or pending_timestamp < last_timestamp
                or pending_timestamp > now + MAX_SOURCE_CLOCK_SKEW_SECONDS
            ):
                raise ValueError("checkpoint pending reset is invalid")
            self._pending_volume_reset[identity] = (
                pending_ltp,
                pending_volume,
                pending_session,
                pending_timestamp,
            )

        last_side = row.get("last_side")
        if last_side is not None:
            if last_side not in {"BUY", "SELL"} or last_tick_row is None:
                raise ValueError("checkpoint last side is invalid")
            self._last_side[identity] = last_side

        last_data_row = row.get("last_data_tick")
        if last_data_row is not None:
            if not isinstance(last_data_row, Mapping):
                raise ValueError("checkpoint last data tick is invalid")
            data_timestamp = _persisted_timestamp(last_data_row.get("timestamp"))
            data_provenance = last_data_row.get("provenance")
            if (
                data_timestamp is None
                or data_timestamp > now + MAX_SOURCE_CLOCK_SKEW_SECONDS
                or data_provenance not in {"trade_tick", "cumulative_quote_delta", "mixed"}
            ):
                raise ValueError("checkpoint last data tick is invalid")
            data_session = _persisted_session(last_data_row.get("session"), data_timestamp)
            try:
                data_bin = self.calculate_aligned_time_bin(data_timestamp, self.time_bin_seconds)
            except (OSError, OverflowError, TypeError, ValueError) as exc:
                raise ValueError("checkpoint last data tick is invalid") from exc
            bin_state = symbol_state.get(data_bin)
            if data_session is None or data_bin not in positive_bins or bin_state is None:
                raise ValueError("checkpoint freshness is not linked to returned data")
            if data_provenance != "mixed" and data_provenance not in bin_state.provenances:
                raise ValueError("checkpoint freshness provenance is inconsistent")
            self._last_data_tick[identity] = (
                data_session,
                data_timestamp,
                data_provenance,
            )

        self._price_level_count += price_level_count
        return identity, len(symbol_state), price_level_count

    def _prepare_replay_ticks(
        self,
        ticks: Iterable[Mapping[str, Any]],
        *,
        now: float | datetime | None,
        max_ticks: int,
        reject_full_window: bool,
        current_session_only: bool,
    ) -> tuple[
        list[Mapping[str, Any]],
        list[tuple[float, int, str, str, float, int, float | None, float | None]],
    ]:
        """Validate and bound replay rows while preserving caller ingest order."""
        if isinstance(max_ticks, bool) or not isinstance(max_ticks, int):
            raise ValueError("max_ticks must be an integer")
        if not 0 < max_ticks <= MAX_RESTORE_TICKS:
            raise ValueError(f"max_ticks must be between 1 and {MAX_RESTORE_TICKS}, got {max_ticks}")
        bounded_ticks = list(islice(ticks, max_ticks + 1))
        if len(bounded_ticks) > max_ticks:
            raise ValueError(f"ticks exceeds max_ticks={max_ticks}; query persisted ticks with a matching limit")
        if reject_full_window and len(bounded_ticks) == max_ticks:
            raise ValueError(
                "persisted tick window is potentially truncated; restore a checkpoint or prove a complete prefix"
            )

        import time as _time

        restore_timestamp = _time.time() if now is None else _persisted_timestamp(now)
        if restore_timestamp is None:
            raise ValueError("now must be a finite timestamp or datetime")
        current_session = _ist_session_date(restore_timestamp) if current_session_only else None
        prepared: list[tuple[float, int, str, str, float, int, float | None, float | None]] = []
        for index, row in enumerate(bounded_ticks):
            if not isinstance(row, Mapping):
                continue
            timestamp = _persisted_timestamp(row.get("ts"))
            symbol = row.get("symbol")
            exchange = row.get("exchange")
            ltp = _persisted_number(row.get("ltp"), positive=True)
            volume = _persisted_volume(row.get("volume"))
            if (
                timestamp is None
                or timestamp > restore_timestamp + MAX_SOURCE_CLOCK_SKEW_SECONDS
                or row.get("timestamp_provenance") != "source"
                or not isinstance(symbol, str)
                or not symbol.strip()
                or not isinstance(exchange, str)
                or not exchange.strip()
                or ltp is None
                or volume is None
                or not math.isfinite(ltp / self.tick_size)
            ):
                continue
            try:
                source_session = _ist_session_date(timestamp)
                if current_session is not None and source_session != current_session:
                    continue
            except (OSError, OverflowError, ValueError):
                continue
            prepared.append(
                (
                    timestamp,
                    index,
                    symbol,
                    exchange,
                    ltp,
                    volume,
                    _persisted_number(row.get("bid"), positive=True),
                    _persisted_number(row.get("ask"), positive=True),
                )
            )

        identities = {_instrument_identity(symbol, exchange) for _, _, symbol, exchange, _, _, _, _ in prepared}
        if len(identities) > self.max_instruments:
            raise ValueError(
                f"restore contains {len(identities)} identities, exceeding max_instruments={self.max_instruments}"
            )
        return bounded_ticks, prepared

    def _replace_all_state_locked(self, source: OrderFlowAggregator) -> None:
        """Replace every mutable state map from a validated scratch instance."""
        self._state = source._state
        self._last_tick = source._last_tick
        self._normalised_volume = source._normalised_volume
        self._counter_offsets = source._counter_offsets
        self._counter_high_watermarks = source._counter_high_watermarks
        self._pending_volume_reset = source._pending_volume_reset
        self._last_side = source._last_side
        self._last_data_tick = source._last_data_tick
        self._identity_recency = source._identity_recency
        self._price_level_count = source._price_level_count

    def _drop_identity_locked(self, identity: _InstrumentIdentity) -> None:
        """Remove one identity from every state map while holding ``_lock``."""
        self._price_level_count -= self._identity_price_level_count_locked(identity)
        self._state.pop(identity, None)
        self._last_tick.pop(identity, None)
        self._normalised_volume.pop(identity, None)
        self._counter_offsets.pop(identity, None)
        self._counter_high_watermarks.pop(identity, None)
        self._pending_volume_reset.pop(identity, None)
        self._last_side.pop(identity, None)
        self._last_data_tick.pop(identity, None)
        self._identity_recency.pop(identity, None)

    def _identity_price_level_count_locked(
        self,
        identity: _InstrumentIdentity,
    ) -> int:
        """Count retained levels for one identity while holding ``_lock``."""
        return sum(len(bin_state.levels) for bin_state in self._state.get(identity, {}).values())

    def _record_data_tick_locked(
        self,
        identity: _InstrumentIdentity,
        timestamp: float,
        provenance: DataProvenance,
    ) -> None:
        """Advance one identity's represented-data clock while holding ``_lock``."""
        session = _ist_session_date(timestamp)
        previous = self._last_data_tick.get(identity)
        if previous is not None and timestamp < previous[1]:
            return
        if previous is not None and timestamp == previous[1] and previous[2] != provenance:
            provenance = "mixed"
        self._last_data_tick[identity] = (session, timestamp, provenance)

    def _touch_identity_locked(self, identity: _InstrumentIdentity) -> None:
        """Mark one identity as recent and enforce the global LRU bound."""
        self._identity_recency.pop(identity, None)
        self._identity_recency[identity] = None
        while len(self._identity_recency) > self.max_instruments:
            oldest = next(iter(self._identity_recency))
            self._drop_identity_locked(oldest)

    def _identity_evictions_for_touch_locked(
        self,
        identity: _InstrumentIdentity,
    ) -> tuple[_InstrumentIdentity, ...]:
        """Predict LRU removals for one touch without mutating live state."""
        recency = list(self._identity_recency)
        if identity in recency:
            recency.remove(identity)
        recency.append(identity)
        excess = max(0, len(recency) - self.max_instruments)
        return tuple(recency[:excess])

    def _identity_evictions_after_replacement_locked(
        self,
        identities: tuple[_InstrumentIdentity, ...],
    ) -> tuple[_InstrumentIdentity, ...]:
        """Predict LRU removals after transactional identity replacement."""
        replacement_set = set(identities)
        recency = [identity for identity in self._identity_recency if identity not in replacement_set]
        recency.extend(identities)
        excess = max(0, len(recency) - self.max_instruments)
        return tuple(recency[:excess])

    def _bin_evictions_after_insert_locked(
        self,
        symbol_state: Mapping[int, _BinState],
        bin_start: int,
    ) -> set[int]:
        """Predict retention removals after adding one bin without mutation."""
        bins_by_session: dict[date, list[int]] = {}
        for candidate in (*symbol_state, bin_start):
            bins_by_session.setdefault(_ist_session_date(candidate), []).append(candidate)

        retained_sessions = set(sorted(bins_by_session)[-self.max_retained_sessions :])
        evictions: set[int] = set()
        for session_date, session_bins in bins_by_session.items():
            if session_date not in retained_sessions:
                evictions.update(session_bins)
                continue
            evictions.update(sorted(set(session_bins))[: -self.max_bins_per_session])
        return evictions

    def _would_retain_bin_locked(
        self,
        identity: _InstrumentIdentity,
        bin_start: int,
    ) -> bool:
        """Return whether a new bin survives retention without mutating state."""
        symbol_state = self._state.get(identity, {})
        return bin_start in symbol_state or bin_start not in self._bin_evictions_after_insert_locked(
            symbol_state,
            bin_start,
        )

    def _evict_retained_state_locked(self, symbol_state: dict[int, _BinState]) -> None:
        """Bound one instrument's bins by newest IST sessions and per-session bins."""
        bins_by_session: dict[date, list[int]] = {}
        for bin_start in symbol_state:
            bins_by_session.setdefault(_ist_session_date(bin_start), []).append(bin_start)

        retained_sessions = sorted(bins_by_session)[-self.max_retained_sessions :]
        retained_session_set = set(retained_sessions)
        for session_date, session_bins in bins_by_session.items():
            if session_date not in retained_session_set:
                for bin_start in session_bins:
                    removed = symbol_state.pop(bin_start, None)
                    if removed is not None:
                        self._price_level_count -= len(removed.levels)
                continue
            for bin_start in sorted(session_bins)[: -self.max_bins_per_session]:
                removed = symbol_state.pop(bin_start, None)
                if removed is not None:
                    self._price_level_count -= len(removed.levels)

    def _round_to_tick(self, price: float) -> float:
        """Round ``price`` to the nearest ``tick_size`` boundary.

        Args:
            price: Raw trade price.

        Returns:
            Price rounded to the nearest tick.
        """
        return round(price / self.tick_size) * self.tick_size


def create_live_market_orderflow_aggregator() -> OrderFlowAggregator:
    """Build the shared production aggregator without collapsing fine-tick instruments.

    The application factory should use this helper for live ingestion. Direct
    analytics callers retain :class:`OrderFlowAggregator`'s established
    ``0.05`` default unless they explicitly choose another grid.
    """
    return OrderFlowAggregator(
        time_bin_seconds=LIVE_MARKET_INGESTION_INTERVAL_SECONDS,
        tick_size=LIVE_MARKET_INGESTION_TICK_SIZE,
    )
