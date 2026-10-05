"""Validate supplied exchange-qualified frames and store local ticks in DuckDB.

This module provides no network capture or broker subscription transport.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import threading
import time
from datetime import UTC, datetime
from typing import Any, Callable

from ._tick_contracts import MAX_SOURCE_CLOCK_SKEW_SECONDS
from .storage import IST, StorageManager, ingest_broker_timestamp

logger = logging.getLogger("flinttrade.data.tick_recorder")


# Subscription modes
MODE_LTP = "ltp"
MODE_QUOTE = "quote"
MODE_DEPTH = "depth"

_MODE_LABELS = {
    MODE_LTP: "LTP",
    MODE_QUOTE: "QUOTE",
    MODE_DEPTH: "DEPTH",
}
_NUMERIC_MODES = {1: MODE_LTP, 2: MODE_QUOTE, 3: MODE_DEPTH}

LegacyLtpSink = Callable[[str, str, float, int], None]
TimestampedLtpSink = Callable[[str, str, float, int, float], None]
LtpSink = LegacyLtpSink | TimestampedLtpSink

NATIVE_TICK_CAPTURE_UNAVAILABLE = "Native tick capture is unavailable until a native source is supported."
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1
_MAX_FRAME_TIMESTAMP_TEXT_LENGTH = 64
_MIN_FRAME_TIMESTAMP_EPOCH = datetime(2000, 1, 1, tzinfo=UTC).timestamp()
_MAX_FRAME_TIMESTAMP_EPOCH = datetime(2100, 1, 1, tzinfo=UTC).timestamp()
_MAX_FRAME_TIMESTAMP_AGE_SECONDS = 5 * 60
MAX_WATCHLIST_INSTRUMENTS = 512
_MISSING_TIMESTAMP = object()
_LTP_SINK_PROBE_ARGS = ("NSE", "RELIANCE", 1.0, 0, 0.0)


def _ltp_sink_positional_arity(sink: LtpSink) -> int:
    """Resolve a supported sink contract once instead of retrying every tick."""
    try:
        signature = inspect.signature(sink)
    except (TypeError, ValueError) as exc:
        raise TypeError("ltp_sink must expose a signature accepting four or five positional arguments") from exc
    for arity in (5, 4):
        try:
            signature.bind(*_LTP_SINK_PROBE_ARGS[:arity])
        except TypeError:
            continue
        return arity
    raise TypeError("ltp_sink must accept four or five positional arguments")


def _finite_float_or_none(value: Any) -> float | None:
    """Normalise one storage-bound floating value without poisoning its batch."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _bigint_or_none(value: Any) -> int | None:
    """Normalise one storage-bound integer to DuckDB's signed BIGINT range."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if _BIGINT_MIN <= number <= _BIGINT_MAX else None


def _normalise_epoch_timestamp(value: Any) -> datetime | None:
    """Parse a bounded epoch value in seconds, milliseconds, microseconds, or nanoseconds."""
    if value is None or isinstance(value, bool):
        return None
    try:
        epoch = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(epoch):
        return None

    magnitude = abs(epoch)
    if magnitude >= 1e17:
        epoch /= 1e9
    elif magnitude >= 1e14:
        epoch /= 1e6
    elif magnitude >= 1e11:
        epoch /= 1e3
    if not _MIN_FRAME_TIMESTAMP_EPOCH <= epoch <= _MAX_FRAME_TIMESTAMP_EPOCH:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC)


def _normalise_frame_timestamp(value: Any) -> datetime | None:
    """Parse one bounded epoch, zoned ISO time, or IST broker wall clock.

    A zone-less ``YYYY-MM-DD HH:MM:SS`` string is the Indian broker wall
    clock (Dhan, Kotak Neo, Upstox, Groww, INDmoney). It is converted to
    UTC before the row is stored. An unparseable value is rejected.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > _MAX_FRAME_TIMESTAMP_TEXT_LENGTH:
            return None
        epoch_timestamp = _normalise_epoch_timestamp(text)
        if epoch_timestamp is not None:
            return epoch_timestamp
        try:
            parsed = ingest_broker_timestamp(text, source_tz=IST)
        except (TypeError, ValueError, OverflowError):
            return None
        if not _MIN_FRAME_TIMESTAMP_EPOCH <= parsed.timestamp() <= _MAX_FRAME_TIMESTAMP_EPOCH:
            return None
        return parsed
    return _normalise_epoch_timestamp(value)


def _frame_timestamp(
    frame: dict[str, Any],
    payload: dict[str, Any],
    received_at: datetime,
) -> tuple[datetime | None, str | None]:
    """Resolve source time and classify an explicit timestamp rejection."""
    candidate = payload.get("timestamp", _MISSING_TIMESTAMP)
    if candidate is _MISSING_TIMESTAMP and payload is not frame:
        candidate = frame.get("timestamp", _MISSING_TIMESTAMP)
    if candidate is _MISSING_TIMESTAMP:
        return None, "invalid"

    parsed = _normalise_frame_timestamp(candidate)
    if parsed is None:
        return None, "invalid"
    age_seconds = (received_at - parsed).total_seconds()
    if age_seconds < -MAX_SOURCE_CLOCK_SKEW_SECONDS:
        return None, "future"
    if age_seconds > _MAX_FRAME_TIMESTAMP_AGE_SECONDS:
        return None, "stale"
    return parsed, None


def _first_level_price(levels: Any, *price_keys: str) -> float | None:
    """Return the first finite price from a best-first depth ladder."""
    if not isinstance(levels, (list, tuple)) or not levels:
        return None
    level = levels[0]
    if isinstance(level, dict):
        for key in price_keys:
            price = _finite_float_or_none(level.get(key))
            if price is not None:
                return price
        return None
    if isinstance(level, (list, tuple)) and level:
        return _finite_float_or_none(level[0])
    return None


def _depth_bbo(depth: Any) -> tuple[float | None, float | None]:
    """Extract best bid and ask from supported native broker depth shapes."""
    if isinstance(depth, dict):
        bid = _finite_float_or_none(depth.get("bid"))
        bid = bid if bid is not None else _finite_float_or_none(depth.get("bid_price"))
        ask = _finite_float_or_none(depth.get("ask"))
        ask = ask if ask is not None else _finite_float_or_none(depth.get("ask_price"))
        for key in ("bids", "buy"):
            if bid is None:
                bid = _first_level_price(depth.get(key), "price", "bid_price", "bid")
        for key in ("asks", "sell"):
            if ask is None:
                ask = _first_level_price(depth.get(key), "price", "ask_price", "ask")
        return bid, ask
    if isinstance(depth, (list, tuple)) and depth and isinstance(depth[0], dict):
        level = depth[0]
        bid = _finite_float_or_none(level.get("bid_price"))
        bid = bid if bid is not None else _finite_float_or_none(level.get("bid"))
        ask = _finite_float_or_none(level.get("ask_price"))
        ask = ask if ask is not None else _finite_float_or_none(level.get("ask"))
        return bid, ask
    return None, None


def _payload_bbo(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """Canonicalise quote aliases and depth ladders into best bid and ask."""
    bid = _finite_float_or_none(payload.get("bid"))
    bid = bid if bid is not None else _finite_float_or_none(payload.get("bid_price"))
    ask = _finite_float_or_none(payload.get("ask"))
    ask = ask if ask is not None else _finite_float_or_none(payload.get("ask_price"))
    if bid is None:
        bid = _first_level_price(payload.get("bids"), "price", "bid_price", "bid")
    if ask is None:
        ask = _first_level_price(payload.get("asks"), "price", "ask_price", "ask")
    depth_bid, depth_ask = _depth_bbo(payload.get("depth"))
    return bid if bid is not None else depth_bid, ask if ask is not None else depth_ask


def _canonical_identity(exchange: Any, symbol: Any) -> tuple[str, str] | None:
    """Return one unambiguous canonical subscription identity."""
    if not isinstance(exchange, str) or not isinstance(symbol, str):
        return None
    canonical_exchange = exchange.strip().upper()
    canonical_symbol = symbol.strip().upper()
    if not canonical_exchange or not canonical_symbol or ":" in canonical_exchange or ":" in canonical_symbol:
        return None
    return canonical_exchange, canonical_symbol


def _canonical_instrument(instrument: Any) -> dict[str, str]:
    """Validate and canonicalise one recorder watchlist entry."""
    if not isinstance(instrument, dict):
        raise ValueError("Instrument must be a mapping with exchange and symbol")
    identity = _canonical_identity(instrument.get("exchange"), instrument.get("symbol"))
    if identity is None:
        raise ValueError("Instrument exchange and symbol must be non-empty strings without ':'")
    exchange, symbol = identity
    return {"exchange": exchange, "symbol": symbol}


class WatchlistCapacityError(ValueError):
    """Raised when a recorder watchlist exceeds its unique-identity limit."""


class TickPersistenceError(RuntimeError):
    """Raised when the recorder cannot persist its final buffered batch."""


class TickRecorder:
    """Validates supplied market-data frames and records ticks to DuckDB.

    Usage::

        recorder = TickRecorder(storage=storage)
        recorder.add_symbols([
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NFO", "symbol": "NIFTY26MAR2524000CE"},
        ], mode="quote")
        recorder._process_tick(local_observation)
        recorder.flush_pending()
    """

    def __init__(
        self,
        storage: StorageManager,
        batch_size: int = 100,
        flush_interval: float = 1.0,
        storage_lock: Any | None = None,
        orderflow_aggregator: Any | None = None,
        post_flush_callback: Callable[[], None] | None = None,
        ltp_sink: LtpSink | None = None,
    ) -> None:
        try:
            normalised_flush_interval = float(flush_interval)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("flush_interval must be a finite positive number") from exc
        if not math.isfinite(normalised_flush_interval) or normalised_flush_interval <= 0:
            raise ValueError("flush_interval must be a finite positive number")

        self._storage = storage
        self._state_lock = threading.RLock()
        self._subscription_lock = threading.RLock()
        self._flush_lock = threading.Lock()
        # Optional live order-flow aggregator fed from each tick (None = off).
        self._orderflow = orderflow_aggregator
        self._post_flush_callback = post_flush_callback
        aggregator_capacity = getattr(orderflow_aggregator, "max_instruments", MAX_WATCHLIST_INSTRUMENTS)
        self._max_instruments = (
            min(aggregator_capacity, MAX_WATCHLIST_INSTRUMENTS)
            if type(aggregator_capacity) is int and aggregator_capacity > 0
            else MAX_WATCHLIST_INSTRUMENTS
        )
        self._batch_size = batch_size
        self._flush_interval = normalised_flush_interval
        # Serialises access to the (single) DuckDB connection this recorder shares
        # with the nightly maintenance job, which runs on the scheduler thread —
        # DuckDB connections are not safe for concurrent use. None = no sharing.
        self._storage_lock = storage_lock
        self._ltp_sink = ltp_sink
        self._ltp_sink_arity = _ltp_sink_positional_arity(ltp_sink) if ltp_sink is not None else 0
        # On a persistent write failure the buffer is RETAINED for retry (a
        # transient lock/disk error must not silently lose ticks), but capped so
        # it cannot grow without bound — drop the oldest beyond this.
        self._max_buffer = max(batch_size * 100, 10_000)

        # Instruments keyed by mode
        self._subscriptions: dict[str, list[dict[str, str]]] = {
            MODE_LTP: [],
            MODE_QUOTE: [],
            MODE_DEPTH: [],
        }
        self._allowed_identities: set[tuple[str, str]] = set()

        self._buffer: list[tuple] = []
        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._connected = False
        self._transport_error = ""
        self._persistence_error = ""
        self._persistence_error_cause = ""
        self._checkpoint_error = ""
        self._source_timestamp_errors: dict[tuple[str, str], str] = {}
        self._tick_count = 0
        self._persisted_tick_count = 0
        self._dropped_tick_count = 0
        self._stale_source_timestamp_rejections = 0
        self._future_source_timestamp_rejections = 0
        self._invalid_source_timestamp_rejections = 0
        self._persistence_clock: Callable[[], float] = time.monotonic
        self._persistence_retry_delay = 1.0
        self._max_persistence_retry_delay = 30.0
        self._persistence_backoff = self._persistence_retry_delay
        self._next_persistence_retry_at = 0.0

    @property
    def tick_count(self) -> int:
        return int(self.status_snapshot()["tick_count"])

    @property
    def persisted_tick_count(self) -> int:
        """Number of received ticks successfully written to storage."""
        return int(self.status_snapshot()["persisted_tick_count"])

    @property
    def pending_tick_count(self) -> int:
        """Number of received ticks currently retained for persistence."""
        return int(self.status_snapshot()["pending_tick_count"])

    @property
    def dropped_tick_count(self) -> int:
        """Number of oldest buffered ticks dropped in this recorder session."""
        return int(self.status_snapshot()["dropped_tick_count"])

    @property
    def is_running(self) -> bool:
        """Whether the run() loop is active (set on start, cleared by stop())."""
        return bool(self.status_snapshot()["running"])

    @property
    def is_connected(self) -> bool:
        """Whether an authorised native capture source is connected."""
        return bool(self.status_snapshot()["connected"])

    @property
    def last_error(self) -> str:
        """Most recent local persistence or source availability error."""
        return str(self.status_snapshot()["last_error"])

    def sanitise_error(self, value: Any) -> str:
        """Format local persistence diagnostics."""
        return self._sanitise(value)

    @property
    def subscription_lock(self) -> Any:
        """Shared re-entrant lock for cross-component watchlist transactions."""
        return self._subscription_lock

    @property
    def max_instruments(self) -> int:
        """Maximum unique exchange-symbol identities accepted by the watchlist."""
        return self._max_instruments

    def status_snapshot(self) -> dict[str, Any]:
        """Return one atomic snapshot of recorder lifecycle and persistence state."""
        with self._state_lock:
            latest_rejected_identity = next(reversed(self._source_timestamp_errors), None)
            source_timestamp_error = (
                self._source_timestamp_errors[latest_rejected_identity] if latest_rejected_identity is not None else ""
            )
            last_error = (
                self._persistence_error or self._checkpoint_error or self._transport_error or source_timestamp_error
            )
            return {
                "running": self._running,
                "connected": self._connected,
                "tick_count": self._tick_count,
                "persisted_tick_count": self._persisted_tick_count,
                "pending_tick_count": len(self._buffer),
                "dropped_tick_count": self._dropped_tick_count,
                "stale_source_timestamp_rejections": self._stale_source_timestamp_rejections,
                "future_source_timestamp_rejections": self._future_source_timestamp_rejections,
                "invalid_source_timestamp_rejections": self._invalid_source_timestamp_rejections,
                "last_error": last_error,
                "transport_error": self._transport_error,
                "persistence_error": self._persistence_error,
                "checkpoint_error": self._checkpoint_error,
                "source_timestamp_error": source_timestamp_error,
            }

    # ------------------------------------------------------------------
    # Watchlist management
    # ------------------------------------------------------------------

    def add_symbols(
        self,
        instruments: list[dict[str, str]],
        mode: str = MODE_QUOTE,
    ) -> None:
        """Add instruments to the subscription watchlist.

        Each instrument: {"exchange": "NSE", "symbol": "RELIANCE"}
        """
        with self._subscription_lock:
            if mode not in self._subscriptions:
                raise ValueError(f"Invalid mode: {mode}. Use {list(_MODE_LABELS)}")
            canonical_instruments = [_canonical_instrument(instrument) for instrument in instruments]
            updated = [dict(instrument) for instrument in self._subscriptions[mode]]
            for inst in canonical_instruments:
                if inst not in updated:
                    updated.append(inst)
            candidate = {**self._subscriptions, mode: updated}
            self._validate_watchlist_capacity_locked(candidate)
            self._subscriptions[mode] = updated
            self._refresh_allowed_identities_locked()

    def remove_symbols(
        self,
        instruments: list[dict[str, str]],
        mode: str = MODE_QUOTE,
    ) -> None:
        """Remove instruments from the watchlist."""
        with self._subscription_lock:
            if mode not in self._subscriptions:
                raise ValueError(f"Invalid mode: {mode}. Use {list(_MODE_LABELS)}")
            canonical_instruments = [_canonical_instrument(instrument) for instrument in instruments]
            for inst in canonical_instruments:
                try:
                    self._subscriptions[mode].remove(inst)
                except ValueError:
                    pass
            self._refresh_allowed_identities_locked()

    def get_watchlist(self) -> dict[str, list[dict[str, str]]]:
        """Return current subscription watchlist by mode."""
        with self._subscription_lock:
            return {
                mode: [dict(instrument) for instrument in instruments]
                for mode, instruments in self._subscriptions.items()
            }

    def replace_watchlist(self, watchlist: dict[str, list[dict[str, str]]]) -> None:
        """Replace all subscriptions exactly, for transactional rollback."""
        with self._subscription_lock:
            if set(watchlist) != set(self._subscriptions):
                raise ValueError("Watchlist must contain ltp, quote and depth modes")
            canonical_watchlist = {
                mode: [_canonical_instrument(instrument) for instrument in watchlist[mode]]
                for mode in self._subscriptions
            }
            self._validate_watchlist_capacity_locked(canonical_watchlist)
            self._subscriptions = canonical_watchlist
            self._refresh_allowed_identities_locked()

    def _validate_watchlist_capacity_locked(
        self,
        watchlist: dict[str, list[dict[str, str]]],
    ) -> None:
        identities = {
            identity
            for instruments in watchlist.values()
            for instrument in instruments
            if (identity := _canonical_identity(instrument.get("exchange"), instrument.get("symbol"))) is not None
        }
        if len(identities) > self._max_instruments:
            raise WatchlistCapacityError(f"watchlist cannot exceed {self._max_instruments} unique instruments")

    def _refresh_allowed_identities_locked(self) -> None:
        """Rebuild the union allowlist while ``_subscription_lock`` is held."""
        self._allowed_identities = {
            identity
            for instruments in self._subscriptions.values()
            for instrument in instruments
            if (identity := _canonical_identity(instrument.get("exchange"), instrument.get("symbol"))) is not None
        }
        with self._state_lock:
            self._source_timestamp_errors = {
                identity: message
                for identity, message in self._source_timestamp_errors.items()
                if identity in self._allowed_identities
            }

    # ------------------------------------------------------------------
    # Capture availability and local storage lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Refuse network capture while retaining supplied local tick processing."""
        self._set_transport_error(NATIVE_TICK_CAPTURE_UNAVAILABLE)
        raise RuntimeError(NATIVE_TICK_CAPTURE_UNAVAILABLE)

    def stop(self) -> None:
        """Signal the recorder to stop after the current iteration."""
        with self._state_lock:
            self._running = False
            stop_event = self._stop_event
        if stop_event is not None:
            stop_event.set()

    def flush_pending(self) -> bool:
        """Force one retained-buffer flush and raise if persistence still fails."""
        return self._flush(force=True, raise_on_error=True)

    def retire_removed_identities(self) -> None:
        """Drop local order-flow state for instruments removed from the allowlist."""
        with self._subscription_lock:
            retain = getattr(self._orderflow, "retain_identities", None)
            if callable(retain):
                retain(set(self._allowed_identities))

    # ------------------------------------------------------------------
    # Internal: subscribe / consume / flush
    # ------------------------------------------------------------------

    def _process_tick(self, data: dict[str, Any]) -> bool:
        """Validate a local observation before buffering it for persistence."""

        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        frame_identity = _canonical_identity(data.get("exchange"), data.get("symbol"))
        payload_identity = (
            _canonical_identity(payload.get("exchange"), payload.get("symbol"))
            if payload is not data
            else frame_identity
        )
        if payload is not data:
            frame_has_identity = "exchange" in data or "symbol" in data
            payload_has_identity = "exchange" in payload or "symbol" in payload
            if (frame_has_identity and frame_identity is None) or (payload_has_identity and payload_identity is None):
                return False
            if frame_identity is not None and payload_identity is not None and frame_identity != payload_identity:
                return False
        identity = payload_identity or frame_identity
        if identity is None:
            return False

        exchange, symbol = identity
        with self._subscription_lock:
            if identity not in self._allowed_identities:
                return False
            return self._process_allowed_tick(data, payload=payload, exchange=exchange, symbol=symbol)

    def _process_allowed_tick(
        self,
        data: dict[str, Any],
        *,
        payload: dict[str, Any],
        exchange: str,
        symbol: str,
    ) -> bool:
        """Buffer and dispatch one canonical frame admitted by the allowlist."""
        received_at = datetime.now(UTC)
        ts, timestamp_rejection = _frame_timestamp(data, payload, received_at)
        if ts is None:
            self._record_source_timestamp_rejection(
                timestamp_rejection or "invalid",
                exchange=exchange,
                symbol=symbol,
            )
            return False
        self._clear_source_timestamp_error(exchange=exchange, symbol=symbol)
        mode = self._detect_mode(payload, data.get("mode"))
        normalised_ltp = _finite_float_or_none(payload.get("ltp"))
        cumulative_volume = _bigint_or_none(payload.get("volume"))
        persisted_volume = cumulative_volume if cumulative_volume is None or cumulative_volume >= 0 else None
        bid, ask = _payload_bbo(payload)

        depth_json = None
        if "depth" in payload:
            depth_json = json.dumps(payload["depth"])
        elif "bids" in payload or "asks" in payload:
            depth_json = json.dumps({"bids": payload.get("bids", []), "asks": payload.get("asks", [])})

        row = (
            ts,
            symbol,
            exchange,
            mode,
            normalised_ltp,
            _finite_float_or_none(payload.get("open")),
            _finite_float_or_none(payload.get("high")),
            _finite_float_or_none(payload.get("low")),
            _finite_float_or_none(payload.get("close")),
            persisted_volume,
            bid,
            ask,
            _bigint_or_none(payload.get("oi")),
            _finite_float_or_none(payload.get("prev_close")),
            depth_json,
            "source",
        )
        with self._state_lock:
            self._buffer.append(row)
            self._tick_count += 1
            if self._persistence_error:
                self._drop_excess_buffer_locked()

        self._dispatch_ltp(
            exchange,
            symbol,
            normalised_ltp,
            persisted_volume,
            ts.timestamp(),
        )

        # Feed the live order-flow aggregator (best-effort — must never break
        # tick recording). LTP + cumulative volume drive the footprint; bid/ask
        # sharpen the aggressor classification when present.
        if self._orderflow is not None:
            if normalised_ltp is not None and cumulative_volume is not None:
                try:
                    self._orderflow.feed_market_tick(
                        symbol,
                        normalised_ltp,
                        cumulative_volume,
                        exchange=exchange,
                        bid=bid,
                        ask=ask,
                        timestamp=ts.timestamp(),
                    )
                except Exception as exc:  # noqa: BLE001 - feeding never breaks recording
                    logger.debug(
                        "order-flow feed skipped for %s: %s",
                        self._sanitise(symbol),
                        self._sanitise(exc),
                    )
        return False

    @staticmethod
    def _detect_mode(data: dict[str, Any], reported_mode: Any = None) -> str:
        """Infer subscription mode from the fields present."""
        if isinstance(reported_mode, str) and reported_mode.lower() in _MODE_LABELS:
            return reported_mode.lower()
        if type(reported_mode) is int and reported_mode in _NUMERIC_MODES:
            return _NUMERIC_MODES[reported_mode]
        if "depth" in data or "bids" in data or "asks" in data:
            return MODE_DEPTH
        if {"bid", "ask", "bid_price", "ask_price", "volume"} & data.keys():
            return MODE_QUOTE
        return MODE_LTP

    def _dispatch_ltp(
        self,
        exchange: str,
        symbol: str,
        ltp: float | None,
        volume: int | None,
        source_timestamp: float,
    ) -> None:
        """Best-effort delivery of a valid LTP and its accepted source time."""
        if self._ltp_sink is None or ltp is None:
            return
        if ltp <= 0:
            return
        volume_value = volume if volume is not None else 0
        try:
            if self._ltp_sink_arity == 5:
                self._ltp_sink(exchange, symbol, ltp, volume_value, source_timestamp)
            else:
                self._ltp_sink(exchange, symbol, ltp, volume_value)
        except Exception as exc:  # noqa: BLE001 - callbacks must not interrupt recording
            logger.debug(
                "LTP sink skipped for %s:%s: %s",
                self._sanitise(exchange),
                self._sanitise(symbol),
                self._sanitise(exc),
            )

    def _record_source_timestamp_rejection(
        self,
        reason: str,
        *,
        exchange: str,
        symbol: str,
    ) -> None:
        """Count and surface a timestamp rejection without replacing source time."""
        with self._state_lock:
            if reason == "stale":
                self._stale_source_timestamp_rejections += 1
                count = self._stale_source_timestamp_rejections
                detail = f"older than {_MAX_FRAME_TIMESTAMP_AGE_SECONDS}s"
            elif reason == "future":
                self._future_source_timestamp_rejections += 1
                count = self._future_source_timestamp_rejections
                detail = f"beyond {MAX_SOURCE_CLOCK_SKEW_SECONDS:g}s clock-skew tolerance"
            else:
                reason = "invalid"
                self._invalid_source_timestamp_rejections += 1
                count = self._invalid_source_timestamp_rejections
                detail = "missing a valid timezone-aware or epoch value"
            message = f"Rejected {reason} source timestamp ({detail}; count={count})"
            identity = (exchange, symbol)
            self._source_timestamp_errors.pop(identity, None)
            self._source_timestamp_errors[identity] = message

        if count == 1 or count & (count - 1) == 0:
            logger.warning("%s", message)

    def _clear_source_timestamp_error(self, *, exchange: str, symbol: str) -> None:
        """Clear one instrument's timestamp diagnostic after an accepted tick."""
        with self._state_lock:
            self._source_timestamp_errors.pop((exchange, symbol), None)

    def _set_transport_error(self, message: Any) -> None:
        """Store source availability diagnostics."""
        sanitised = self._sanitise(message)
        with self._state_lock:
            self._transport_error = sanitised

    def _set_persistence_error(self, message: Any) -> None:
        """Store a sanitised storage error without discarding transport state."""
        sanitised = self._sanitise(message)
        with self._state_lock:
            self._persistence_error_cause = sanitised
            self._refresh_persistence_error_locked()

    def _clear_persistence_error(self) -> None:
        """Clear only the error state resolved by a successful flush."""
        with self._state_lock:
            self._persistence_error = ""
            self._persistence_error_cause = ""

    def _refresh_persistence_error_locked(self) -> None:
        if not self._persistence_error_cause:
            self._persistence_error = ""
            return
        self._persistence_error = self._persistence_error_cause
        if self._dropped_tick_count:
            self._persistence_error += f"; dropped {self._dropped_tick_count} oldest buffered ticks"

    def _drop_excess_buffer_locked(self) -> int:
        dropped = max(0, len(self._buffer) - self._max_buffer)
        if not dropped:
            return 0
        del self._buffer[:dropped]
        self._dropped_tick_count += dropped
        self._refresh_persistence_error_locked()
        return dropped

    def _sanitise(self, value: Any) -> str:
        """Return bounded exception context or a local recorder diagnostic."""
        return type(value).__name__ if isinstance(value, BaseException) else str(value)

    async def _flush_on_interval(self) -> None:
        """Persist buffered local observations on the configured cadence."""
        while True:
            with self._state_lock:
                stop_event = self._stop_event
                running = self._running
            if not running or stop_event is None:
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._flush_interval)
            except TimeoutError:
                self._flush()
                continue
            return

    def _flush(self, *, force: bool = False, raise_on_error: bool = False) -> bool:
        """Write buffered ticks to DuckDB.

        Clears the buffer ONLY after a successful insert. On failure the batch is
        retained for the next flush (so a transient lock/disk error cannot
        silently discard captured ticks), bounded by ``_max_buffer`` so a
        persistent failure cannot grow memory without limit.
        """
        with self._subscription_lock, self._flush_lock, self._state_lock:
            if not self._buffer:
                return False

            now = self._persistence_clock()
            if not force and now < self._next_persistence_retry_at:
                return False

            batch_size = len(self._buffer)
            try:
                if self._storage_lock is not None:
                    # This blocking lock is shared with the nightly maintenance job
                    # (scheduler thread). If that job is mid-CHECKPOINT the event loop
                    # briefly parks here — bounded and acceptable: maintenance runs
                    # off-market (00:30 IST) when tick flow is idle, and the insert is
                    # atomic so a retained batch is safe to retry.
                    with self._storage_lock:
                        self._storage.insert_ticks_batch(self._buffer)
                        self._run_post_flush_callback()
                else:
                    self._storage.insert_ticks_batch(self._buffer)
                    self._run_post_flush_callback()
            except Exception as exc:
                logger.error(
                    "Failed to flush %d ticks (retaining for retry): %s",
                    batch_size,
                    self._sanitise(exc),
                )
                self._persistence_error_cause = self._sanitise(f"Tick persistence failed: {exc}")
                dropped = self._drop_excess_buffer_locked()
                if dropped:
                    logger.warning(
                        "Tick buffer exceeded %d; dropped %d oldest ticks",
                        self._max_buffer,
                        dropped,
                    )
                self._refresh_persistence_error_locked()
                retry_delay = min(self._persistence_backoff, self._max_persistence_retry_delay)
                self._next_persistence_retry_at = now + retry_delay
                self._persistence_backoff = min(retry_delay * 2, self._max_persistence_retry_delay)
                if raise_on_error:
                    raise TickPersistenceError(self._persistence_error) from None
                return False

            logger.debug("Flushed %d ticks to DuckDB", batch_size)
            self._persisted_tick_count += batch_size
            self._buffer.clear()
            self._persistence_error = ""
            self._persistence_error_cause = ""
            self._next_persistence_retry_at = 0.0
            self._persistence_backoff = self._persistence_retry_delay
            return True

    def _run_post_flush_callback(self) -> None:
        """Publish restart state after storage commits without duplicating ticks.

        The callback runs inside the recorder ingestion barrier and shared
        storage lock. Its failure cannot roll back an already-committed DuckDB
        batch, so it is surfaced separately and retried after a later flush or
        during clean shutdown while the tick buffer is still cleared exactly
        once.
        """
        callback = self._post_flush_callback
        if callback is None:
            self._checkpoint_error = ""
            return
        try:
            callback()
        except Exception as exc:  # noqa: BLE001 - tick persistence already committed
            self._checkpoint_error = f"Order-flow checkpoint failed ({type(exc).__name__})"
            logger.error("Order-flow checkpoint failed after tick flush (%s)", type(exc).__name__)
        else:
            self._checkpoint_error = ""
