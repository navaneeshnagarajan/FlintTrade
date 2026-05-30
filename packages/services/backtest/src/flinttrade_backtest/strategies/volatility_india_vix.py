"""India VIX Regime strategy — Volatility category.

India VIX measures market-implied volatility from Nifty options (similar to CBOE VIX).
In backtesting we approximate VIX rising/falling by comparing the current ATR to its
own short-term EMA — a rising ATR relative to its EMA signals increasing fear/volatility.

Real-world usage:
    - If you have actual India VIX data (NSE symbol: INDIAVIX), pass it as the
      close prices to a separate VIX bar feed.
    - This implementation uses ATR(14) > EMA(ATR, 5) as the VIX-rising proxy.

Trading rules:
    BUY  when VIX rising (ATR expanding) AND price is BELOW its SMA
         (market fearful, but price has already fallen — buy the dip).
    SELL when VIX rising AND price is ABOVE its SMA
         (market fearful and price still elevated — short the elevated level).
    FLAT when VIX is not rising (low-volatility regime — no new trades).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr, ema, sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_india_vix")


class IndiaVIXRegime(BaseStrategy, _BacktestStrategyMixin):
    """India VIX regime filter strategy (ATR proxy).

    Uses ATR vs its own EMA to detect rising-volatility (fear) regimes and
    trades mean reversion during those regimes.

    Args:
        atr_period: ATR period (default 14).
        vix_ema_period: EMA period applied to ATR series as VIX proxy (default 5).
        sma_period: SMA period for price context (default 20).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "IndiaVIXRegime",
        exchange: str = "NSE",
        product: str = "MIS",
        atr_period: int = 14,
        vix_ema_period: int = 5,
        sma_period: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.atr_period = atr_period
        self.vix_ema_period = vix_ema_period
        self.sma_period = sma_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and trade the VIX regime.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        min_bars = max(self.atr_period, self.sma_period) + self.vix_ema_period + 1
        if len(self._closes) < min_bars:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        # Filter zero-seeded values before computing EMA
        valid_atr = [v if v > 0 else atr_vals[self.atr_period] for v in atr_vals]
        vix_ema_vals = ema(valid_atr, self.vix_ema_period)
        sma_vals = sma(self._closes, self.sma_period)

        cur_atr = atr_vals[-1]
        cur_vix_ema = vix_ema_vals[-1]
        cur_ma = sma_vals[-1]
        close = self._closes[-1]

        if cur_atr == 0 or cur_vix_ema == 0 or cur_ma == 0:
            return

        vix_rising = cur_atr > cur_vix_ema

        if self._position == 0:
            if vix_rising and close < cur_ma:
                logger.debug(
                    "VIX-rise | atr=%.4f vix_ema=%.4f | price below MA | BUY | %s",
                    cur_atr,
                    cur_vix_ema,
                    self._symbol,
                )
                self._buy()
            elif vix_rising and close > cur_ma:
                logger.debug(
                    "VIX-rise | atr=%.4f vix_ema=%.4f | price above MA | SELL | %s",
                    cur_atr,
                    cur_vix_ema,
                    self._symbol,
                )
                self._sell()
        elif self._position == 1:
            # Exit when volatility drops or price rises back above MA
            if not vix_rising or close >= cur_ma:
                self._sell()
                self._flat()
        elif self._position == -1:
            # Exit when volatility drops or price falls back below MA
            if not vix_rising or close <= cur_ma:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear all pending orders.

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
