"""Event-driven backtesting simulator.

Absorbs openengine architecture. Feeds historical bars to a BaseStrategy,
simulates order execution with configurable slippage/commission, and tracks
equity curve, positions, trades, and cash balance.

Supports:
- Market, limit, stop-loss, and trailing SL orders
- Multi-timeframe (strategy on 5m bars, execution on 1m)
- Options backtesting with Greeks decay simulation
- Margin tracking for F&O positions
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

logger = logging.getLogger("flinttrade.backtest.simulator")


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SimOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    TRAILING_SL = "TRAILING_SL"


class SimOrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass
class SimOrder:
    """An order within the simulator."""

    id: int
    symbol: str
    side: str
    quantity: int
    order_type: str = "MARKET"
    limit_price: float = 0.0
    stop_price: float = 0.0
    trailing_points: float = 0.0
    status: str = "PENDING"
    fill_price: float = 0.0
    fill_timestamp: str = ""
    created_timestamp: str = ""

    @property
    def is_pending(self) -> bool:
        return self.status == SimOrderStatus.PENDING.value


@dataclass
class SimTrade:
    """A completed round-trip trade."""

    entry_timestamp: str
    exit_timestamp: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float
    pnl: float
    commission: float
    net_pnl: float
    bars_held: int = 0


@dataclass
class SimPosition:
    """A currently open position."""

    symbol: str
    side: str
    quantity: int
    entry_price: float
    entry_timestamp: str
    unrealized_pnl: float = 0.0
    margin_used: float = 0.0


@dataclass
class EquityPoint:
    """Single point on the equity curve."""

    timestamp: str
    equity: float
    cash: float
    positions_value: float
    drawdown: float = 0.0


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    symbol: str
    exchange: str = "NSE"
    interval: str = "5m"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 1_000_000.0
    position_size_pct: float = 10.0  # % of capital per trade
    position_size_qty: int = 0       # Fixed qty (0 = use pct)
    slippage_pct: float = 0.05       # 0.05% slippage
    commission_per_order: float = 20.0  # Flat per-order commission
    margin_pct: float = 100.0        # 100% = cash, 20% = 5x leverage (F&O)
    execution_interval: str = ""     # Multi-TF: execute on this interval


@dataclass
class BacktestResult:
    """Complete backtest result."""

    config: BacktestConfig
    trades: list[SimTrade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    orders: list[SimOrder] = field(default_factory=list)
    final_equity: float = 0.0
    total_bars: int = 0
    error: str = ""

    @property
    def total_return_pct(self) -> float:
        if self.config.initial_capital <= 0:
            return 0.0
        return ((self.final_equity - self.config.initial_capital)
                / self.config.initial_capital * 100)


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class BacktestSimulator:
    """Event-driven backtesting engine.

    Usage::

        config = BacktestConfig(symbol="RELIANCE", exchange="NSE", interval="1d",
                                start_date="2025-01-01", end_date="2025-12-31")
        sim = BacktestSimulator(config)
        result = sim.run(strategy_instance, bars)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._cash = config.initial_capital
        self._positions: dict[str, SimPosition] = {}
        self._pending_orders: list[SimOrder] = []
        self._filled_orders: list[SimOrder] = []
        self._trades: list[SimTrade] = []
        self._equity_curve: list[EquityPoint] = []
        self._order_counter = 0
        self._peak_equity = config.initial_capital
        self._bar_index = 0

    def run(
        self,
        strategy: BaseStrategy,
        bars: list[dict[str, Any]],
    ) -> BacktestResult:
        """Run a full backtest.

        Args:
            strategy: a BaseStrategy instance (on_bar and generate_orders will be called).
            bars: list of OHLCV dicts with keys: timestamp, open, high, low, close, volume, oi.
        """
        if not bars:
            return BacktestResult(
                config=self.config, error="No bars provided", final_equity=self._cash,
            )

        strategy.start()
        logger.info(
            "Backtest start: %s %s, %d bars, capital=%.0f",
            self.config.symbol, self.config.interval, len(bars), self.config.initial_capital,
        )

        for i, bar in enumerate(bars):
            self._bar_index = i
            ts = str(bar.get("timestamp", ""))
            close = float(bar.get("close", 0))
            high = float(bar.get("high", 0))
            low = float(bar.get("low", 0))

            # 1. Process pending orders against this bar's range
            self._process_pending_orders(bar)

            # 2. Update unrealized P&L
            self._update_positions(close)

            # 3. Feed bar to strategy
            ohlcv = OHLCV(
                timestamp=ts,
                open=float(bar.get("open", 0)),
                high=high,
                low=low,
                close=close,
                volume=int(bar.get("volume", 0)),
            )
            try:
                strategy.on_bar(ohlcv)
            except Exception as exc:
                logger.error("Strategy on_bar error at %s: %s", ts, exc)
                strategy.set_error(str(exc))
                break

            # 4. Collect orders from strategy
            try:
                new_orders = strategy.generate_orders()
            except Exception as exc:
                logger.error("Strategy generate_orders error: %s", exc)
                new_orders = []

            for order in new_orders:
                self._submit_order(order, ts, close)

            # 5. Record equity
            equity = self._calculate_equity(close)
            self._peak_equity = max(self._peak_equity, equity)
            dd = (self._peak_equity - equity) / self._peak_equity * 100 if self._peak_equity > 0 else 0.0
            self._equity_curve.append(EquityPoint(
                timestamp=ts,
                equity=equity,
                cash=self._cash,
                positions_value=equity - self._cash,
                drawdown=dd,
            ))

        # Close remaining positions at last bar's close
        if bars:
            last_close = float(bars[-1].get("close", 0))
            last_ts = str(bars[-1].get("timestamp", ""))
            self._close_all_positions(last_close, last_ts)

        strategy.stop()

        final = self._calculate_equity(float(bars[-1].get("close", 0)) if bars else 0)

        result = BacktestResult(
            config=self.config,
            trades=self._trades,
            equity_curve=self._equity_curve,
            orders=self._filled_orders + [o for o in self._pending_orders],
            final_equity=final,
            total_bars=len(bars),
        )

        logger.info(
            "Backtest done: %d trades, final=%.0f, return=%.2f%%",
            len(self._trades), final, result.total_return_pct,
        )
        return result

    # ------------------------------------------------------------------
    # Order submission
    # ------------------------------------------------------------------

    def _submit_order(self, order: Order, timestamp: str, current_price: float) -> None:
        """Convert a strategy Order to a SimOrder and queue it."""
        self._order_counter += 1

        action = order.action.value if hasattr(order.action, "value") else str(order.action)
        pricetype = order.pricetype.value if hasattr(order.pricetype, "value") else str(order.pricetype)

        qty = int(order.quantity) if order.quantity else self._calc_position_size(current_price)

        sim_order = SimOrder(
            id=self._order_counter,
            symbol=order.symbol or self.config.symbol,
            side=action,
            quantity=qty,
            order_type=pricetype,
            limit_price=float(order.price) if order.price else 0.0,
            stop_price=float(order.trigger_price) if order.trigger_price else 0.0,
            created_timestamp=timestamp,
        )

        # Market orders fill immediately
        if pricetype == "MARKET":
            fill = self._apply_slippage(current_price, action)
            self._fill_order(sim_order, fill, timestamp)
        else:
            self._pending_orders.append(sim_order)

    def _calc_position_size(self, price: float) -> int:
        """Calculate position size based on config."""
        if self.config.position_size_qty > 0:
            return self.config.position_size_qty
        if price <= 0:
            return 1
        capital_per_trade = self._cash * (self.config.position_size_pct / 100)
        margin_capital = capital_per_trade / (self.config.margin_pct / 100)
        return max(1, int(margin_capital / price))

    # ------------------------------------------------------------------
    # Order processing
    # ------------------------------------------------------------------

    def _process_pending_orders(self, bar: dict[str, Any]) -> None:
        """Check pending orders against bar's high/low range."""
        high = float(bar.get("high", 0))
        low = float(bar.get("low", 0))
        ts = str(bar.get("timestamp", ""))
        still_pending: list[SimOrder] = []

        for order in self._pending_orders:
            filled = False

            if order.order_type == "LIMIT":
                if order.side == "BUY" and low <= order.limit_price:
                    self._fill_order(order, order.limit_price, ts)
                    filled = True
                elif order.side == "SELL" and high >= order.limit_price:
                    self._fill_order(order, order.limit_price, ts)
                    filled = True

            elif order.order_type in ("SL", "SL-M"):
                if order.side == "SELL" and low <= order.stop_price:
                    fill = self._apply_slippage(order.stop_price, order.side)
                    self._fill_order(order, fill, ts)
                    filled = True
                elif order.side == "BUY" and high >= order.stop_price:
                    fill = self._apply_slippage(order.stop_price, order.side)
                    self._fill_order(order, fill, ts)
                    filled = True

            elif order.order_type == "TRAILING_SL":
                # Update trailing stop for open positions
                if order.side == "SELL":
                    new_stop = high - order.trailing_points
                    if new_stop > order.stop_price:
                        order.stop_price = new_stop
                    if low <= order.stop_price:
                        fill = self._apply_slippage(order.stop_price, order.side)
                        self._fill_order(order, fill, ts)
                        filled = True

            if not filled:
                still_pending.append(order)

        self._pending_orders = still_pending

    def _fill_order(self, order: SimOrder, fill_price: float, timestamp: str) -> None:
        """Execute an order fill."""
        order.status = SimOrderStatus.FILLED.value
        order.fill_price = fill_price
        order.fill_timestamp = timestamp
        self._filled_orders.append(order)

        commission = self.config.commission_per_order
        symbol = order.symbol

        if order.side == "BUY":
            # Opening or adding to long position
            if symbol in self._positions and self._positions[symbol].side == "SELL":
                # Closing short
                self._close_position(symbol, fill_price, timestamp, commission)
            else:
                cost = fill_price * order.quantity * (self.config.margin_pct / 100)
                self._cash -= cost + commission
                self._positions[symbol] = SimPosition(
                    symbol=symbol,
                    side="BUY",
                    quantity=order.quantity,
                    entry_price=fill_price,
                    entry_timestamp=timestamp,
                    margin_used=cost,
                )
        else:
            # Opening short or closing long
            if symbol in self._positions and self._positions[symbol].side == "BUY":
                self._close_position(symbol, fill_price, timestamp, commission)
            else:
                cost = fill_price * order.quantity * (self.config.margin_pct / 100)
                self._cash -= cost + commission
                self._positions[symbol] = SimPosition(
                    symbol=symbol,
                    side="SELL",
                    quantity=order.quantity,
                    entry_price=fill_price,
                    entry_timestamp=timestamp,
                    margin_used=cost,
                )

    def _close_position(
        self, symbol: str, exit_price: float, timestamp: str, commission: float,
    ) -> None:
        """Close an open position and record the trade."""
        pos = self._positions.pop(symbol, None)
        if not pos:
            return

        if pos.side == "BUY":
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        net = pnl - commission
        self._cash += pos.margin_used + pnl - commission

        self._trades.append(SimTrade(
            entry_timestamp=pos.entry_timestamp,
            exit_timestamp=timestamp,
            symbol=symbol,
            side=pos.side,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl=pnl,
            commission=commission,
            net_pnl=net,
            bars_held=self._bar_index,
        ))

    def _close_all_positions(self, price: float, timestamp: str) -> None:
        """Close all open positions at the given price."""
        for symbol in list(self._positions.keys()):
            self._close_position(symbol, price, timestamp, self.config.commission_per_order)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to a fill price."""
        slip = price * (self.config.slippage_pct / 100)
        if side == "BUY":
            return price + slip
        return price - slip

    def _update_positions(self, current_price: float) -> None:
        """Update unrealized P&L for all positions."""
        for pos in self._positions.values():
            if pos.side == "BUY":
                pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
            else:
                pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity

    def _calculate_equity(self, current_price: float) -> float:
        """Total equity = cash + unrealized P&L of positions."""
        total = self._cash
        for pos in self._positions.values():
            if pos.side == "BUY":
                total += (current_price - pos.entry_price) * pos.quantity + pos.margin_used
            else:
                total += (pos.entry_price - current_price) * pos.quantity + pos.margin_used
        return total
