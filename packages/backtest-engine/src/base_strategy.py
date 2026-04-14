"""Strategy base class for FlintTrade backtest engine.

All backtestable strategies must inherit from ``BaseBacktestStrategy``.
Provides:

- Abstract ``on_bar`` hook (required) and ``on_tick`` hook (optional)
- Signal enumeration (BUY / SELL / HOLD / EXIT_LONG / EXIT_SHORT)
- Position management helpers: ``enter_long``, ``enter_short``, ``exit_position``
- Order management helpers: ``cancel_all_orders``, ``get_open_orders``
- Indicator access shim (delegates to ``packages.indicators`` when available)
- State serialisation for walk-forward and Monte Carlo restarts

Usage::

    from .base_strategy import BaseBacktestStrategy, Signal

    class MyCrossover(BaseBacktestStrategy):
        def __init__(self, fast: int = 9, slow: int = 21, **kwargs):
            super().__init__(name="MyCrossover", **kwargs)
            self.fast = fast
            self.slow = slow
            self._closes: list[float] = []

        def on_bar(self, bar) -> None:
            self._closes.append(bar.close)
            if len(self._closes) < self.slow:
                return
            fast_avg = sum(self._closes[-self.fast:]) / self.fast
            slow_avg = sum(self._closes[-self.slow:]) / self.slow
            if fast_avg > slow_avg:
                self.enter_long()
            elif fast_avg < slow_avg:
                self.exit_position()
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger("flinttrade.backtest.strategy")


# ---------------------------------------------------------------------------
# Signal enum
# ---------------------------------------------------------------------------


class Signal(StrEnum):
    """Strategy signals emitted by ``on_bar``.

    Attributes:
        BUY: Enter a long position.
        SELL: Enter a short position (if allowed).
        HOLD: Do nothing.
        EXIT_LONG: Close the current long position.
        EXIT_SHORT: Cover the current short position.
    """

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT_LONG = "EXIT_LONG"
    EXIT_SHORT = "EXIT_SHORT"


# ---------------------------------------------------------------------------
# Indicator proxy
# ---------------------------------------------------------------------------


class _IndicatorProxy:
    """Thin wrapper that resolves indicator functions at call time.

    Prefers ``packages.indicators`` (TA-Lib / Numba), falls back to the
    lightweight pure-Python implementations in ``strategies.py``.
    """

    @staticmethod
    def ema(values: list[float], period: int) -> list[float]:
        """Exponential Moving Average.

        Args:
            values: Price series (newest last).
            period: EMA period.

        Returns:
            EMA series of the same length.
        """
        try:
            from packages.indicators.src import ema as _ema  # type: ignore[import]
            return list(_ema(values, period))
        except ImportError:
            pass
        # Pure-Python fallback
        if len(values) < period:
            return [0.0] * len(values)
        k = 2.0 / (period + 1)
        result = [0.0] * len(values)
        result[period - 1] = sum(values[:period]) / period
        for i in range(period, len(values)):
            result[i] = values[i] * k + result[i - 1] * (1 - k)
        return result

    @staticmethod
    def sma(values: list[float], period: int) -> list[float]:
        """Simple Moving Average.

        Args:
            values: Price series.
            period: SMA period.

        Returns:
            SMA series; values before ``period`` are 0.0.
        """
        result = [0.0] * len(values)
        for i in range(period - 1, len(values)):
            result[i] = sum(values[i - period + 1 : i + 1]) / period
        return result

    @staticmethod
    def rsi(values: list[float], period: int = 14) -> list[float]:
        """Relative Strength Index.

        Args:
            values: Price series.
            period: RSI period (default 14).

        Returns:
            RSI series; values before ``period`` are 0.0.
        """
        if len(values) < period + 1:
            return [0.0] * len(values)
        result = [0.0] * len(values)
        gains, losses = [], []
        for i in range(1, period + 1):
            diff = values[i] - values[i - 1]
            gains.append(max(0.0, diff))
            losses.append(max(0.0, -diff))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        for i in range(period, len(values)):
            if i > period:
                diff = values[i] - values[i - 1]
                avg_gain = (avg_gain * (period - 1) + max(0.0, diff)) / period
                avg_loss = (avg_loss * (period - 1) + max(0.0, -diff)) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else float("inf")
            result[i] = 100 - 100 / (1 + rs)
        return result

    @staticmethod
    def atr(
        highs: list[float], lows: list[float], closes: list[float], period: int = 14
    ) -> list[float]:
        """Average True Range.

        Args:
            highs: Bar highs series.
            lows: Bar lows series.
            closes: Bar closes series.
            period: ATR period (default 14).

        Returns:
            ATR series; values before ``period`` are 0.0.
        """
        if len(closes) < 2:
            return [0.0] * len(closes)
        trs = [0.0]
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)
        result = [0.0] * len(closes)
        if len(trs) >= period:
            result[period - 1] = sum(trs[:period]) / period
            for i in range(period, len(closes)):
                result[i] = (result[i - 1] * (period - 1) + trs[i]) / period
        return result

    @staticmethod
    def bollinger_bands(
        values: list[float], period: int = 20, num_std: float = 2.0
    ) -> tuple[list[float], list[float], list[float]]:
        """Bollinger Bands.

        Args:
            values: Price series.
            period: Lookback period (default 20).
            num_std: Standard deviations for bands (default 2.0).

        Returns:
            Tuple of (upper, middle, lower) lists.
        """
        import math
        n = len(values)
        upper = [0.0] * n
        middle = [0.0] * n
        lower = [0.0] * n
        for i in range(period - 1, n):
            window = values[i - period + 1 : i + 1]
            mean = sum(window) / period
            variance = sum((v - mean) ** 2 for v in window) / period
            std = math.sqrt(variance)
            middle[i] = mean
            upper[i] = mean + num_std * std
            lower[i] = mean - num_std * std
        return upper, middle, lower


# Global indicator instance — strategies access as ``self.indicators.ema(...)``
indicators = _IndicatorProxy()


# ---------------------------------------------------------------------------
# Order builder helpers
# ---------------------------------------------------------------------------


@dataclass
class OrderIntent:
    """A pending order intent from a strategy.

    Strategies return these from ``generate_orders()``. The engine converts
    them into ``EngineOrder`` objects.

    Attributes:
        symbol: Instrument symbol (empty = engine's primary symbol).
        side: BUY or SELL.
        quantity: Lot/share quantity (0 = use engine position sizing).
        order_type: MARKET | LIMIT | STOP | STOP_LIMIT.
        limit_price: Limit price (required for LIMIT and STOP_LIMIT).
        stop_price: Stop trigger price (required for STOP and STOP_LIMIT).
        tag: Optional label for P&L attribution.
    """

    symbol: str = ""
    side: Signal = Signal.BUY
    quantity: int = 0
    order_type: str = "MARKET"
    limit_price: float = 0.0
    stop_price: float = 0.0
    tag: str = ""

    # Aliases for engine compatibility
    @property
    def action(self) -> str:
        """Alias for side (BUY/SELL)."""
        return "BUY" if self.side in (Signal.BUY, Signal.EXIT_SHORT) else "SELL"

    @property
    def pricetype(self) -> str:
        """Alias for order_type (engine compatibility)."""
        return self.order_type

    @property
    def price(self) -> float:
        """Alias for limit_price."""
        return self.limit_price

    @property
    def trigger_price(self) -> float:
        """Alias for stop_price."""
        return self.stop_price


# ---------------------------------------------------------------------------
# Base strategy
# ---------------------------------------------------------------------------


class BaseBacktestStrategy(ABC):
    """Abstract base class for all FlintTrade backtest strategies.

    Subclasses must implement ``on_bar``. All other methods have sensible
    defaults that can be overridden.

    Args:
        name: Human-readable strategy name.
        symbol: Primary instrument symbol (used when submitting orders).
        params: Arbitrary strategy parameters stored for serialisation.
    """

    def __init__(
        self,
        name: str = "Strategy",
        symbol: str = "",
        **params: Any,
    ) -> None:
        self.name = name
        self.symbol = symbol
        self.params: dict[str, Any] = dict(params)

        # Engine reference — set by BacktestEngine.set_strategy()
        self._engine: Any | None = None

        # State tracking
        self._started: bool = False
        self._error: str = ""
        self._pending_orders: list[OrderIntent] = []
        self._bar_count: int = 0

        # Indicator helper (accessible as self.indicators inside strategies)
        self.indicators: _IndicatorProxy = indicators

        logger.debug("Strategy initialised: %s symbol=%s", name, symbol)

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Called once before the first bar. Override to allocate resources."""
        self._started = True
        logger.debug("Strategy started: %s", self.name)

    def stop(self) -> None:
        """Called once after the last bar. Override to release resources."""
        logger.debug("Strategy stopped: %s", self.name)

    # ------------------------------------------------------------------
    # Required hook
    # ------------------------------------------------------------------

    @abstractmethod
    def on_bar(self, bar: Any) -> None:
        """Process a new OHLCV bar and optionally queue orders.

        This is the primary entry point. Strategies should:
        1. Append ``bar.close`` (or whichever price) to their internal series.
        2. Compute indicator values.
        3. Generate signals by calling ``enter_long``, ``enter_short``,
           ``exit_position``, or ``queue_order``.

        Args:
            bar: OHLCV bar object with attributes: timestamp, open, high,
                 low, close, volume. Compatible with both the FlintTrade
                 core ``OHLCV`` model and plain dicts.
        """

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def on_tick(self, tick: Any) -> None:
        """Process a single market tick (for tick-level strategies).

        Default implementation does nothing. Override for tick-level logic.

        Args:
            tick: Tick object with at least a ``ltp`` (last traded price) attribute.
        """

    def on_order_update(self, order: Any) -> None:
        """Called when an order changes status (filled, cancelled, rejected).

        Args:
            order: The updated order object.
        """

    def on_trade(self, trade: Any) -> None:
        """Called when a round-trip trade is closed.

        Args:
            trade: EngineTrade object with P&L, duration, etc.
        """

    # ------------------------------------------------------------------
    # Order management helpers
    # ------------------------------------------------------------------

    def enter_long(
        self,
        quantity: int = 0,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        symbol: str = "",
        tag: str = "",
    ) -> None:
        """Queue a long-entry order.

        If ``limit_price`` is non-zero, creates a LIMIT order.
        If ``stop_price`` is non-zero, creates a STOP order.
        If both are provided, creates a STOP_LIMIT order.
        Otherwise creates a MARKET order.

        Args:
            quantity: Lot quantity (0 = use engine position sizing).
            limit_price: Limit price for LIMIT / STOP_LIMIT orders.
            stop_price: Stop trigger price for STOP / STOP_LIMIT orders.
            symbol: Override instrument symbol.
            tag: Label for P&L attribution.
        """
        order_type = self._infer_order_type(limit_price, stop_price)
        self._pending_orders.append(OrderIntent(
            symbol=symbol or self.symbol,
            side=Signal.BUY,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            tag=tag,
        ))

    def enter_short(
        self,
        quantity: int = 0,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        symbol: str = "",
        tag: str = "",
    ) -> None:
        """Queue a short-entry order (requires ``allow_short=True`` in EngineConfig).

        Args:
            quantity: Lot quantity (0 = use engine position sizing).
            limit_price: Limit price.
            stop_price: Stop trigger price.
            symbol: Override instrument symbol.
            tag: Label for P&L attribution.
        """
        order_type = self._infer_order_type(limit_price, stop_price)
        self._pending_orders.append(OrderIntent(
            symbol=symbol or self.symbol,
            side=Signal.SELL,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            tag=tag,
        ))

    def exit_position(
        self,
        quantity: int = 0,
        limit_price: float = 0.0,
        stop_price: float = 0.0,
        symbol: str = "",
        tag: str = "",
    ) -> None:
        """Queue an exit order for the current position.

        Automatically determines BUY (cover short) or SELL (close long)
        by querying the engine's current position.

        Args:
            quantity: Quantity to close (0 = full position).
            limit_price: Limit price.
            stop_price: Stop trigger price.
            symbol: Override instrument symbol.
            tag: Label for P&L attribution.
        """
        sym = symbol or self.symbol
        pos = self._get_position(sym)
        if pos is None:
            logger.debug("exit_position: no open position for %s", sym)
            return

        side = Signal.SELL if pos.get("side", "BUY") == "BUY" else Signal.BUY
        qty = quantity or pos.get("quantity", 0)
        order_type = self._infer_order_type(limit_price, stop_price)

        self._pending_orders.append(OrderIntent(
            symbol=sym,
            side=side,
            quantity=qty,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            tag=tag or "exit",
        ))

    def queue_order(self, intent: OrderIntent) -> None:
        """Directly queue an OrderIntent.

        Args:
            intent: The OrderIntent to queue.
        """
        self._pending_orders.append(intent)

    def cancel_all_orders(self) -> list[str]:
        """Cancel all pending orders through the engine.

        Returns:
            List of cancelled order IDs.
        """
        cancelled: list[str] = []
        if self._engine and hasattr(self._engine, "_pending_orders"):
            for order in list(self._engine._pending_orders):
                if self._engine.cancel_order(getattr(order, "id", "")):
                    cancelled.append(getattr(order, "id", ""))
        # Also clear local pending
        self._pending_orders.clear()
        return cancelled

    def get_open_orders(self) -> list[Any]:
        """Return all currently pending orders from the engine.

        Returns:
            List of pending EngineOrder objects.
        """
        if self._engine and hasattr(self._engine, "_pending_orders"):
            return list(self._engine._pending_orders)
        return []

    # ------------------------------------------------------------------
    # generate_orders — consumed by BacktestEngine each bar
    # ------------------------------------------------------------------

    def generate_orders(self) -> list[OrderIntent]:
        """Return and clear the pending order queue.

        Called by the engine after each ``on_bar`` call to collect orders.

        Returns:
            List of OrderIntent objects to submit.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Context and engine binding
    # ------------------------------------------------------------------

    def set_engine(self, engine: Any) -> None:
        """Bind the strategy to a BacktestEngine instance.

        Called automatically by ``BacktestEngine.set_strategy()``.

        Args:
            engine: BacktestEngine instance.
        """
        self._engine = engine
        logger.debug("Strategy %s bound to engine", self.name)

    def set_error(self, error: str) -> None:
        """Record an error string (set by the engine on strategy exceptions).

        Args:
            error: Error message.
        """
        self._error = error
        logger.error("Strategy %s error: %s", self.name, error)

    # ------------------------------------------------------------------
    # Position and portfolio accessors
    # ------------------------------------------------------------------

    def get_position(self, symbol: str = "") -> dict[str, Any] | None:
        """Return the current open position for a symbol.

        Args:
            symbol: Instrument symbol (defaults to strategy's primary symbol).

        Returns:
            Position dict with keys: symbol, side, quantity, avg_cost, unrealized_pnl.
            None if no position is open.
        """
        return self._get_position(symbol or self.symbol)

    def get_cash(self) -> float:
        """Return available cash from the engine.

        Returns:
            Cash balance as float (0 if no engine bound).
        """
        if self._engine:
            return float(self._engine.get_cash())
        return 0.0

    def get_equity(self) -> float:
        """Return total equity (cash + unrealized P&L) from the engine.

        Returns:
            Total equity as float.
        """
        if self._engine:
            return float(self._engine.get_equity())
        return 0.0

    def has_position(self, symbol: str = "") -> bool:
        """Return True if an open position exists for the symbol.

        Args:
            symbol: Instrument symbol.

        Returns:
            True if position exists.
        """
        return self._get_position(symbol or self.symbol) is not None

    # ------------------------------------------------------------------
    # State serialisation (for walk-forward restarts)
    # ------------------------------------------------------------------

    def get_state(self) -> dict[str, Any]:
        """Serialise strategy state for persistence across walk-forward windows.

        Override to include indicator series or custom state.

        Returns:
            State dictionary that can be passed back to ``load_state``.
        """
        return {
            "name": self.name,
            "symbol": self.symbol,
            "params": self.params,
            "bar_count": self._bar_count,
            "error": self._error,
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore strategy state from a previously serialised dict.

        Args:
            state: State dict produced by ``get_state``.
        """
        self.name = state.get("name", self.name)
        self.symbol = state.get("symbol", self.symbol)
        self.params.update(state.get("params", {}))
        self._bar_count = state.get("bar_count", 0)
        self._error = state.get("error", "")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_position(self, symbol: str) -> dict[str, Any] | None:
        """Retrieve position dict from engine.

        Args:
            symbol: Symbol to look up.

        Returns:
            Position dict or None.
        """
        if self._engine is None:
            return None
        pos = self._engine.get_position(symbol)
        if pos is None:
            return None
        return {
            "symbol": pos.symbol,
            "side": pos.side.value if hasattr(pos.side, "value") else str(pos.side),
            "quantity": pos.quantity,
            "avg_cost": float(pos.avg_cost),
            "unrealized_pnl": float(pos.unrealized_pnl),
        }

    @staticmethod
    def _infer_order_type(limit_price: float, stop_price: float) -> str:
        """Determine order type from price parameters.

        Args:
            limit_price: Limit price (non-zero = LIMIT order).
            stop_price: Stop price (non-zero = STOP order).

        Returns:
            Order type string: MARKET | LIMIT | STOP | STOP_LIMIT.
        """
        if limit_price > 0 and stop_price > 0:
            return "STOP_LIMIT"
        if limit_price > 0:
            return "LIMIT"
        if stop_price > 0:
            return "STOP"
        return "MARKET"

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, symbol={self.symbol!r})"
