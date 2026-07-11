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
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from threading import RLock
from typing import Literal

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
_InstrumentIdentity = tuple[str, str]


def _instrument_identity(symbol: str, exchange: str) -> _InstrumentIdentity:
    """Return the canonical identity for an instrument stream."""
    return exchange.strip().upper(), symbol.strip().upper()


def _ist_session_date(timestamp: int | float) -> date:
    """Return the IST calendar date represented by one bin timestamp."""
    if _HAS_TZ and _IST is not None:
        return datetime.fromtimestamp(timestamp, tz=_IST).date()  # type: ignore[arg-type]
    return datetime.fromtimestamp(timestamp).date()


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
    """

    price_level: float
    buy_volume: int
    sell_volume: int
    delta: int
    timestamp_bin: int

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

    def add(self, price_level: float, side: Side, volume: int) -> None:
        """Accumulate ``volume`` into ``price_level`` for ``side``.

        Args:
            price_level: Rounded price level.
            side: ``"BUY"`` or ``"SELL"``.
            volume: Volume to add (must be non-negative).
        """
        if price_level not in self.levels:
            self.levels[price_level] = [0, 0]  # [buy, sell]
        if side == "BUY":
            self.levels[price_level][0] += volume
        else:
            self.levels[price_level][1] += volume

    def to_buckets(self) -> list[FootprintBucket]:
        """Convert accumulated levels into a list of :class:`FootprintBucket`.

        Returns:
            List sorted by ``price_level`` ascending.
        """
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
            raise ValueError(
                f"time_bin_seconds must be positive, got {time_bin_seconds}"
            )
        if tick_size <= 0:
            raise ValueError(
                f"tick_size must be positive, got {tick_size}"
            )
        if max_retained_sessions <= 0:
            raise ValueError(
                f"max_retained_sessions must be positive, got {max_retained_sessions}"
            )
        if max_bins_per_session is not None and max_bins_per_session <= 0:
            raise ValueError(
                f"max_bins_per_session must be positive, got {max_bins_per_session}"
            )
        if max_instruments <= 0:
            raise ValueError(f"max_instruments must be positive, got {max_instruments}")

        self.time_bin_seconds = time_bin_seconds
        self.tick_size = tick_size
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
        self._last_side: dict[_InstrumentIdentity, Side] = {}
        self._identity_recency: OrderedDict[_InstrumentIdentity, None] = OrderedDict()
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
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side must be 'BUY' or 'SELL', got '{side}'")

        import time as _time

        ts = timestamp if timestamp is not None else _time.time()
        bin_start = self.calculate_aligned_time_bin(
            ts, self.time_bin_seconds, _MARKET_OPEN_DEFAULT
        )
        price_level = self._round_to_tick(price)
        volume = max(0, int(volume))

        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            self._touch_identity_locked(identity)
            if identity not in self._state:
                self._state[identity] = {}
            symbol_state = self._state[identity]

            if bin_start not in symbol_state:
                symbol_state[bin_start] = _BinState(bin_start=bin_start)
                self._evict_retained_state_locked(symbol_state)

            bin_state = symbol_state.get(bin_start)
            if bin_state is not None:
                bin_state.add(price_level, side, volume)
        logger.debug(
            "add_tick: exchange=%s symbol=%s price=%.4f vol=%d side=%s bin=%d",
            identity[0], identity[1], price_level, volume, side, bin_start,
        )
        return bin_start

    def _classify_side(self, symbol: str, ltp: float, prev_ltp: float,
                       bid: float | None, ask: float | None,
                       *, exchange: str = "") -> Side:
        """Aggressor side via the quote rule (preferred) or the tick rule.

        Lee-Ready style: a trade at or above the ask is buyer-initiated; at or
        below the bid is seller-initiated; otherwise (or with no quote) the tick
        rule — up-trade = buy, down-trade = sell, unchanged = carry the previous
        side. Not a guess: the standard trade-side classification.
        """
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            if bid is not None and ask is not None and ask >= bid > 0:
                if ltp >= ask:
                    self._last_side[identity] = "BUY"
                    return "BUY"
                if ltp <= bid:
                    self._last_side[identity] = "SELL"
                    return "SELL"
            if ltp > prev_ltp:
                side: Side = "BUY"
            elif ltp < prev_ltp:
                side = "SELL"
            else:
                side = self._last_side.get(identity, "BUY")
            self._last_side[identity] = side
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

        Derives the incremental traded volume (this tick's cumulative minus the
        instrument's last cumulative) and the aggressor side (see
        :meth:`_classify_side`), then records it via :meth:`add_tick`. A no-op
        until a second tick establishes a baseline, and when no volume traded
        between ticks. This is the glue that turns the live tick stream into a
        real order-flow footprint instead of synthetic data.
        """
        import time as _time

        tick_timestamp = timestamp if timestamp is not None else _time.time()
        session_date = _ist_session_date(tick_timestamp)
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            current_volume = int(cumulative_volume)
            prev = self._last_tick.get(identity)
            if prev is not None:
                if tick_timestamp < prev[3]:
                    return
                if tick_timestamp == prev[3] and current_volume < prev[1]:
                    return
            if current_volume < 0:
                self._last_tick.pop(identity, None)
                self._last_side.pop(identity, None)
                return
            self._touch_identity_locked(identity)
            if prev is None or prev[2] != session_date:
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._last_side.pop(identity, None)
                return
            prev_ltp, prev_vol, _, _ = prev
            self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
            if current_volume < prev_vol:
                self._last_side.pop(identity, None)
                return

            inc_volume = current_volume - prev_vol
            if inc_volume <= 0:
                return
            side = self._classify_side(symbol, ltp, prev_ltp, bid, ask, exchange=exchange)
            self.add_tick(symbol, ltp, inc_volume, side, timestamp=tick_timestamp, exchange=exchange)

    def retain_identities(self, identities: set[_InstrumentIdentity]) -> None:
        """Discard every identity no longer present in the recorder watchlist."""
        allowed = {
            (str(exchange).strip().upper(), str(symbol).strip().upper())
            for exchange, symbol in identities
        }
        with self._lock:
            known = (
                set(self._state)
                | set(self._last_tick)
                | set(self._last_side)
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
        with self._lock:
            symbol_state = self._state.get(_instrument_identity(symbol, exchange))
            if not symbol_state:
                return []

            # Select the n_bins most recent bin keys and materialise a stable
            # view before another thread can mutate the nested dictionaries.
            all_bins = sorted(symbol_state)
            latest_session = _ist_session_date(all_bins[-1])
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
                self._last_side.clear()
                self._identity_recency.clear()
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

    def _drop_identity_locked(self, identity: _InstrumentIdentity) -> None:
        """Remove one identity from every state map while holding ``_lock``."""
        self._state.pop(identity, None)
        self._last_tick.pop(identity, None)
        self._last_side.pop(identity, None)
        self._identity_recency.pop(identity, None)

    def _touch_identity_locked(self, identity: _InstrumentIdentity) -> None:
        """Mark one identity as recent and enforce the global LRU bound."""
        self._identity_recency.pop(identity, None)
        self._identity_recency[identity] = None
        while len(self._identity_recency) > self.max_instruments:
            oldest, _ = self._identity_recency.popitem(last=False)
            self._state.pop(oldest, None)
            self._last_tick.pop(oldest, None)
            self._last_side.pop(oldest, None)

    def _evict_retained_state_locked(self, symbol_state: dict[int, _BinState]) -> None:
        """Bound one instrument's bins by newest IST sessions and per-session bins."""
        bins_by_session: dict[date, list[int]] = {}
        for bin_start in symbol_state:
            bins_by_session.setdefault(_ist_session_date(bin_start), []).append(bin_start)

        retained_sessions = sorted(bins_by_session)[-self.max_retained_sessions:]
        retained_session_set = set(retained_sessions)
        for session_date, session_bins in bins_by_session.items():
            if session_date not in retained_session_set:
                for bin_start in session_bins:
                    symbol_state.pop(bin_start, None)
                continue
            for bin_start in sorted(session_bins)[:-self.max_bins_per_session]:
                symbol_state.pop(bin_start, None)

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
