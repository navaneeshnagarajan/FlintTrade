"""Canonical mixed-source signal hub and live rule engine.

Architecture:
    WebSocket ticks --> process_tick() --> streaming indicators --> SignalEvent
    scheduled bars --> SignalPipeline --> ingest_ml_cycle() -------> SignalEvent

Each instrument keeps independent streaming-indicator state. Rule and ML events
share one bounded, source-tagged feed with monotonic IDs for reliable SSE replay.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from collections import deque
from typing import Any

from .signal_models import SignalConfig, SignalEvent, now_iso
from flinttrade_indicators.streaming import StreamingEMA, StreamingRSI

logger = logging.getLogger("flinttrade.ai.signal_pipeline")

# Maximum number of signals retained in the ring buffer per pipeline instance.
_MAX_SIGNALS = 100


class _InstrumentState:
    """Per-instrument streaming indicator state."""

    def __init__(self, config: SignalConfig) -> None:
        self.rsi: StreamingRSI | None = None
        self.ema_fast: StreamingEMA | None = None
        self.ema_slow: StreamingEMA | None = None
        self.macd_fast_ema: StreamingEMA | None = None
        self.macd_slow_ema: StreamingEMA | None = None
        self.macd_signal_ema: StreamingEMA | None = None
        self.prev_ema_fast: float | None = None
        self.prev_ema_slow: float | None = None
        self.prev_macd_hist: float | None = None
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
            instruments=["NIFTY", "BANKNIFTY"],
            indicators=[{"name": "RSI", "params": {"period": 14}}],
            thresholds={"rsi_oversold": 30, "rsi_overbought": 70},
        )
        signal = pipeline.process_tick("NIFTY", 22450.5, volume=1234567)
        if signal:
            print(signal.message)

    Args:
        instruments: List of instrument symbols to track.
        indicators:  List of indicator configs, each ``{"name": ..., "params": {...}}``.
        thresholds:  Dict of threshold names to values.
    """

    def __init__(
        self,
        instruments: list[str] | None = None,
        indicators: list[dict[str, object]] | None = None,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        self.config = SignalConfig(
            instruments=instruments or SignalConfig().instruments,
            indicators=indicators or SignalConfig().indicators,
            thresholds=thresholds or SignalConfig().thresholds,
        )
        self.signals: deque[SignalEvent] = deque(maxlen=_MAX_SIGNALS)
        self._states: dict[str, _InstrumentState] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._sequence = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_tick(
        self,
        symbol: str,
        ltp: float,
        volume: int = 0,
    ) -> SignalEvent | None:
        """Process one tick under the same lock used by reconfiguration."""
        with self._lock:
            return self._process_tick_locked(symbol, ltp, volume)

    def _process_tick_locked(
        self,
        symbol: str,
        ltp: float,
        volume: int = 0,
    ) -> SignalEvent | None:
        """Process a single tick and return a Signal if a threshold is crossed.

        Only the *first* indicator to trigger wins per tick.  If no indicator
        crosses a threshold, ``None`` is returned.

        Args:
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            ltp:    Last traded price.
            volume: Tick volume (informational, not used by v1 indicators).

        Returns:
            A ``Signal`` instance if a threshold was crossed, else ``None``.
        """
        state = self._get_or_create_state(symbol)
        thresholds = self.config.thresholds

        # --- RSI ---
        if state.rsi is not None:
            rsi_val = state.rsi.update(ltp)
            if rsi_val is not None:
                oversold = thresholds.get("rsi_oversold", 30.0)
                overbought = thresholds.get("rsi_overbought", 70.0)

                if rsi_val <= oversold:
                    sig = SignalEvent(
                        timestamp=now_iso(),
                        symbol=symbol,
                        signal_type="BUY",
                        indicator="RSI",
                        value=rsi_val,
                        threshold=oversold,
                        confidence=min(1.0, (oversold - rsi_val) / oversold + 0.5),
                        message=f"{symbol} RSI({state.rsi.period}) = {rsi_val:.1f} "
                                f"below oversold threshold {oversold:.0f}",
                    )
                    self._publish_locked(sig)
                    return sig

                if rsi_val >= overbought:
                    sig = SignalEvent(
                        timestamp=now_iso(),
                        symbol=symbol,
                        signal_type="SELL",
                        indicator="RSI",
                        value=rsi_val,
                        threshold=overbought,
                        confidence=min(1.0, (rsi_val - overbought) / (100 - overbought) + 0.5),
                        message=f"{symbol} RSI({state.rsi.period}) = {rsi_val:.1f} "
                                f"above overbought threshold {overbought:.0f}",
                    )
                    self._publish_locked(sig)
                    return sig

        # --- EMA Crossover ---
        if state.ema_fast is not None and state.ema_slow is not None:
            fast_val = state.ema_fast.update(ltp)
            slow_val = state.ema_slow.update(ltp)

            if fast_val is not None and slow_val is not None:
                prev_fast = state.prev_ema_fast
                prev_slow = state.prev_ema_slow

                if prev_fast is not None and prev_slow is not None:
                    # Bullish crossover: fast crosses above slow
                    if prev_fast <= prev_slow and fast_val > slow_val:
                        sig = SignalEvent(
                            timestamp=now_iso(),
                            symbol=symbol,
                            signal_type="BUY",
                            indicator="EMA_Cross",
                            value=fast_val - slow_val,
                            threshold=0.0,
                            confidence=0.65,
                            message=f"{symbol} EMA({state.ema_fast.period}) "
                                    f"crossed above EMA({state.ema_slow.period})",
                        )
                        self._publish_locked(sig)
                        state.prev_ema_fast = fast_val
                        state.prev_ema_slow = slow_val
                        return sig

                    # Bearish crossover: fast crosses below slow
                    if prev_fast >= prev_slow and fast_val < slow_val:
                        sig = SignalEvent(
                            timestamp=now_iso(),
                            symbol=symbol,
                            signal_type="SELL",
                            indicator="EMA_Cross",
                            value=fast_val - slow_val,
                            threshold=0.0,
                            confidence=0.65,
                            message=f"{symbol} EMA({state.ema_fast.period}) "
                                    f"crossed below EMA({state.ema_slow.period})",
                        )
                        self._publish_locked(sig)
                        state.prev_ema_fast = fast_val
                        state.prev_ema_slow = slow_val
                        return sig

                state.prev_ema_fast = fast_val
                state.prev_ema_slow = slow_val

        # --- MACD ---
        if (
            state.macd_fast_ema is not None
            and state.macd_slow_ema is not None
            and state.macd_signal_ema is not None
        ):
            macd_fast_val = state.macd_fast_ema.update(ltp)
            macd_slow_val = state.macd_slow_ema.update(ltp)

            if macd_fast_val is not None and macd_slow_val is not None:
                macd_line = macd_fast_val - macd_slow_val
                signal_line = state.macd_signal_ema.update(macd_line)

                if signal_line is not None:
                    macd_hist = macd_line - signal_line
                    prev_hist = state.prev_macd_hist

                    if prev_hist is not None:
                        # Bullish: histogram crosses from negative to positive
                        if prev_hist <= 0 and macd_hist > 0:
                            sig = SignalEvent(
                                timestamp=now_iso(),
                                symbol=symbol,
                                signal_type="BUY",
                                indicator="MACD",
                                value=macd_hist,
                                threshold=0.0,
                                confidence=0.60,
                                message=f"{symbol} MACD histogram turned positive ({macd_hist:.2f})",
                            )
                            self._publish_locked(sig)
                            state.prev_macd_hist = macd_hist
                            return sig

                        # Bearish: histogram crosses from positive to negative
                        if prev_hist >= 0 and macd_hist < 0:
                            sig = SignalEvent(
                                timestamp=now_iso(),
                                symbol=symbol,
                                signal_type="SELL",
                                indicator="MACD",
                                value=macd_hist,
                                threshold=0.0,
                                confidence=0.60,
                                message=f"{symbol} MACD histogram turned negative ({macd_hist:.2f})",
                            )
                            self._publish_locked(sig)
                            state.prev_macd_hist = macd_hist
                            return sig

                    state.prev_macd_hist = macd_hist

        return None

    def publish_signal(self, signal: SignalEvent) -> SignalEvent:
        """Publish one event with a hub-owned monotonic identifier."""
        with self._lock:
            return self._publish_locked(signal)

    def _publish_locked(self, signal: SignalEvent) -> SignalEvent:
        """Publish while the hub lock is held and wake SSE subscribers."""
        self._sequence += 1
        signal.event_id = self._sequence
        signal.timestamp = signal.timestamp or now_iso()
        signal.confidence = max(0.0, min(1.0, float(signal.confidence)))
        if not signal.method:
            signal.method = signal.indicator
        self.signals.appendleft(signal)
        self._condition.notify_all()
        return signal

    @property
    def latest_event_id(self) -> int:
        """Return the newest hub event ID without exposing mutable state."""
        with self._lock:
            return self._sequence

    def get_signals_after(self, event_id: int) -> list[SignalEvent]:
        """Return retained events newer than ``event_id`` in emission order."""
        with self._lock:
            return sorted(
                (signal for signal in self.signals if signal.event_id > event_id),
                key=lambda signal: signal.event_id,
            )

    def wait_for_signals_after(
        self,
        event_id: int,
        timeout: float,
    ) -> list[SignalEvent]:
        """Wait for a newer event, then return every retained event after it."""
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > event_id, timeout=timeout)
            return sorted(
                (signal for signal in self.signals if signal.event_id > event_id),
                key=lambda signal: signal.event_id,
            )

    def ingest_ml_cycle(
        self,
        results: Mapping[str, Mapping[str, Any]],
    ) -> list[SignalEvent]:
        """Convert one scheduled ML cycle into canonical source-tagged events."""
        published: list[SignalEvent] = []
        for key, info in results.items():
            symbol = str(info.get("symbol") or key.rsplit(":", 1)[-1])
            exchange = str(info.get("exchange") or key.partition(":")[0])
            signal_type = str(info.get("signal", "HOLD")).upper()
            if signal_type == "NEUTRAL":
                signal_type = "HOLD"
            if signal_type not in {"BUY", "SELL", "HOLD", "ALERT"}:
                logger.warning("Unknown ML signal type %r for %s; emitting ALERT", signal_type, key)
                signal_type = "ALERT"

            method = str(info.get("method", "ml_model"))
            indicator = "LightGBM" if method.startswith("ml_model") else "EMA_Cross"
            ltp = _as_float(info.get("ltp"))
            turbulence = _as_float(info.get("turbulence_score"))
            confidence = _as_float(info.get("confidence"))
            method_label = method.replace("_", " ")
            message = f"{symbol} scheduled {method_label} signal: {signal_type}"

            published.append(
                self.publish_signal(
                    SignalEvent(
                        timestamp=str(info.get("timestamp") or now_iso()),
                        symbol=symbol,
                        exchange=exchange,
                        signal_type=signal_type,
                        source="ml",
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
            return list(self.signals)[:limit]

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
            if instruments is not None:
                self.config.instruments = instruments
            if indicators is not None:
                self.config.indicators = indicators
            if thresholds is not None:
                self.config.thresholds = thresholds
            # Reset per-instrument state so indicators re-initialise with new params.
            # The sequence remains monotonic so SSE reconnect cursors cannot wedge.
            self._states.clear()
            self.signals.clear()
        logger.info("Signal pipeline config updated: %s", self.config.to_dict())
        return self.config

    def get_config(self) -> SignalConfig:
        """Return the current pipeline configuration."""
        return self.config

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create_state(self, symbol: str) -> _InstrumentState:
        """Lazily create per-instrument indicator state."""
        if symbol not in self._states:
            self._states[symbol] = _InstrumentState(self.config)
        return self._states[symbol]


def _as_float(value: Any) -> float:
    """Convert external numeric metadata without allowing NaN or infinities."""
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return result if result == result and result not in {float("inf"), float("-inf")} else 0.0
