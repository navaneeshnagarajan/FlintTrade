"""Event-driven backtest engine.

Upgrades the existing BacktestSimulator with:
- STOP and STOP_LIMIT order types (in addition to MARKET and LIMIT)
- Tick-level and bar-level execution modes
- Configurable slippage (basis points) and commission (flat or percentage)
- Multi-symbol position tracking with long/short, partial fills, and averaging
- Trade log with round-trip P&L, holding duration, and tax integration
- Equity curve with per-bar drawdown tracking
- Progress callback for async UI integration

Usage::

    from .engine import BacktestEngine, EngineConfig
    from .base_strategy import BaseStrategy

    config = EngineConfig(
        symbol="NIFTY",
        exchange="NSE",
        initial_capital=Decimal("1000000"),
        slippage_bps=Decimal("2"),
        commission_per_order=Decimal("20"),
    )
    engine = BacktestEngine(config)
    engine.set_strategy(strategy_instance)
    result = engine.run(bars)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger("flinttrade.backtest.engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TWO_PLACES = Decimal("0.01")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OrderSide(StrEnum):
    """Side of the order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Order type — controls fill logic."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"           # Stop-market: triggers at stop_price, fills at market
    STOP_LIMIT = "STOP_LIMIT"  # Stop-limit: triggers at stop_price, limit at limit_price


class OrderStatus(StrEnum):
    """Current lifecycle status of an order."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class FillMode(StrEnum):
    """How fills are computed from bar data."""

    NEXT_OPEN = "NEXT_OPEN"  # Market orders fill at next bar open (realistic)
    CURRENT_CLOSE = "CURRENT_CLOSE"  # Fills at current bar close (simplified)


# ---------------------------------------------------------------------------
# Pydantic-style dataclasses (using stdlib dataclasses for zero-dependency)
# ---------------------------------------------------------------------------


@dataclass
class EngineConfig:
    """Configuration for a BacktestEngine run.

    All monetary values use Decimal for precision.

    Attributes:
        symbol: Primary symbol being backtested.
        exchange: Exchange (NSE, BSE, MCX, etc.).
        initial_capital: Starting capital in INR.
        slippage_bps: Slippage per fill in basis points (1 bps = 0.01%).
        commission_per_order: Fixed brokerage per order in INR.
        commission_pct: Percentage brokerage (applied on top of fixed fee).
        margin_pct: Margin percentage (100 = full cash, 20 = 5x leverage).
        position_size_pct: Default % of capital per trade (0 = use qty).
        position_size_qty: Fixed quantity per trade (0 = use pct).
        fill_mode: How market orders are filled relative to bars.
        allow_short: Whether short selling is permitted.
        tax_enabled: Apply Indian tax charges (STT, GST, etc.).
        instrument_type: equity_delivery | equity_intraday | fo (F&O).
    """

    symbol: str = "UNKNOWN"
    exchange: str = "NSE"
    initial_capital: Decimal = field(default_factory=lambda: Decimal(1000000))
    slippage_bps: Decimal = field(default_factory=lambda: Decimal(2))
    commission_per_order: Decimal = field(default_factory=lambda: Decimal(20))
    commission_pct: Decimal = field(default_factory=lambda: Decimal(0))
    margin_pct: Decimal = field(default_factory=lambda: Decimal(100))
    position_size_pct: Decimal = field(default_factory=lambda: Decimal(10))
    position_size_qty: int = 0
    fill_mode: FillMode = FillMode.NEXT_OPEN
    allow_short: bool = False
    tax_enabled: bool = True
    instrument_type: str = "fo"  # fo | equity_delivery | equity_intraday


@dataclass
class EngineOrder:
    """An order within the engine.

    Attributes:
        id: Unique order identifier.
        symbol: Instrument symbol.
        side: BUY or SELL.
        order_type: MARKET, LIMIT, STOP, STOP_LIMIT.
        quantity: Requested quantity.
        limit_price: Limit price (for LIMIT and STOP_LIMIT orders).
        stop_price: Stop trigger price (for STOP and STOP_LIMIT orders).
        status: Current order status.
        filled_quantity: Cumulative filled quantity so far.
        avg_fill_price: Volume-weighted average fill price.
        submitted_at: Timestamp when submitted.
        filled_at: Timestamp of last (or full) fill.
        stop_triggered: Whether the stop trigger has fired.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: int = 0
    limit_price: Decimal = Decimal(0)
    stop_price: Decimal = Decimal(0)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: Decimal = Decimal(0)
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    stop_triggered: bool = False

    @property
    def remaining_quantity(self) -> int:
        """Unfilled quantity remaining."""
        return self.quantity - self.filled_quantity

    @property
    def is_active(self) -> bool:
        """True if the order can still receive fills."""
        return self.status in (OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.PARTIAL)


@dataclass
class EnginePosition:
    """An open position in a symbol.

    Attributes:
        symbol: Instrument symbol.
        side: BUY (long) or SELL (short).
        quantity: Total open quantity.
        avg_cost: Volume-weighted average cost per unit.
        last_price: Most recent market price.
        opened_at: Timestamp of first entry.
    """

    symbol: str
    side: OrderSide
    quantity: int
    avg_cost: Decimal
    last_price: Decimal = Decimal(0)
    opened_at: datetime | None = None

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized P&L at last_price."""
        if self.side == OrderSide.BUY:
            return (self.last_price - self.avg_cost) * self.quantity
        return (self.avg_cost - self.last_price) * self.quantity

    @property
    def market_value(self) -> Decimal:
        """Current market value of the position."""
        return self.last_price * self.quantity


@dataclass
class EngineTrade:
    """A completed round-trip trade.

    Attributes:
        id: Trade identifier (matches closing order ID).
        symbol: Instrument symbol.
        side: BUY (long round-trip) or SELL (short round-trip).
        quantity: Trade quantity.
        entry_price: Weighted average entry price.
        exit_price: Weighted average exit price.
        entry_time: Entry timestamp.
        exit_time: Exit timestamp.
        gross_pnl: Raw P&L before charges.
        charges: Total transaction charges (commission + tax).
        net_pnl: Net P&L after all charges.
        holding_seconds: Duration in seconds.
        is_intraday: True if entry and exit on same calendar day.
    """

    id: str
    symbol: str
    side: OrderSide
    quantity: int
    entry_price: Decimal
    exit_price: Decimal
    entry_time: datetime
    exit_time: datetime
    gross_pnl: Decimal
    charges: Decimal
    net_pnl: Decimal
    holding_seconds: float = 0.0
    is_intraday: bool = False

    @property
    def holding_hours(self) -> float:
        """Holding duration in hours."""
        return self.holding_seconds / 3600.0

    @property
    def return_pct(self) -> float:
        """Return percentage on entry capital."""
        cost = float(self.entry_price) * self.quantity
        if cost == 0:
            return 0.0
        return float(self.net_pnl) / cost * 100


@dataclass
class EngineEquityPoint:
    """Single point on the equity curve.

    Attributes:
        timestamp: Bar timestamp (ISO string).
        equity: Total portfolio equity.
        cash: Available cash.
        positions_value: Unrealized P&L of open positions.
        drawdown_pct: Drawdown from peak as percentage.
    """

    timestamp: str
    equity: Decimal
    cash: Decimal
    positions_value: Decimal
    drawdown_pct: Decimal = Decimal(0)


@dataclass
class EngineResult:
    """Complete output from a BacktestEngine run.

    Attributes:
        config: The engine configuration used.
        trades: All completed round-trip trades.
        equity_curve: Per-bar equity snapshot.
        orders: All submitted orders (filled, cancelled, rejected).
        final_equity: Terminal equity value.
        total_bars: Number of bars processed.
        execution_seconds: Wall-clock time for the run.
        error: Non-empty string if the run failed.
    """

    config: EngineConfig
    trades: list[EngineTrade] = field(default_factory=list)
    equity_curve: list[EngineEquityPoint] = field(default_factory=list)
    orders: list[EngineOrder] = field(default_factory=list)
    final_equity: Decimal = Decimal(0)
    total_bars: int = 0
    execution_seconds: float = 0.0
    error: str = ""

    @property
    def total_return_pct(self) -> float:
        """Total return percentage from initial capital."""
        ic = float(self.config.initial_capital)
        if ic <= 0:
            return 0.0
        return (float(self.final_equity) - ic) / ic * 100


# ---------------------------------------------------------------------------
# BacktestEngine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Event-driven backtest engine.

    Processes historical bars one at a time, feeding each bar to the
    registered strategy's ``on_bar`` method, collecting orders, simulating
    fills, updating positions and the equity curve.

    Supports:
    - MARKET, LIMIT, STOP, STOP_LIMIT order types
    - Bar-level and tick-level execution (controlled by FillMode)
    - Configurable slippage (basis points) and commission
    - Multi-symbol positions with averaging on re-entry
    - Optional Indian tax charges via TaxCalculator integration
    - Async progress callback for UI integration

    Args:
        config: Engine configuration (EngineConfig).
    """

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self._cash: Decimal = config.initial_capital
        self._positions: dict[str, EnginePosition] = {}
        self._pending_orders: list[EngineOrder] = []
        self._all_orders: list[EngineOrder] = []
        self._trades: list[EngineTrade] = []
        self._equity_curve: list[EngineEquityPoint] = []

        self._peak_equity: Decimal = config.initial_capital
        self._bar_index: int = 0
        self._current_time: datetime | None = None
        self._is_running: bool = False
        self._strategy: Any | None = None  # BaseStrategy
        self._progress_callback: Callable | None = None

        # Lazy import to avoid circular dependency
        self._tax_calculator: Any | None = None
        if config.tax_enabled:
            from .tax_calculator import IndianTaxCalculator
            self._tax_calculator = IndianTaxCalculator(instrument_type=config.instrument_type)

        logger.info(
            "BacktestEngine initialised: symbol=%s capital=%s slippage=%sbps commission=%s",
            config.symbol, config.initial_capital,
            config.slippage_bps, config.commission_per_order,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_strategy(self, strategy: Any) -> None:
        """Register the strategy that will receive bar callbacks.

        Args:
            strategy: An instance that implements BaseStrategy (on_bar, generate_orders).
        """
        self._strategy = strategy
        if hasattr(strategy, "set_engine"):
            strategy.set_engine(self)
        logger.debug("Strategy registered: %s", getattr(strategy, "name", type(strategy).__name__))

    def set_progress_callback(self, callback: Callable) -> None:
        """Register an async/sync callback for progress updates.

        The callback receives a status dict on every 100th bar.

        Args:
            callback: Callable accepting a dict.
        """
        self._progress_callback = callback

    def submit_order(self, order: EngineOrder) -> bool:
        """Submit an order from outside the bar loop (e.g. from strategy).

        Args:
            order: The EngineOrder to submit.

        Returns:
            True if the order was accepted, False if rejected.
        """
        return self._accept_order(order)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID.

        Args:
            order_id: The ID of the order to cancel.

        Returns:
            True if found and cancelled.
        """
        for order in self._pending_orders:
            if order.id == order_id and order.is_active:
                order.status = OrderStatus.CANCELLED
                logger.debug("Order %s cancelled", order_id)
                return True
        return False

    def get_position(self, symbol: str) -> EnginePosition | None:
        """Return the current open position for a symbol, or None.

        Args:
            symbol: Instrument symbol.
        """
        return self._positions.get(symbol)

    def get_cash(self) -> Decimal:
        """Return current available cash."""
        return self._cash

    def get_equity(self) -> Decimal:
        """Return current total equity (cash + unrealized P&L)."""
        return self._calculate_equity()

    def run(self, bars: list[dict[str, Any]]) -> EngineResult:
        """Run a full backtest over historical bars.

        Args:
            bars: List of OHLCV dicts. Each dict must contain:
                  timestamp (str), open, high, low, close (float),
                  volume (int). Optional: oi (int).

        Returns:
            EngineResult with complete backtest output.
        """
        if not bars:
            return EngineResult(
                config=self.config,
                error="No bars provided",
                final_equity=self._cash,
            )
        if self._strategy is None:
            return EngineResult(
                config=self.config,
                error="No strategy set — call set_strategy() before run()",
                final_equity=self._cash,
            )

        self._is_running = True
        start_wall = time.perf_counter()

        if hasattr(self._strategy, "start"):
            self._strategy.start()

        logger.info(
            "BacktestEngine.run: symbol=%s bars=%d capital=%s",
            self.config.symbol, len(bars), self.config.initial_capital,
        )

        for i, bar in enumerate(bars):
            if not self._is_running:
                logger.info("Backtest stopped early at bar %d", i)
                break

            self._bar_index = i
            ts = str(bar.get("timestamp", ""))
            self._current_time = self._parse_timestamp(ts)

            open_p = Decimal(str(bar.get("open", 0)))
            high_p = Decimal(str(bar.get("high", 0)))
            low_p = Decimal(str(bar.get("low", 0)))
            close_p = Decimal(str(bar.get("close", 0)))

            # 1. Process pending orders (against this bar's range)
            self._process_pending_orders(bar, open_p, high_p, low_p, close_p, ts)

            # 2. Update unrealized P&L for open positions
            self._update_positions(close_p)

            # 3. Feed bar to strategy
            if self._strategy:
                try:
                    # Support both dict-based and OHLCV-model strategies
                    if hasattr(self._strategy, "on_bar"):
                        self._strategy.on_bar(_make_ohlcv(bar))
                except Exception as exc:
                    logger.error("Strategy on_bar error at bar %d (%s): %s", i, ts, exc)
                    if hasattr(self._strategy, "set_error"):
                        self._strategy.set_error(str(exc))
                    break

            # 4. Collect and submit orders from strategy
            if self._strategy and hasattr(self._strategy, "generate_orders"):
                try:
                    new_orders = self._strategy.generate_orders() or []
                except Exception as exc:
                    logger.error("Strategy generate_orders error: %s", exc)
                    new_orders = []

                for raw_order in new_orders:
                    engine_order = self._convert_strategy_order(raw_order, close_p, ts)
                    if engine_order:
                        self._accept_order(engine_order)

            # 5. Immediately fill market orders placed this bar (CURRENT_CLOSE mode)
            if self.config.fill_mode == FillMode.CURRENT_CLOSE:
                self._fill_immediate_market_orders(close_p, ts)

            # 6. Record equity
            equity = self._calculate_equity()
            if equity > self._peak_equity:
                self._peak_equity = equity
            dd_pct = (
                (self._peak_equity - equity) / self._peak_equity * 100
                if self._peak_equity > 0
                else Decimal(0)
            )
            self._equity_curve.append(EngineEquityPoint(
                timestamp=ts,
                equity=equity,
                cash=self._cash,
                positions_value=equity - self._cash,
                drawdown_pct=dd_pct.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            ))

            # Progress callback every 100 bars
            if self._progress_callback and i % 100 == 0:
                status = self._build_status(i, len(bars))
                try:
                    result = self._progress_callback(status)
                    # Support both sync and async callbacks
                    if hasattr(result, "__await__"):
                        import asyncio
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(result)
                            else:
                                loop.run_until_complete(result)
                        except RuntimeError:
                            pass
                except Exception as exc:
                    logger.debug("Progress callback error: %s", exc)

        # Close remaining positions at last bar's close
        if bars and self._positions:
            last_close = Decimal(str(bars[-1].get("close", 0)))
            last_ts = str(bars[-1].get("timestamp", ""))
            for symbol in list(self._positions.keys()):
                self._close_position(symbol, last_close, last_ts, reason="end_of_backtest")

        if hasattr(self._strategy, "stop"):
            self._strategy.stop()

        self._is_running = False
        execution_seconds = time.perf_counter() - start_wall

        final_equity = self._calculate_equity()

        result = EngineResult(
            config=self.config,
            trades=list(self._trades),
            equity_curve=list(self._equity_curve),
            orders=list(self._all_orders),
            final_equity=final_equity,
            total_bars=len(bars),
            execution_seconds=execution_seconds,
        )

        logger.info(
            "BacktestEngine.run done: bars=%d trades=%d final_equity=%s return=%.2f%% time=%.2fs",
            len(bars), len(self._trades), final_equity,
            result.total_return_pct, execution_seconds,
        )
        return result

    def stop(self) -> None:
        """Request early termination of the run loop."""
        self._is_running = False

    # ------------------------------------------------------------------
    # Order acceptance
    # ------------------------------------------------------------------

    def _accept_order(self, order: EngineOrder) -> bool:
        """Validate and queue an order.

        Args:
            order: Order to accept.

        Returns:
            True if accepted.
        """
        if order.quantity <= 0:
            logger.warning("Order rejected: quantity %d <= 0", order.quantity)
            order.status = OrderStatus.REJECTED
            self._all_orders.append(order)
            return False

        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and order.limit_price <= 0:
            logger.warning("Order rejected: LIMIT/STOP_LIMIT with no limit_price")
            order.status = OrderStatus.REJECTED
            self._all_orders.append(order)
            return False

        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and order.stop_price <= 0:
            logger.warning("Order rejected: STOP/STOP_LIMIT with no stop_price")
            order.status = OrderStatus.REJECTED
            self._all_orders.append(order)
            return False

        # Simplified cash check for BUY market orders
        if order.side == OrderSide.BUY and order.order_type == OrderType.MARKET:
            est_price = self._last_price(order.symbol)
            if est_price > 0:
                est_cost = est_price * order.quantity
                if self._cash < est_cost:
                    logger.debug(
                        "Order rejected: insufficient cash %.2f < %.2f",
                        float(self._cash), float(est_cost),
                    )
                    order.status = OrderStatus.REJECTED
                    self._all_orders.append(order)
                    return False

        order.status = OrderStatus.SUBMITTED
        order.submitted_at = self._current_time
        self._pending_orders.append(order)
        self._all_orders.append(order)
        logger.debug(
            "Order accepted: %s %s %d %s lp=%s sp=%s",
            order.id, order.side, order.quantity, order.order_type,
            order.limit_price, order.stop_price,
        )
        return True

    # ------------------------------------------------------------------
    # Order processing
    # ------------------------------------------------------------------

    def _process_pending_orders(
        self,
        bar: dict[str, Any],
        open_p: Decimal,
        high_p: Decimal,
        low_p: Decimal,
        close_p: Decimal,
        ts: str,
    ) -> None:
        """Attempt to fill all pending orders against the current bar.

        Args:
            bar: Raw bar dict.
            open_p: Bar open price.
            high_p: Bar high price.
            low_p: Bar low price.
            close_p: Bar close price.
            ts: Bar timestamp string.
        """
        still_pending: list[EngineOrder] = []

        for order in self._pending_orders:
            if not order.is_active:
                continue

            fill_price: Decimal | None = None

            if order.order_type == OrderType.MARKET:
                # NEXT_OPEN mode: fill at this bar's open (order was submitted previous bar)
                if self.config.fill_mode == FillMode.NEXT_OPEN:
                    fill_price = open_p
                # CURRENT_CLOSE handled separately in _fill_immediate_market_orders

            elif order.order_type == OrderType.LIMIT:
                fill_price = self._check_limit_fill(order, high_p, low_p)

            elif order.order_type == OrderType.STOP:
                # Step 1: check if stop triggers
                if not order.stop_triggered:
                    triggered = self._check_stop_trigger(order, high_p, low_p)
                    if triggered:
                        order.stop_triggered = True
                # Step 2: if triggered, fill at market
                if order.stop_triggered:
                    fill_price = self._apply_slippage(open_p, order.side)

            elif order.order_type == OrderType.STOP_LIMIT:
                # Step 1: trigger
                if not order.stop_triggered:
                    triggered = self._check_stop_trigger(order, high_p, low_p)
                    if triggered:
                        order.stop_triggered = True
                # Step 2: fill at limit
                if order.stop_triggered:
                    fill_price = self._check_limit_fill(order, high_p, low_p)

            if fill_price is not None:
                slipped = self._apply_slippage(fill_price, order.side)
                filled = self._execute_fill(order, slipped, order.quantity, ts)
                if not filled:
                    still_pending.append(order)
            else:
                still_pending.append(order)

        # Remove active duplicates already in still_pending
        self._pending_orders = [o for o in still_pending if o.is_active]

    def _fill_immediate_market_orders(self, close_p: Decimal, ts: str) -> None:
        """Fill market orders at current bar close (CURRENT_CLOSE mode).

        Args:
            close_p: Bar close price.
            ts: Bar timestamp.
        """
        still_pending: list[EngineOrder] = []
        for order in self._pending_orders:
            if order.order_type == OrderType.MARKET and order.is_active:
                slipped = self._apply_slippage(close_p, order.side)
                self._execute_fill(order, slipped, order.quantity, ts)
            else:
                still_pending.append(order)
        self._pending_orders = [o for o in still_pending if o.is_active]

    def _check_limit_fill(
        self, order: EngineOrder, high_p: Decimal, low_p: Decimal
    ) -> Decimal | None:
        """Return fill price if a limit order can execute, else None.

        Args:
            order: Limit order.
            high_p: Bar high.
            low_p: Bar low.

        Returns:
            Fill price or None.
        """
        if order.side == OrderSide.BUY and low_p <= order.limit_price:
            return min(order.limit_price, low_p)
        if order.side == OrderSide.SELL and high_p >= order.limit_price:
            return max(order.limit_price, high_p)
        return None

    def _check_stop_trigger(
        self, order: EngineOrder, high_p: Decimal, low_p: Decimal
    ) -> bool:
        """Return True if a stop order's trigger price is hit.

        Args:
            order: Stop order.
            high_p: Bar high.
            low_p: Bar low.

        Returns:
            True if triggered.
        """
        # BUY stop triggers when price rises through stop_price
        if order.side == OrderSide.BUY and high_p >= order.stop_price:
            return True
        # SELL stop triggers when price falls through stop_price
        if order.side == OrderSide.SELL and low_p <= order.stop_price:
            return True
        return False

    # ------------------------------------------------------------------
    # Fill execution and position management
    # ------------------------------------------------------------------

    def _execute_fill(
        self, order: EngineOrder, fill_price: Decimal, quantity: int, ts: str
    ) -> bool:
        """Execute a fill for an order.

        Updates the order, position, cash, and trade log.

        Args:
            order: The order being filled.
            fill_price: Price at which the fill occurs.
            quantity: Quantity to fill.
            ts: Timestamp string.

        Returns:
            True if fill was executed successfully.
        """
        commission = self._calculate_commission(quantity, fill_price)
        symbol = order.symbol or self.config.symbol

        if order.side == OrderSide.BUY:
            total_cost = fill_price * quantity + commission
            if self._cash < total_cost:
                logger.debug(
                    "Fill rejected: insufficient cash %.2f for %.2f cost",
                    float(self._cash), float(total_cost),
                )
                order.status = OrderStatus.REJECTED
                return False

            self._cash -= total_cost

            if symbol in self._positions and self._positions[symbol].side == OrderSide.BUY:
                # Average up/down existing long position
                pos = self._positions[symbol]
                total_qty = pos.quantity + quantity
                pos.avg_cost = (
                    (pos.avg_cost * pos.quantity + fill_price * quantity) / total_qty
                ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
                pos.quantity = total_qty
            elif symbol in self._positions and self._positions[symbol].side == OrderSide.SELL:
                # Close short position
                self._close_position(symbol, fill_price, ts, closing_order_id=order.id)
                self._cash += commission  # Refund since close_position charges its own
            else:
                self._positions[symbol] = EnginePosition(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=quantity,
                    avg_cost=fill_price,
                    last_price=fill_price,
                    opened_at=self._current_time,
                )

        else:  # SELL
            if symbol in self._positions and self._positions[symbol].side == OrderSide.BUY:
                # Close or reduce long position
                self._close_position(
                    symbol, fill_price, ts,
                    close_qty=quantity,
                    closing_order_id=order.id,
                )
                self._cash -= commission
            elif self.config.allow_short:
                # Open short position
                margin_req = fill_price * quantity * (self.config.margin_pct / 100)
                self._cash -= margin_req + commission
                self._positions[symbol] = EnginePosition(
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=quantity,
                    avg_cost=fill_price,
                    last_price=fill_price,
                    opened_at=self._current_time,
                )
            else:
                logger.debug("SELL order %s rejected: no long position and short not allowed", order.id)
                order.status = OrderStatus.REJECTED
                return False

        # Update order fill state
        order.filled_quantity += quantity
        # VWAP fill price update
        if order.avg_fill_price == 0:
            order.avg_fill_price = fill_price
        else:
            total_filled = order.filled_quantity
            order.avg_fill_price = (
                (order.avg_fill_price * (total_filled - quantity) + fill_price * quantity)
                / total_filled
            ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        order.filled_at = self._current_time

        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIAL

        # Notify strategy
        if self._strategy and hasattr(self._strategy, "on_order_update"):
            try:
                self._strategy.on_order_update(order)
            except Exception as exc:
                logger.debug("on_order_update error: %s", exc)

        logger.debug(
            "Fill: %s %s %d @ %s commission=%s",
            order.side, symbol, quantity, fill_price, commission,
        )
        return True

    def _close_position(
        self,
        symbol: str,
        exit_price: Decimal,
        ts: str,
        close_qty: int | None = None,
        closing_order_id: str = "",
        reason: str = "signal",
    ) -> None:
        """Record a completed trade and update position/cash.

        Args:
            symbol: Symbol to close.
            exit_price: Exit price per unit.
            ts: Timestamp string.
            close_qty: Partial close quantity (None = full position).
            closing_order_id: ID of the closing order for tracking.
            reason: Reason for closing (signal, end_of_backtest, etc.).
        """
        pos = self._positions.get(symbol)
        if pos is None:
            return

        qty = close_qty if close_qty is not None else pos.quantity
        qty = min(qty, pos.quantity)

        if pos.side == OrderSide.BUY:
            gross_pnl = (exit_price - pos.avg_cost) * qty
        else:
            gross_pnl = (pos.avg_cost - exit_price) * qty

        commission = self._calculate_commission(qty, exit_price)

        # Indian tax charges
        tax_charges = Decimal(0)
        if self._tax_calculator is not None:
            entry_dt = pos.opened_at
            exit_dt = self._current_time
            is_intraday = (
                entry_dt is not None
                and exit_dt is not None
                and entry_dt.date() == exit_dt.date()
            )
            from .tax_calculator import TradeType
            trade_type = TradeType.INTRADAY if is_intraday else TradeType.DELIVERY
            if "fo" in self.config.instrument_type.lower():
                trade_type = TradeType.FO
            breakdown = self._tax_calculator.calculate(
                trade_value=exit_price * qty,
                trade_type=trade_type,
                is_buy=False,
            )
            tax_charges = breakdown.total_charges

        total_charges = commission + tax_charges
        net_pnl = gross_pnl - total_charges

        # Return margin/proceeds to cash
        if pos.side == OrderSide.BUY:
            self._cash += exit_price * qty - total_charges
        else:
            # Short: return margin + profit/loss
            margin_returned = pos.avg_cost * qty * (self.config.margin_pct / 100)
            self._cash += margin_returned + gross_pnl - total_charges

        # Determine intraday status
        entry_dt = pos.opened_at
        exit_dt = self._current_time
        is_intraday = (
            entry_dt is not None
            and exit_dt is not None
            and entry_dt.date() == exit_dt.date()
        )
        holding_secs = 0.0
        if entry_dt and exit_dt:
            holding_secs = (exit_dt - entry_dt).total_seconds()

        trade = EngineTrade(
            id=closing_order_id or str(uuid.uuid4())[:8],
            symbol=symbol,
            side=pos.side,
            quantity=qty,
            entry_price=pos.avg_cost,
            exit_price=exit_price,
            entry_time=entry_dt or exit_dt or datetime.now(),
            exit_time=exit_dt or datetime.now(),
            gross_pnl=gross_pnl.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            charges=total_charges.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            net_pnl=net_pnl.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
            holding_seconds=holding_secs,
            is_intraday=is_intraday,
        )
        self._trades.append(trade)

        if self._strategy and hasattr(self._strategy, "on_trade"):
            try:
                self._strategy.on_trade(trade)
            except Exception as exc:
                logger.debug("on_trade callback error: %s", exc)

        # Update or remove position
        if qty >= pos.quantity:
            del self._positions[symbol]
        else:
            pos.quantity -= qty

        logger.debug(
            "Trade closed: %s %s %d @ %s net_pnl=%s reason=%s",
            pos.side, symbol, qty, exit_price, net_pnl, reason,
        )

    # ------------------------------------------------------------------
    # Pricing helpers
    # ------------------------------------------------------------------

    def _apply_slippage(self, price: Decimal, side: OrderSide) -> Decimal:
        """Apply slippage in basis points to a fill price.

        Buys pay more; sells receive less.

        Args:
            price: Pre-slippage price.
            side: Order side.

        Returns:
            Post-slippage price.
        """
        slip = price * self.config.slippage_bps / Decimal(10000)
        if side == OrderSide.BUY:
            return (price + slip).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        return (price - slip).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def _calculate_commission(self, quantity: int, price: Decimal) -> Decimal:
        """Calculate brokerage commission for a fill.

        Args:
            quantity: Fill quantity.
            price: Fill price.

        Returns:
            Total commission in INR.
        """
        pct_fee = price * quantity * self.config.commission_pct / Decimal(100)
        return (self.config.commission_per_order + pct_fee).quantize(
            _TWO_PLACES, rounding=ROUND_HALF_UP
        )

    def _calculate_equity(self) -> Decimal:
        """Return total portfolio equity (cash + unrealized P&L)."""
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        return (self._cash + unrealized).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

    def _update_positions(self, close_p: Decimal) -> None:
        """Update last_price on all open positions.

        Args:
            close_p: Current bar close price.
        """
        for pos in self._positions.values():
            pos.last_price = close_p

    def _last_price(self, symbol: str) -> Decimal:
        """Return last known price for a symbol.

        Args:
            symbol: Instrument symbol.

        Returns:
            Last price or 0 if unknown.
        """
        pos = self._positions.get(symbol)
        if pos and pos.last_price > 0:
            return pos.last_price
        return Decimal(0)

    def _calc_position_size(self, price: Decimal) -> int:
        """Calculate default position size from config.

        Args:
            price: Current market price.

        Returns:
            Quantity to trade.
        """
        if self.config.position_size_qty > 0:
            return self.config.position_size_qty
        if price <= 0:
            return 1
        capital_per_trade = self._cash * (self.config.position_size_pct / Decimal(100))
        margin_adj = capital_per_trade / (self.config.margin_pct / Decimal(100))
        return max(1, int(margin_adj / price))

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _convert_strategy_order(
        self, raw_order: Any, current_price: Decimal, ts: str
    ) -> EngineOrder | None:
        """Convert a strategy-emitted Order model to an EngineOrder.

        Handles both the FlintTrade core Order model and plain dicts.

        Args:
            raw_order: Order from strategy.generate_orders().
            current_price: Current close price (for market orders).
            ts: Timestamp string.

        Returns:
            EngineOrder or None if conversion fails.
        """
        try:
            if isinstance(raw_order, EngineOrder):
                return raw_order

            if isinstance(raw_order, dict):
                side_str = str(raw_order.get("action", raw_order.get("side", "BUY"))).upper()
                order_type_str = str(raw_order.get("pricetype", raw_order.get("order_type", "MARKET"))).upper()
                symbol = str(raw_order.get("symbol", self.config.symbol))
                qty = int(raw_order.get("quantity", 0)) or self._calc_position_size(current_price)
                limit_p = Decimal(str(raw_order.get("price", raw_order.get("limit_price", 0))))
                stop_p = Decimal(str(raw_order.get("trigger_price", raw_order.get("stop_price", 0))))
            else:
                # Assume FlintTrade core Order model
                action = getattr(raw_order, "action", None)
                side_str = action.value if hasattr(action, "value") else str(action).upper()
                pricetype = getattr(raw_order, "pricetype", None)
                order_type_str = pricetype.value if hasattr(pricetype, "value") else str(pricetype).upper()
                symbol = getattr(raw_order, "symbol", None) or self.config.symbol
                qty = int(getattr(raw_order, "quantity", 0) or 0) or self._calc_position_size(current_price)
                limit_p = Decimal(str(getattr(raw_order, "price", 0) or 0))
                stop_p = Decimal(str(getattr(raw_order, "trigger_price", 0) or 0))

            side = OrderSide.BUY if "BUY" in side_str else OrderSide.SELL
            order_type_map = {
                "MARKET": OrderType.MARKET,
                "LIMIT": OrderType.LIMIT,
                "SL": OrderType.STOP,
                "SL-M": OrderType.STOP,
                "STOP": OrderType.STOP,
                "STOP_LIMIT": OrderType.STOP_LIMIT,
            }
            order_type = order_type_map.get(order_type_str, OrderType.MARKET)

            return EngineOrder(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=qty,
                limit_price=limit_p,
                stop_price=stop_p,
            )
        except Exception as exc:
            logger.warning("Failed to convert strategy order: %s — %s", raw_order, exc)
            return None

    @staticmethod
    def _parse_timestamp(ts: str) -> datetime:
        """Parse a timestamp string into a datetime.

        Args:
            ts: Timestamp string (ISO 8601 or common date formats).

        Returns:
            Parsed datetime or current time on failure.
        """
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        return datetime.now()

    def _build_status(self, bar_index: int, total_bars: int) -> dict[str, Any]:
        """Build a status dict for the progress callback.

        Args:
            bar_index: Current bar index.
            total_bars: Total number of bars.

        Returns:
            Status dictionary.
        """
        equity = self._calculate_equity()
        return {
            "bar_index": bar_index,
            "total_bars": total_bars,
            "progress_pct": bar_index / total_bars * 100 if total_bars > 0 else 0,
            "equity": float(equity),
            "cash": float(self._cash),
            "open_positions": len(self._positions),
            "completed_trades": len(self._trades),
            "pending_orders": len(self._pending_orders),
        }


# ---------------------------------------------------------------------------
# Helper — minimal OHLCV object for strategy compatibility
# ---------------------------------------------------------------------------


class _OHLCVProxy:
    """Lightweight OHLCV proxy compatible with both dict-based and model-based strategies."""

    __slots__ = ("timestamp", "open", "high", "low", "close", "volume", "oi")

    def __init__(self, bar: dict[str, Any]) -> None:
        self.timestamp: str = str(bar.get("timestamp", ""))
        self.open: float = float(bar.get("open", 0))
        self.high: float = float(bar.get("high", 0))
        self.low: float = float(bar.get("low", 0))
        self.close: float = float(bar.get("close", 0))
        self.volume: int = int(bar.get("volume", 0))
        self.oi: int = int(bar.get("oi", 0))


def _make_ohlcv(bar: dict[str, Any]) -> Any:
    """Create an OHLCV object from a bar dict.

    Tries to use the FlintTrade core OHLCV model; falls back to _OHLCVProxy.

    Args:
        bar: Raw bar dict.

    Returns:
        OHLCV-compatible object.
    """
    try:
        from flinttrade_core.models import OHLCV
        return OHLCV(
            timestamp=str(bar.get("timestamp", "")),
            open=float(bar.get("open", 0)),
            high=float(bar.get("high", 0)),
            low=float(bar.get("low", 0)),
            close=float(bar.get("close", 0)),
            volume=int(bar.get("volume", 0)),
        )
    except ImportError:
        return _OHLCVProxy(bar)
