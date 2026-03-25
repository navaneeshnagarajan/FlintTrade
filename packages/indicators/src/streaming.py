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
