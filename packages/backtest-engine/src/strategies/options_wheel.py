"""Wheel Strategy — Options category.

The Wheel (Cash-Secured Put → Covered Call) is a systematic income strategy:

Phase 1 — Cash-Secured Put (CSP):
    Sell OTM put below current price. Collect premium.
    If assigned, acquire the underlying at the strike price.

Phase 2 — Covered Call (CC):
    After assignment, sell OTM call above acquisition price. Collect premium.
    If called away, restart from Phase 1.

In backtest mode with OHLCV data:
    - Proxy the put/call as a single synthetic premium series.
    - Manage via time-based entry/exit and SL/target parameters.
    - Track assignment events through price breaching the put strike.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_wheel")


class WheelStrategy(BaseStrategy, _BacktestStrategyMixin):
    """Wheel options income strategy (simplified backtest model).

    Tracks two phases:
    - CASH_SECURED_PUT: Sell a put at put_strike_pct below current price.
    - COVERED_CALL: After notional assignment, sell a call at call_strike_pct above cost.

    Simplification: uses underlying OHLCV; premium is estimated as a fraction
    of the strike distance (premium_pct of underlying price).

    Args:
        put_strike_pct: Put strike as % below current price (default 3.0).
        call_strike_pct: Call strike as % above cost basis (default 3.0).
        premium_pct: Premium received as % of underlying (default 0.5).
        stop_loss_mult: Stop if underlying falls by this multiple of premium (default 2.0).
        entry_time: Daily entry time HH:MM (default "09:30").
        exit_time: EOD force-exit time HH:MM (default "15:15").
        symbol: Underlying instrument symbol.
    """

    def __init__(
        self,
        name: str = "WheelStrategy",
        exchange: str = "NFO",
        product: str = "NRML",
        put_strike_pct: float = 3.0,
        call_strike_pct: float = 3.0,
        premium_pct: float = 0.5,
        stop_loss_mult: float = 2.0,
        entry_time: str = "09:30",
        exit_time: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.put_strike_pct = put_strike_pct
        self.call_strike_pct = call_strike_pct
        self.premium_pct = premium_pct
        self.stop_loss_mult = stop_loss_mult
        self.entry_time = entry_time
        self.exit_time = exit_time
        self._symbol = symbol
        self._init_history()

        self._phase: str = "CASH_SECURED_PUT"  # or "COVERED_CALL"
        self._cost_basis: float = 0.0
        self._put_strike: float = 0.0
        self._call_strike: float = 0.0
        self._entry_premium: float = 0.0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        ts = bar.timestamp
        time_part = ts[11:16] if len(ts) > 16 else ""
        close = bar.close

        if time_part == self.entry_time and self._position == 0:
            premium = close * (self.premium_pct / 100)
            if self._phase == "CASH_SECURED_PUT":
                self._put_strike = close * (1 - self.put_strike_pct / 100)
                self._entry_premium = premium
                logger.info(
                    "CSP entry: underlying=%.2f put_strike=%.2f premium=%.2f | %s",
                    close, self._put_strike, premium, self._symbol,
                )
                self._sell()  # Sell the put (short premium)
            else:
                # Covered call phase
                self._call_strike = self._cost_basis * (1 + self.call_strike_pct / 100)
                self._entry_premium = premium
                logger.info(
                    "CC entry: cost=%.2f call_strike=%.2f premium=%.2f | %s",
                    self._cost_basis, self._call_strike, premium, self._symbol,
                )
                self._sell()  # Sell the call (short premium)
            return

        if self._position == -1:
            if self._phase == "CASH_SECURED_PUT":
                # Assignment: underlying trades below put strike
                if close < self._put_strike:
                    self._buy()  # Buy back put (assigned); switch to covered call
                    self._cost_basis = self._put_strike - self._entry_premium
                    self._phase = "COVERED_CALL"
                    logger.info(
                        "CSP assigned | cost_basis=%.2f | %s", self._cost_basis, self._symbol,
                    )
                    return
                # Stop loss
                loss = self._entry_premium - (self._put_strike - close) / close * close
                if loss < -self.stop_loss_mult * self._entry_premium:
                    self._buy()
                    return
            else:
                # Called away: underlying trades above call strike
                if close > self._call_strike:
                    self._buy()  # Buy back call (called away); restart
                    self._phase = "CASH_SECURED_PUT"
                    self._cost_basis = 0.0
                    logger.info("CC called away | %s", self._symbol)
                    return

            # EOD exit for backtesting realism
            if time_part >= self.exit_time:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
