"""Indian F&O Short Straddle strategy — unified parameterised implementation.

Absorbs all 14 variants from algo_trading_strategies_india/short-straddle:

    Variant group              Reference file
    ─────────────────────────  ─────────────────────────────────────────────
    0920 ATM straddle          0920_short_straddle/{nifty50,banknifty,
                               finnifty,sensex}_0920_short_straddle.py
    Combined premium SL/TSL    combined_premium/{bank_nifty,finnifty,
                               nifty50,sensex}_combined_premium_*.py
    Fixed points SL            fixed_stop_loss/bank_nifty_fixed_stop_loss_*.py
    Account-level MTM SL       fixed_stop_loss/bank_nifty_account_level_mtm_*.py
    MTM-based rupee target     mtm_based_target/{bank_nifty,nifty50}_mtm_*.py
    Trailing SL (TSL)          trailing_stop_loss/bank_nifty_trailing_*.py

Supports NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY.

SL modes
─────────
``percentage``    Per-leg SL: each leg exits independently when its option premium
                  rises above ``(sell_price * sl_pct / 100)``. This is the classic
                  0920 variant used by most reference scripts.

``combined``      Combined-premium SL: both legs are monitored together; exit
                  when ``(ce_ltp + pe_ltp) >= (ce_sell + pe_sell) + sl_points``.
                  Mirrors the combined_premium scripts.

``fixed_points``  Fixed-points SL per leg: exit when option price rises by
                  ``ce_sl_points`` / ``pe_sl_points`` absolute points.

``mtm_rupees``    Account-level MTM: monitor total P&L (in rupees) and exit when
                  loss >= ``mtm_sl_rupees`` or profit >= ``mtm_target_rupees``.
                  Mirrors the mtm_based_target and account_level scripts.

``trailing``      Trailing combined-premium SL: if the combined premium falls
                  below the previous base, the base is reset and the SL level
                  tightens by ``tsl_points``. Mirrors the trailing script.

Target modes
────────────
``premium_pct``   Exit when combined premium has decayed by ``target_pct`` of
                  the entry combined premium.

``mtm_rupees``    Exit when total P&L (rupees) reaches ``mtm_target_rupees``.

``none``          No target; only SL and time-based exit.

State machine
─────────────
WAITING → (entry_time reached) → ACTIVE
ACTIVE  → (SL hit on a leg)    → SL_HIT (one leg gone, other still live)
        → (both legs gone)     → EXITED (per-session terminal state)
SL_HIT  → (re-entry cond.)    → ACTIVE (re-enter at new ATM)
ACTIVE  → (exit_time reached)  → square off all open legs → EXITED

The backtest engine passes a single ``bar`` at a time. Because both legs move
concurrently in real life but we only receive one price series, the strategy
uses the bar's underlying spot price (bar.close) to derive synthetic option
prices on each bar using an intrinsic-value + time-value proxy:

    option_price ≈ max(intrinsic, entry_premium * decay_factor)

In production the bar passed in would be the option-premium series directly.
The strategy supports both modes via ``price_series_mode``:

    ``"spot"``    bar.close is the underlying spot price; synthetic option
                  prices are computed internally (backtest / demo mode).

    ``"premium"`` bar.close is the combined CE+PE premium (like ATMStraddleSell).
                  Useful when the data provider gives a synthetic straddle series.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any, Literal

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_short_straddle_indian")


# ---------------------------------------------------------------------------
# Registry tables
# ---------------------------------------------------------------------------

LOT_SIZES: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "SENSEX": 10,
    "MIDCPNIFTY": 50,
}

STRIKE_INTERVALS: dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "SENSEX": 100,
    "MIDCPNIFTY": 25,
}

# Sensible default exchange per underlying
UNDERLYING_EXCHANGE: dict[str, str] = {
    "NIFTY": "NFO",
    "BANKNIFTY": "NFO",
    "FINNIFTY": "NFO",
    "SENSEX": "BFO",
    "MIDCPNIFTY": "NFO",
}

DEFAULT_LOT_SIZE: int = 1
DEFAULT_STRIKE_INTERVAL: int = 50


# ---------------------------------------------------------------------------
# Typed enums
# ---------------------------------------------------------------------------

class SLMode(StrEnum):
    PERCENTAGE = "percentage"
    COMBINED = "combined"
    FIXED_POINTS = "fixed_points"
    MTM_RUPEES = "mtm_rupees"
    TRAILING = "trailing"


class TargetMode(StrEnum):
    PREMIUM_PCT = "premium_pct"
    MTM_RUPEES = "mtm_rupees"
    NONE = "none"


class StraddleState(StrEnum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    SL_HIT = "SL_HIT"
    EXITED = "EXITED"


# ---------------------------------------------------------------------------
# Pure utility functions (no IO, fully testable)
# ---------------------------------------------------------------------------

def lot_size_for(underlying: str) -> int:
    """Return the standard lot size for an F&O underlying.

    Args:
        underlying: Underlying symbol name (case-insensitive).

    Returns:
        Lot size integer. Falls back to 1 for unknown underlyings.
    """
    key = underlying.strip().upper()
    return LOT_SIZES.get(key, DEFAULT_LOT_SIZE)


def strike_interval_for(underlying: str) -> int:
    """Return the standard strike interval for an F&O underlying.

    Args:
        underlying: Underlying symbol name (case-insensitive).

    Returns:
        Strike interval integer. Falls back to 50 for unknown underlyings.
    """
    key = underlying.strip().upper()
    return STRIKE_INTERVALS.get(key, DEFAULT_STRIKE_INTERVAL)


def atm_strike(spot_price: float, underlying: str) -> int:
    """Calculate the nearest ATM strike price.

    Rounds to the nearest multiple of the underlying's strike interval using
    standard NSE/BSE rounding: if the remainder is >= half the interval,
    round up; otherwise round down.

    Args:
        spot_price: Current underlying spot price.
        underlying: Underlying symbol name.

    Returns:
        ATM strike price as an integer.

    Examples:
        >>> atm_strike(19453.0, "NIFTY")   # interval=50 → 19450
        19450
        >>> atm_strike(19476.0, "NIFTY")   # remainder=26 >= 25 → round up
        19500
        >>> atm_strike(44987.0, "BANKNIFTY")  # interval=100
        45000
    """
    interval = strike_interval_for(underlying)
    remainder = spot_price % interval
    if remainder < interval / 2:
        return int(spot_price - remainder)
    return int(spot_price - remainder + interval)


def _time_str_to_minutes(time_str: str) -> int:
    """Convert HH:MM string to minutes since midnight.

    Args:
        time_str: Time in "HH:MM" format.

    Returns:
        Minutes since midnight.
    """
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def _bar_time_minutes(timestamp: str) -> int:
    """Extract time from bar timestamp and convert to minutes since midnight.

    Handles both ``"YYYY-MM-DD HH:MM:SS"`` and ``"YYYY-MM-DDTHH:MM:SS"`` formats.

    Args:
        timestamp: ISO-style timestamp string.

    Returns:
        Minutes since midnight from the timestamp's time component.
    """
    # Find time separator — space or T
    sep_idx = max(timestamp.find(" "), timestamp.find("T"))
    if sep_idx == -1:
        return 0
    time_part = timestamp[sep_idx + 1:]  # "HH:MM:SS"
    hh = int(time_part[0:2])
    mm = int(time_part[3:5])
    return hh * 60 + mm


# ---------------------------------------------------------------------------
# Main strategy
# ---------------------------------------------------------------------------

class IndianShortStraddle(BaseStrategy, _BacktestStrategyMixin):
    """Indian F&O Short Straddle — unified parameterised backtest strategy.

    Sells the ATM CE + ATM PE at ``entry_time`` and manages the position
    using one of five SL modes until ``exit_time`` or until both legs are
    exited by their respective SLs.

    Supports NIFTY, BANKNIFTY, FINNIFTY, SENSEX, MIDCPNIFTY.

    Usage::

        strategy = IndianShortStraddle(
            underlying="NIFTY",
            sl_mode="percentage",
            ce_sl_pct=25.0,
            pe_sl_pct=25.0,
            lots=1,
        )
        strategy.start()
        for bar in bars:
            strategy.on_bar(bar)
        orders = strategy.generate_orders()

    Parameters:
        underlying: Index name — NIFTY/BANKNIFTY/FINNIFTY/SENSEX/MIDCPNIFTY.
        exchange: Exchange code (defaults based on underlying).
        product: Product type (default NRML for options).
        entry_time: Bar time (HH:MM) at which to enter the straddle (default 09:20).
        exit_time: Bar time (HH:MM) for forced square-off (default 15:06).
        sl_mode: Stop-loss mode — ``percentage``, ``combined``, ``fixed_points``,
            ``mtm_rupees``, or ``trailing``.
        ce_sl_pct: Per-leg CE SL as % of sell price (used in percentage mode, default 25).
        pe_sl_pct: Per-leg PE SL as % of sell price (used in percentage mode, default 25).
        ce_sl_points: Fixed CE SL in absolute option-price points (fixed_points mode).
        pe_sl_points: Fixed PE SL in absolute option-price points (fixed_points mode).
        combined_sl_points: Combined premium SL in points above entry combined (combined mode).
        mtm_sl_rupees: MTM loss threshold in rupees to exit (mtm_rupees mode, positive).
        mtm_target_rupees: MTM profit target in rupees to exit (mtm_rupees mode, positive).
        tsl_points: Trailing SL distance in combined-premium points (trailing mode).
        target_mode: Take-profit mode — ``premium_pct``, ``mtm_rupees``, or ``none``.
        target_pct: % decay of combined premium to trigger profit-target exit.
        re_entry_enabled: Whether to re-enter after both-leg SL (default True).
        re_entry_time: Latest time (HH:MM) at which re-entry is allowed (default 12:30).
        lots: Number of lots to trade (default 1).
        price_series_mode: ``"spot"`` if bar.close is underlying price; ``"premium"``
            if bar.close is the combined straddle premium (default ``"spot"``).
    """

    def __init__(
        self,
        underlying: str = "NIFTY",
        exchange: str | None = None,
        product: str = "NRML",
        entry_time: str = "09:20",
        exit_time: str = "15:06",
        sl_mode: str | SLMode = SLMode.PERCENTAGE,
        ce_sl_pct: float = 25.0,
        pe_sl_pct: float = 25.0,
        ce_sl_points: float = 50.0,
        pe_sl_points: float = 60.0,
        combined_sl_points: float = 5.0,
        mtm_sl_rupees: float = 5000.0,
        mtm_target_rupees: float = 20000.0,
        tsl_points: float = 1.0,
        target_mode: str | TargetMode = TargetMode.NONE,
        target_pct: float = 30.0,
        re_entry_enabled: bool = True,
        re_entry_time: str = "12:30",
        lots: int = 1,
        price_series_mode: Literal["spot", "premium"] = "spot",
        **kwargs: Any,
    ) -> None:
        underlying_upper = underlying.strip().upper()
        if underlying_upper not in LOT_SIZES:
            raise ValueError(
                f"Unknown underlying '{underlying}'. "
                f"Supported: {sorted(LOT_SIZES.keys())}"
            )

        resolved_exchange = exchange or UNDERLYING_EXCHANGE.get(underlying_upper, "NFO")
        name = kwargs.pop(
            "name",
            f"IndianShortStraddle_{underlying_upper}_{sl_mode}_{lots}L",
        )
        super().__init__(name=name, exchange=resolved_exchange, product=product)
        self._init_history()

        # Underlying configuration
        self._underlying = underlying_upper
        self._lot_size: int = lot_size_for(underlying_upper)
        self._strike_interval: int = strike_interval_for(underlying_upper)
        self._quantity: int = lots * self._lot_size

        # Timing
        self._entry_time_mins: int = _time_str_to_minutes(entry_time)
        self._exit_time_mins: int = _time_str_to_minutes(exit_time)
        self._re_entry_time_mins: int = _time_str_to_minutes(re_entry_time)

        # Parameters
        self.lots = lots
        self.sl_mode = SLMode(sl_mode)
        self.ce_sl_pct = ce_sl_pct
        self.pe_sl_pct = pe_sl_pct
        self.ce_sl_points = ce_sl_points
        self.pe_sl_points = pe_sl_points
        self.combined_sl_points = combined_sl_points
        self.mtm_sl_rupees = abs(mtm_sl_rupees)
        self.mtm_target_rupees = abs(mtm_target_rupees)
        self.tsl_points = tsl_points
        self.target_mode = TargetMode(target_mode)
        self.target_pct = target_pct
        self.re_entry_enabled = re_entry_enabled
        self.price_series_mode: Literal["spot", "premium"] = price_series_mode

        # Per-trade state (reset on each new entry)
        self._straddle_state: StraddleState = StraddleState.WAITING
        self._atm: int = 0

        # CE leg state
        self._ce_sell_price: float = 0.0
        self._ce_ltp: float = 0.0
        self._ce_sl_level: float = 0.0
        self._ce_active: bool = False

        # PE leg state
        self._pe_sell_price: float = 0.0
        self._pe_ltp: float = 0.0
        self._pe_sl_level: float = 0.0
        self._pe_active: bool = False

        # Combined / MTM / trailing state
        self._entry_combined_premium: float = 0.0
        self._combined_sl_threshold: float = 0.0
        self._tsl_base: float = 0.0
        self._tsl_sl_threshold: float = 0.0

        # Re-entry tracking
        self._re_entry_count: int = 0

        logger.info(
            "IndianShortStraddle init | underlying=%s lot=%d qty=%d sl_mode=%s",
            self._underlying, self._lot_size, self._quantity, self.sl_mode,
        )

    # ------------------------------------------------------------------
    # BaseStrategy abstract hooks
    # ------------------------------------------------------------------

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — self-contained signal generation."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed OHLCV bar through the straddle state machine.

        The state machine progresses as follows:

        1. WAITING  — if bar time >= entry_time, execute entry and move to ACTIVE.
        2. ACTIVE   — evaluate SL/target per bar; queue exit orders as needed.
        3. SL_HIT   — if re-entry conditions met, re-enter and move back to ACTIVE.
        4. Any state — if bar time >= exit_time, square off and move to EXITED.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return

        self._record_bar(bar)
        bar_mins = _bar_time_minutes(bar.timestamp)

        # -- Forced exit at exit_time (always honoured) --
        if bar_mins >= self._exit_time_mins and self._straddle_state in (
            StraddleState.ACTIVE, StraddleState.SL_HIT
        ):
            self._square_off_all(bar)
            return

        # -- State dispatch --
        if self._straddle_state == StraddleState.WAITING:
            if bar_mins >= self._entry_time_mins:
                self._enter_straddle(bar)
            return

        if self._straddle_state == StraddleState.ACTIVE:
            self._manage_position(bar)
            return

        if self._straddle_state == StraddleState.SL_HIT:
            # Check re-entry window
            if (
                self.re_entry_enabled
                and bar_mins < self._re_entry_time_mins
                and bar_mins >= self._entry_time_mins
            ):
                self._enter_straddle(bar)

    def generate_orders(self) -> list[Order]:
        """Return and clear pending orders queued by on_bar().

        Returns:
            List of Order objects ready to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Entry logic
    # ------------------------------------------------------------------

    def _enter_straddle(self, bar: OHLCV) -> None:
        """Execute straddle entry: sell ATM CE + PE at the current bar close.

        Derives ATM strike from bar.close (if price_series_mode == "spot"),
        sets per-leg sell prices, computes SL thresholds for the chosen mode,
        and updates the straddle state to ACTIVE.

        Args:
            bar: The entry bar.
        """
        spot = bar.close

        if self.price_series_mode == "premium":
            # Combined-premium mode: treat bar.close as the straddle premium.
            # We can only use combined/trailing/mtm SL modes here.
            self._entry_combined_premium = spot
            self._ce_sell_price = spot / 2.0
            self._pe_sell_price = spot / 2.0
            self._atm = 0
        else:
            # Spot mode: compute ATM, proxy option price as ~0.5% of spot
            self._atm = atm_strike(spot, self._underlying)
            # Synthetic option price — in backtesting without live option data
            # we use a simple proxy: 0.5% of spot rounded to tick (0.05)
            proxy_premium = _round_tick(spot * 0.005)
            self._ce_sell_price = proxy_premium
            self._pe_sell_price = proxy_premium
            self._entry_combined_premium = self._ce_sell_price + self._pe_sell_price

        qty_str = str(self._quantity)

        # Build synthetic option symbol strings
        ce_sym = f"{self._underlying}{self._atm}CE" if self._atm else f"{self._underlying}CE"
        pe_sym = f"{self._underlying}{self._atm}PE" if self._atm else f"{self._underlying}PE"

        # Queue SELL orders for both legs
        self._pending_orders.append(Order(
            symbol=ce_sym,
            action="SELL",
            exchange=self.exchange,
            quantity=qty_str,
            strategy=self.name,
        ))
        self._pending_orders.append(Order(
            symbol=pe_sym,
            action="SELL",
            exchange=self.exchange,
            quantity=qty_str,
            strategy=self.name,
        ))

        self._ce_active = True
        self._pe_active = True

        # Compute SL thresholds based on mode
        self._recompute_sl_thresholds()

        self._straddle_state = StraddleState.ACTIVE
        self._re_entry_count += 1 if self._straddle_state == StraddleState.SL_HIT else 0

        logger.info(
            "Straddle entry #%d | underlying=%s atm=%d ce_sell=%.2f pe_sell=%.2f "
            "combined=%.2f sl_mode=%s | bar=%s",
            self._re_entry_count,
            self._underlying, self._atm,
            self._ce_sell_price, self._pe_sell_price,
            self._entry_combined_premium, self.sl_mode, bar.timestamp,
        )

    def _recompute_sl_thresholds(self) -> None:
        """Recompute all SL/target threshold values from current sell prices.

        Called once on entry and again after re-entry.
        """
        if self.sl_mode == SLMode.PERCENTAGE:
            ce_sl_delta = _round_tick(self._ce_sell_price * self.ce_sl_pct / 100.0)
            pe_sl_delta = _round_tick(self._pe_sell_price * self.pe_sl_pct / 100.0)
            self._ce_sl_level = _round_tick(self._ce_sell_price + ce_sl_delta)
            self._pe_sl_level = _round_tick(self._pe_sell_price + pe_sl_delta)

        elif self.sl_mode == SLMode.FIXED_POINTS:
            self._ce_sl_level = _round_tick(self._ce_sell_price + self.ce_sl_points)
            self._pe_sl_level = _round_tick(self._pe_sell_price + self.pe_sl_points)

        elif self.sl_mode in (SLMode.COMBINED, SLMode.MTM_RUPEES):
            # SL at entry combined + combined_sl_points
            self._combined_sl_threshold = self._entry_combined_premium + self.combined_sl_points
            # Per-leg proxies kept as infinity when in combined mode
            self._ce_sl_level = float("inf")
            self._pe_sl_level = float("inf")

        elif self.sl_mode == SLMode.TRAILING:
            self._tsl_base = self._entry_combined_premium
            self._tsl_sl_threshold = self._entry_combined_premium + self.tsl_points
            self._ce_sl_level = float("inf")
            self._pe_sl_level = float("inf")

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def _manage_position(self, bar: OHLCV) -> None:
        """Monitor open legs and trigger exits as per the active SL mode.

        Called on every bar while straddle_state == ACTIVE.

        Args:
            bar: The current OHLCV bar.
        """
        # Derive synthetic leg prices from bar
        ce_ltp, pe_ltp = self._derive_leg_ltps(bar)
        self._ce_ltp = ce_ltp
        self._pe_ltp = pe_ltp
        combined_ltp = ce_ltp + pe_ltp

        qty_str = str(self._quantity)
        ce_sym = f"{self._underlying}{self._atm}CE" if self._atm else f"{self._underlying}CE"
        pe_sym = f"{self._underlying}{self._atm}PE" if self._atm else f"{self._underlying}PE"

        # ── Target check (runs before SL; profit > safety) ─────────────
        if self._check_target_hit(combined_ltp):
            self._exit_leg("CE", ce_sym, qty_str, "target")
            self._exit_leg("PE", pe_sym, qty_str, "target")
            self._straddle_state = StraddleState.EXITED
            return

        # ── SL checks per mode ──────────────────────────────────────────
        if self.sl_mode == SLMode.PERCENTAGE:
            self._handle_percentage_sl(bar, ce_sym, pe_sym, ce_ltp, pe_ltp, qty_str)

        elif self.sl_mode == SLMode.FIXED_POINTS:
            self._handle_fixed_points_sl(bar, ce_sym, pe_sym, ce_ltp, pe_ltp, qty_str)

        elif self.sl_mode == SLMode.COMBINED:
            self._handle_combined_sl(bar, ce_sym, pe_sym, combined_ltp, qty_str)

        elif self.sl_mode == SLMode.MTM_RUPEES:
            self._handle_mtm_sl(bar, ce_sym, pe_sym, ce_ltp, pe_ltp, qty_str)

        elif self.sl_mode == SLMode.TRAILING:
            self._handle_trailing_sl(bar, ce_sym, pe_sym, combined_ltp, qty_str)

    def _handle_percentage_sl(
        self,
        bar: OHLCV,
        ce_sym: str,
        pe_sym: str,
        ce_ltp: float,
        pe_ltp: float,
        qty_str: str,
    ) -> None:
        """Handle per-leg percentage-based SL exit.

        Each leg is checked independently. If both legs exit, transition
        to SL_HIT for potential re-entry.

        Args:
            bar: Current bar (for logging).
            ce_sym: CE option symbol string.
            pe_sym: PE option symbol string.
            ce_ltp: CE option current price.
            pe_ltp: PE option current price.
            qty_str: Quantity as string.
        """
        if self._ce_active and ce_ltp >= self._ce_sl_level:
            self._exit_leg("CE", ce_sym, qty_str, f"SL_pct({self.ce_sl_pct}%)")
            logger.info(
                "CE SL hit | ltp=%.2f sl=%.2f | %s | bar=%s",
                ce_ltp, self._ce_sl_level, self._underlying, bar.timestamp,
            )

        if self._pe_active and pe_ltp >= self._pe_sl_level:
            self._exit_leg("PE", pe_sym, qty_str, f"SL_pct({self.pe_sl_pct}%)")
            logger.info(
                "PE SL hit | ltp=%.2f sl=%.2f | %s | bar=%s",
                pe_ltp, self._pe_sl_level, self._underlying, bar.timestamp,
            )

        self._check_both_legs_exited()

    def _handle_fixed_points_sl(
        self,
        bar: OHLCV,
        ce_sym: str,
        pe_sym: str,
        ce_ltp: float,
        pe_ltp: float,
        qty_str: str,
    ) -> None:
        """Handle per-leg fixed-points SL exit.

        Args:
            bar: Current bar (for logging).
            ce_sym: CE symbol string.
            pe_sym: PE symbol string.
            ce_ltp: CE current price.
            pe_ltp: PE current price.
            qty_str: Quantity string.
        """
        if self._ce_active and ce_ltp >= self._ce_sl_level:
            self._exit_leg("CE", ce_sym, qty_str, f"SL_pts({self.ce_sl_points}pts)")
            logger.info(
                "CE fixed-pts SL hit | ltp=%.2f sl=%.2f | %s | bar=%s",
                ce_ltp, self._ce_sl_level, self._underlying, bar.timestamp,
            )

        if self._pe_active and pe_ltp >= self._pe_sl_level:
            self._exit_leg("PE", pe_sym, qty_str, f"SL_pts({self.pe_sl_points}pts)")
            logger.info(
                "PE fixed-pts SL hit | ltp=%.2f sl=%.2f | %s | bar=%s",
                pe_ltp, self._pe_sl_level, self._underlying, bar.timestamp,
            )

        self._check_both_legs_exited()

    def _handle_combined_sl(
        self,
        bar: OHLCV,
        ce_sym: str,
        pe_sym: str,
        combined_ltp: float,
        qty_str: str,
    ) -> None:
        """Handle combined-premium SL exit.

        Args:
            bar: Current bar (for logging).
            ce_sym: CE symbol string.
            pe_sym: PE symbol string.
            combined_ltp: Sum of CE + PE current prices.
            qty_str: Quantity string.
        """
        if combined_ltp >= self._combined_sl_threshold:
            logger.info(
                "Combined SL hit | combined=%.2f threshold=%.2f | %s | bar=%s",
                combined_ltp, self._combined_sl_threshold, self._underlying, bar.timestamp,
            )
            if self._ce_active:
                self._exit_leg("CE", ce_sym, qty_str, "combined_SL")
            if self._pe_active:
                self._exit_leg("PE", pe_sym, qty_str, "combined_SL")
            self._straddle_state = StraddleState.SL_HIT

    def _handle_mtm_sl(
        self,
        bar: OHLCV,
        ce_sym: str,
        pe_sym: str,
        ce_ltp: float,
        pe_ltp: float,
        qty_str: str,
    ) -> None:
        """Handle account-level MTM stop-loss and target.

        P&L is calculated as:
            pnl = (ce_sell - ce_ltp + pe_sell - pe_ltp) * quantity

        Args:
            bar: Current bar (for logging).
            ce_sym: CE symbol string.
            pe_sym: PE symbol string.
            ce_ltp: CE current price.
            pe_ltp: PE current price.
            qty_str: Quantity string.
        """
        pnl = (
            (self._ce_sell_price - ce_ltp + self._pe_sell_price - pe_ltp)
            * self._quantity
        )

        if pnl <= -self.mtm_sl_rupees:
            logger.info(
                "MTM SL hit | pnl=%.0f threshold=-%.0f | %s | bar=%s",
                pnl, self.mtm_sl_rupees, self._underlying, bar.timestamp,
            )
            if self._ce_active:
                self._exit_leg("CE", ce_sym, qty_str, "mtm_SL")
            if self._pe_active:
                self._exit_leg("PE", pe_sym, qty_str, "mtm_SL")
            self._straddle_state = StraddleState.SL_HIT

    def _handle_trailing_sl(
        self,
        bar: OHLCV,
        ce_sym: str,
        pe_sym: str,
        combined_ltp: float,
        qty_str: str,
    ) -> None:
        """Handle trailing combined-premium SL.

        If the combined premium falls below (base - tsl_points), reset the
        base and tighten the SL. If it rises above the current SL threshold,
        exit all positions.

        Args:
            bar: Current bar (for logging).
            ce_sym: CE symbol string.
            pe_sym: PE symbol string.
            combined_ltp: Sum of CE + PE current prices.
            qty_str: Quantity string.
        """
        # Ratchet the trailing base down as premium decays
        if combined_ltp < self._tsl_base - self.tsl_points:
            self._tsl_base = combined_ltp
            self._tsl_sl_threshold = combined_ltp + self.tsl_points
            logger.debug(
                "TSL ratcheted | base=%.2f new_sl=%.2f | %s | bar=%s",
                self._tsl_base, self._tsl_sl_threshold, self._underlying, bar.timestamp,
            )

        if combined_ltp >= self._tsl_sl_threshold:
            logger.info(
                "TSL hit | combined=%.2f sl=%.2f | %s | bar=%s",
                combined_ltp, self._tsl_sl_threshold, self._underlying, bar.timestamp,
            )
            if self._ce_active:
                self._exit_leg("CE", ce_sym, qty_str, "trailing_SL")
            if self._pe_active:
                self._exit_leg("PE", pe_sym, qty_str, "trailing_SL")
            self._straddle_state = StraddleState.SL_HIT

    # ------------------------------------------------------------------
    # Target check
    # ------------------------------------------------------------------

    def _check_target_hit(self, combined_ltp: float) -> bool:
        """Return True if the target exit condition is met.

        Args:
            combined_ltp: Current combined premium (CE + PE).

        Returns:
            True if a target exit should be triggered.
        """
        if self.target_mode == TargetMode.NONE:
            return False

        if self.target_mode == TargetMode.PREMIUM_PCT:
            if self._entry_combined_premium <= 0:
                return False
            decay_pct = (
                (self._entry_combined_premium - combined_ltp)
                / self._entry_combined_premium
                * 100.0
            )
            return decay_pct >= self.target_pct

        if self.target_mode == TargetMode.MTM_RUPEES:
            pnl = (
                (self._ce_sell_price - self._ce_ltp + self._pe_sell_price - self._pe_ltp)
                * self._quantity
            )
            return pnl >= self.mtm_target_rupees

        return False

    # ------------------------------------------------------------------
    # Exit helpers
    # ------------------------------------------------------------------

    def _exit_leg(self, leg: str, symbol: str, qty_str: str, reason: str) -> None:
        """Queue a BUY (close) order for an option leg and mark it inactive.

        For a short straddle, closing a leg requires buying back the option.

        Args:
            leg: "CE" or "PE" (for state tracking).
            symbol: Option symbol string.
            qty_str: Quantity string.
            reason: Human-readable reason string (for logging).
        """
        self._pending_orders.append(Order(
            symbol=symbol,
            action="BUY",
            exchange=self.exchange,
            quantity=qty_str,
            strategy=self.name,
        ))
        if leg == "CE":
            self._ce_active = False
        else:
            self._pe_active = False
        logger.debug(
            "Exit leg %s | symbol=%s reason=%s qty=%s", leg, symbol, reason, qty_str,
        )

    def _square_off_all(self, bar: OHLCV) -> None:
        """Close all open legs at exit_time (forced square-off).

        Args:
            bar: The exit bar (for logging only).
        """
        qty_str = str(self._quantity)
        ce_sym = f"{self._underlying}{self._atm}CE" if self._atm else f"{self._underlying}CE"
        pe_sym = f"{self._underlying}{self._atm}PE" if self._atm else f"{self._underlying}PE"

        if self._ce_active:
            self._exit_leg("CE", ce_sym, qty_str, "squareoff")
        if self._pe_active:
            self._exit_leg("PE", pe_sym, qty_str, "squareoff")

        self._straddle_state = StraddleState.EXITED
        logger.info(
            "Square-off executed | %s | bar=%s", self._underlying, bar.timestamp,
        )

    def _check_both_legs_exited(self) -> None:
        """Transition to SL_HIT if both legs are no longer active."""
        if not self._ce_active and not self._pe_active:
            self._straddle_state = StraddleState.SL_HIT

    # ------------------------------------------------------------------
    # Price derivation helper
    # ------------------------------------------------------------------

    def _derive_leg_ltps(self, bar: OHLCV) -> tuple[float, float]:
        """Derive synthetic CE and PE LTPs from the bar.

        In ``"spot"`` mode: We use the bar.close as the spot. The option LTPs
        decay linearly as a fraction of the entry premium with a simple
        intrinsic-value component so that ITM behaviour is modelled correctly.

        In ``"premium"`` mode: bar.close is the combined premium; we split it
        equally between CE and PE.

        This is intentionally a lightweight proxy. For high-fidelity backtesting
        the caller should provide individual option bar series or use the
        ``"premium"`` mode with a synthetic straddle premium series.

        Args:
            bar: Current OHLCV bar.

        Returns:
            Tuple of (ce_ltp, pe_ltp).
        """
        if self.price_series_mode == "premium":
            half = bar.close / 2.0
            return half, half

        # Spot mode: proxy CE and PE LTP from spot movement since entry
        # ce_ltp goes up when spot goes up (call becomes ITM)
        # pe_ltp goes up when spot goes down (put becomes ITM)
        n = len(self._closes)
        # Identify entry bar index conservatively — use first close recorded
        entry_close = self._closes[0] if n > 0 else bar.close
        delta = bar.close - entry_close

        # CE intrinsic: max(spot - strike, 0) proxied as max(delta, 0)
        # PE intrinsic: max(strike - spot, 0) proxied as max(-delta, 0)
        ce_intrinsic = max(delta, 0.0)
        pe_intrinsic = max(-delta, 0.0)

        ce_ltp = _round_tick(self._ce_sell_price + ce_intrinsic)
        pe_ltp = _round_tick(self._pe_sell_price + pe_intrinsic)

        return max(ce_ltp, 0.05), max(pe_ltp, 0.05)

    # ------------------------------------------------------------------
    # Public convenience accessors
    # ------------------------------------------------------------------

    @property
    def straddle_state(self) -> StraddleState:
        """Current straddle state machine state."""
        return self._straddle_state

    @property
    def atm_strike_cached(self) -> int:
        """The ATM strike selected at entry (0 if not yet entered)."""
        return self._atm

    @property
    def entry_combined_premium(self) -> float:
        """Combined CE+PE sell premium at entry (0 if not yet entered)."""
        return self._entry_combined_premium


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _round_tick(price: float, tick: float = 0.05) -> float:
    """Round an option price to the standard NSE tick size (0.05).

    Args:
        price: Raw price.
        tick: Tick size (default 0.05).

    Returns:
        Price rounded down to the nearest tick.
    """
    return round(round(price / tick) * tick, 2)


__all__ = [
    "IndianShortStraddle",
    "LOT_SIZES",
    "STRIKE_INTERVALS",
    "SLMode",
    "TargetMode",
    "StraddleState",
    "lot_size_for",
    "strike_interval_for",
    "atm_strike",
]
