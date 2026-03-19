"""Per-account and aggregate risk monitoring.

Absorbs AlgoMirror's risk_manager.py patterns. Tracks daily P&L, position
counts, margin utilization, and trade quality per account. Auto-pauses
accounts when risk thresholds are breached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from enum import Enum, StrEnum


logger = logging.getLogger("flinttrade.ditto.risk")

IST = timezone(timedelta(hours=5, minutes=30))


class RiskStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    PAUSED = "PAUSED"


class TradeGrade(StrEnum):
    A = "A"  # Excellent: good entry, minimal slippage, disciplined exit
    B = "B"  # Good: decent entry, some slippage
    C = "C"  # Mediocre: late entry or early exit
    D = "D"  # Poor: chased entry, large slippage, no stop loss


@dataclass
class RiskConfig:
    """Risk limits for a single account."""

    max_loss_daily: float = 50_000.0
    max_loss_combined: float = 200_000.0  # Across all accounts
    max_positions: int = 10
    margin_warn_pct: float = 70.0   # Warn when utilization exceeds this
    margin_block_pct: float = 90.0  # Block new orders above this
    max_single_trade_loss: float = 25_000.0


@dataclass
class AccountRiskState:
    """Current risk state for a single account."""

    account_id: str
    status: str = "OK"
    daily_pnl: float = 0.0
    position_count: int = 0
    margin_utilization_pct: float = 0.0
    trade_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    alerts: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.trade_count == 0:
            return 0.0
        return (self.winning_trades / self.trade_count) * 100


@dataclass
class TradeQuality:
    """Quality grading for a single trade."""

    symbol: str
    grade: str = "B"
    slippage_pct: float = 0.0
    entry_timing_score: float = 0.5  # 0=worst, 1=best
    exit_discipline: float = 0.5
    pnl: float = 0.0
    reasoning: str = ""


@dataclass
class RiskCheckResult:
    """Result of a risk check before placing an order."""

    allowed: bool = True
    account_id: str = ""
    reason: str = ""
    risk_status: str = "OK"


def grade_trade(
    entry_price: float,
    exit_price: float,
    expected_entry: float,
    expected_exit: float,
    had_stop_loss: bool,
    side: str = "BUY",
) -> TradeQuality:
    """Grade a completed trade on quality metrics.

    A: slippage < 0.1%, good timing, disciplined exit with SL
    B: slippage < 0.3%, decent timing
    C: slippage < 0.5%, late entry or early exit
    D: slippage > 0.5%, no SL, undisciplined
    """
    # Slippage
    entry_slip = abs(entry_price - expected_entry) / expected_entry * 100 if expected_entry > 0 else 0
    exit_slip = abs(exit_price - expected_exit) / expected_exit * 100 if expected_exit > 0 else 0
    avg_slip = (entry_slip + exit_slip) / 2

    # P&L
    if side.upper() == "BUY":
        pnl = exit_price - entry_price
    else:
        pnl = entry_price - exit_price

    # Timing score (simplified: based on slippage)
    timing = max(0, 1.0 - entry_slip / 1.0)
    exit_disc = 1.0 if had_stop_loss else 0.3

    # Grade
    if avg_slip < 0.1 and had_stop_loss and timing > 0.8:
        grade = TradeGrade.A.value
    elif avg_slip < 0.3 and timing > 0.5:
        grade = TradeGrade.B.value
    elif avg_slip < 0.5:
        grade = TradeGrade.C.value
    else:
        grade = TradeGrade.D.value

    return TradeQuality(
        symbol="",
        grade=grade,
        slippage_pct=avg_slip,
        entry_timing_score=timing,
        exit_discipline=exit_disc,
        pnl=pnl,
    )


class RiskManager:
    """Per-account and aggregate risk monitoring.

    Usage::

        risk = RiskManager()
        risk.set_config("acc1", RiskConfig(max_loss_daily=50000))
        risk.update_pnl("acc1", daily_pnl=-30000)
        check = risk.check_order("acc1", margin_required=100000)
        if not check.allowed:
            print(f"Blocked: {check.reason}")
    """

    def __init__(self, default_config: RiskConfig | None = None) -> None:
        self._default_config = default_config or RiskConfig()
        self._configs: dict[str, RiskConfig] = {}
        self._states: dict[str, AccountRiskState] = {}
        self._trade_grades: list[TradeQuality] = []

    def set_config(self, account_id: str, config: RiskConfig) -> None:
        self._configs[account_id] = config

    def get_config(self, account_id: str) -> RiskConfig:
        return self._configs.get(account_id, self._default_config)

    def get_state(self, account_id: str) -> AccountRiskState:
        if account_id not in self._states:
            self._states[account_id] = AccountRiskState(account_id=account_id)
        return self._states[account_id]

    @property
    def trade_grades(self) -> list[TradeQuality]:
        return list(self._trade_grades)

    # ------------------------------------------------------------------
    # State updates
    # ------------------------------------------------------------------

    def update_pnl(self, account_id: str, daily_pnl: float) -> None:
        """Update daily P&L for an account and check thresholds."""
        state = self.get_state(account_id)
        state.daily_pnl = daily_pnl
        self._evaluate_risk(account_id)

    def update_positions(self, account_id: str, position_count: int) -> None:
        state = self.get_state(account_id)
        state.position_count = position_count
        self._evaluate_risk(account_id)

    def update_margin(self, account_id: str, utilization_pct: float) -> None:
        state = self.get_state(account_id)
        state.margin_utilization_pct = utilization_pct
        self._evaluate_risk(account_id)

    def record_trade(
        self, account_id: str, pnl: float, quality: TradeQuality | None = None,
    ) -> None:
        """Record a completed trade."""
        state = self.get_state(account_id)
        state.trade_count += 1
        if pnl > 0:
            state.winning_trades += 1
        else:
            state.losing_trades += 1
        if quality:
            quality.pnl = pnl
            self._trade_grades.append(quality)

    # ------------------------------------------------------------------
    # Risk evaluation
    # ------------------------------------------------------------------

    def _evaluate_risk(self, account_id: str) -> None:
        """Evaluate risk status and generate alerts."""
        state = self.get_state(account_id)
        config = self.get_config(account_id)
        state.alerts.clear()

        # P&L check
        if state.daily_pnl <= -config.max_loss_daily:
            state.status = RiskStatus.PAUSED.value
            state.alerts.append(
                f"PAUSED: Daily loss {state.daily_pnl:+,.0f} exceeds limit {-config.max_loss_daily:,.0f}"
            )
            logger.critical("Account %s PAUSED: daily loss exceeded", account_id)
            return

        # Margin check
        if state.margin_utilization_pct >= config.margin_block_pct:
            state.status = RiskStatus.CRITICAL.value
            state.alerts.append(
                f"CRITICAL: Margin utilization {state.margin_utilization_pct:.0f}% >= {config.margin_block_pct}%"
            )
        elif state.margin_utilization_pct >= config.margin_warn_pct:
            state.status = RiskStatus.WARNING.value
            state.alerts.append(
                f"WARNING: Margin utilization {state.margin_utilization_pct:.0f}% >= {config.margin_warn_pct}%"
            )

        # Position count
        if state.position_count >= config.max_positions:
            state.status = max(state.status, RiskStatus.WARNING.value)
            state.alerts.append(
                f"WARNING: Position count {state.position_count} >= limit {config.max_positions}"
            )

        if not state.alerts:
            state.status = RiskStatus.OK.value

    # ------------------------------------------------------------------
    # Pre-order check
    # ------------------------------------------------------------------

    def check_order(
        self,
        account_id: str,
        margin_required: float = 0.0,
        trade_loss_potential: float = 0.0,
    ) -> RiskCheckResult:
        """Check if an order should be allowed for this account."""
        state = self.get_state(account_id)
        config = self.get_config(account_id)

        # Account paused
        if state.status == RiskStatus.PAUSED.value:
            return RiskCheckResult(
                allowed=False,
                account_id=account_id,
                reason="Account is PAUSED due to daily loss limit",
                risk_status=state.status,
            )

        # Margin block
        if state.margin_utilization_pct >= config.margin_block_pct:
            return RiskCheckResult(
                allowed=False,
                account_id=account_id,
                reason=f"Margin utilization {state.margin_utilization_pct:.0f}% exceeds block threshold {config.margin_block_pct}%",
                risk_status=RiskStatus.CRITICAL.value,
            )

        # Position limit
        if state.position_count >= config.max_positions:
            return RiskCheckResult(
                allowed=False,
                account_id=account_id,
                reason=f"Position count {state.position_count} at limit {config.max_positions}",
                risk_status=RiskStatus.WARNING.value,
            )

        # Single trade loss potential
        if trade_loss_potential > config.max_single_trade_loss:
            return RiskCheckResult(
                allowed=False,
                account_id=account_id,
                reason=f"Potential loss {trade_loss_potential:,.0f} exceeds single-trade limit {config.max_single_trade_loss:,.0f}",
                risk_status=RiskStatus.WARNING.value,
            )

        return RiskCheckResult(
            allowed=True,
            account_id=account_id,
            risk_status=state.status,
        )

    # ------------------------------------------------------------------
    # Aggregate risk
    # ------------------------------------------------------------------

    def combined_daily_pnl(self) -> float:
        """Sum of daily P&L across all accounts."""
        return sum(s.daily_pnl for s in self._states.values())

    def check_combined_loss(self, max_combined: float | None = None) -> bool:
        """Check if combined loss across all accounts exceeds limit.

        Returns True if within limits.
        """
        limit = max_combined or self._default_config.max_loss_combined
        return self.combined_daily_pnl() > -limit

    def pause_account(self, account_id: str) -> None:
        """Manually pause an account."""
        state = self.get_state(account_id)
        state.status = RiskStatus.PAUSED.value
        state.alerts.append("Manually paused")
        logger.warning("Account %s manually paused", account_id)

    def resume_account(self, account_id: str) -> None:
        """Resume a paused account."""
        state = self.get_state(account_id)
        state.status = RiskStatus.OK.value
        state.alerts = [a for a in state.alerts if "PAUSED" not in a and "paused" not in a]
        logger.info("Account %s resumed", account_id)

    def reset_daily(self) -> None:
        """Reset daily counters (run at start of day)."""
        for state in self._states.values():
            state.daily_pnl = 0.0
            state.trade_count = 0
            state.winning_trades = 0
            state.losing_trades = 0
            state.alerts.clear()
            if state.status == RiskStatus.PAUSED.value:
                state.status = RiskStatus.OK.value
        logger.info("Daily risk counters reset for %d accounts", len(self._states))
