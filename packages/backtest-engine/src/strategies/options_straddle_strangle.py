"""Straddle and Strangle options strategies — Options category.

ATM Straddle Sell: Sell ATM CE + PE at market open; exit at target/SL/time.
OTM Strangle Sell: Sell OTM CE + PE; wider breakeven but lower premium.

These strategies model options-selling (short premium) approaches common
in Indian F&O markets (Nifty/BankNifty weekly expiry).

In backtest mode, options are represented as a single synthetic instrument
with combined premium as the price series. The simulator tracks P&L
on a premium basis.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_straddle_strangle")


class ATMStraddleSell(BaseStrategy, _BacktestStrategyMixin):
    """ATM Straddle Sell strategy.

    Enters a short straddle at entry_time; exits at exit_time or on SL.
    Models the combined CE+PE premium as a single short position.

    Args:
        entry_time: Bar timestamp (HH:MM) to enter the straddle (default "09:20").
        exit_time: Bar timestamp (HH:MM) to force exit (default "15:15").
        stop_loss_pct: Stop-loss as % of entry premium (default 50.0).
        target_pct: Profit target as % of entry premium (default 30.0).
        symbol: Options instrument symbol (combined premium series).
    """

    def __init__(
        self,
        name: str = "ATMStraddleSell",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:20",
        exit_time: str = "15:15",
        stop_loss_pct: float = 50.0,
        target_pct: float = 30.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.stop_loss_pct = stop_loss_pct
        self.target_pct = target_pct
        self._symbol = symbol
        self._init_history()
        self._entry_premium: float = 0.0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""

        if time_part == self.entry_time and self._position == 0:
            # Short straddle: sell combined premium
            self._sell()
            self._entry_premium = bar.close
            return

        if self._position == -1 and self._entry_premium > 0:
            current_premium = bar.close
            pnl_pct = (self._entry_premium - current_premium) / self._entry_premium * 100

            # Target hit (premium decayed by target_pct)
            if pnl_pct >= self.target_pct:
                self._buy()
                self._entry_premium = 0.0
                logger.info("Straddle target hit | pnl=%.1f%% | %s", pnl_pct, self._symbol)
                return

            # Stop loss (premium expanded by stop_loss_pct)
            if -pnl_pct >= self.stop_loss_pct:
                self._buy()
                self._entry_premium = 0.0
                logger.info("Straddle SL hit | pnl=%.1f%% | %s", pnl_pct, self._symbol)
                return

            # Time-based exit
            if time_part >= self.exit_time:
                self._buy()
                self._entry_premium = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


class OTMStrangleSell(ATMStraddleSell):
    """OTM Strangle Sell strategy.

    Like ATMStraddleSell but models out-of-the-money options.
    Additional parameter `otm_distance_pct` represents how far OTM the strikes are.

    Args:
        otm_distance_pct: OTM distance as % of underlying (default 1.0).
    """

    def __init__(
        self,
        name: str = "OTMStrangleSell",
        otm_distance_pct: float = 1.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self.otm_distance_pct = otm_distance_pct


__all__ = ["ATMStraddleSell", "OTMStrangleSell"]
