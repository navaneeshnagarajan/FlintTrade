"""Position sizing calculator for FlintTrade strategies.

Provides four sizing methods used in F&O / equity trading:

* :meth:`~PositionSizer.from_capital` — invest a fixed rupee amount.
* :meth:`~PositionSizer.from_risk_percent` — risk a percentage of capital on a
  single trade (uses distance to stop-loss).
* :meth:`~PositionSizer.from_kelly` — fractional Kelly criterion sizing.
* :meth:`~PositionSizer.max_lots` — maximum lots affordable given margin.

All methods return an integer quantity (number of shares / units).  They never
raise on bad inputs — they return 0 instead so callers can safely use the
result as a quantity guard.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger("flinttrade.engine.position_sizer")


class PositionSizer:
    """Stateless helper for position size calculations.

    All methods are ``@staticmethod`` so you can call them without
    instantiation::

        qty = PositionSizer.from_risk_percent(
            capital=100_000, risk_pct=0.01, entry=450.0, sl=445.0, lot_size=50
        )
    """

    @staticmethod
    def from_capital(
        capital: float,
        ltp: float,
        lot_size: int = 1,
    ) -> int:
        """Calculate quantity from a rupee capital amount.

        Formula: ``floor(capital / ltp) * lot_size``

        Args:
            capital: Rupee amount to deploy (must be > 0).
            ltp: Last traded price of the instrument (must be > 0).
            lot_size: Lot size for F&O instruments (1 for equities).

        Returns:
            Integer quantity.  Returns 0 when inputs are invalid or when the
            capital is insufficient for even one lot.

        Examples::

            PositionSizer.from_capital(50_000, 500.0, lot_size=50)  # 100
        """
        if capital <= 0 or ltp <= 0 or lot_size < 1:
            logger.debug(
                "from_capital: invalid inputs capital=%.2f ltp=%.2f lot_size=%d",
                capital,
                ltp,
                lot_size,
            )
            return 0
        raw = math.floor(capital / ltp)
        qty = (raw // lot_size) * lot_size
        return max(0, qty)

    @staticmethod
    def from_risk_percent(
        capital: float,
        risk_pct: float,
        entry: float,
        sl: float,
        lot_size: int = 1,
    ) -> int:
        """Risk-based position sizing.

        Sizes the position so that if the stop-loss is hit the loss equals
        ``risk_pct`` of ``capital``.

        Formula: ``floor((capital * risk_pct) / |entry - sl|) * lot_size``

        Args:
            capital: Total account capital in rupees (must be > 0).
            risk_pct: Fraction of capital to risk, e.g. 0.01 for 1%
                (must be in range (0, 1]).
            entry: Entry price (must be > 0).
            sl: Stop-loss price (must be > 0 and not equal to ``entry``).
            lot_size: Lot size for F&O instruments (1 for equities).

        Returns:
            Integer quantity rounded down to the nearest lot.  Returns 0 when
            inputs are invalid or the risk amount is smaller than one tick.

        Examples::

            PositionSizer.from_risk_percent(
                capital=100_000, risk_pct=0.01, entry=450.0, sl=445.0, lot_size=50
            )
            # risk = 1000, distance = 5, raw_qty = 200 → 200 (4 lots of 50)
        """
        if capital <= 0 or risk_pct <= 0 or risk_pct > 1:
            logger.debug("from_risk_percent: invalid capital or risk_pct")
            return 0
        if entry <= 0 or sl <= 0:
            logger.debug("from_risk_percent: entry/sl must be > 0")
            return 0
        distance = abs(entry - sl)
        if distance == 0:
            logger.debug("from_risk_percent: entry == sl, cannot size")
            return 0
        risk_amount = capital * risk_pct
        raw = math.floor(risk_amount / distance)
        qty = (raw // lot_size) * lot_size
        return max(0, qty)

    @staticmethod
    def from_kelly(
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        capital: float,
        ltp: float,
    ) -> int:
        """Kelly criterion position sizing (half-Kelly for safety).

        Computes the full Kelly fraction then halves it (half-Kelly) to reduce
        variance while preserving most of the theoretical growth advantage.

        Full Kelly formula: ``f = win_rate - (1 - win_rate) / (avg_win / avg_loss)``
        Applied capital: ``kelly_frac * 0.5 * capital``

        Args:
            win_rate: Historical win rate, 0.0–1.0.
            avg_win: Average profit per winning trade in rupees (must be > 0).
            avg_loss: Average loss per losing trade in rupees (must be > 0).
            capital: Account capital in rupees (must be > 0).
            ltp: Last traded price used to convert monetary amount to units
                (must be > 0).

        Returns:
            Integer quantity.  Returns 0 when Kelly fraction is non-positive
            (i.e. the system is unprofitable by Kelly standards) or when
            inputs are invalid.

        Examples::

            PositionSizer.from_kelly(
                win_rate=0.55, avg_win=500, avg_loss=300, capital=200_000, ltp=500
            )
        """
        if not (0 < win_rate < 1):
            logger.debug("from_kelly: win_rate must be in (0, 1)")
            return 0
        if avg_win <= 0 or avg_loss <= 0 or capital <= 0 or ltp <= 0:
            logger.debug("from_kelly: avg_win/avg_loss/capital/ltp must be > 0")
            return 0

        loss_rate = 1.0 - win_rate
        win_loss_ratio = avg_win / avg_loss
        kelly_fraction = win_rate - (loss_rate / win_loss_ratio)

        if kelly_fraction <= 0:
            # System is unprofitable by Kelly metric — do not trade
            return 0

        # Half-Kelly to reduce variance
        deploy = capital * kelly_fraction * 0.5
        qty = math.floor(deploy / ltp)
        return max(0, qty)

    @staticmethod
    def max_lots(
        capital: float,
        margin_per_lot: float,
    ) -> int:
        """Maximum number of lots affordable given available margin.

        Formula: ``floor(capital / margin_per_lot)``

        Args:
            capital: Available margin / capital in rupees (must be > 0).
            margin_per_lot: Margin required per lot in rupees (must be > 0).

        Returns:
            Integer number of lots.  Returns 0 when inputs are invalid.

        Examples::

            PositionSizer.max_lots(capital=500_000, margin_per_lot=120_000)  # 4
        """
        if capital <= 0 or margin_per_lot <= 0:
            logger.debug(
                "max_lots: invalid inputs capital=%.2f margin_per_lot=%.2f",
                capital,
                margin_per_lot,
            )
            return 0
        return math.floor(capital / margin_per_lot)
