"""Streaming (online) indicator classes for real-time tick processing.

Each class processes one tick at a time in O(1) after warm-up.  No arrays are
retained in memory beyond what is needed for the algorithm.

All classes:
- Accept float scalars via ``update()``
- Return float | None (None during warm-up)
- Expose a ``value`` property reflecting the latest computed value
- Are not thread-safe — synchronise externally if needed
"""

from __future__ import annotations

from collections import deque


class StreamingEMA:
    """Online Exponential Moving Average.

    Seeded with a simple arithmetic mean over the first ``period`` prices.
    After seeding, each tick applies k = 2 / (period + 1) as the smoothing
    multiplier: EMA = price * k + prev_EMA * (1 - k).

    Attributes:
        period: EMA window used for seeding and the multiplier.

    Args:
        period: Must be >= 1.

    Raises:
        ValueError: If period < 1.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"StreamingEMA period must be >= 1, got {period}")
        self.period = period
        self._k: float = 2.0 / (period + 1.0)
        self._1mk: float = 1.0 - self._k
        self._seed_buf: list[float] = []
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        """Feed one new price tick.

        Args:
            price: Latest price.

        Returns:
            Current EMA, or None if still warming up.
        """
        if self._value is None:
            self._seed_buf.append(price)
            if len(self._seed_buf) >= self.period:
                self._value = sum(self._seed_buf) / len(self._seed_buf)
                self._seed_buf = []  # free seed buffer
        else:
            self._value = price * self._k + self._value * self._1mk
        return self._value

    @property
    def value(self) -> float | None:
        """Latest EMA value, or None during warm-up."""
        return self._value

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._seed_buf = []
        self._value = None


class StreamingSMA:
    """Online Simple Moving Average using a sliding window and running sum.

    Memory usage is O(period) for the deque.  Per-tick cost is O(1).

    Args:
        period: Window length (must be >= 1).

    Raises:
        ValueError: If period < 1.
    """

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"StreamingSMA period must be >= 1, got {period}")
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum: float = 0.0

    def update(self, price: float) -> float | None:
        """Feed one new price tick.

        Args:
            price: Latest price.

        Returns:
            Current SMA, or None if the window is not yet full.
        """
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]  # will be evicted by maxlen
        self._buf.append(price)
        self._sum += price
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    @property
    def value(self) -> float | None:
        """Latest SMA, or None during warm-up."""
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._buf.clear()
        self._sum = 0.0


class StreamingRSI:
    """Online RSI using Wilder (RMA) smoothing.

    Warm-up phase collects ``period + 1`` prices to compute the first ``period``
    price changes, seeds avg_gain and avg_loss with their simple means, and
    emits the first RSI.  Subsequent ticks use Wilder smoothing — O(1) per tick.

    Args:
        period: RSI period (default 14, must be >= 1).

    Raises:
        ValueError: If period < 1.
    """

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"StreamingRSI period must be >= 1, got {period}")
        self.period = period
        self._seed_prices: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._prev_price: float | None = None
        self._value: float | None = None

    def _rsi_from_avgs(self, avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0.0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def update(self, price: float) -> float | None:
        """Feed one new price tick.

        Args:
            price: Latest price.

        Returns:
            Current RSI (0–100), or None during warm-up.
        """
        if self._avg_gain is None:
            # Still in seed phase
            self._seed_prices.append(price)
            if len(self._seed_prices) == self.period + 1:
                gains: list[float] = []
                losses: list[float] = []
                for i in range(1, len(self._seed_prices)):
                    delta = self._seed_prices[i] - self._seed_prices[i - 1]
                    gains.append(max(delta, 0.0))
                    losses.append(max(-delta, 0.0))
                self._avg_gain = sum(gains) / self.period
                self._avg_loss = sum(losses) / self.period
                self._prev_price = self._seed_prices[-1]
                self._value = self._rsi_from_avgs(self._avg_gain, self._avg_loss)
                self._seed_prices = []  # free
        else:
            assert self._avg_gain is not None
            assert self._avg_loss is not None
            assert self._prev_price is not None
            delta = price - self._prev_price
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
            self._prev_price = price
            self._value = self._rsi_from_avgs(self._avg_gain, self._avg_loss)
        return self._value

    @property
    def value(self) -> float | None:
        """Latest RSI, or None during warm-up."""
        return self._value

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._seed_prices = []
        self._avg_gain = None
        self._avg_loss = None
        self._prev_price = None
        self._value = None


class StreamingATR:
    """Online Average True Range using Wilder (RMA) smoothing.

    Requires H/L/C per tick.  Warm-up seeds the RMA with the simple mean of
    the first ``period`` True Range values; subsequent ticks use Wilder
    smoothing in O(1).

    Args:
        period: ATR period (default 14, must be >= 1).

    Raises:
        ValueError: If period < 1.
    """

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"StreamingATR period must be >= 1, got {period}")
        self.period = period
        self._tr_seed: list[float] = []
        self._prev_close: float | None = None
        self._atr: float | None = None

    def _true_range(self, high: float, low: float, close: float) -> float:
        if self._prev_close is None:
            return high - low
        return max(
            high - low,
            abs(high - self._prev_close),
            abs(low - self._prev_close),
        )

    def update(self, high: float, low: float, close: float) -> float | None:
        """Feed one new H/L/C tick.

        Args:
            high:  High price for this bar.
            low:   Low price for this bar.
            close: Close price for this bar.

        Returns:
            Current ATR, or None during warm-up.
        """
        tr = self._true_range(high, low, close)
        self._prev_close = close

        if self._atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) >= self.period:
                self._atr = sum(self._tr_seed) / self.period
                self._tr_seed = []  # free
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / self.period

        return self._atr

    @property
    def value(self) -> float | None:
        """Latest ATR, or None during warm-up."""
        return self._atr

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._tr_seed = []
        self._prev_close = None
        self._atr = None


class StreamingMACD:
    """Online MACD (Moving Average Convergence Divergence).

    Computes MACD line, signal line, and histogram in real time using three
    chained StreamingEMA instances.  No arrays are retained beyond the EMA state.

    Args:
        fast_period:   Fast EMA period (default 12).
        slow_period:   Slow EMA period (default 26).
        signal_period: Signal EMA period (default 9).

    Raises:
        ValueError: If fast_period >= slow_period or any period < 1.
    """

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> None:
        if fast_period >= slow_period:
            raise ValueError(
                f"fast_period ({fast_period}) must be less than slow_period ({slow_period})"
            )
        if signal_period < 1:
            raise ValueError(f"signal_period must be >= 1, got {signal_period}")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self._fast_ema = StreamingEMA(fast_period)
        self._slow_ema = StreamingEMA(slow_period)
        self._signal_ema = StreamingEMA(signal_period)
        self._macd: float | None = None
        self._signal: float | None = None
        self._histogram: float | None = None

    def update(
        self, price: float
    ) -> tuple[float | None, float | None, float | None]:
        """Feed one new price tick.

        Args:
            price: Latest close price.

        Returns:
            Tuple of (macd_line, signal_line, histogram).
            Any element is None while still warming up.
        """
        fast_val = self._fast_ema.update(price)
        slow_val = self._slow_ema.update(price)

        if fast_val is None or slow_val is None:
            return None, None, None

        macd_val = fast_val - slow_val
        signal_val = self._signal_ema.update(macd_val)

        if signal_val is None:
            self._macd = macd_val
            self._signal = None
            self._histogram = None
            return macd_val, None, None

        histogram = macd_val - signal_val
        self._macd = macd_val
        self._signal = signal_val
        self._histogram = histogram
        return macd_val, signal_val, histogram

    @property
    def macd(self) -> float | None:
        """Latest MACD line value, or None during warm-up."""
        return self._macd

    @property
    def signal(self) -> float | None:
        """Latest signal line value, or None during warm-up."""
        return self._signal

    @property
    def histogram(self) -> float | None:
        """Latest histogram value, or None during warm-up."""
        return self._histogram

    def reset(self) -> None:
        """Reset all state — discard all history."""
        self._fast_ema.reset()
        self._slow_ema.reset()
        self._signal_ema.reset()
        self._macd = None
        self._signal = None
        self._histogram = None


class StreamingBollingerBands:
    """Online Bollinger Bands (SMA ± N * rolling std).

    Uses a sliding window of ``period`` prices to compute:
    - Middle band: SMA of the window
    - Upper band: middle + std_dev * rolling_std
    - Lower band: middle - std_dev * rolling_std

    Standard deviation uses population formula (ddof=0), matching TradingView.
    Memory usage is O(period) for the price buffer.

    Args:
        period:  Rolling window length (default 20, must be >= 2).
        std_dev: Number of standard deviations for the bands (default 2.0).

    Raises:
        ValueError: If period < 2.
    """

    def __init__(self, period: int = 20, std_dev: float = 2.0) -> None:
        if period < 2:
            raise ValueError(f"StreamingBollingerBands period must be >= 2, got {period}")
        self.period = period
        self.std_dev = std_dev
        from collections import deque
        self._buf: deque[float] = deque(maxlen=period)
        self._upper: float | None = None
        self._middle: float | None = None
        self._lower: float | None = None

    def update(
        self, price: float
    ) -> tuple[float | None, float | None, float | None]:
        """Feed one new close price.

        Args:
            price: Latest close price.

        Returns:
            Tuple of (upper, middle, lower).  All None during warm-up.
        """
        self._buf.append(price)
        if len(self._buf) < self.period:
            return None, None, None

        import numpy as _np
        arr = _np.array(self._buf, dtype=_np.float64)
        middle = float(_np.mean(arr))
        std = float(_np.std(arr, ddof=0))
        upper = middle + self.std_dev * std
        lower = middle - self.std_dev * std
        self._upper = upper
        self._middle = middle
        self._lower = lower
        return upper, middle, lower

    @property
    def upper(self) -> float | None:
        """Latest upper band, or None during warm-up."""
        return self._upper

    @property
    def middle(self) -> float | None:
        """Latest middle band (SMA), or None during warm-up."""
        return self._middle

    @property
    def lower(self) -> float | None:
        """Latest lower band, or None during warm-up."""
        return self._lower

    @property
    def bandwidth(self) -> float | None:
        """Bollinger Bandwidth = (upper - lower) / middle * 100, or None."""
        if self._upper is None or self._middle is None or self._lower is None:
            return None
        if self._middle == 0.0:
            return 0.0
        return (self._upper - self._lower) / self._middle * 100.0

    @property
    def percent_b(self) -> float | None:
        """Bollinger %B = (close - lower) / (upper - lower), or None."""
        if self._upper is None or self._lower is None or len(self._buf) == 0:
            return None
        band_width = self._upper - self._lower
        if band_width == 0.0:
            return 0.5
        return (self._buf[-1] - self._lower) / band_width

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._buf.clear()
        self._upper = None
        self._middle = None
        self._lower = None


class StreamingSupertrend:
    """Online Supertrend indicator.

    Uses a streaming ATR to compute the dynamic support/resistance bands.
    Emits direction (+1 long, -1 short) and the supertrend line value.

    Args:
        period:     ATR period (default 10).
        multiplier: ATR multiplier for band width (default 3.0).

    Raises:
        ValueError: If period < 1.
    """

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        if period < 1:
            raise ValueError(f"StreamingSupertrend period must be >= 1, got {period}")
        self.period = period
        self.multiplier = multiplier
        self._atr = StreamingATR(period)
        self._direction: int | None = None       # +1 uptrend, -1 downtrend
        self._supertrend: float | None = None    # current supertrend line
        self._upper_band: float | None = None
        self._lower_band: float | None = None
        self._prev_close: float | None = None

    def update(
        self, high: float, low: float, close: float
    ) -> tuple[float | None, int | None]:
        """Feed one H/L/C bar.

        Args:
            high:  High price of the bar.
            low:   Low price of the bar.
            close: Close price of the bar.

        Returns:
            Tuple of (supertrend_value, direction).
            supertrend_value is the line level; direction is +1 (uptrend) or
            -1 (downtrend). Both are None during ATR warm-up.
        """
        atr_val = self._atr.update(high, low, close)
        if atr_val is None:
            self._prev_close = close
            return None, None

        hl2 = (high + low) / 2.0
        raw_upper = hl2 + self.multiplier * atr_val
        raw_lower = hl2 - self.multiplier * atr_val

        # First valid bar — initialise bands and direction
        if self._upper_band is None:
            self._upper_band = raw_upper
            self._lower_band = raw_lower
            self._direction = -1 if close >= raw_lower else 1
            self._supertrend = (
                self._lower_band if self._direction == -1 else self._upper_band
            )
            self._prev_close = close
            return self._supertrend, self._direction

        # Tighten bands (never widen them relative to the previous bar)
        prev_upper = self._upper_band
        prev_lower = self._lower_band

        new_upper = (
            raw_upper
            if raw_upper < prev_upper or (self._prev_close is not None and self._prev_close > prev_upper)
            else prev_upper
        )
        new_lower = (
            raw_lower
            if raw_lower > prev_lower or (self._prev_close is not None and self._prev_close < prev_lower)
            else prev_lower
        )

        # Update direction
        prev_dir = self._direction
        if prev_dir == -1:
            self._direction = 1 if close < new_lower else -1
        else:
            self._direction = -1 if close > new_upper else 1

        self._upper_band = new_upper
        self._lower_band = new_lower
        self._supertrend = (
            new_lower if self._direction == -1 else new_upper
        )
        self._prev_close = close
        return self._supertrend, self._direction

    @property
    def value(self) -> float | None:
        """Latest Supertrend line value, or None during warm-up."""
        return self._supertrend

    @property
    def direction(self) -> int | None:
        """Current trend direction: -1 (uptrend/support), +1 (downtrend/resistance), or None."""
        return self._direction

    def reset(self) -> None:
        """Reset state — discard all history."""
        self._atr.reset()
        self._direction = None
        self._supertrend = None
        self._upper_band = None
        self._lower_band = None
        self._prev_close = None


class StreamingVWAP:
    """Online VWAP (Volume Weighted Average Price).

    Optionally resets at the start of each trading session (day/week/month).
    Pass ``anchor=True`` to any ``update()`` call to trigger a reset at that bar.

    Memory usage: O(1) — stores only running sums.

    Args:
        None

    Example::

        vwap = StreamingVWAP()
        for bar in intraday_bars:
            is_session_start = bar["time"].hour == 9 and bar["time"].minute == 15
            v = vwap.update(bar["high"], bar["low"], bar["close"], bar["volume"],
                            anchor=is_session_start)
    """

    def __init__(self) -> None:
        self._cumulative_pv: float = 0.0
        self._cumulative_vol: float = 0.0
        self._value: float | None = None

    def update(
        self,
        high: float,
        low: float,
        close: float,
        volume: float,
        anchor: bool = False,
    ) -> float | None:
        """Feed one H/L/C/V bar.

        Args:
            high:   High price.
            low:    Low price.
            close:  Close price.
            volume: Bar volume.
            anchor: If True, reset accumulators (start of session).

        Returns:
            Current VWAP, or None if cumulative volume is zero.
        """
        if anchor:
            self._cumulative_pv = 0.0
            self._cumulative_vol = 0.0

        typical_price = (high + low + close) / 3.0
        self._cumulative_pv += typical_price * volume
        self._cumulative_vol += volume

        if self._cumulative_vol == 0.0:
            return None

        self._value = self._cumulative_pv / self._cumulative_vol
        return self._value

    @property
    def value(self) -> float | None:
        """Latest VWAP value, or None if no data fed."""
        return self._value

    def reset(self) -> None:
        """Reset accumulators — equivalent to a session anchor."""
        self._cumulative_pv = 0.0
        self._cumulative_vol = 0.0
        self._value = None


class StreamingCumulativeDelta:
    """Online Cumulative Delta — running net buy vs sell volume.

    Cumulative delta approximates order flow imbalance by treating volume on
    up-bars as aggressive buying (positive) and volume on down-bars as
    aggressive selling (negative).  Flat bars contribute zero delta.

    Memory usage: O(1) — stores only the running sum.

    Args:
        None
    """

    def __init__(self) -> None:
        self._cum_delta: float = 0.0
        self._prev_close: float | None = None

    def update(self, close: float, volume: float) -> float:
        """Feed one close/volume tick.

        Args:
            close:  Close price.
            volume: Bar volume (must be >= 0).

        Returns:
            Current cumulative delta.
        """
        if self._prev_close is not None:
            if close > self._prev_close:
                self._cum_delta += volume
            elif close < self._prev_close:
                self._cum_delta -= volume
            # flat bar → delta unchanged
        self._prev_close = close
        return self._cum_delta

    @property
    def value(self) -> float:
        """Current cumulative delta (0.0 until first update)."""
        return self._cum_delta

    def reset(self) -> None:
        """Reset to zero — discard all history."""
        self._cum_delta = 0.0
        self._prev_close = None
