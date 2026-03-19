"""5-layer safety system for order validation and risk management.

Layer 1: Order validation (price, qty, exchange, symbol, market hours)
Layer 2: Position limits (max simultaneous, margin usage)
Layer 3: Portfolio risk (net delta/vega limits for options)
Layer 4: Daily P&L limits (pause trigger, kill switch)
Layer 5: Kill switch (cancel all + close all)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from enum import Enum, StrEnum

from packages.core.src.models import Order, Position
from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.engine.safety")

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Result type shared by all layers
# ---------------------------------------------------------------------------


class SafetyVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class SafetyResult:
    """Result from a single safety layer check."""

    verdict: SafetyVerdict
    layer: str
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == SafetyVerdict.PASS


# ---------------------------------------------------------------------------
# Per-exchange market hours (IST)
# ---------------------------------------------------------------------------

MARKET_HOURS: dict[str, tuple[dt_time, dt_time]] = {
    "NSE":   (dt_time(9, 15), dt_time(15, 30)),
    "BSE":   (dt_time(9, 15), dt_time(15, 30)),
    "NFO":   (dt_time(9, 15), dt_time(15, 30)),
    "BFO":   (dt_time(9, 15), dt_time(15, 30)),
    "CDS":   (dt_time(9, 0),  dt_time(17, 0)),
    "BCD":   (dt_time(9, 0),  dt_time(17, 0)),
    "MCX":   (dt_time(9, 0),  dt_time(23, 30)),
    "NCDEX": (dt_time(10, 0), dt_time(17, 0)),
    "DELTA": (dt_time(0, 0),  dt_time(23, 59)),  # 24/7 crypto
}

# Exchanges that are quote-only — orders always rejected
_QUOTE_ONLY_EXCHANGES = {"NSE_INDEX", "BSE_INDEX"}

# Exchange routing: all exchanges route through OpenAlgo (including Delta Exchange)
OPENALGO_EXCHANGES = {
    "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX",
    "NSE_INDEX", "BSE_INDEX", "NCDEX", "DELTA",
}


def is_market_open(exchange: str, at: datetime | None = None) -> bool:
    """Check if the given exchange is currently open for trading.

    - NSE_INDEX / BSE_INDEX: always False (quote-only, no orders)
    - DELTA: always True (24/7 crypto via ccxt, not OpenAlgo)
    - Unknown exchanges: False
    - Known exchanges: True only if current IST time is within market hours
    """
    if exchange in _QUOTE_ONLY_EXCHANGES:
        return False

    # Delta Exchange — 24/7 via native OpenAlgo broker integration
    if exchange == "DELTA":
        return True

    if exchange not in MARKET_HOURS:
        return False

    now = at or datetime.now(IST)
    current_time = now.time().replace(tzinfo=None)
    open_time, close_time = MARKET_HOURS[exchange]
    return open_time <= current_time < close_time


def get_expiry_time(exchange: str) -> dt_time:
    """Return the expiry/settlement time for the given exchange.

    Used for accurate Greeks/theta calculations.
    """
    expiry_times: dict[str, dt_time] = {
        "NFO":   dt_time(15, 30),
        "BFO":   dt_time(15, 30),
        "CDS":   dt_time(12, 30),
        "BCD":   dt_time(12, 30),
        "MCX":   dt_time(23, 30),
        "DELTA": dt_time(18, 0),  # BTC/ETH weekly options + daily futures: 12:30 UTC = 18:00 IST
    }
    return expiry_times.get(exchange, dt_time(15, 30))


def _format_market_hours(exchange: str) -> str:
    """Format market hours for error messages."""
    if exchange in MARKET_HOURS:
        o, c = MARKET_HOURS[exchange]
        return f"{o.strftime('%H:%M')}–{c.strftime('%H:%M')} IST"
    return "unknown"


# ---------------------------------------------------------------------------
# Layer 1 — Order Validation
# ---------------------------------------------------------------------------

# Valid exchanges that can receive orders (excludes index-only segments)
_TRADEABLE_EXCHANGES = {"NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "DELTA"}

# Per-exchange max single-order quantity defaults (can be overridden)
_DEFAULT_QTY_LIMITS: dict[str, int] = {
    "NSE": 50_000,
    "BSE": 50_000,
    "NFO": 5_000,
    "BFO": 5_000,
    "MCX": 1_000,
    "CDS": 10_000,
    "BCD": 10_000,
    "NCDEX": 5_000,
}


class OrderValidation:
    """Layer 1: Validates individual order fields before submission.

    Checks:
    - Exchange is tradeable (not NSE_INDEX/BSE_INDEX)
    - Market is open for the exchange (per-exchange hours)
    - Symbol is non-empty
    - Quantity is positive and within exchange limits
    - For LIMIT/SL orders, price is within 5% of LTP
    """

    def __init__(
        self,
        price_deviation_pct: float = 5.0,
        qty_limits: dict[str, int] | None = None,
        check_market_hours: bool = True,
    ) -> None:
        self.price_deviation_pct = price_deviation_pct
        self.qty_limits = qty_limits or dict(_DEFAULT_QTY_LIMITS)
        self.check_market_hours = check_market_hours

    def validate(self, order: Order, ltp: float | None = None, at: datetime | None = None) -> SafetyResult:
        exchange = order.exchange.value if hasattr(order.exchange, "value") else str(order.exchange)

        # Exchange check
        if exchange not in _TRADEABLE_EXCHANGES:
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", f"Exchange {exchange} is not tradeable")

        # Market hours check
        if self.check_market_hours and not is_market_open(exchange, at=at):
            now = at or datetime.now(IST)
            current_time = now.time().replace(tzinfo=None).strftime("%H:%M")
            hours = _format_market_hours(exchange)
            return SafetyResult(
                SafetyVerdict.FAIL, "L1_ORDER",
                f"{exchange} is open {hours}. Current time: {current_time}. Market closed.",
            )

        # Log Delta Exchange orders routed through native OpenAlgo broker
        if exchange == "DELTA":
            logger.info(
                "Order for DELTA exchange — routes via OpenAlgo Delta Exchange broker integration",
            )

        # Symbol check
        if not order.symbol or not order.symbol.strip():
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", "Symbol is empty")

        # Quantity check
        qty = int(order.quantity)
        if qty <= 0:
            return SafetyResult(SafetyVerdict.FAIL, "L1_ORDER", f"Quantity must be positive, got {qty}")

        max_qty = self.qty_limits.get(exchange, 50_000)
        if qty > max_qty:
            return SafetyResult(
                SafetyVerdict.FAIL, "L1_ORDER",
                f"Quantity {qty} exceeds {exchange} limit of {max_qty}",
            )

        # Price check for LIMIT / SL orders
        pricetype = order.pricetype.value if hasattr(order.pricetype, "value") else str(order.pricetype)
        if pricetype in ("LIMIT", "SL") and ltp is not None and ltp > 0:
            order_price = float(order.price)
            if order_price > 0:
                deviation = abs(order_price - ltp) / ltp * 100
                if deviation > self.price_deviation_pct:
                    return SafetyResult(
                        SafetyVerdict.FAIL, "L1_ORDER",
                        f"Price {order_price} deviates {deviation:.1f}% from LTP {ltp} "
                        f"(max {self.price_deviation_pct}%)",
                    )

        return SafetyResult(SafetyVerdict.PASS, "L1_ORDER")


# ---------------------------------------------------------------------------
# Layer 2 — Position Limits
# ---------------------------------------------------------------------------


class PositionLimits:
    """Layer 2: Enforces portfolio-level position and margin constraints.

    Checks:
    - Max simultaneous open positions (default 5)
    - Max margin usage percentage (default 60%)
    """

    def __init__(
        self,
        max_positions: int = 5,
        max_margin_pct: float = 60.0,
    ) -> None:
        self.max_positions = max_positions
        self.max_margin_pct = max_margin_pct

    def validate(
        self,
        current_positions: list[Position],
        used_margin: float,
        total_balance: float,
    ) -> SafetyResult:
        # Count positions with non-zero quantity
        active = [p for p in current_positions if int(p.quantity) != 0]
        if len(active) >= self.max_positions:
            return SafetyResult(
                SafetyVerdict.FAIL, "L2_POSITION",
                f"Already at max positions ({len(active)}/{self.max_positions})",
            )

        # Margin usage check
        if total_balance > 0:
            margin_pct = (used_margin / total_balance) * 100
            if margin_pct >= self.max_margin_pct:
                return SafetyResult(
                    SafetyVerdict.FAIL, "L2_POSITION",
                    f"Margin usage {margin_pct:.1f}% exceeds limit of {self.max_margin_pct}%",
                )

        return SafetyResult(SafetyVerdict.PASS, "L2_POSITION")


# ---------------------------------------------------------------------------
# Layer 3 — Portfolio Risk (Options Greeks)
# ---------------------------------------------------------------------------


class PortfolioRisk:
    """Layer 3: Net Greeks limits for options portfolios.

    Checks:
    - Absolute net delta doesn't exceed limit
    - Absolute net vega doesn't exceed limit
    """

    def __init__(
        self,
        max_net_delta: float = 500.0,
        max_net_vega: float = 10_000.0,
    ) -> None:
        self.max_net_delta = max_net_delta
        self.max_net_vega = max_net_vega

    def validate(
        self,
        net_delta: float,
        net_vega: float,
    ) -> SafetyResult:
        if abs(net_delta) > self.max_net_delta:
            return SafetyResult(
                SafetyVerdict.FAIL, "L3_PORTFOLIO",
                f"Net delta {net_delta:.1f} exceeds limit of ±{self.max_net_delta}",
            )

        if abs(net_vega) > self.max_net_vega:
            return SafetyResult(
                SafetyVerdict.FAIL, "L3_PORTFOLIO",
                f"Net vega {net_vega:.1f} exceeds limit of ±{self.max_net_vega}",
            )

        return SafetyResult(SafetyVerdict.PASS, "L3_PORTFOLIO")


# ---------------------------------------------------------------------------
# Layer 4 — Daily P&L Limits
# ---------------------------------------------------------------------------


class DailyPnLLimits:
    """Layer 4: Daily P&L circuit breakers.

    - Pause trigger: 3% loss → pause all strategies (reversible)
    - Kill switch: 15% loss → full kill switch (requires manual reset)
    """

    def __init__(
        self,
        pause_pct: float = 3.0,
        kill_pct: float = 15.0,
    ) -> None:
        self.pause_pct = pause_pct
        self.kill_pct = kill_pct
        self._paused = False
        self._killed = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_killed(self) -> bool:
        return self._killed

    def reset_pause(self) -> None:
        """Manually resume after a pause trigger."""
        self._paused = False
        logger.info("Daily P&L pause reset")

    def reset_kill(self) -> None:
        """Manually resume after a kill trigger. Requires explicit action."""
        self._killed = False
        logger.warning("Daily P&L kill switch reset — manual override")

    def validate(self, daily_pnl: float, starting_capital: float) -> SafetyResult:
        if self._killed:
            return SafetyResult(
                SafetyVerdict.FAIL, "L4_PNL",
                "Kill switch active — manual reset required",
            )

        if self._paused:
            return SafetyResult(
                SafetyVerdict.FAIL, "L4_PNL",
                "Trading paused due to daily P&L limit — call reset_pause() to resume",
            )

        if starting_capital <= 0:
            return SafetyResult(SafetyVerdict.PASS, "L4_PNL")

        loss_pct = (-daily_pnl / starting_capital) * 100 if daily_pnl < 0 else 0.0

        if loss_pct >= self.kill_pct:
            self._killed = True
            logger.critical(
                "KILL SWITCH triggered: daily loss %.1f%% exceeds %.1f%%",
                loss_pct, self.kill_pct,
            )
            return SafetyResult(
                SafetyVerdict.FAIL, "L4_PNL",
                f"Kill switch triggered: daily loss {loss_pct:.1f}% exceeds {self.kill_pct}%",
            )

        if loss_pct >= self.pause_pct:
            self._paused = True
            logger.warning(
                "PAUSE triggered: daily loss %.1f%% exceeds %.1f%%",
                loss_pct, self.pause_pct,
            )
            return SafetyResult(
                SafetyVerdict.FAIL, "L4_PNL",
                f"Pause triggered: daily loss {loss_pct:.1f}% exceeds {self.pause_pct}%",
            )

        return SafetyResult(SafetyVerdict.PASS, "L4_PNL")


# ---------------------------------------------------------------------------
# Layer 5 — Kill Switch
# ---------------------------------------------------------------------------


class KillSwitch:
    """Layer 5: Emergency kill — cancel all orders + close all positions.

    Once activated, blocks ALL orders until manually reset.
    """

    def __init__(self) -> None:
        self._active = False
        self._reason: str = ""

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def activate(self, reason: str, client: OpenAlgoClient | None = None) -> None:
        """Activate kill switch. Optionally cancel/close via the API client."""
        self._active = True
        self._reason = reason
        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

        if client is not None:
            try:
                client.cancel_all_orders()
                logger.info("Kill switch: all orders cancelled")
            except Exception as exc:
                logger.error("Kill switch: cancel_all_orders failed: %s", exc)

            try:
                client.close_position()
                logger.info("Kill switch: close_position sent")
            except Exception as exc:
                logger.error("Kill switch: close_position failed: %s", exc)

    def reset(self) -> None:
        """Manually deactivate kill switch."""
        logger.warning("Kill switch deactivated — manual override by operator")
        self._active = False
        self._reason = ""

    def validate(self) -> SafetyResult:
        if self._active:
            return SafetyResult(
                SafetyVerdict.FAIL, "L5_KILL",
                f"Kill switch active: {self._reason}",
            )
        return SafetyResult(SafetyVerdict.PASS, "L5_KILL")


# ---------------------------------------------------------------------------
# Composite SafetySystem
# ---------------------------------------------------------------------------


@dataclass
class SafetyConfig:
    """Tuneable parameters for the safety system."""

    price_deviation_pct: float = 5.0
    qty_limits: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_QTY_LIMITS))
    max_positions: int = 5
    max_margin_pct: float = 60.0
    max_net_delta: float = 500.0
    max_net_vega: float = 10_000.0
    pnl_pause_pct: float = 3.0
    pnl_kill_pct: float = 15.0
    check_market_hours: bool = True


class SafetySystem:
    """Composite of all 5 safety layers, run in order.

    Usage::

        safety = SafetySystem()
        results = safety.check_order(order, context)
        if not all(r.passed for r in results):
            blocked_by = [r for r in results if not r.passed]
            ...
    """

    def __init__(self, config: SafetyConfig | None = None) -> None:
        cfg = config or SafetyConfig()
        self.l1_order = OrderValidation(cfg.price_deviation_pct, cfg.qty_limits, cfg.check_market_hours)
        self.l2_position = PositionLimits(cfg.max_positions, cfg.max_margin_pct)
        self.l3_portfolio = PortfolioRisk(cfg.max_net_delta, cfg.max_net_vega)
        self.l4_pnl = DailyPnLLimits(cfg.pnl_pause_pct, cfg.pnl_kill_pct)
        self.l5_kill = KillSwitch()

    def check_order(
        self,
        order: Order,
        *,
        ltp: float | None = None,
        positions: list[Position] | None = None,
        used_margin: float = 0.0,
        total_balance: float = 0.0,
        net_delta: float = 0.0,
        net_vega: float = 0.0,
        daily_pnl: float = 0.0,
        starting_capital: float = 0.0,
        at: datetime | None = None,
    ) -> list[SafetyResult]:
        """Run order through all 5 layers and return results.

        Stops at the first failing layer (fail-fast).
        """
        results: list[SafetyResult] = []

        # L5 first — if kill switch is on, nothing passes
        r5 = self.l5_kill.validate()
        results.append(r5)
        if not r5.passed:
            return results

        # L4 — daily P&L
        r4 = self.l4_pnl.validate(daily_pnl, starting_capital)
        results.append(r4)
        if not r4.passed:
            return results

        # L1 — order validation (exchange, market hours, symbol, qty, price)
        r1 = self.l1_order.validate(order, ltp, at=at)
        results.append(r1)
        if not r1.passed:
            return results

        # L2 — position limits
        r2 = self.l2_position.validate(
            positions or [], used_margin, total_balance,
        )
        results.append(r2)
        if not r2.passed:
            return results

        # L3 — portfolio greeks
        r3 = self.l3_portfolio.validate(net_delta, net_vega)
        results.append(r3)

        return results
