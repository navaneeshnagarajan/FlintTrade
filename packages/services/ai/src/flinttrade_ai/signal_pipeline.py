"""Canonical mixed-source signal hub and live rule engine.

Architecture:
    WebSocket ticks --> process_tick() --> streaming indicators --> SignalEvent
    scheduled bars --> SignalPipeline --> ingest_ml_cycle() -------> SignalEvent

Each instrument keeps independent streaming-indicator state. Rule and ML events
share one bounded, source-tagged feed with monotonic IDs for reliable SSE replay.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from .signal_models import SignalConfig, SignalEvent, normalise_instrument_identity, now_iso
from flinttrade_indicators.streaming import StreamingEMA, StreamingRSI

logger = logging.getLogger("flinttrade.ai.signal_pipeline")

# Maximum number of signals retained in the ring buffer per pipeline instance.
_MAX_SIGNALS = 100
_STREAM_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
_STREAM_SHUTDOWN_POLL_SECONDS = 0.05


def _normalise_stream_id(value: str | None) -> str:
    stream_id = uuid4().hex if value is None else value
    if not isinstance(stream_id, str) or _STREAM_ID_PATTERN.fullmatch(stream_id) is None:
        raise ValueError("stream_id must contain only letters, numbers, underscores, or hyphens")
    return stream_id


def _nonzero_side(value: float) -> Literal[-1, 1] | None:
    """Return the sign while treating exact zero as no side transition."""
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return None


def _normalise_event_number(value: object, *, field_name: str) -> float:
    """Convert one finite event number without leaking conversion errors."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field_name} must be a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


def _normalise_observation_timestamp(value: object | None) -> datetime | None:
    """Return one UTC observation timestamp without replacing invalid source time."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool):
        return None
    elif isinstance(value, int | float):
        try:
            epoch = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(epoch):
            return None
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _normalise_event(signal: SignalEvent) -> SignalEvent:
    """Build a validated event copy before assigning a hub-owned identifier."""
    if not isinstance(signal, SignalEvent):
        raise TypeError("signal must be a SignalEvent")
    event = deepcopy(signal)
    event.value = _normalise_event_number(event.value, field_name="value")
    event.threshold = _normalise_event_number(event.threshold, field_name="threshold")
    confidence = _normalise_event_number(event.confidence, field_name="confidence")
    event.confidence = max(0.0, min(1.0, confidence))
    if not isinstance(event.metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    event.metadata = deepcopy(dict(event.metadata))
    event.timestamp = event.timestamp or now_iso()
    event.method = event.method or event.indicator
    return event


class _InstrumentState:
    """Per-instrument streaming indicator state."""

    def __init__(self, config: SignalConfig) -> None:
        self.rsi: StreamingRSI | None = None
        self.ema_fast: StreamingEMA | None = None
        self.ema_slow: StreamingEMA | None = None
        self.macd_fast_ema: StreamingEMA | None = None
        self.macd_slow_ema: StreamingEMA | None = None
        self.macd_signal_ema: StreamingEMA | None = None
        self.rsi_zone: Literal["OVERSOLD", "NEUTRAL", "OVERBOUGHT"] | None = None
        self.prev_ema_fast: float | None = None
        self.prev_ema_slow: float | None = None
        self.prev_macd_hist: float | None = None
        self.ema_armed_direction: Literal["BUY", "SELL"] | None = None
        self.macd_armed_direction: Literal["BUY", "SELL"] | None = None
        self.ema_last_nonzero_side: Literal[-1, 1] | None = None
        self.macd_last_nonzero_side: Literal[-1, 1] | None = None
        self.ema_side_observed = False
        self.macd_side_observed = False
        self._init_indicators(config)

    def _init_indicators(self, config: SignalConfig) -> None:
        """Instantiate streaming indicators based on config."""
        for ind in config.indicators:
            name = str(ind.get("name", ""))
            params: dict[str, Any] = dict(ind.get("params", {}))  # type: ignore[arg-type]

            if name == "RSI":
                period = int(params.get("period", 14))
                self.rsi = StreamingRSI(period=period)

            elif name == "EMA_Cross":
                fast = int(params.get("fast", 9))
                slow = int(params.get("slow", 21))
                self.ema_fast = StreamingEMA(period=fast)
                self.ema_slow = StreamingEMA(period=slow)

            elif name == "MACD":
                fast = int(params.get("fast", 12))
                slow = int(params.get("slow", 26))
                sig = int(params.get("signal", 9))
                self.macd_fast_ema = StreamingEMA(period=fast)
                self.macd_slow_ema = StreamingEMA(period=slow)
                self.macd_signal_ema = StreamingEMA(period=sig)


class LiveSignalPipeline:
    """Processes real-time ticks through indicator + threshold layers to
    generate trading signals.

    Usage::

        pipeline = LiveSignalPipeline(
            instruments=["NSE_INDEX:NIFTY", "NSE_INDEX:BANKNIFTY"],
            indicators=[{"name": "RSI", "params": {"period": 14}}],
            thresholds={"rsi_oversold": 30, "rsi_overbought": 70},
        )
        signal = pipeline.process_tick("NSE_INDEX", "NIFTY", 22450.5, volume=1234567)
        if signal:
            print(signal.message)

    Args:
        instruments: List of ``EXCHANGE:SYMBOL`` instrument identities to track.
        indicators:  List of indicator configs, each ``{"name": ..., "params": {...}}``.
        thresholds:  Dict of threshold names to values.
    """

    def __init__(
        self,
        instruments: list[str] | None = None,
        indicators: list[dict[str, object]] | None = None,
        thresholds: dict[str, float] | None = None,
        *,
        stream_id: str | None = None,
    ) -> None:
        default_config = SignalConfig()
        candidate_config = SignalConfig(
            instruments=default_config.instruments if instruments is None else instruments,
            indicators=default_config.indicators if indicators is None else indicators,
            thresholds=default_config.thresholds if thresholds is None else thresholds,
        )
        self._config = candidate_config
        self._signals: deque[SignalEvent] = deque(maxlen=_MAX_SIGNALS)
        self._states: dict[tuple[str, str], _InstrumentState] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._sequence = 0
        self._rejected_out_of_order_tick_count = 0
        self._last_observation_at: dict[tuple[str, str], datetime] = {}
        self._stream_id = _normalise_stream_id(stream_id)
        self._instrument_observer: Callable[[list[str]], Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_tick(
        self,
        exchange: str,
        symbol: str,
        ltp: float,
        volume: int = 0,
        source_timestamp: float | str | datetime | None = None,
    ) -> SignalEvent | None:
        """Process one exchange-qualified tick with its immutable source time."""
        if not isinstance(exchange, str) or not isinstance(symbol, str):
            return None
        exchange = exchange.strip().upper()
        symbol = symbol.strip().upper()
        try:
            ltp = float(ltp)
        except (TypeError, ValueError, OverflowError):
            return None
        if not exchange or not symbol or not math.isfinite(ltp) or ltp <= 0:
            return None
        observation_at = _normalise_observation_timestamp(source_timestamp)
        if observation_at is None:
            return None
        with self._lock:
            if f"{exchange}:{symbol}" not in self._config.instruments:
                return None
            return self._process_tick_locked(exchange, symbol, ltp, volume, observation_at)

    def _process_tick_locked(
        self,
        exchange: str,
        symbol: str,
        ltp: float,
        volume: int = 0,
        observation_at: datetime | None = None,
    ) -> SignalEvent | None:
        """Process a single tick and return a Signal if a threshold is crossed.

        Only the *first* indicator to trigger wins per tick.  If no indicator
        crosses a threshold, ``None`` is returned.

        Args:
            exchange: Instrument exchange (e.g. ``"NSE_INDEX"``).
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            ltp:    Last traded price.
            volume: Tick volume (informational, not used by v1 indicators).

        Returns:
            A ``Signal`` instance if a threshold was crossed, else ``None``.
        """
        observation_at = observation_at or datetime.now(timezone.utc)
        identity = (exchange, symbol)
        previous_observation = self._last_observation_at.get(identity)
        if previous_observation is not None and observation_at < previous_observation:
            self._rejected_out_of_order_tick_count += 1
            return None
        self._last_observation_at[identity] = observation_at
        state = self._get_or_create_state(exchange, symbol)
        event_timestamp = observation_at.isoformat()
        thresholds = self._config.thresholds
        pending_signal: SignalEvent | None = None

        # --- RSI ---
        if state.rsi is not None:
            rsi_val = state.rsi.update(ltp)
            if rsi_val is not None:
                oversold = thresholds.get("rsi_oversold", 30.0)
                overbought = thresholds.get("rsi_overbought", 70.0)
                if rsi_val <= oversold:
                    zone: Literal["OVERSOLD", "NEUTRAL", "OVERBOUGHT"] = "OVERSOLD"
                elif rsi_val >= overbought:
                    zone = "OVERBOUGHT"
                else:
                    zone = "NEUTRAL"
                entered_zone = zone != state.rsi_zone
                state.rsi_zone = zone

                if entered_zone and zone == "OVERSOLD":
                    pending_signal = SignalEvent(
                        timestamp=event_timestamp,
                        symbol=symbol,
                        exchange=exchange,
                        signal_type="BUY",
                        indicator="RSI",
                        value=rsi_val,
                        threshold=oversold,
                        confidence=min(1.0, (oversold - rsi_val) / oversold + 0.5),
                        message=f"{symbol} RSI({state.rsi.period}) = {rsi_val:.1f} "
                        f"below oversold threshold {oversold:.0f}",
                    )
                elif entered_zone and zone == "OVERBOUGHT":
                    pending_signal = SignalEvent(
                        timestamp=event_timestamp,
                        symbol=symbol,
                        exchange=exchange,
                        signal_type="SELL",
                        indicator="RSI",
                        value=rsi_val,
                        threshold=overbought,
                        confidence=min(1.0, (rsi_val - overbought) / (100 - overbought) + 0.5),
                        message=f"{symbol} RSI({state.rsi.period}) = {rsi_val:.1f} "
                        f"above overbought threshold {overbought:.0f}",
                    )

        # --- EMA Crossover ---
        if state.ema_fast is not None and state.ema_slow is not None:
            fast_val = state.ema_fast.update(ltp)
            slow_val = state.ema_slow.update(ltp)

            if fast_val is not None and slow_val is not None:
                spread_pct = (fast_val - slow_val) / slow_val * 100.0 if slow_val else 0.0
                minimum = thresholds.get("ema_cross_min_pct", 0.0)
                bullish_threshold = minimum
                bearish_threshold = -minimum

                side = _nonzero_side(spread_pct)
                if not state.ema_side_observed:
                    state.ema_side_observed = True
                    state.ema_last_nonzero_side = side
                elif side is not None and side != state.ema_last_nonzero_side:
                    state.ema_last_nonzero_side = side
                    state.ema_armed_direction = "BUY" if side > 0 else "SELL"

                if state.ema_armed_direction == "BUY" and spread_pct > bullish_threshold:
                    state.ema_armed_direction = None
                    sig = SignalEvent(
                        timestamp=event_timestamp,
                        symbol=symbol,
                        exchange=exchange,
                        signal_type="BUY",
                        indicator="EMA_Cross",
                        value=spread_pct,
                        threshold=bullish_threshold,
                        confidence=0.65,
                        message=f"{symbol} EMA({state.ema_fast.period}) crossed above EMA({state.ema_slow.period})",
                    )
                    state.prev_ema_fast = fast_val
                    state.prev_ema_slow = slow_val
                    if pending_signal is None:
                        pending_signal = sig

                elif state.ema_armed_direction == "SELL" and spread_pct < bearish_threshold:
                    state.ema_armed_direction = None
                    sig = SignalEvent(
                        timestamp=event_timestamp,
                        symbol=symbol,
                        exchange=exchange,
                        signal_type="SELL",
                        indicator="EMA_Cross",
                        value=spread_pct,
                        threshold=bearish_threshold,
                        confidence=0.65,
                        message=f"{symbol} EMA({state.ema_fast.period}) crossed below EMA({state.ema_slow.period})",
                    )
                    state.prev_ema_fast = fast_val
                    state.prev_ema_slow = slow_val
                    if pending_signal is None:
                        pending_signal = sig

                state.prev_ema_fast = fast_val
                state.prev_ema_slow = slow_val

        # --- MACD ---
        if state.macd_fast_ema is not None and state.macd_slow_ema is not None and state.macd_signal_ema is not None:
            macd_fast_val = state.macd_fast_ema.update(ltp)
            macd_slow_val = state.macd_slow_ema.update(ltp)

            if macd_fast_val is not None and macd_slow_val is not None:
                macd_line = macd_fast_val - macd_slow_val
                signal_line = state.macd_signal_ema.update(macd_line)

                if signal_line is not None:
                    macd_hist = macd_line - signal_line
                    minimum = thresholds.get("macd_crossover_min", 0.0)
                    bullish_threshold = minimum
                    bearish_threshold = -minimum

                    side = _nonzero_side(macd_hist)
                    if not state.macd_side_observed:
                        state.macd_side_observed = True
                        state.macd_last_nonzero_side = side
                    elif side is not None and side != state.macd_last_nonzero_side:
                        state.macd_last_nonzero_side = side
                        state.macd_armed_direction = "BUY" if side > 0 else "SELL"

                    if state.macd_armed_direction == "BUY" and macd_hist > bullish_threshold:
                        state.macd_armed_direction = None
                        sig = SignalEvent(
                            timestamp=event_timestamp,
                            symbol=symbol,
                            exchange=exchange,
                            signal_type="BUY",
                            indicator="MACD",
                            value=macd_hist,
                            threshold=bullish_threshold,
                            confidence=0.60,
                            message=f"{symbol} MACD histogram turned positive ({macd_hist:.2f})",
                        )
                        state.prev_macd_hist = macd_hist
                        if pending_signal is None:
                            pending_signal = sig

                    elif state.macd_armed_direction == "SELL" and macd_hist < bearish_threshold:
                        state.macd_armed_direction = None
                        sig = SignalEvent(
                            timestamp=event_timestamp,
                            symbol=symbol,
                            exchange=exchange,
                            signal_type="SELL",
                            indicator="MACD",
                            value=macd_hist,
                            threshold=bearish_threshold,
                            confidence=0.60,
                            message=f"{symbol} MACD histogram turned negative ({macd_hist:.2f})",
                        )
                        state.prev_macd_hist = macd_hist
                        if pending_signal is None:
                            pending_signal = sig

                    state.prev_macd_hist = macd_hist

        return self._publish_locked(pending_signal) if pending_signal is not None else None

    def publish_signal(self, signal: SignalEvent) -> SignalEvent:
        """Publish one event with a hub-owned monotonic identifier."""
        with self._lock:
            return self._publish_locked(signal)

    def _publish_locked(self, signal: SignalEvent) -> SignalEvent:
        """Validate and publish an isolated event while the hub lock is held."""
        published = _normalise_event(signal)
        next_event_id = self._sequence + 1
        published.event_id = next_event_id
        self._signals.appendleft(deepcopy(published))
        self._sequence = next_event_id
        self._condition.notify_all()
        return published

    @property
    def signals(self) -> deque[SignalEvent]:
        """Return an isolated snapshot of the retained event ring."""
        with self._lock:
            return deque((deepcopy(signal) for signal in self._signals), maxlen=_MAX_SIGNALS)

    @property
    def latest_event_id(self) -> int:
        """Return the newest hub event ID without exposing mutable state."""
        with self._lock:
            return self._sequence

    @property
    def rejected_out_of_order_tick_count(self) -> int:
        """Return the number of source-time regressions rejected by this hub."""
        with self._lock:
            return self._rejected_out_of_order_tick_count

    @property
    def stream_id(self) -> str:
        """Return the opaque identity for this process's SSE event sequence."""
        return self._stream_id

    def sse_event_id(self, event_id: int) -> str:
        """Qualify a process-local sequence number for the SSE ``id`` field."""
        return f"{self._stream_id}:{event_id}"

    def get_signals_after(self, event_id: int) -> list[SignalEvent]:
        """Return retained events newer than ``event_id`` in emission order."""
        with self._lock:
            return sorted(
                (deepcopy(signal) for signal in self._signals if signal.event_id > event_id),
                key=lambda signal: signal.event_id,
            )

    def wait_for_signals_after(
        self,
        event_id: int,
        timeout: float,
    ) -> list[SignalEvent]:
        """Wait for a retained newer event, then return every matching replay event."""
        _, retained = self.wait_for_replay_snapshot_after(event_id, timeout)
        return [signal for signal in retained if signal.event_id > event_id]

    def wait_for_replay_snapshot_after(
        self,
        event_id: int,
        timeout: float,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[int, list[SignalEvent]]:
        """Wait for newer data and atomically snapshot the retained replay window."""
        with self._condition:
            deadline = time.monotonic() + max(0.0, timeout)
            while not any(signal.event_id > event_id for signal in self._signals):
                if stop_requested is not None and stop_requested():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                wait_for = remaining
                if stop_requested is not None:
                    wait_for = min(wait_for, _STREAM_SHUTDOWN_POLL_SECONDS)
                self._condition.wait(timeout=wait_for)
            retained = sorted(
                (deepcopy(signal) for signal in self._signals),
                key=lambda signal: signal.event_id,
            )
            return self._sequence, retained

    def get_replay_snapshot(self) -> tuple[int, list[SignalEvent]]:
        """Return one atomic, isolated snapshot of the retained replay window."""
        with self._lock:
            retained = sorted(
                (deepcopy(signal) for signal in self._signals),
                key=lambda signal: signal.event_id,
            )
            return self._sequence, retained

    def ingest_ml_cycle(
        self,
        results: Mapping[str, Mapping[str, Any]],
    ) -> list[SignalEvent]:
        """Convert one scheduled ML cycle into canonical source-tagged events."""
        published: list[SignalEvent] = []
        with self._lock:
            allowed_instruments = set(self._config.instruments)
            for key, info in results.items():
                raw_symbol = str(info.get("symbol") or key.rsplit(":", 1)[-1])
                raw_exchange = str(info.get("exchange") or key.partition(":")[0])
                try:
                    identity = normalise_instrument_identity(f"{raw_exchange}:{raw_symbol}")
                except ValueError:
                    logger.warning("Invalid scheduled signal identity %r; event skipped", key)
                    continue
                if identity not in allowed_instruments:
                    logger.debug("Unconfigured scheduled signal identity %s; event skipped", identity)
                    continue
                exchange, symbol = identity.split(":", 1)

                signal_type = str(info.get("signal", "HOLD")).upper()
                if signal_type == "NEUTRAL":
                    signal_type = "HOLD"
                if signal_type not in {"BUY", "SELL", "HOLD", "ALERT"}:
                    logger.warning("Unknown ML signal type %r for %s; emitting ALERT", signal_type, key)
                    signal_type = "ALERT"

                method = str(info.get("method", "ml_model"))
                if method.startswith("ml_model"):
                    source = "ml"
                    indicator = "LightGBM"
                elif method.startswith("ema_crossover_fallback"):
                    source = "fallback"
                    indicator = "EMA_Cross"
                else:
                    logger.warning("Unknown scheduled signal method %r for %s; event skipped", method, key)
                    continue
                ltp = _as_float(info.get("ltp"))
                turbulence = _as_float(info.get("turbulence_score"))
                confidence = _as_float(info.get("confidence"))
                method_label = method.replace("_", " ")
                message = f"{symbol} scheduled {method_label} signal: {signal_type}"

                published.append(
                    self._publish_locked(
                        SignalEvent(
                            timestamp=str(info.get("timestamp") or now_iso()),
                            symbol=symbol,
                            exchange=exchange,
                            signal_type=signal_type,
                            source=source,
                            method=method,
                            indicator=indicator,
                            value=ltp,
                            confidence=confidence,
                            message=message,
                            metadata={
                                "ltp": ltp,
                                "turbulence_score": turbulence,
                            },
                        )
                    )
                )
        return published

    def get_recent_signals(self, limit: int = 20) -> list[SignalEvent]:
        """Return recent signals, newest first.

        Args:
            limit: Maximum number of signals to return.

        Returns:
            List of ``Signal`` instances ordered newest first.
        """
        with self._lock:
            return [deepcopy(signal) for signal in list(self._signals)[:limit]]

    def update_config(
        self,
        instruments: list[str] | None = None,
        indicators: list[dict[str, object]] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> SignalConfig:
        """Update pipeline configuration and reset indicator state.

        Only provided fields are updated; ``None`` leaves the existing value.

        Returns:
            The updated ``SignalConfig``.
        """
        with self._lock:
            merged_thresholds = (
                self._config.thresholds
                if thresholds is None
                else {**self._config.thresholds, **thresholds}
            )
            candidate_config = SignalConfig(
                instruments=self._config.instruments if instruments is None else instruments,
                indicators=self._config.indicators if indicators is None else indicators,
                thresholds=merged_thresholds,
            )
            state_config_changed = (
                set(candidate_config.instruments) != set(self._config.instruments)
                or candidate_config.indicators != self._config.indicators
                or candidate_config.thresholds != self._config.thresholds
            )
            if state_config_changed:
                instruments_changed = set(candidate_config.instruments) != set(self._config.instruments)
                if instruments_changed and self._instrument_observer is not None:
                    self._instrument_observer(list(candidate_config.instruments))
                self._config = candidate_config
                # Indicator state belongs to the old configuration; shared event
                # history and its monotonic IDs remain valid across the update.
                self._states.clear()
            else:
                candidate_config = self._config
            snapshot = SignalConfig.from_dict(candidate_config.to_dict())
        logger.info("Signal pipeline config updated: %s", snapshot.to_dict())
        return snapshot

    def set_instrument_observer(
        self,
        observer: Callable[[list[str]], Any] | None,
    ) -> None:
        """Bind the scheduled-roster observer and synchronise it immediately."""
        with self._lock:
            if observer is not None:
                observer(list(self._config.instruments))
            self._instrument_observer = observer

    def get_config(self) -> SignalConfig:
        """Return an isolated, validated snapshot of the current configuration."""
        with self._lock:
            return SignalConfig.from_dict(self._config.to_dict())

    @property
    def config(self) -> SignalConfig:
        """Return a compatibility snapshot without exposing live mutable state."""
        return self.get_config()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_state(self, exchange: str, symbol: str) -> _InstrumentState:
        """Lazily create per-instrument indicator state."""
        identity = (exchange, symbol)
        if identity not in self._states:
            self._states[identity] = _InstrumentState(self._config)
        return self._states[identity]


def _as_float(value: Any) -> float:
    """Convert external numeric metadata without allowing NaN or infinities."""
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if result == result and result not in {float("inf"), float("-inf")} else 0.0
