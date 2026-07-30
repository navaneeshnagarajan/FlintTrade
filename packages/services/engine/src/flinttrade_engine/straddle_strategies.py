"""Short straddle strategy implementations for FlintTrade.

Provides four broker-agnostic classes for options short-straddle trading.
All broker I/O is injected via callable dependencies so the strategies work
with any OpenAlgo-compatible API without referencing broker libraries.

Classes:
    StraddleConfig       — shared Pydantic config model.
    MTMStraddleStrategy  — MTM-based target and stop-loss short straddle.
    TrailingStopStraddle — trailing-percentage stop with ratchet logic.
    CombinedPremiumStraddle — entry/exit driven by combined CE+PE premium.
    MTMMonitor           — standalone aggregate P&L monitor / auto-square-off.

All times are assumed to be in IST (Asia/Kolkata). No broker library is
imported; order placement is done through injected callables that mirror the
OpenAlgo REST API surface.

Supported indices: NIFTY, BANKNIFTY, FINNIFTY, SENSEX.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dtime
from enum import StrEnum
from typing import Callable, Optional

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("flinttrade.engine.straddle_strategies")

# ---------------------------------------------------------------------------
# IST helper
# ---------------------------------------------------------------------------


def _now_ist() -> datetime:
    """Return current datetime in IST."""
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+

        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now()


def _current_time() -> dtime:
    return _now_ist().time()


# ---------------------------------------------------------------------------
# Index configuration table
# ---------------------------------------------------------------------------

#: ATM rounding step (in points) for each index.
_INDEX_STEP: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "SENSEX": 100,
}

#: Exchange code used when querying options for each index.
_INDEX_EXCHANGE: dict[str, str] = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
    "SENSEX": "BFO",
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StrategyState(StrEnum):
    """Lifecycle state of a strategy instance."""

    WAITING = "WAITING"
    ENTERED = "ENTERED"
    EXITED = "EXITED"


class ExitReason(StrEnum):
    """Reason codes for strategy exit."""

    TARGET = "TARGET"
    STOPLOSS = "STOPLOSS"
    TRAILING_SL = "TRAILING_SL"
    SQUAREOFF_TIME = "SQUAREOFF_TIME"
    PARTIAL_FILL = "PARTIAL_FILL"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------


class StraddleConfig(BaseModel):
    """Shared configuration for all short-straddle strategies.

    Attributes:
        index:            Underlying index name (NIFTY / BANKNIFTY / FINNIFTY / SENSEX).
        lots:             Number of lots to trade.
        lot_size:         Lot size for the index (units per lot).
        entry_hour:       Hour component of the entry time (IST, 24-h).
        entry_minute:     Minute component of the entry time.
        squareoff_hour:   Hour component of the auto square-off time (IST).
        squareoff_minute: Minute component of the auto square-off time.
        exchange:         Options exchange code.  Auto-derived from index if blank.
        strike_offset:    Strike offset in points from ATM (0 = ATM, positive = ITM CE).
        poll_interval:    Seconds to wait between market-data polls.
    """

    index: str = "BANKNIFTY"
    lots: int = Field(default=1, ge=1)
    lot_size: int = Field(default=15, ge=1)
    entry_hour: int = Field(default=9, ge=0, le=23)
    entry_minute: int = Field(default=20, ge=0, le=59)
    squareoff_hour: int = Field(default=15, ge=0, le=23)
    squareoff_minute: int = Field(default=15, ge=0, le=59)
    exchange: str = ""
    strike_offset: int = 0  # 0 = ATM; positive moves CE ITM / PE OTM
    poll_interval: float = Field(default=1.0, ge=0.01)

    @model_validator(mode="after")
    def _derive_exchange(self) -> "StraddleConfig":
        if not self.exchange:
            self.exchange = _INDEX_EXCHANGE.get(self.index.upper(), "NFO")
        return self

    @property
    def entry_time(self) -> dtime:
        """Configured entry time as a datetime.time object."""
        return dtime(self.entry_hour, self.entry_minute)

    @property
    def squareoff_time(self) -> dtime:
        """Configured square-off time as a datetime.time object."""
        return dtime(self.squareoff_hour, self.squareoff_minute)

    @property
    def quantity(self) -> int:
        """Total quantity in units (lots × lot_size)."""
        return self.lots * self.lot_size


# ---------------------------------------------------------------------------
# ATM calculation helpers
# ---------------------------------------------------------------------------


def _atm_strike(ltp: float, index: str) -> int:
    """Round LTP to the nearest ATM strike for the given index.

    Args:
        ltp:   Last traded price of the underlying index.
        index: Index name (NIFTY, BANKNIFTY, FINNIFTY, SENSEX).

    Returns:
        ATM strike price as an integer.
    """
    step = _INDEX_STEP.get(index.upper(), 50)
    remainder = ltp % step
    if remainder < step / 2:
        return int(ltp - remainder)
    return int(ltp - remainder + step)


# ---------------------------------------------------------------------------
# Type aliases for injected API callables
# ---------------------------------------------------------------------------

#: Callable that returns the LTP of the index (e.g. BANKNIFTY).
#: Signature: (symbol: str, exchange: str) -> float
LTPFn = Callable[[str, str], float]

#: Callable that returns (ce_symbol, pe_symbol) for an expiry and strike.
#: Signature: (index: str, expiry: date, strike: int) -> tuple[str, str]
SymbolLookupFn = Callable[[str, date, int], tuple[str, str]]

#: Callable that returns (ce_ltp, pe_ltp).
#: Signature: (ce_symbol: str, pe_symbol: str, exchange: str) -> tuple[float, float]
OptionLTPFn = Callable[[str, str, str], tuple[float, float]]

#: Callable that places a market sell order and returns an order ID.
#: Signature: (symbol: str, quantity: int, exchange: str) -> str
MarketSellFn = Callable[[str, int, str], str]

#: Callable that places a market buy order and returns an order ID.
#: Signature: (symbol: str, quantity: int, exchange: str) -> str
MarketBuyFn = Callable[[str, int, str], str]

#: Callable that returns the nearest expiry date for an index.
#: Signature: (index: str) -> date
ExpiryFn = Callable[[str], date]


# ---------------------------------------------------------------------------
# MTMStraddleStrategy
# ---------------------------------------------------------------------------


class MTMStraddleConfig(StraddleConfig):
    """Configuration for MTMStraddleStrategy.

    Attributes:
        target_pct:  Exit when MTM profit reaches this fraction of premium collected (0–1).
        stoploss_pct: Exit when MTM loss reaches this fraction of premium collected (0–1).
    """

    target_pct: float = Field(default=0.5, ge=0.0, le=10.0)
    stoploss_pct: float = Field(default=1.0, ge=0.0, le=10.0)


class MTMStraddleStrategy:
    """Short straddle with MTM-based target and stop-loss.

    Entry:
        Sell ATM CE and ATM PE at ``config.entry_time`` (IST).

    Exit (first trigger wins):
        - MTM profit >= ``target_pct * premium_collected``
        - MTM loss   >= ``stoploss_pct * premium_collected``
        - Time reaches ``config.squareoff_time``

    All broker calls are injected so the strategy is broker-agnostic.

    Example::

        strategy = MTMStraddleStrategy(
            config=MTMStraddleConfig(index="NIFTY", lots=2, target_pct=0.5),
            get_index_ltp=my_ltp_fn,
            get_expiry=my_expiry_fn,
            get_option_symbols=my_symbol_fn,
            get_option_ltp=my_option_ltp_fn,
            place_sell=my_sell_fn,
            place_buy=my_buy_fn,
        )
        strategy.run()
    """

    def __init__(
        self,
        config: MTMStraddleConfig,
        get_index_ltp: LTPFn,
        get_expiry: ExpiryFn,
        get_option_symbols: SymbolLookupFn,
        get_option_ltp: OptionLTPFn,
        place_sell: MarketSellFn,
        place_buy: MarketBuyFn,
    ) -> None:
        self.config = config
        self._get_index_ltp = get_index_ltp
        self._get_expiry = get_expiry
        self._get_option_symbols = get_option_symbols
        self._get_option_ltp = get_option_ltp
        self._place_sell = place_sell
        self._place_buy = place_buy

        self.state: StrategyState = StrategyState.WAITING
        self.ce_symbol: str = ""
        self.pe_symbol: str = ""
        self.ce_sell_price: float = 0.0
        self.pe_sell_price: float = 0.0
        self.premium_collected: float = 0.0
        self.exit_reason: Optional[ExitReason] = None
        self.final_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until strategy completes (entry → monitoring → exit)."""
        logger.info("[MTMStraddle] Waiting for entry time %s …", self.config.entry_time)
        self._wait_for_entry()
        self._enter()
        if self.state != StrategyState.ENTERED:
            return
        self._monitor()

    def tick(self) -> bool:
        """Single monitoring tick.  Returns True while still active.

        Useful for externally-driven loops (scheduler, backtest runner).
        """
        if self.state != StrategyState.ENTERED:
            return False
        return self._check_exit_conditions()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _wait_for_entry(self) -> None:
        while _current_time() < self.config.entry_time:
            time.sleep(self.config.poll_interval)

    def _enter(self) -> None:
        """Sell ATM CE and PE."""
        expiry = self._get_expiry(self.config.index)
        ltp = self._get_index_ltp(self.config.index, "NSE_INDEX")
        atm = _atm_strike(ltp, self.config.index)
        ce_strike = atm - self.config.strike_offset
        _pe_strike = atm + self.config.strike_offset  # noqa: F841 — kept for symmetry

        self.ce_symbol, self.pe_symbol = self._get_option_symbols(
            self.config.index, expiry, ce_strike
        )
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )

        ce_order = self._place_sell(self.ce_symbol, self.config.quantity, self.config.exchange)
        pe_order = self._place_sell(self.pe_symbol, self.config.quantity, self.config.exchange)

        self.ce_sell_price = ce_ltp
        self.pe_sell_price = pe_ltp
        self.premium_collected = (ce_ltp + pe_ltp) * self.config.quantity

        logger.info(
            "[MTMStraddle] Entered: %s CE@%.2f + %s PE@%.2f | Premium=%.2f | orders=%s,%s",
            self.ce_symbol,
            ce_ltp,
            self.pe_symbol,
            pe_ltp,
            self.premium_collected,
            ce_order,
            pe_order,
        )
        self.state = StrategyState.ENTERED

    def _calculate_mtm(self) -> float:
        """Return current MTM P&L (positive = profit)."""
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )
        current_value = (ce_ltp + pe_ltp) * self.config.quantity
        return self.premium_collected - current_value

    def _monitor(self) -> None:
        while True:
            if not self._check_exit_conditions():
                return
            time.sleep(self.config.poll_interval)

    def _check_exit_conditions(self) -> bool:
        """Evaluate all exit conditions. Returns True to continue monitoring."""
        mtm = self._calculate_mtm()
        target = self.config.target_pct * self.premium_collected
        stoploss = -self.config.stoploss_pct * self.premium_collected

        logger.debug("[MTMStraddle] MTM=%.2f target=%.2f sl=%.2f", mtm, target, stoploss)

        if mtm >= target:
            self._exit(ExitReason.TARGET, mtm)
            return False
        if mtm <= stoploss:
            self._exit(ExitReason.STOPLOSS, mtm)
            return False
        if _current_time() >= self.config.squareoff_time:
            self._exit(ExitReason.SQUAREOFF_TIME, mtm)
            return False
        return True

    def _exit(self, reason: ExitReason, pnl: float) -> None:
        logger.info("[MTMStraddle] Exiting — reason=%s pnl=%.2f", reason, pnl)
        self._place_buy(self.ce_symbol, self.config.quantity, self.config.exchange)
        self._place_buy(self.pe_symbol, self.config.quantity, self.config.exchange)
        self.exit_reason = reason
        self.final_pnl = pnl
        self.state = StrategyState.EXITED


# ---------------------------------------------------------------------------
# TrailingStopStraddle
# ---------------------------------------------------------------------------


class TrailingStopConfig(StraddleConfig):
    """Configuration for TrailingStopStraddle.

    Attributes:
        initial_sl_pct: Initial stop-loss as a fraction of premium collected (0–1).
        trail_pct:      Trail distance — stop moves up when profit exceeds this fraction.
        trail_step:     Minimum premium drop (in points) required before ratcheting stop.
    """

    initial_sl_pct: float = Field(default=1.0, ge=0.0, le=10.0)
    trail_pct: float = Field(default=0.5, ge=0.0)
    trail_step: float = Field(default=1.0, ge=0.0)


class TrailingStopStraddle:
    """Short straddle with ratchet trailing-percentage stop loss.

    Entry:
        Sell ATM CE and ATM PE at ``config.entry_time``.

    Stop management:
        - Initial stop = sell_premium + (initial_sl_pct × sell_premium).
        - When combined premium drops by ``trail_pct × sell_premium``, the stop
          is ratcheted down by the same amount (ratchet-only: never moves up).
        - Stop is expressed as a combined premium level (CE+PE); triggers when
          current premium rises back above the stop.

    Exit (first trigger wins):
        - Current combined premium >= trailing stop level.
        - Time reaches ``config.squareoff_time``.
    """

    def __init__(
        self,
        config: TrailingStopConfig,
        get_index_ltp: LTPFn,
        get_expiry: ExpiryFn,
        get_option_symbols: SymbolLookupFn,
        get_option_ltp: OptionLTPFn,
        place_sell: MarketSellFn,
        place_buy: MarketBuyFn,
    ) -> None:
        self.config = config
        self._get_index_ltp = get_index_ltp
        self._get_expiry = get_expiry
        self._get_option_symbols = get_option_symbols
        self._get_option_ltp = get_option_ltp
        self._place_sell = place_sell
        self._place_buy = place_buy

        self.state: StrategyState = StrategyState.WAITING
        self.ce_symbol: str = ""
        self.pe_symbol: str = ""
        self.sell_premium: float = 0.0  # combined CE+PE at entry
        self.stop_premium: float = 0.0  # current combined premium stop level
        self.premium_base: float = 0.0  # lowest combined premium seen so far
        self.exit_reason: Optional[ExitReason] = None
        self.final_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until strategy completes."""
        self._wait_for_entry()
        self._enter()
        if self.state != StrategyState.ENTERED:
            return
        self._monitor()

    def tick(self) -> bool:
        """Single monitoring tick.  Returns True while still active."""
        if self.state != StrategyState.ENTERED:
            return False
        return self._check_exit_conditions()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _wait_for_entry(self) -> None:
        while _current_time() < self.config.entry_time:
            time.sleep(self.config.poll_interval)

    def _enter(self) -> None:
        expiry = self._get_expiry(self.config.index)
        ltp = self._get_index_ltp(self.config.index, "NSE_INDEX")
        atm = _atm_strike(ltp, self.config.index)
        ce_strike = atm - self.config.strike_offset
        _pe_strike = atm + self.config.strike_offset  # noqa: F841 — kept for symmetry

        self.ce_symbol, self.pe_symbol = self._get_option_symbols(
            self.config.index, expiry, ce_strike
        )
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )

        self._place_sell(self.ce_symbol, self.config.quantity, self.config.exchange)
        self._place_sell(self.pe_symbol, self.config.quantity, self.config.exchange)

        self.sell_premium = ce_ltp + pe_ltp
        self.premium_base = self.sell_premium
        self.stop_premium = self.sell_premium + self.config.initial_sl_pct * self.sell_premium

        logger.info(
            "[TrailingStop] Entered: combined_premium=%.2f initial_stop=%.2f",
            self.sell_premium,
            self.stop_premium,
        )
        self.state = StrategyState.ENTERED

    def _monitor(self) -> None:
        while True:
            if not self._check_exit_conditions():
                return
            time.sleep(self.config.poll_interval)

    def _check_exit_conditions(self) -> bool:
        """Ratchet trailing stop and check exit.  Returns True to continue."""
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )
        current = ce_ltp + pe_ltp

        # Ratchet: if premium drops past trail_step, move stop down.
        drop = self.premium_base - current
        if drop >= self.config.trail_step:
            new_stop = current + self.config.initial_sl_pct * self.sell_premium
            # Ratchet-only: stop can only move lower, never higher.
            if new_stop < self.stop_premium:
                self.stop_premium = new_stop
                logger.info(
                    "[TrailingStop] Ratcheted stop to %.2f (current premium=%.2f, drop=%.2f)",
                    self.stop_premium,
                    current,
                    drop,
                )
            self.premium_base = current

        if current >= self.stop_premium:
            pnl = (self.sell_premium - current) * self.config.quantity
            self._exit(ExitReason.TRAILING_SL, pnl)
            return False

        if _current_time() >= self.config.squareoff_time:
            pnl = (self.sell_premium - current) * self.config.quantity
            self._exit(ExitReason.SQUAREOFF_TIME, pnl)
            return False

        return True

    def _exit(self, reason: ExitReason, pnl: float) -> None:
        logger.info("[TrailingStop] Exiting — reason=%s pnl=%.2f", reason, pnl)
        self._place_buy(self.ce_symbol, self.config.quantity, self.config.exchange)
        self._place_buy(self.pe_symbol, self.config.quantity, self.config.exchange)
        self.exit_reason = reason
        self.final_pnl = pnl
        self.state = StrategyState.EXITED


# ---------------------------------------------------------------------------
# CombinedPremiumStraddle
# ---------------------------------------------------------------------------


class CombinedPremiumConfig(StraddleConfig):
    """Configuration for CombinedPremiumStraddle.

    Attributes:
        min_premium:  Minimum combined CE+PE premium required to enter.
        target_drop:  Exit when combined premium drops by this amount from entry.
        stop_rise:    Exit when combined premium rises by this amount from entry.
    """

    min_premium: float = Field(default=0.0, ge=0.0)
    target_drop: float = Field(default=50.0, ge=0.0)
    stop_rise: float = Field(default=30.0, ge=0.0)


class CombinedPremiumStraddle:
    """Short straddle with combined-premium threshold entry.

    Entry:
        Between ``config.entry_time`` and ``config.squareoff_time``, poll
        option LTPs. Enter when combined CE+PE premium >= ``min_premium``.
        If ``min_premium`` is 0, enter immediately at entry_time.

    Exit (first trigger wins):
        - Combined premium drops by ``target_drop`` from entry → target hit.
        - Combined premium rises by ``stop_rise`` from entry → stop hit.
        - Time reaches ``config.squareoff_time``.
    """

    def __init__(
        self,
        config: CombinedPremiumConfig,
        get_index_ltp: LTPFn,
        get_expiry: ExpiryFn,
        get_option_symbols: SymbolLookupFn,
        get_option_ltp: OptionLTPFn,
        place_sell: MarketSellFn,
        place_buy: MarketBuyFn,
    ) -> None:
        self.config = config
        self._get_index_ltp = get_index_ltp
        self._get_expiry = get_expiry
        self._get_option_symbols = get_option_symbols
        self._get_option_ltp = get_option_ltp
        self._place_sell = place_sell
        self._place_buy = place_buy

        self.state: StrategyState = StrategyState.WAITING
        self.ce_symbol: str = ""
        self.pe_symbol: str = ""
        self.entry_premium: float = 0.0
        self.exit_reason: Optional[ExitReason] = None
        self.final_pnl: float = 0.0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Block until strategy completes."""
        self._wait_for_entry_window()
        self._resolve_symbols()
        entered = self._wait_for_premium()
        if not entered:
            logger.info("[CombinedPremium] Premium threshold never met — no trade today.")
            return
        self._enter()
        if self.state != StrategyState.ENTERED:
            return
        self._monitor()

    def tick(self) -> bool:
        """Single monitoring tick.  Returns True while still active."""
        if self.state != StrategyState.ENTERED:
            return False
        return self._check_exit_conditions()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _wait_for_entry_window(self) -> None:
        while _current_time() < self.config.entry_time:
            time.sleep(self.config.poll_interval)

    def _resolve_symbols(self) -> None:
        expiry = self._get_expiry(self.config.index)
        ltp = self._get_index_ltp(self.config.index, "NSE_INDEX")
        atm = _atm_strike(ltp, self.config.index)
        ce_strike = atm - self.config.strike_offset
        self.ce_symbol, self.pe_symbol = self._get_option_symbols(
            self.config.index, expiry, ce_strike
        )

    def _wait_for_premium(self) -> bool:
        """Poll until combined premium >= min_premium or squareoff time.

        Returns:
            True if threshold was met, False if squareoff time was reached first.
        """
        if self.config.min_premium <= 0:
            return True
        while _current_time() < self.config.squareoff_time:
            ce_ltp, pe_ltp = self._get_option_ltp(
                self.ce_symbol, self.pe_symbol, self.config.exchange
            )
            combined = ce_ltp + pe_ltp
            if combined >= self.config.min_premium:
                logger.info(
                    "[CombinedPremium] Premium threshold met: %.2f >= %.2f",
                    combined,
                    self.config.min_premium,
                )
                return True
            time.sleep(self.config.poll_interval)
        return False

    def _enter(self) -> None:
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )
        self._place_sell(self.ce_symbol, self.config.quantity, self.config.exchange)
        self._place_sell(self.pe_symbol, self.config.quantity, self.config.exchange)
        self.entry_premium = ce_ltp + pe_ltp
        logger.info(
            "[CombinedPremium] Entered: %s + %s combined_premium=%.2f",
            self.ce_symbol,
            self.pe_symbol,
            self.entry_premium,
        )
        self.state = StrategyState.ENTERED

    def _monitor(self) -> None:
        while True:
            if not self._check_exit_conditions():
                return
            time.sleep(self.config.poll_interval)

    def _check_exit_conditions(self) -> bool:
        """Check target, stop, and squareoff.  Returns True to continue."""
        ce_ltp, pe_ltp = self._get_option_ltp(
            self.ce_symbol, self.pe_symbol, self.config.exchange
        )
        current = ce_ltp + pe_ltp
        drop = self.entry_premium - current
        rise = current - self.entry_premium
        pnl = drop * self.config.quantity

        if drop >= self.config.target_drop:
            self._exit(ExitReason.TARGET, pnl)
            return False
        if rise >= self.config.stop_rise:
            self._exit(ExitReason.STOPLOSS, pnl)
            return False
        if _current_time() >= self.config.squareoff_time:
            self._exit(ExitReason.SQUAREOFF_TIME, pnl)
            return False
        return True

    def _exit(self, reason: ExitReason, pnl: float) -> None:
        logger.info("[CombinedPremium] Exiting — reason=%s pnl=%.2f", reason, pnl)
        self._place_buy(self.ce_symbol, self.config.quantity, self.config.exchange)
        self._place_buy(self.pe_symbol, self.config.quantity, self.config.exchange)
        self.exit_reason = reason
        self.final_pnl = pnl
        self.state = StrategyState.EXITED


# ---------------------------------------------------------------------------
# MTMMonitor (standalone utility)
# ---------------------------------------------------------------------------


class MTMMonitorConfig(BaseModel):
    """Configuration for MTMMonitor.

    Attributes:
        max_loss:          Aggregate MTM loss limit (positive value, in INR).
                           Triggers square-off when total unrealised loss >= max_loss.
        max_profit:        Optional profit-lock target.  Square-off if total
                           unrealised profit >= max_profit.  0 = disabled.
        squareoff_hour:    Auto square-off hour (IST).
        squareoff_minute:  Auto square-off minute (IST).
        poll_interval:     Seconds between P&L checks.
        lot_size:          Default lot size (used for quantity-weighted P&L).
    """

    max_loss: float = Field(default=10_000.0, ge=0.0)
    max_profit: float = Field(default=0.0, ge=0.0)
    squareoff_hour: int = Field(default=15, ge=0, le=23)
    squareoff_minute: int = Field(default=15, ge=0, le=59)
    poll_interval: float = Field(default=5.0, ge=0.01)
    lot_size: int = Field(default=25, ge=1)

    @property
    def squareoff_time(self) -> dtime:
        return dtime(self.squareoff_hour, self.squareoff_minute)


class OptionPosition(BaseModel):
    """A tracked open option position.

    Attributes:
        symbol:     Trading symbol (e.g. ``NIFTY30DEC2523500CE``).
        exchange:   Exchange code (``NFO``, ``BFO``).
        direction:  ``SELL`` (short) or ``BUY`` (long).
        quantity:   Total units held.
        entry_price: Average fill price.
    """

    symbol: str
    exchange: str = "NFO"
    direction: str = "SELL"
    quantity: int = Field(ge=1)
    entry_price: float = Field(ge=0.0)


class MTMMonitor:
    """Standalone aggregate P&L monitor for open option positions.

    Tracks unrealised MTM across all registered positions and triggers a
    square-off callback when the aggregate loss breaches ``max_loss``.  Works
    independently of any strategy class — plug it into the position_tracker or
    use it standalone.

    Example::

        monitor = MTMMonitor(
            config=MTMMonitorConfig(max_loss=15000),
            get_option_ltp=my_ltp_fn,
            place_buy=my_buy_fn,
            place_sell=my_sell_fn,
        )
        monitor.add_position(OptionPosition(
            symbol="NIFTY30DEC2523500CE",
            exchange="NFO",
            direction="SELL",
            quantity=50,
            entry_price=200.0,
        ))
        monitor.run()
    """

    def __init__(
        self,
        config: MTMMonitorConfig,
        get_option_ltp: Callable[[str, str], float],
        place_buy: Callable[[str, int, str], str],
        place_sell: Callable[[str, int, str], str],
    ) -> None:
        self.config = config
        self._get_ltp = get_option_ltp
        self._place_buy = place_buy
        self._place_sell = place_sell

        self._positions: list[OptionPosition] = []
        self._running: bool = False
        self.squaredoff: bool = False
        self.squaredoff_reason: str = ""
        self.last_mtm: float = 0.0

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def add_position(self, position: OptionPosition) -> None:
        """Register an open position for monitoring."""
        self._positions.append(position)
        logger.info(
            "[MTMMonitor] Added position: %s %s qty=%d entry=%.2f",
            position.direction,
            position.symbol,
            position.quantity,
            position.entry_price,
        )

    def remove_position(self, symbol: str) -> None:
        """Remove a position from monitoring (e.g. after manual exit)."""
        self._positions = [p for p in self._positions if p.symbol != symbol]

    def clear_positions(self) -> None:
        """Remove all monitored positions."""
        self._positions.clear()

    # ------------------------------------------------------------------
    # MTM calculation
    # ------------------------------------------------------------------

    def calculate_mtm(self) -> float:
        """Calculate aggregate unrealised MTM across all positions.

        For SELL positions: MTM = (entry_price - current_ltp) * quantity.
        For BUY positions:  MTM = (current_ltp - entry_price) * quantity.

        Returns:
            Total unrealised P&L in INR.  Positive = profit, negative = loss.
        """
        total = 0.0
        for pos in self._positions:
            try:
                ltp = self._get_ltp(pos.symbol, pos.exchange)
                if pos.direction.upper() == "SELL":
                    total += (pos.entry_price - ltp) * pos.quantity
                else:
                    total += (ltp - pos.entry_price) * pos.quantity
            except Exception as exc:  # noqa: BLE001
                logger.warning("[MTMMonitor] LTP fetch failed for %s: %s", pos.symbol, exc)
        self.last_mtm = total
        return total

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Poll MTM and trigger square-off on breach.  Blocking call."""
        self._running = True
        logger.info(
            "[MTMMonitor] Started — max_loss=%.0f max_profit=%.0f squareoff=%s",
            self.config.max_loss,
            self.config.max_profit,
            self.config.squareoff_time,
        )
        while self._running:
            self.tick()
            if self.squaredoff:
                break
            time.sleep(self.config.poll_interval)

    def stop(self) -> None:
        """Stop the monitoring loop gracefully."""
        self._running = False

    def tick(self) -> bool:
        """Single monitor tick.  Returns True while still active."""
        mtm = self.calculate_mtm()
        logger.debug("[MTMMonitor] MTM=%.2f positions=%d", mtm, len(self._positions))

        if mtm <= -self.config.max_loss:
            logger.warning("[MTMMonitor] Loss limit breached: %.2f >= %.0f", -mtm, self.config.max_loss)
            self._square_off_all("MAX_LOSS_BREACH")
            return False

        if self.config.max_profit > 0 and mtm >= self.config.max_profit:
            logger.info("[MTMMonitor] Profit target reached: %.2f", mtm)
            self._square_off_all("MAX_PROFIT_REACHED")
            return False

        if _current_time() >= self.config.squareoff_time:
            logger.info("[MTMMonitor] Auto square-off time reached.")
            self._square_off_all("SQUAREOFF_TIME")
            return False

        return True

    # ------------------------------------------------------------------
    # Square-off
    # ------------------------------------------------------------------

    def _square_off_all(self, reason: str) -> None:
        """Close all open positions with market orders."""
        logger.info("[MTMMonitor] Squaring off %d positions — reason=%s", len(self._positions), reason)
        for pos in list(self._positions):
            try:
                if pos.direction.upper() == "SELL":
                    order_id = self._place_buy(pos.symbol, pos.quantity, pos.exchange)
                else:
                    order_id = self._place_sell(pos.symbol, pos.quantity, pos.exchange)
                logger.info("[MTMMonitor] Closed %s qty=%d order=%s", pos.symbol, pos.quantity, order_id)
            except Exception as exc:  # noqa: BLE001
                logger.error("[MTMMonitor] Failed to close %s: %s", pos.symbol, exc)
        self.squaredoff = True
        self.squaredoff_reason = reason
        self._running = False
