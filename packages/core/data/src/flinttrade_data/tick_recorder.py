"""WebSocket tick recorder — connects to OpenAlgo WS and stores ticks in DuckDB.

Supports all exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, DELTA.
MCX ticks arrive until 11:55 PM IST, DELTA ticks are 24/7.

Protocol:
  authenticate → API-key authentication
  subscribe    → LTP, quote, or depth market data
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import websockets
import websockets.exceptions

from ._tick_contracts import MAX_SOURCE_CLOCK_SKEW_SECONDS
from .storage import StorageManager

logger = logging.getLogger("flinttrade.data.tick_recorder")

_DEFAULT_WS_URL = f"ws://127.0.0.1:{os.getenv('OPENALGO_WS_PORT', '8765')}"

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

_RETRYABLE_HANDSHAKE_STATUSES = frozenset({500, 502, 503, 504})
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1
_MAX_FRAME_TIMESTAMP_TEXT_LENGTH = 64
_MIN_FRAME_TIMESTAMP_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
_MAX_FRAME_TIMESTAMP_EPOCH = datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()
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


def _optional_websocket_exception(name: str) -> type[BaseException] | None:
    """Resolve an exception class without requiring it in every supported release."""
    candidate = vars(websockets.exceptions).get(name)
    return candidate if isinstance(candidate, type) and issubclass(candidate, BaseException) else None


def _is_websocket_exception(error: BaseException, name: str) -> bool:
    exception_type = _optional_websocket_exception(name)
    return exception_type is not None and isinstance(error, exception_type)


def _handshake_status_code(error: BaseException) -> int | None:
    """Read new and legacy websockets handshake status shapes."""
    if _is_websocket_exception(error, "InvalidStatus"):
        status = getattr(getattr(error, "response", None), "status_code", None)
    elif _is_websocket_exception(error, "InvalidStatusCode") or type(error).__name__ == "InvalidStatusCode":
        status = getattr(error, "status_code", None)
    else:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _is_transient_connection_error(error: BaseException) -> bool:
    """Match only failures for which reconnecting with the same config can work."""
    if isinstance(error, (EOFError, OSError, TimeoutError)):
        return True
    if _is_websocket_exception(error, "ConnectionClosed"):
        return True
    if _is_websocket_exception(error, "InvalidMessage") and isinstance(
        error.__cause__ or error.__context__, EOFError
    ):
        return True
    return _handshake_status_code(error) in _RETRYABLE_HANDSHAKE_STATUSES


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
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


def _normalise_frame_timestamp(value: Any) -> datetime | None:
    """Parse one bounded OpenAlgo epoch or timezone-aware ISO timestamp."""
    if isinstance(value, str):
        text = value.strip()
        if not text or len(text) > _MAX_FRAME_TIMESTAMP_TEXT_LENGTH:
            return None
        epoch_timestamp = _normalise_epoch_timestamp(text)
        if epoch_timestamp is not None:
            return epoch_timestamp
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        parsed = parsed.astimezone(timezone.utc)
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
        return received_at, None

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
    """Extract best bid and ask from supported OpenAlgo depth shapes."""
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


class _ReconnectRequired(RuntimeError):
    """Internal marker for a recoverable recorder connection failure."""


class _ConnectionReconfigured(RuntimeError):
    """Internal marker for an obsolete connection attempt."""


class WatchlistCapacityError(ValueError):
    """Raised when a recorder watchlist exceeds its unique-identity limit."""


class TickPersistenceError(RuntimeError):
    """Raised when the recorder cannot persist its final buffered batch."""


class TickRecorder:
    """Connects to OpenAlgo WebSocket and records ticks to DuckDB.

    Usage::

        recorder = TickRecorder(storage=storage)
        recorder.add_symbols([
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NFO", "symbol": "NIFTY26MAR2524000CE"},
        ], mode="quote")
        await recorder.run()   # blocks, auto-reconnects
    """

    def __init__(
        self,
        storage: StorageManager,
        ws_url: str | None = None,
        batch_size: int = 100,
        flush_interval: float = 1.0,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
        storage_lock: Any | None = None,
        orderflow_aggregator: Any | None = None,
        api_key: str = "",
        ltp_sink: LtpSink | None = None,
        auth_response_timeout: float = 10.0,
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
        aggregator_capacity = getattr(orderflow_aggregator, "max_instruments", MAX_WATCHLIST_INSTRUMENTS)
        self._max_instruments = (
            min(aggregator_capacity, MAX_WATCHLIST_INSTRUMENTS)
            if type(aggregator_capacity) is int and aggregator_capacity > 0
            else MAX_WATCHLIST_INSTRUMENTS
        )
        self._ws_url = ws_url or _DEFAULT_WS_URL
        self._batch_size = batch_size
        self._flush_interval = normalised_flush_interval
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        # Serialises access to the (single) DuckDB connection this recorder shares
        # with the nightly maintenance job, which runs on the scheduler thread —
        # DuckDB connections are not safe for concurrent use. None = no sharing.
        self._storage_lock = storage_lock
        self._api_key = api_key
        self._redaction_keys = {api_key} if api_key else set()
        self._connection_revision = 0
        self._ltp_sink = ltp_sink
        self._ltp_sink_arity = _ltp_sink_positional_arity(ltp_sink) if ltp_sink is not None else 0
        self._auth_response_timeout = auth_response_timeout
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
        self._reconfigure_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active_ws: Any | None = None
        self._connected = False
        self._transport_error = ""
        self._persistence_error = ""
        self._persistence_error_cause = ""
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
        """Whether the recorder has an authenticated WebSocket connection."""
        return bool(self.status_snapshot()["connected"])

    @property
    def last_error(self) -> str:
        """Most recent sanitised persistence, connection, or control error."""
        return str(self.status_snapshot()["last_error"])

    def sanitise_error(self, value: Any) -> str:
        """Sanitise a diagnostic with every API key seen by this recorder."""
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
                self._source_timestamp_errors[latest_rejected_identity]
                if latest_rejected_identity is not None
                else ""
            )
            last_error = self._persistence_error or self._transport_error or source_timestamp_error
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
            raise WatchlistCapacityError(
                f"watchlist cannot exceed {self._max_instruments} unique instruments"
            )

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
    # WebSocket loop with auto-reconnect
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop — connect, subscribe, consume ticks. Auto-reconnects."""
        with self._state_lock:
            self._running = True
            self._stop_event = asyncio.Event()
            self._reconfigure_event = asyncio.Event()
            self._loop = asyncio.get_running_loop()
        delay = self._reconnect_delay
        flush_task = asyncio.create_task(self._flush_on_interval())

        try:
            while self._running:
                ws_url, api_key, revision = self._connection_snapshot()
                attempt_ws: Any | None = None
                try:
                    try:
                        async with websockets.connect(ws_url) as ws:
                            attempt_ws = ws
                            self._activate_socket(ws, revision)
                            logger.info("WebSocket connected: %s", self._sanitise(ws_url))
                            await self._authenticate(ws, api_key=api_key, revision=revision)
                            self._mark_connected(revision)
                            delay = self._reconnect_delay  # reset on successful authentication

                            await self._subscribe_all(ws)
                            await self._consume(ws)
                    finally:
                        with self._state_lock:
                            self._connected = False
                            if self._active_ws is attempt_ws:
                                self._active_ws = None

                except _ConnectionReconfigured:
                    delay = self._reconnect_delay
                    continue
                except _ReconnectRequired:
                    if not self._is_current_revision(revision):
                        delay = self._reconnect_delay
                        continue
                except Exception as exc:
                    if not self._is_current_revision(revision):
                        delay = self._reconnect_delay
                        continue
                    self._set_transport_error(exc)
                    if not _is_transient_connection_error(exc):
                        raise
                else:
                    if not self._running:
                        break
                    if not self._is_current_revision(revision):
                        delay = self._reconnect_delay
                        continue
                    self._set_transport_error("WebSocket stream ended")

                if not self._running:
                    break
                logger.warning(
                    "WebSocket disconnected: %s; reconnecting in %.0fs",
                    self.last_error,
                    delay,
                )
                await self._wait_for_reconnect_delay(delay, revision=revision)
                if not self._is_current_revision(revision):
                    delay = self._reconnect_delay
                    continue
                delay = min(delay * 2, self._max_reconnect_delay)
        finally:
            flush_task.cancel()
            await asyncio.gather(flush_task, return_exceptions=True)
            with self._state_lock:
                self._connected = False
                self._running = False
                self._stop_event = None
                self._reconfigure_event = None
                self._active_ws = None
                self._loop = None
            self._flush(force=True, raise_on_error=True)
            logger.info("TickRecorder stopped. Total ticks recorded: %d", self._tick_count)

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

    def reconfigure_connection(self, *, ws_url: str, api_key: str) -> bool:
        """Atomically replace connection credentials and retire any stale attempt."""
        if not isinstance(ws_url, str) or not ws_url.strip():
            raise ValueError("WebSocket URL must be a non-empty string")
        if not isinstance(api_key, str):
            raise TypeError("API key must be a string")

        new_ws_url = ws_url.strip()
        with self._state_lock:
            if self._ws_url == new_ws_url and self._api_key == api_key:
                return False
            if self._api_key:
                self._redaction_keys.add(self._api_key)
            if api_key:
                self._redaction_keys.add(api_key)
            self._ws_url = new_ws_url
            self._api_key = api_key
            self._connection_revision += 1
            self._transport_error = ""
            loop = self._loop
            ws = self._active_ws
            reconfigure_event = self._reconfigure_event

        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(self._notify_reconfiguration, ws, reconfigure_event)
            except RuntimeError:
                pass
        return True

    def _connection_snapshot(self) -> tuple[str, str, int]:
        with self._state_lock:
            return self._ws_url, self._api_key, self._connection_revision

    def _is_current_revision(self, revision: int) -> bool:
        with self._state_lock:
            return revision == self._connection_revision

    def _assert_current_revision(self, revision: int) -> None:
        if not self._is_current_revision(revision):
            raise _ConnectionReconfigured()

    def _activate_socket(self, ws: Any, revision: int) -> None:
        with self._state_lock:
            if revision != self._connection_revision:
                raise _ConnectionReconfigured()
            self._active_ws = ws

    def _mark_connected(self, revision: int) -> None:
        with self._state_lock:
            if revision != self._connection_revision:
                raise _ConnectionReconfigured()
            self._connected = True
            self._transport_error = ""

    def _notify_reconfiguration(self, ws: Any | None, reconfigure_event: asyncio.Event | None) -> None:
        if reconfigure_event is not None:
            reconfigure_event.set()
        if ws is not None:
            self._schedule_socket_close(ws)

    def request_reconnect(self) -> bool:
        """Schedule closure of the active socket from a non-recorder thread.

        Returns ``True`` only when a close callback was queued on the recorder
        event loop. The callback rechecks that the socket is still active before
        closing it, so callers can safely invoke this before or after ``run()``.
        """
        # Watchlist routes call this only after the signal-hub transaction has
        # committed. Pruning here preserves aggregator state when that earlier
        # transaction rolls the recorder watchlist back.
        with self._subscription_lock:
            retain_identities = getattr(self._orderflow, "retain_identities", None)
            if callable(retain_identities):
                retain_identities(set(self._allowed_identities))
        with self._state_lock:
            loop = self._loop
            ws = self._active_ws
        if loop is None or ws is None or not loop.is_running():
            return False
        try:
            loop.call_soon_threadsafe(self._schedule_socket_close, ws)
        except RuntimeError:
            return False
        return True

    def _schedule_socket_close(self, ws: Any) -> None:
        """Create the socket-close task on the recorder event loop."""
        with self._state_lock:
            if self._active_ws is not ws:
                return
        asyncio.create_task(self._close_socket_for_reconnect(ws))

    async def _close_socket_for_reconnect(self, ws: Any) -> None:
        """Close a requested socket without exposing recoverable close errors."""
        try:
            await ws.close()
        except Exception as exc:
            self._set_transport_error(f"WebSocket reconnect close failed: {exc}")
            if not _is_transient_connection_error(exc):
                raise

    # ------------------------------------------------------------------
    # Internal: subscribe / consume / flush
    # ------------------------------------------------------------------

    async def _authenticate(
        self,
        ws: Any,
        *,
        api_key: str | None = None,
        revision: int | None = None,
    ) -> None:
        """Authenticate and wait for the OpenAlgo control response."""
        if api_key is None or revision is None:
            _, snapshot_api_key, snapshot_revision = self._connection_snapshot()
            if api_key is None:
                api_key = snapshot_api_key
            if revision is None:
                revision = snapshot_revision

        self._assert_current_revision(revision)
        await ws.send(json.dumps({"action": "authenticate", "api_key": api_key}))
        self._assert_current_revision(revision)
        try:
            raw_response = await asyncio.wait_for(ws.recv(), timeout=self._auth_response_timeout)
            self._assert_current_revision(revision)
            response = json.loads(raw_response)
        except TimeoutError as exc:
            self._assert_current_revision(revision)
            self._set_transport_error("Authentication response timed out")
            raise _ReconnectRequired(self._transport_error) from exc
        except UnicodeDecodeError as exc:
            self._assert_current_revision(revision)
            self._set_transport_error("Invalid authentication response: invalid UTF-8")
            raise _ReconnectRequired(self._transport_error) from exc
        except (TypeError, json.JSONDecodeError) as exc:
            self._assert_current_revision(revision)
            self._set_transport_error("Invalid authentication response")
            raise _ReconnectRequired(self._transport_error) from exc

        if not isinstance(response, dict):
            self._set_transport_error("Invalid authentication response: expected JSON object")
            raise _ReconnectRequired(self._transport_error)

        status = str(response.get("status", "")).lower()
        if status not in {"authenticated", "success"}:
            self._set_transport_error(response.get("message") or response.get("error") or "Authentication failed")
            raise _ReconnectRequired(self._transport_error)

    async def _subscribe_all(self, ws: Any) -> None:
        """Send subscription messages for all configured watchlists."""
        subscriptions = self.get_watchlist()
        for mode, instruments in subscriptions.items():
            if not instruments:
                continue
            msg = json.dumps({"action": "subscribe", "symbols": instruments, "mode": _MODE_LABELS[mode]})
            await ws.send(msg)
            logger.info("Subscribed %s: %d instruments", self._sanitise(mode), len(instruments))

    async def _consume(self, ws: Any) -> None:
        """Read messages until disconnected or stopped."""
        async for raw in ws:
            if not self._running:
                break

            try:
                data = json.loads(raw)
            except UnicodeDecodeError:
                self._set_transport_error("Invalid WebSocket message: invalid UTF-8")
                logger.debug("Invalid UTF-8 message: %s", self._sanitise(raw)[:100])
                continue
            except (TypeError, json.JSONDecodeError):
                logger.debug("Non-JSON message: %s", self._sanitise(raw)[:100])
                continue

            if not isinstance(data, dict):
                self._set_transport_error("Invalid WebSocket message: expected JSON object")
                logger.debug("Ignored non-object JSON message: %s", self._sanitise(raw)[:100])
                continue

            if self._process_tick(data):
                raise _ReconnectRequired()

            if self.pending_tick_count >= self._batch_size:
                self._flush()

    def _process_tick(self, data: dict[str, Any]) -> bool:
        """Parse a WebSocket message into a tick tuple and buffer it."""
        handled, reconnect = self._handle_control_message(data)
        if handled:
            return reconnect

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
        received_at = datetime.now(timezone.utc)
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
            payload.get("volume"),
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
        volume: Any,
        source_timestamp: float,
    ) -> None:
        """Best-effort delivery of a valid LTP and its accepted source time."""
        if self._ltp_sink is None or ltp is None:
            return
        if ltp <= 0:
            return
        try:
            volume_value = max(0, int(volume)) if volume is not None else 0
        except (TypeError, ValueError, OverflowError):
            volume_value = 0
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

    def _handle_control_message(self, data: dict[str, Any]) -> tuple[bool, bool]:
        """Record OpenAlgo control errors without treating them as market ticks."""
        status = str(data.get("status", "")).lower()
        if str(data.get("type", "")).lower() == "subscribe" and status == "partial":
            subscriptions = data.get("subscriptions")
            if not isinstance(subscriptions, list):
                self._set_transport_error("Partial subscription failure: invalid subscriptions response")
                return True, True
            successes = [
                entry
                for entry in subscriptions
                if isinstance(entry, dict) and str(entry.get("status", "")).lower() in {"ok", "success", "subscribed"}
            ]
            failures = [
                entry
                for entry in subscriptions
                if isinstance(entry, dict) and str(entry.get("status", "")).lower() in {"error", "failed", "failure"}
            ]
            details = []
            for failure in failures:
                identity = ":".join(
                    part for part in (str(failure.get("exchange", "")), str(failure.get("symbol", ""))) if part
                )
                message = failure.get("message") or failure.get("error") or "subscription failed"
                details.append(f"{identity}: {message}" if identity else str(message))
            self._set_transport_error(
                "Partial subscription failure: " + "; ".join(details)
                if details
                else data.get("message") or "Partial subscription failure"
            )
            return True, not successes
        if str(data.get("type", "")).lower() == "error" or status in {"error", "failed", "failure"}:
            self._set_transport_error(data.get("message") or data.get("error") or "OpenAlgo control error")
            return True, True
        return False, False

    def _set_transport_error(self, message: Any) -> None:
        """Store a sanitised WebSocket or control-plane error."""
        sanitised = self._sanitise(message)
        with self._state_lock:
            self._transport_error = sanitised

    def _clear_transport_error(self) -> None:
        """Clear only the reconnectable transport/control error state."""
        with self._state_lock:
            self._transport_error = ""

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
        """Return display-safe text without changing recorder state."""
        text = str(value)
        with self._state_lock:
            redaction_keys = tuple(self._redaction_keys)
        for api_key in redaction_keys:
            text = text.replace(api_key, "[redacted]")
        return text

    async def _wait_for_reconnect_delay(self, delay: float, *, revision: int | None = None) -> None:
        """Wait for backoff completion or an explicit stop, whichever comes first."""
        with self._state_lock:
            stop_event = self._stop_event
            reconfigure_event = self._reconfigure_event
        if reconfigure_event is not None:
            reconfigure_event.clear()
        if revision is not None and not self._is_current_revision(revision):
            return
        if stop_event is None:
            await asyncio.sleep(delay)
            return

        delay_task = asyncio.create_task(asyncio.sleep(delay))
        stop_task = asyncio.create_task(stop_event.wait())
        reconfigure_task = asyncio.create_task(reconfigure_event.wait()) if reconfigure_event is not None else None
        tasks = tuple(task for task in (delay_task, stop_task, reconfigure_task) if task is not None)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _flush_on_interval(self) -> None:
        """Flush buffered tails independently of socket traffic and reconnects."""
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
        with self._flush_lock, self._state_lock:
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
                else:
                    self._storage.insert_ticks_batch(self._buffer)
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
