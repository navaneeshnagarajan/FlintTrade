"""EMA 20/50 + Supertrend 10/3 + DEMA 15 — F&O trend-following strategy.

Strategy specification:

Entry conditions (all must be true on bar close):
    1. EMA 20 crosses ABOVE EMA 50 (golden cross on the current candle)
    2. Supertrend 10/3 is in UPTREND (direction == True)
    3. Both conditions confirmed simultaneously

Stop-loss logic:
    - Static SL: set at the Supertrend value at the bar of entry
    - Becomes dynamic ONLY after close price crosses above entry price
    - Dynamic SL: always at current Supertrend value (trailing support)
    - Exit rule: exit on CANDLE CLOSE when Supertrend is broken (close < ST)
    - 5-candle rule: if Supertrend is unbroken after 5 candles, SL order is placed
      at the current Supertrend level (locks in the position formally)

Target logic:
    - At the DEMA 15 level where Supertrend started stabilizing (i.e. the
      Supertrend value at the entry bar)
    - Target is placed AFTER the 5th candle close, if Supertrend is still stable
      (direction unchanged) and unbroken

Exchange lot sizes:
    - NIFTY:      25
    - BANKNIFTY:  15
    - FINNIFTY:   25
    - MIDCPNIFTY: 50

This module is a backtest-engine strategy. It extends BaseStrategy via the
_BacktestStrategyMixin and processes bars sequentially through on_bar().
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy
from flinttrade_screener.lot_sizes import FALLBACK_LOT_SIZES

from ..strategies import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.ema_supertrend_dema")


# ---------------------------------------------------------------------------
# Lot-size registry
# ---------------------------------------------------------------------------

# Contract sizes come from the screener's unified table (this file's private
# copy pre-dated the 2024 SEBI lot revisions — NIFTY 25 vs the current 75).
# Historical backtests over pre-revision periods should override per run.
LOT_SIZES: dict[str, int] = FALLBACK_LOT_SIZES

DEFAULT_LOT_SIZE: int = 1


def lot_size_for(symbol: str) -> int:
    """Return the standard lot size for an F&O underlying symbol.

    Args:
        symbol: Underlying symbol name (case-insensitive check).

    Returns:
        Lot size integer. Falls back to 1 for unknown symbols.
    """
    upper = symbol.upper()
    for key, size in LOT_SIZES.items():
        if upper.startswith(key):
            return size
    return DEFAULT_LOT_SIZE


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class EMASuperTrendDEMA(BaseStrategy, _BacktestStrategyMixin):
    """EMA 20/50 + Supertrend 10/3 + DEMA 15 — F&O trend-following strategy.

    Entry: EMA 20 crosses above EMA 50 AND Supertrend is in uptrend.
    Stop-loss: Static at Supertrend value at entry; becomes dynamic (trailing)
               after price exceeds entry; triggered on candle close below ST.
    Target: DEMA 15 level at entry bar, placed after 5th candle if ST stable.
    Lots: NIFTY 25, BANKNIFTY 15, FINNIFTY 25, MIDCPNIFTY 50.

    Usage in backtest::

        strategy = EMASuperTrendDEMA(
            symbol="NIFTY",
            exchange="NFO",
            product="MIS",
        )
        strategy.start()
        for bar in bars:
            strategy.on_bar(bar)
        orders = strategy.generate_orders()

    Attributes:
        ema_fast: Fast EMA period (default 20).
        ema_slow: Slow EMA period (default 50).
        st_period: Supertrend ATR period (default 10).
        st_multiplier: Supertrend ATR multiplier (default 3.0).
        dema_period: DEMA period for target level (default 15).
        lots: Number of lots to trade (default 1).
    """

    def __init__(
        self,
        symbol: str = "NIFTY",
        exchange: str = "NFO",
        product: str = "MIS",
        ema_fast: int = 20,
        ema_slow: int = 50,
        st_period: int = 10,
        st_multiplier: float = 3.0,
        dema_period: int = 15,
        lots: int = 1,
        **kwargs: Any,
    ) -> None:
        name = kwargs.pop(
            "name",
            f"EMA{ema_fast}_{ema_slow}_ST{st_period}_{st_multiplier}_DEMA{dema_period}_{symbol}",
        )
        super().__init__(name=name, exchange=exchange, product=product)
        self._init_history()

        self._symbol = symbol
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.st_period = st_period
        self.st_multiplier = st_multiplier
        self.dema_period = dema_period

        self.lots = lots
        self._quantity = str(lots * lot_size_for(symbol))

        # Entry state
        self._entry_price: float = 0.0
        self._entry_st_value: float = 0.0    # Supertrend at entry (static SL)
        self._entry_dema_value: float = 0.0  # DEMA 15 at entry (initial target)
        self._candles_since_entry: int = 0
        self._sl_activated: bool = False      # True once SL order has been placed
        self._target_activated: bool = False  # True once target order has been placed
        self._dynamic_sl: bool = False        # True once close > entry price

    # ------------------------------------------------------------------
    # BaseStrategy hooks
    # ------------------------------------------------------------------

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed OHLCV bar.

        Called once per closed candle. Computes indicators, checks entry and
        exit conditions, and queues orders into _pending_orders.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return

        self._record_bar(bar)
        n = len(self._closes)

        # Need enough bars for the slowest indicator (EMA 50)
        if n < self.ema_slow + 1:
            return

        closes = np.array(self._closes, dtype=np.float64)
        highs = np.array(self._highs, dtype=np.float64)
        lows = np.array(self._lows, dtype=np.float64)

        # -- Compute indicators --
        from flinttrade_indicators.trend import dema, ema, supertrend

        ema_fast_vals = ema(closes, self.ema_fast)
        ema_slow_vals = ema(closes, self.ema_slow)
        st_vals, st_direction = supertrend(highs, lows, closes, self.st_period, self.st_multiplier)
        dema_vals = dema(closes, self.dema_period)

        cur = n - 1  # current bar index
        prev = cur - 1

        # Guard against NaN in any indicator
        if any(
            np.isnan(v)
            for v in [
                ema_fast_vals[cur], ema_fast_vals[prev],
                ema_slow_vals[cur], ema_slow_vals[prev],
                st_vals[cur], dema_vals[cur],
            ]
        ):
            return

        cur_close = self._closes[-1]
        cur_st = float(st_vals[cur])
        cur_dema = float(dema_vals[cur])
        cur_direction = bool(st_direction[cur])

        # ----------------------------------------------------------------
        # In-position management
        # ----------------------------------------------------------------
        if self._position == 1:
            self._candles_since_entry += 1

            # Dynamic SL activates once close exceeds entry price
            if cur_close > self._entry_price:
                self._dynamic_sl = True

            # Active SL level: dynamic (trailing) or static
            sl_level = cur_st if self._dynamic_sl else self._entry_st_value

            # Exit condition: candle close below Supertrend level
            if cur_close < sl_level or not cur_direction:
                logger.info(
                    "SL exit | close=%.2f st=%.2f dynamic=%s | %s",
                    cur_close, sl_level, self._dynamic_sl, self._symbol,
                )
                self._sell(qty=self._quantity)
                self._reset_position_state()
                return

            # 5-candle rule: place formal SL and target orders
            if self._candles_since_entry == 5 and not self._sl_activated:
                if cur_direction:  # Supertrend still stable
                    self._place_sl_order(cur_st)
                    self._place_target_order(self._entry_dema_value)
                    self._sl_activated = True
                    self._target_activated = True
                    logger.info(
                        "5-candle rule: SL=%.2f target=%.2f | %s",
                        cur_st, self._entry_dema_value, self._symbol,
                    )

            return

        # ----------------------------------------------------------------
        # Entry conditions (flat position only)
        # ----------------------------------------------------------------
        if self._position != 0:
            return

        ema_cross_up = (
            ema_fast_vals[cur] > ema_slow_vals[cur]
            and ema_fast_vals[prev] <= ema_slow_vals[prev]
        )

        if ema_cross_up and cur_direction:
            logger.info(
                "Entry signal | EMA20=%.2f EMA50=%.2f ST=%.2f DEMA=%.2f close=%.2f | %s",
                ema_fast_vals[cur], ema_slow_vals[cur], cur_st, cur_dema,
                cur_close, self._symbol,
            )
            self._buy(qty=self._quantity)
            self._entry_price = cur_close
            self._entry_st_value = cur_st
            self._entry_dema_value = cur_dema
            self._candles_since_entry = 0
            self._sl_activated = False
            self._target_activated = False
            self._dynamic_sl = False

    def generate_orders(self) -> list[Order]:
        """Return and clear any pending orders queued by on_bar().

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _buy(self, qty: str = "1") -> None:  # type: ignore[override]
        """Queue a BUY order and update position tracking."""
        if self._position <= 0:
            self._pending_orders.append(
                Order(
                    symbol=self._symbol,
                    action="BUY",
                    exchange=self.exchange,
                    quantity=qty,
                    strategy=self.name,
                )
            )
            self._position = 1

    def _sell(self, qty: str = "1") -> None:  # type: ignore[override]
        """Queue a SELL order and update position tracking."""
        if self._position >= 0:
            self._pending_orders.append(
                Order(
                    symbol=self._symbol,
                    action="SELL",
                    exchange=self.exchange,
                    quantity=qty,
                    strategy=self.name,
                )
            )
            self._position = -1

    def _place_sl_order(self, sl_price: float) -> None:
        """Queue a stop-loss SELL order at sl_price.

        In live trading this should be a SL-M (stop market) order.
        In backtest mode, the simulator will handle it as a limit order.

        Args:
            sl_price: Stop-loss trigger price.
        """
        self._pending_orders.append(
            Order(
                symbol=self._symbol,
                action="SELL",
                exchange=self.exchange,
                pricetype="SL-M",
                quantity=self._quantity,
                trigger_price=f"{sl_price:.2f}",
                strategy=self.name,
            )
        )
        logger.debug("SL order queued: trigger=%.2f | %s", sl_price, self._symbol)

    def _place_target_order(self, target_price: float) -> None:
        """Queue a take-profit SELL limit order at target_price.

        Args:
            target_price: Target (limit) price for the exit.
        """
        self._pending_orders.append(
            Order(
                symbol=self._symbol,
                action="SELL",
                exchange=self.exchange,
                pricetype="LIMIT",
                quantity=self._quantity,
                price=f"{target_price:.2f}",
                strategy=self.name,
            )
        )
        logger.debug("Target order queued: price=%.2f | %s", target_price, self._symbol)

    def _reset_position_state(self) -> None:
        """Clear all per-trade state after an exit."""
        self._position = 0
        self._entry_price = 0.0
        self._entry_st_value = 0.0
        self._entry_dema_value = 0.0
        self._candles_since_entry = 0
        self._sl_activated = False
        self._target_activated = False
        self._dynamic_sl = False
