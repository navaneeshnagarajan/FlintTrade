"""Live market signals pipeline — processes real-time ticks through streaming
indicators and emits rule-based trading signals when thresholds are crossed.

Architecture:
    WebSocket ticks --> process_tick() --> streaming indicators --> threshold check --> Signal

This is the v1 rule-based pipeline.  ML scoring will be layered on top in a
future iteration.  Each instrument maintains its own set of streaming indicator
instances so that warm-up state is independent.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from .signal_models import Signal, SignalConfig, now_iso
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
        self.signals: deque[Signal] = deque(maxlen=_MAX_SIGNALS)
        self._states: dict[str, _InstrumentState] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_tick(
        self,
        symbol: str,
        ltp: float,
        volume: int = 0,
    ) -> Signal | None:
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
                    sig = Signal(
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
                    self.signals.appendleft(sig)
                    return sig

                if rsi_val >= overbought:
                    sig = Signal(
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
                    self.signals.appendleft(sig)
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
                        sig = Signal(
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
                        self.signals.appendleft(sig)
                        state.prev_ema_fast = fast_val
                        state.prev_ema_slow = slow_val
                        return sig

                    # Bearish crossover: fast crosses below slow
                    if prev_fast >= prev_slow and fast_val < slow_val:
                        sig = Signal(
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
                        self.signals.appendleft(sig)
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
                            sig = Signal(
                                timestamp=now_iso(),
                                symbol=symbol,
                                signal_type="BUY",
                                indicator="MACD",
                                value=macd_hist,
                                threshold=0.0,
                                confidence=0.60,
                                message=f"{symbol} MACD histogram turned positive ({macd_hist:.2f})",
                            )
                            self.signals.appendleft(sig)
                            state.prev_macd_hist = macd_hist
                            return sig

                        # Bearish: histogram crosses from positive to negative
                        if prev_hist >= 0 and macd_hist < 0:
                            sig = Signal(
                                timestamp=now_iso(),
                                symbol=symbol,
                                signal_type="SELL",
                                indicator="MACD",
                                value=macd_hist,
                                threshold=0.0,
                                confidence=0.60,
                                message=f"{symbol} MACD histogram turned negative ({macd_hist:.2f})",
                            )
                            self.signals.appendleft(sig)
                            state.prev_macd_hist = macd_hist
                            return sig

                    state.prev_macd_hist = macd_hist

        return None

    def get_recent_signals(self, limit: int = 20) -> list[Signal]:
        """Return recent signals, newest first.

        Args:
            limit: Maximum number of signals to return.

        Returns:
            List of ``Signal`` instances ordered newest first.
        """
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
        if instruments is not None:
            self.config.instruments = instruments
        if indicators is not None:
            self.config.indicators = indicators
        if thresholds is not None:
            self.config.thresholds = thresholds
        # Reset per-instrument state so indicators re-initialise with new params
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
