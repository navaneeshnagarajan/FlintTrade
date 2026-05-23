"""Iron Condor strategy — Options category.

Iron Condor: Sell OTM call spread + OTM put spread simultaneously.
Profits when underlying stays within a defined range (low IV environment).

Structure:
  Short call at strike C, long call at C + width (call spread).
  Short put at strike P, long put at P - width (put spread).
  C > current_price > P.

In backtest mode, the net premium is modelled as a single combined synthetic price.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_iron_condor")


class IronCondorStrategy(BaseStrategy, _BacktestStrategyMixin):
    """Iron Condor options strategy.

    Sells a bounded range position. Profits from time decay and range-bound markets.
    Stop-loss triggered when combined premium expands beyond sl_pct of entry.
    Target: premium decays by target_pct.

    Args:
        entry_time: Entry bar time HH:MM (default "09:30").
        exit_time: Force-exit bar time HH:MM (default "15:15").
        stop_loss_pct: Max allowable loss as % of entry premium (default 100.0).
        target_pct: Profit target as % decay of entry premium (default 40.0).
        wing_width_pct: Wing width as % of underlying price (default 2.0).
        symbol: Synthetic combined-premium instrument symbol.
    """

    def __init__(
        self,
        name: str = "IronCondorStrategy",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:30",
        exit_time: str = "15:15",
        stop_loss_pct: float = 100.0,
        target_pct: float = 40.0,
        wing_width_pct: float = 2.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.stop_loss_pct = stop_loss_pct
        self.target_pct = target_pct
        self.wing_width_pct = wing_width_pct
        self._symbol = symbol
        self._init_history()
        self._entry_premium: float = 0.0
        self._underlying_at_entry: float = 0.0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""

        if time_part == self.entry_time and self._position == 0:
            self._sell()
            self._entry_premium = bar.close
            self._underlying_at_entry = bar.close
            return

        if self._position == -1 and self._entry_premium > 0:
            cur_premium = bar.close
            pnl_pct = (self._entry_premium - cur_premium) / self._entry_premium * 100

            if pnl_pct >= self.target_pct:
                self._buy()
                self._entry_premium = 0.0
                logger.info("IC target hit | pnl=%.1f%% | %s", pnl_pct, self._symbol)
                return

            if -pnl_pct >= self.stop_loss_pct:
                self._buy()
                self._entry_premium = 0.0
                logger.info("IC SL hit | pnl=%.1f%% | %s", pnl_pct, self._symbol)
                return

            if time_part >= self.exit_time:
                self._buy()
                self._entry_premium = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IronCondorStrategy"]
