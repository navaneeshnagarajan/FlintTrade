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
from datetime import date, datetime, time as dt_time, timezone
from itertools import islice
from threading import RLock
from typing import Any, Literal

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
            timestamp = (
                value.replace(tzinfo=timezone.utc).timestamp()
                if value.tzinfo is None
                else value.timestamp()
            )
        elif isinstance(value, (int, float)):
            timestamp = float(value)
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            timestamp = (
                parsed.replace(tzinfo=timezone.utc).timestamp()
                if parsed.tzinfo is None
                else parsed.timestamp()
            )
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
        if price_level not in self.levels:
            self.levels[price_level] = [0, 0]  # [buy, sell]
        if side == "BUY":
            self.levels[price_level][0] += volume
        else:
            self.levels[price_level][1] += volume
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
        # Raw cumulative counters can reset and later recover to an earlier
        # namespace. Keep a monotonic logical total plus a bounded set of
        # observed namespace offsets so recovery cannot count volume twice.
        self._normalised_volume: dict[_InstrumentIdentity, int] = {}
        self._counter_offsets: dict[_InstrumentIdentity, tuple[int, ...]] = {}
        # A lower intraday cumulative counter needs a second monotonic sample
        # before it can replace the last trusted baseline.
        self._pending_volume_reset: dict[
            _InstrumentIdentity, tuple[float, int, date, float]
        ] = {}
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
                bin_state.add(price_level, side, volume, provenance)
        logger.debug(
            "add_tick: exchange=%s symbol=%s price=%.4f vol=%d side=%s bin=%d provenance=%s",
            identity[0], identity[1], price_level, volume, side, bin_start, provenance,
        )
        return bin_start

    def _classify_side(self, symbol: str, ltp: float, prev_ltp: float,
                       bid: float | None, ask: float | None,
                       *, exchange: str = "") -> Side:
        """Aggressor side via the quote rule (preferred) or the tick rule.

        Lee-Ready style: a trade at or above the ask is buyer-initiated; at or
        below the bid is seller-initiated; otherwise (or with no quote) the tick
        rule — up-trade = buy, down-trade = sell, unchanged = carry the previous
        side. This is a standard estimate; cumulative quote snapshots do not
        identify each underlying trade's exact price or aggressor side.
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

        Estimates incremental volume from changes in the cumulative counter and
        estimates one side/price for that whole interval (see
        :meth:`_classify_side`). The resulting buckets remain useful order-flow
        estimates but are not exact trade-by-trade exchange prints. A first
        snapshot establishes only a baseline.
        """
        import time as _time

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
            self._touch_identity_locked(identity)
            if prev is None or prev[2] != session_date:
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._normalised_volume[identity] = current_volume
                self._counter_offsets[identity] = (0,)
                self._pending_volume_reset.pop(identity, None)
                self._last_side.pop(identity, None)
                return
            prev_ltp, prev_vol, _, _ = prev
            previous_normalised = self._normalised_volume.get(identity, prev_vol)
            offsets = self._counter_offsets.get(
                identity,
                (previous_normalised - prev_vol,),
            )
            if current_volume < prev_vol:
                pending = self._pending_volume_reset.get(identity)
                if pending is None or pending[2] != session_date:
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
                    self._pending_volume_reset[identity] = (
                        ltp,
                        current_volume,
                        session_date,
                        tick_timestamp,
                    )
                    return

                self._pending_volume_reset.pop(identity, None)
                new_offset = previous_normalised - pending_volume
                normalised, offsets = self._select_counter_namespace(
                    current_volume,
                    previous_normalised,
                    (new_offset, *offsets),
                )
                self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
                self._normalised_volume[identity] = normalised
                self._counter_offsets[identity] = offsets
                inc_volume = normalised - previous_normalised
                if inc_volume <= 0:
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
                return
            self._pending_volume_reset.pop(identity, None)
            normalised, offsets = self._select_counter_namespace(
                current_volume,
                previous_normalised,
                offsets,
            )
            self._last_tick[identity] = (ltp, current_volume, session_date, tick_timestamp)
            self._normalised_volume[identity] = normalised
            self._counter_offsets[identity] = offsets

            inc_volume = normalised - previous_normalised
            if inc_volume <= 0:
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

    @staticmethod
    def _select_counter_namespace(
        raw_volume: int,
        previous_normalised: int,
        offsets: tuple[int, ...],
    ) -> tuple[int, tuple[int, ...]]:
        """Choose the least non-decreasing interpretation of a raw counter.

        A confirmed reset introduces another ``raw + offset`` namespace. If a
        feed later recovers an earlier counter, selecting the smallest logical
        value that does not move backwards avoids counting the same interval a
        second time.
        """
        unique_offsets = tuple(dict.fromkeys(offsets))[:_MAX_COUNTER_EPOCHS] or (0,)
        candidates = [
            (raw_volume + offset, index, offset)
            for index, offset in enumerate(unique_offsets)
            if raw_volume + offset >= previous_normalised
        ]
        if candidates:
            normalised, _, selected_offset = min(candidates)
        else:
            selected_offset = unique_offsets[0]
            normalised = previous_normalised
        reordered = (selected_offset, *(offset for offset in unique_offsets if offset != selected_offset))
        return normalised, reordered[:_MAX_COUNTER_EPOCHS]

    def get_market_freshness(
        self,
        symbol: str,
        *,
        exchange: str = "",
        now: float | None = None,
    ) -> dict[str, str | float | bool | None]:
        """Return last-tick recency and IST-session freshness for an identity."""
        import time as _time

        now_timestamp = _time.time() if now is None else float(now)
        current_session = _ist_session_date(now_timestamp)
        identity = _instrument_identity(symbol, exchange)
        with self._lock:
            last_tick = self._last_tick.get(identity)

        if last_tick is None:
            return {
                "state": "unavailable",
                "is_fresh": False,
                "last_tick_timestamp": None,
                "last_tick_session": None,
                "current_session": current_session.isoformat(),
                "age_seconds": None,
            }

        last_timestamp = last_tick[3]
        last_session = last_tick[2]
        age_seconds = now_timestamp - last_timestamp
        if last_session != current_session:
            state = "stale"
        elif age_seconds < 0 or age_seconds > LIVE_TICK_FRESHNESS_SECONDS:
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
        }

    def restore_current_session(
        self,
        ticks: Iterable[Mapping[str, Any]],
        *,
        now: float | datetime | None = None,
        max_ticks: int = DEFAULT_RESTORE_MAX_TICKS,
    ) -> dict[str, int]:
        """Replace represented identities with replayed current-session ticks.

        Persisted rows must use the ``StorageManager.get_ticks`` field names.
        Naive datetimes are interpreted as UTC, matching the DuckDB schema.
        Input is materialised only up to ``max_ticks + 1``; overflow raises
        before any live state changes. Invalid and non-current-session rows are
        skipped. Replay occurs on a scratch aggregator, then swaps into this
        instance under one lock so a failed replay cannot leave partial state.

        Call this before starting live ingestion. Repeating the same restore is
        idempotent because represented identities are replaced, not appended.
        """
        if isinstance(max_ticks, bool) or not isinstance(max_ticks, int):
            raise ValueError("max_ticks must be an integer")
        if not 0 < max_ticks <= MAX_RESTORE_TICKS:
            raise ValueError(
                f"max_ticks must be between 1 and {MAX_RESTORE_TICKS}, got {max_ticks}"
            )

        bounded_ticks = list(islice(ticks, max_ticks + 1))
        if len(bounded_ticks) > max_ticks:
            raise ValueError(f"ticks exceeds max_ticks={max_ticks}; query persisted ticks with a matching limit")

        import time as _time

        restore_timestamp = _time.time() if now is None else _persisted_timestamp(now)
        if restore_timestamp is None:
            raise ValueError("now must be a finite timestamp or datetime")
        current_session = _ist_session_date(restore_timestamp)

        prepared: list[tuple[float, int, str, str, float, int, float | None, float | None]] = []
        for index, row in enumerate(bounded_ticks):
            if not isinstance(row, Mapping):
                continue
            timestamp = _persisted_timestamp(row.get("ts"))
            symbol_value = row.get("symbol")
            exchange_value = row.get("exchange")
            ltp = _persisted_number(row.get("ltp"), positive=True)
            volume = _persisted_volume(row.get("volume"))
            if (
                timestamp is None
                or not isinstance(symbol_value, str)
                or not symbol_value.strip()
                or not isinstance(exchange_value, str)
                or not exchange_value.strip()
                or ltp is None
                or volume is None
                or not math.isfinite(ltp / self.tick_size)
            ):
                continue
            try:
                if _ist_session_date(timestamp) != current_session:
                    continue
            except (OSError, OverflowError, ValueError):
                continue
            prepared.append(
                (
                    timestamp,
                    index,
                    symbol_value,
                    exchange_value,
                    ltp,
                    volume,
                    _persisted_number(row.get("bid"), positive=True),
                    _persisted_number(row.get("ask"), positive=True),
                )
            )

        identities = {
            _instrument_identity(symbol, exchange)
            for _, _, symbol, exchange, _, _, _, _ in prepared
        }
        if len(identities) > self.max_instruments:
            raise ValueError(
                f"restore contains {len(identities)} identities, exceeding max_instruments={self.max_instruments}"
            )

        prepared.sort(key=lambda item: (item[0], item[1]))
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

                for identity in identities:
                    self._drop_identity_locked(identity)
                    for target, source in (
                        (self._state, scratch._state),
                        (self._last_tick, scratch._last_tick),
                        (self._normalised_volume, scratch._normalised_volume),
                        (self._counter_offsets, scratch._counter_offsets),
                        (self._pending_volume_reset, scratch._pending_volume_reset),
                        (self._last_side, scratch._last_side),
                    ):
                        if identity in source:
                            target[identity] = source[identity]
                    self._touch_identity_locked(identity)

        return {
            "input_ticks": len(bounded_ticks),
            "restored_ticks": len(prepared),
            "skipped_ticks": len(bounded_ticks) - len(prepared),
            "identities": len(identities),
        }

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
                | set(self._normalised_volume)
                | set(self._counter_offsets)
                | set(self._pending_volume_reset)
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
            session_bins = [
                bin_start
                for bin_start in all_bins
                if _ist_session_date(bin_start) == latest_session
            ]
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
                self._pending_volume_reset.clear()
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
        self._normalised_volume.pop(identity, None)
        self._counter_offsets.pop(identity, None)
        self._pending_volume_reset.pop(identity, None)
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
            self._normalised_volume.pop(oldest, None)
            self._counter_offsets.pop(oldest, None)
            self._pending_volume_reset.pop(oldest, None)
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
