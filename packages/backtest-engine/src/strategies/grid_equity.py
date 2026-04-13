"""NSE Equity/Futures Grid Trading strategy.

Arithmetic grid strategy suited to Indian equity and index futures.

Strategy logic:
- Define an arithmetic grid between ``lower_bound`` and ``upper_bound``
  divided into ``n_grids`` equal intervals.
- Buy at each grid level when price moves down through the level.
- Sell at each grid level when price moves up through the level.
- Hard stop-loss one grid-spacing below ``lower_bound``.
- Take-profit one grid-spacing above ``upper_bound``.
- Auto-reset when price breaks out of the grid (above upper or below lower),
  preserving flat position until re-entry conditions are met.

Initial mode:
- ``"wait_for_buy"`` (default): wait for price to enter the grid from above
  (i.e. price falls below ``upper_bound``) before activating.
- ``"immediate"``: activate as soon as the strategy starts, treating the
  current price as already inside the grid.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.grid_equity")


# ---------------------------------------------------------------------------
# GridConfig
# ---------------------------------------------------------------------------


@dataclass
class GridConfig:
    """Parameters for the arithmetic grid.

    Args:
        lower_bound:   Lowest grid level (price floor).  Stop-loss is placed
                       one grid-spacing below this.
        upper_bound:   Highest grid level (price ceiling).  Take-profit is
                       placed one grid-spacing above this.
        n_grids:       Number of equal grid intervals.  The strategy places
                       ``n_grids + 1`` horizontal levels.
        initial_mode:  ``"wait_for_buy"`` (default) — do not trade until
                       price first enters the grid from above.
                       ``"immediate"`` — start trading right away.

    Grid levels are computed as:
        ``levels[i] = lower_bound + i * (upper_bound - lower_bound) / n_grids``
        for ``i`` in ``range(n_grids + 1)``.

    Example::

        cfg = GridConfig(lower_bound=22000, upper_bound=24000, n_grids=10)
        # 11 levels: 22000, 22200, 22400, … 24000
        # grid_spacing = 200
        # stop_loss    = 21800 (22000 - 200)
        # take_profit  = 24200 (24000 + 200)
    """

    lower_bound: float
    upper_bound: float
    n_grids: int = 10
    initial_mode: str = "wait_for_buy"  # "wait_for_buy" | "immediate"

    def __post_init__(self) -> None:
        if self.lower_bound >= self.upper_bound:
            raise ValueError(
                f"lower_bound ({self.lower_bound}) must be less than "
                f"upper_bound ({self.upper_bound})"
            )
        if self.n_grids < 2:
            raise ValueError(f"n_grids must be >= 2, got {self.n_grids}")
        if self.initial_mode not in ("wait_for_buy", "immediate"):
            raise ValueError(
                f"initial_mode must be 'wait_for_buy' or 'immediate', "
                f"got {self.initial_mode!r}"
            )

    @property
    def grid_spacing(self) -> float:
        """Distance between adjacent grid levels."""
        return (self.upper_bound - self.lower_bound) / self.n_grids

    @property
    def stop_loss(self) -> float:
        """Hard stop-loss price — one spacing below lower_bound."""
        return self.lower_bound - self.grid_spacing

    @property
    def take_profit(self) -> float:
        """Take-profit price — one spacing above upper_bound."""
        return self.upper_bound + self.grid_spacing

    @property
    def levels(self) -> list[float]:
        """All ``n_grids + 1`` grid levels, ascending.

        Returns:
            List of price levels from ``lower_bound`` to ``upper_bound``.
        """
        spacing = self.grid_spacing
        return [
            self.lower_bound + i * spacing
            for i in range(self.n_grids + 1)
        ]


# ---------------------------------------------------------------------------
# GridEquityStrategy
# ---------------------------------------------------------------------------


class GridEquityStrategy(BaseStrategy, _BacktestStrategyMixin):
    """Arithmetic grid strategy for Indian equity and futures backtesting.

    On each bar close the strategy checks whether price has crossed a grid
    level since the previous bar.  Downward crosses generate BUY orders;
    upward crosses generate SELL orders.

    Stop-loss and take-profit are handled as hard price checks: when the
    bar close reaches the SL or TP boundary, all open positions are closed
    and the grid resets.

    After a breakout (price exits the grid range), the strategy auto-resets
    and waits for price to re-enter before trading again (``wait_for_buy``
    semantics: waits for price to fall below ``upper_bound`` from above).

    Args:
        config:        :class:`GridConfig` with grid parameters.
        symbol:        Instrument symbol (e.g. ``"NIFTY25APRFUT"``).
        exchange:      Exchange code (default ``"NFO"``).
        product:       Product type (default ``"MIS"``).
        qty_per_grid:  Quantity to trade at each grid level (default ``1``).

    Example::

        cfg  = GridConfig(lower_bound=22000, upper_bound=24000, n_grids=10)
        strat = GridEquityStrategy(config=cfg, symbol="NIFTY25APRFUT")
        strat.start()
        for bar in bars:
            strat.on_bar(bar)
            orders = strat.generate_orders()
    """

    def __init__(
        self,
        config: GridConfig,
        symbol: str = "",
        exchange: str = "NFO",
        product: str = "MIS",
        qty_per_grid: int = 1,
        **kwargs: Any,
    ) -> None:
        name = kwargs.pop("name", f"GridEquity_{symbol}_{config.lower_bound}_{config.upper_bound}")
        super().__init__(name=name, exchange=exchange, product=product)
        self._init_history()

        self.config = config
        self._symbol = symbol
        self.qty_per_grid = qty_per_grid

        # Pre-compute grid levels for fast lookup
        self._levels: list[float] = config.levels
        self._spacing: float = config.grid_spacing

        # Current grid index: index of the level just at-or-below price
        self._prev_grid_idx: int | None = None

        # Whether we have entered the grid at least once (initial_mode gate)
        self._grid_active: bool = config.initial_mode == "immediate"

        # Reset count for observability
        self._reset_count: int = 0

        logger.info(
            "GridEquityStrategy init: symbol=%s levels=%d spacing=%.2f "
            "SL=%.2f TP=%.2f initial_mode=%s",
            symbol, len(self._levels), self._spacing,
            config.stop_loss, config.take_profit, config.initial_mode,
        )

    # ------------------------------------------------------------------
    # BaseStrategy abstract method implementations
    # ------------------------------------------------------------------

    def on_tick(self, quote: Quote) -> None:
        """Not used — this strategy runs on bar closes."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — grid generates its own signals."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed OHLCV bar.

        Args:
            bar: Completed OHLCV bar with ``close`` price.
        """
        self._record_bar(bar)
        price = bar.close

        cfg = self.config

        # ----------------------------------------------------------------
        # Stop-loss check
        # ----------------------------------------------------------------
        if price <= cfg.stop_loss:
            if self._position != 0:
                logger.warning(
                    "Grid SL hit: price=%.2f SL=%.2f symbol=%s — closing",
                    price, cfg.stop_loss, self._symbol,
                )
                self._close_all(bar)
            self._reset_grid(reason="stop_loss", price=price)
            return

        # ----------------------------------------------------------------
        # Take-profit check
        # ----------------------------------------------------------------
        if price >= cfg.take_profit:
            if self._position != 0:
                logger.info(
                    "Grid TP hit: price=%.2f TP=%.2f symbol=%s — closing",
                    price, cfg.take_profit, self._symbol,
                )
                self._close_all(bar)
            self._reset_grid(reason="take_profit", price=price)
            return

        # ----------------------------------------------------------------
        # Breakout check (price outside grid but inside SL/TP)
        # ----------------------------------------------------------------
        if price > cfg.upper_bound:
            if self._grid_active:
                logger.info(
                    "Grid breakout above upper_bound: price=%.2f upper=%.2f symbol=%s",
                    price, cfg.upper_bound, self._symbol,
                )
                if self._position != 0:
                    self._close_all(bar)
                self._reset_grid(reason="breakout_above", price=price)
            return

        if price < cfg.lower_bound:
            if self._grid_active:
                logger.info(
                    "Grid breakout below lower_bound: price=%.2f lower=%.2f symbol=%s",
                    price, cfg.lower_bound, self._symbol,
                )
                if self._position != 0:
                    self._close_all(bar)
                self._reset_grid(reason="breakout_below", price=price)
            return

        # ----------------------------------------------------------------
        # Initial mode gate — wait for first entry from above
        # ----------------------------------------------------------------
        if not self._grid_active:
            if price <= cfg.upper_bound:
                self._grid_active = True
                logger.info(
                    "Grid activated: price=%.2f entered grid (upper=%.2f) symbol=%s",
                    price, cfg.upper_bound, self._symbol,
                )
            else:
                return  # still waiting

        # ----------------------------------------------------------------
        # Normal grid operation — detect grid level crosses
        # ----------------------------------------------------------------
        cur_idx = self._price_to_grid_idx(price)

        if self._prev_grid_idx is None:
            # First bar inside the grid — initialise without trading
            self._prev_grid_idx = cur_idx
            return

        if cur_idx < self._prev_grid_idx:
            # Price moved DOWN through one or more grid levels → BUY
            levels_crossed = self._prev_grid_idx - cur_idx
            for _ in range(levels_crossed):
                self._buy(str(self.qty_per_grid))
            logger.debug(
                "Grid BUY: price=%.2f idx=%d→%d levels_crossed=%d symbol=%s",
                price, self._prev_grid_idx, cur_idx, levels_crossed, self._symbol,
            )

        elif cur_idx > self._prev_grid_idx:
            # Price moved UP through one or more grid levels → SELL
            levels_crossed = cur_idx - self._prev_grid_idx
            for _ in range(levels_crossed):
                self._sell(str(self.qty_per_grid))
            logger.debug(
                "Grid SELL: price=%.2f idx=%d→%d levels_crossed=%d symbol=%s",
                price, self._prev_grid_idx, cur_idx, levels_crossed, self._symbol,
            )

        self._prev_grid_idx = cur_idx

    def generate_orders(self) -> list[Order]:
        """Return and clear any pending grid orders.

        Returns:
            List of :class:`~packages.core.src.models.Order` objects queued
            since the last call.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # State persistence helpers
    # ------------------------------------------------------------------

    def get_state_dict(self) -> dict[str, Any]:
        """Serialise grid state for crash recovery.

        Returns:
            Dict with ``prev_grid_idx``, ``grid_active``, ``position``,
            ``reset_count``.
        """
        return {
            "prev_grid_idx": self._prev_grid_idx,
            "grid_active": self._grid_active,
            "position": self._position,
            "reset_count": self._reset_count,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _price_to_grid_idx(self, price: float) -> int:
        """Return the index of the highest grid level at or below *price*.

        Args:
            price: Current market price.

        Returns:
            Integer index into ``self._levels``.
        """
        levels = self._levels
        for i in range(len(levels) - 1, -1, -1):
            if price >= levels[i]:
                return i
        return 0

    def _close_all(self, bar: OHLCV) -> None:
        """Close any open position at market.

        Args:
            bar: Current bar (used for logging).
        """
        if self._position == 1:
            self._sell(str(self.qty_per_grid))
            logger.info("GridEquity: closed LONG at %.2f symbol=%s", bar.close, self._symbol)
        elif self._position == -1:
            self._buy(str(self.qty_per_grid))
            logger.info("GridEquity: closed SHORT at %.2f symbol=%s", bar.close, self._symbol)

    def _reset_grid(self, reason: str, price: float) -> None:
        """Reset grid state for a fresh start.

        Args:
            reason: Human-readable reset reason for logging.
            price:  Price at which the reset occurred.
        """
        self._prev_grid_idx = None
        self._grid_active = self.config.initial_mode == "immediate"
        self._reset_count += 1
        logger.info(
            "GridEquity reset #%d (%s) at price=%.2f symbol=%s",
            self._reset_count, reason, price, self._symbol,
        )


__all__ = ["GridConfig", "GridEquityStrategy"]
