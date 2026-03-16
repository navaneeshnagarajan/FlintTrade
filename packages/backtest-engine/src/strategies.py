"""12 built-in strategy templates.

Each inherits from engine's BaseStrategy and has configurable parameters.
These are ready-to-backtest templates covering equity momentum, mean-reversion,
options selling, and intraday breakout patterns.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

logger = logging.getLogger("flinttrade.backtest.strategies")


# ---------------------------------------------------------------------------
# Helpers — simple indicator calculations (no external dependency needed)
# ---------------------------------------------------------------------------


def ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if not values or period <= 0:
        return []
    result: list[float] = []
    k = 2 / (period + 1)
    prev = values[0]
    for v in values:
        prev = v * k + prev * (1 - k)
        result.append(prev)
    return result


def sma(values: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    if len(values) < period:
        return [0.0] * len(values)
    result: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1: i + 1]) / period)
    return result


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = [50.0] * (period + 1)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))
    return result


def bollinger_bands(
    closes: list[float], period: int = 20, std_mult: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Bollinger Bands — returns (upper, middle, lower)."""
    mid = sma(closes, period)
    upper: list[float] = []
    lower: list[float] = []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(0.0)
            lower.append(0.0)
            continue
        window = closes[i - period + 1: i + 1]
        m = sum(window) / period
        std = (sum((v - m) ** 2 for v in window) / period) ** 0.5
        upper.append(m + std_mult * std)
        lower.append(m - std_mult * std)
    return upper, mid, lower


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9,
) -> tuple[list[float], list[float], list[float]]:
    """MACD — returns (macd_line, signal_line, histogram)."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


def supertrend(
    highs: list[float], lows: list[float], closes: list[float],
    period: int = 10, multiplier: float = 3.0,
) -> tuple[list[float], list[bool]]:
    """Supertrend indicator. Returns (supertrend_values, is_uptrend)."""
    n = len(closes)
    if n < period:
        return [0.0] * n, [True] * n

    # ATR
    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr = sma(tr, period)

    st: list[float] = [0.0] * n
    uptrend: list[bool] = [True] * n

    for i in range(period, n):
        basic_upper = (highs[i] + lows[i]) / 2 + multiplier * atr[i]
        basic_lower = (highs[i] + lows[i]) / 2 - multiplier * atr[i]

        if i == period:
            st[i] = basic_lower if closes[i] > basic_lower else basic_upper
            uptrend[i] = closes[i] > basic_lower
            continue

        if uptrend[i - 1]:
            st[i] = max(basic_lower, st[i - 1]) if closes[i] > st[i - 1] else basic_upper
            uptrend[i] = closes[i] > st[i]
        else:
            st[i] = min(basic_upper, st[i - 1]) if closes[i] < st[i - 1] else basic_lower
            uptrend[i] = closes[i] > st[i]

    return st, uptrend


# ---------------------------------------------------------------------------
# Base backtest strategy mixin
# ---------------------------------------------------------------------------


class _BacktestStrategyMixin:
    """Mixin providing bar history tracking for backtest strategies."""

    def _init_history(self) -> None:
        self._opens: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._volumes: list[int] = []
        self._timestamps: list[str] = []
        self._pending_orders: list[Order] = []
        self._position: int = 0  # +1=long, -1=short, 0=flat

    def _record_bar(self, bar: OHLCV) -> None:
        self._opens.append(bar.open)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._closes.append(bar.close)
        self._volumes.append(bar.volume)
        self._timestamps.append(bar.timestamp)

    def _buy(self, qty: str = "1") -> None:
        if self._position <= 0:
            self._pending_orders.append(Order(
                symbol=getattr(self, "_symbol", ""),
                action="BUY", exchange=getattr(self, "exchange", "NSE"),
                quantity=qty, strategy=getattr(self, "name", "Flint"),
            ))
            self._position = 1

    def _sell(self, qty: str = "1") -> None:
        if self._position >= 0:
            self._pending_orders.append(Order(
                symbol=getattr(self, "_symbol", ""),
                action="SELL", exchange=getattr(self, "exchange", "NSE"),
                quantity=qty, strategy=getattr(self, "name", "Flint"),
            ))
            self._position = -1

    def _flat(self) -> None:
        self._position = 0


# ---------------------------------------------------------------------------
# 1. EMA Crossover
# ---------------------------------------------------------------------------


class EMACrossover(BaseStrategy, _BacktestStrategyMixin):
    """EMA crossover strategy: buy when fast EMA > slow EMA, sell when reverse."""

    def __init__(
        self, name: str = "EMACrossover", exchange: str = "NSE", product: str = "MIS",
        fast_period: int = 9, slow_period: int = 21, symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.slow_period + 1:
            return
        fast = ema(self._closes, self.fast_period)
        slow = ema(self._closes, self.slow_period)
        if fast[-1] > slow[-1] and fast[-2] <= slow[-2]:
            self._buy()
        elif fast[-1] < slow[-1] and fast[-2] >= slow[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 2. Supertrend
# ---------------------------------------------------------------------------


class SupertrendStrategy(BaseStrategy, _BacktestStrategyMixin):
    """Supertrend indicator strategy."""

    def __init__(
        self, name: str = "Supertrend", exchange: str = "NSE", product: str = "MIS",
        period: int = 10, multiplier: float = 3.0, symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.multiplier = multiplier
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 2:
            return
        _, trend = supertrend(self._highs, self._lows, self._closes, self.period, self.multiplier)
        if trend[-1] and not trend[-2]:
            self._buy()
        elif not trend[-1] and trend[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 3. MACD + RSI
# ---------------------------------------------------------------------------


class MACDRSIStrategy(BaseStrategy, _BacktestStrategyMixin):
    """MACD crossover confirmed by RSI."""

    def __init__(
        self, name: str = "MACD_RSI", exchange: str = "NSE", product: str = "MIS",
        macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
        rsi_period: int = 14, rsi_oversold: float = 30, rsi_overbought: float = 70,
        symbol: str = "", **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.macd_slow + self.macd_signal + 1:
            return
        _, _, hist = macd(self._closes, self.macd_fast, self.macd_slow, self.macd_signal)
        rsi_vals = rsi(self._closes, self.rsi_period)
        if hist[-1] > 0 and hist[-2] <= 0 and rsi_vals[-1] < self.rsi_overbought:
            self._buy()
        elif hist[-1] < 0 and hist[-2] >= 0 and rsi_vals[-1] > self.rsi_oversold:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 4. Bollinger Band Mean Reversion
# ---------------------------------------------------------------------------


class BollingerMeanReversion(BaseStrategy, _BacktestStrategyMixin):
    """Buy at lower band, sell at upper band."""

    def __init__(
        self, name: str = "BollingerMR", exchange: str = "NSE", product: str = "MIS",
        period: int = 20, std_mult: float = 2.0, symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.std_mult = std_mult
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return
        upper, mid, lower = bollinger_bands(self._closes, self.period, self.std_mult)
        if self._closes[-1] <= lower[-1] and self._closes[-2] > lower[-2]:
            self._buy()
        elif self._closes[-1] >= upper[-1] and self._closes[-2] < upper[-2]:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 5. VWAP Deviation
# ---------------------------------------------------------------------------


class VWAPDeviation(BaseStrategy, _BacktestStrategyMixin):
    """Trade deviations from VWAP. Buy below VWAP - threshold, sell above + threshold."""

    def __init__(
        self, name: str = "VWAPDev", exchange: str = "NSE", product: str = "MIS",
        deviation_pct: float = 1.0, symbol: str = "", **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.deviation_pct = deviation_pct
        self._symbol = symbol
        self._init_history()
        self._cum_vol_price = 0.0
        self._cum_vol = 0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        typical = (bar.high + bar.low + bar.close) / 3
        self._cum_vol_price += typical * bar.volume
        self._cum_vol += bar.volume
        if self._cum_vol == 0:
            return
        vwap = self._cum_vol_price / self._cum_vol
        lower = vwap * (1 - self.deviation_pct / 100)
        upper = vwap * (1 + self.deviation_pct / 100)
        if bar.close <= lower:
            self._buy()
        elif bar.close >= upper:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 6–10. Options strategies (simplified for backtesting)
# ---------------------------------------------------------------------------


class StraddleSell(BaseStrategy, _BacktestStrategyMixin):
    """ATM straddle sell with time-based exit."""

    def __init__(
        self, name: str = "StraddleSell", exchange: str = "NFO", product: str = "NRML",
        entry_time: str = "09:20", exit_time: str = "15:15",
        stop_loss_pct: float = 30.0, symbol: str = "", **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.stop_loss_pct = stop_loss_pct
        self._symbol = symbol
        self._init_history()
        self._entry_premium = 0.0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""
        if time_part == self.entry_time and self._position == 0:
            self._sell()
            self._entry_premium = bar.close
        elif time_part >= self.exit_time and self._position != 0:
            self._buy()
            self._flat()
        elif self._position != 0 and self._entry_premium > 0:
            loss_pct = (bar.close - self._entry_premium) / self._entry_premium * 100
            if loss_pct > self.stop_loss_pct:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


class StrangleSell(StraddleSell):
    """OTM strangle sell (uses same logic as straddle with wider strikes)."""

    def __init__(self, name: str = "StrangleSell", delta: float = 0.3, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self.delta = delta


class IronCondor(StraddleSell):
    """Iron Condor strategy (simplified for backtesting)."""

    def __init__(self, name: str = "IronCondor", wing_width: int = 100, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self.wing_width = wing_width


class BullPutSpread(StraddleSell):
    """Bull Put Spread (simplified for backtesting)."""

    def __init__(self, name: str = "BullPutSpread", spread_width: int = 100, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self.spread_width = spread_width


class BearCallSpread(StraddleSell):
    """Bear Call Spread (simplified for backtesting)."""

    def __init__(self, name: str = "BearCallSpread", spread_width: int = 100, **kwargs: Any) -> None:
        super().__init__(name=name, **kwargs)
        self.spread_width = spread_width


# ---------------------------------------------------------------------------
# 11. Momentum Breakout
# ---------------------------------------------------------------------------


class MomentumBreakout(BaseStrategy, _BacktestStrategyMixin):
    """Buy on price+volume breakout above N-period high."""

    def __init__(
        self, name: str = "MomentumBreakout", exchange: str = "NSE", product: str = "MIS",
        lookback: int = 20, volume_mult: float = 1.5, symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self.volume_mult = volume_mult
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.lookback + 1:
            return
        prev_high = max(self._highs[-self.lookback - 1:-1])
        avg_vol = sum(self._volumes[-self.lookback - 1:-1]) / self.lookback
        if bar.close > prev_high and bar.volume > avg_vol * self.volume_mult:
            self._buy()
        prev_low = min(self._lows[-self.lookback - 1:-1])
        if bar.close < prev_low and bar.volume > avg_vol * self.volume_mult:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# 12. Opening Range Breakout
# ---------------------------------------------------------------------------


class OpeningRangeBreakout(BaseStrategy, _BacktestStrategyMixin):
    """Trade breakout of the first N minutes high/low."""

    def __init__(
        self, name: str = "ORB", exchange: str = "NSE", product: str = "MIS",
        range_minutes: int = 15, exit_time: str = "15:15",
        symbol: str = "", **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.range_minutes = range_minutes
        self.exit_time = exit_time
        self._symbol = symbol
        self._init_history()
        self._range_high = 0.0
        self._range_low = float("inf")
        self._range_bars = 0
        self._range_set = False

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""

        # Reset at day open (9:15)
        if time_part == "09:15":
            self._range_high = 0.0
            self._range_low = float("inf")
            self._range_bars = 0
            self._range_set = False
            self._flat()

        if not self._range_set:
            self._range_high = max(self._range_high, bar.high)
            self._range_low = min(self._range_low, bar.low)
            self._range_bars += 1
            if self._range_bars >= self.range_minutes:
                self._range_set = True
            return

        if time_part >= self.exit_time:
            if self._position != 0:
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                self._flat()
            return

        if bar.close > self._range_high and self._position <= 0:
            self._buy()
        elif bar.close < self._range_low and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


# ---------------------------------------------------------------------------
# Strategy catalog
# ---------------------------------------------------------------------------

BUILTIN_STRATEGIES: dict[str, type[BaseStrategy]] = {
    "EMACrossover": EMACrossover,
    "Supertrend": SupertrendStrategy,
    "MACD_RSI": MACDRSIStrategy,
    "BollingerMR": BollingerMeanReversion,
    "VWAPDev": VWAPDeviation,
    "StraddleSell": StraddleSell,
    "StrangleSell": StrangleSell,
    "IronCondor": IronCondor,
    "BullPutSpread": BullPutSpread,
    "BearCallSpread": BearCallSpread,
    "MomentumBreakout": MomentumBreakout,
    "ORB": OpeningRangeBreakout,
}
