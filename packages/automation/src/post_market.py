"""Automated post-market analysis — runs at 3:45 PM IST.

Collects today's trades and P&L, generates a daily report, compares strategy
performance, stores in DuckDB, and sends a Telegram summary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("flinttrade.automation.post_market")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class TradeEntry:
    """A single trade for the daily report."""

    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl: float = 0.0
    strategy: str = ""


@dataclass
class StrategyPerformance:
    """Performance of a single strategy for the day."""

    strategy: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_pnl: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100


@dataclass
class DailyReport:
    """Complete post-market daily report."""

    report_date: str = ""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    fees: float = 0.0
    best_trade: TradeEntry | None = None
    worst_trade: TradeEntry | None = None
    strategy_breakdown: list[StrategyPerformance] = field(default_factory=list)
    trades: list[TradeEntry] = field(default_factory=list)
    llm_analysis: str = ""

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "gross_pnl": self.gross_pnl,
            "net_pnl": self.net_pnl,
            "fees": self.fees,
            "win_rate": self.win_rate,
            "best_trade_pnl": self.best_trade.pnl if self.best_trade else 0,
            "worst_trade_pnl": self.worst_trade.pnl if self.worst_trade else 0,
            "strategy_count": len(self.strategy_breakdown),
        }


def build_report(trades: list[TradeEntry], report_date: str = "") -> DailyReport:
    """Build a DailyReport from a list of trades."""
    d = report_date or datetime.now(IST).strftime("%Y-%m-%d")
    report = DailyReport(report_date=d, trades=trades)

    if not trades:
        return report

    report.total_trades = len(trades)
    report.winning_trades = sum(1 for t in trades if t.pnl > 0)
    report.losing_trades = sum(1 for t in trades if t.pnl <= 0)
    report.gross_pnl = sum(t.pnl for t in trades)
    report.net_pnl = report.gross_pnl - report.fees

    # Best/worst trades
    report.best_trade = max(trades, key=lambda t: t.pnl)
    report.worst_trade = min(trades, key=lambda t: t.pnl)

    # Strategy breakdown
    by_strategy: dict[str, list[TradeEntry]] = {}
    for t in trades:
        by_strategy.setdefault(t.strategy or "default", []).append(t)

    for strat_name, strat_trades in by_strategy.items():
        perf = StrategyPerformance(
            strategy=strat_name,
            total_trades=len(strat_trades),
            winning_trades=sum(1 for t in strat_trades if t.pnl > 0),
            losing_trades=sum(1 for t in strat_trades if t.pnl <= 0),
            gross_pnl=sum(t.pnl for t in strat_trades),
            net_pnl=sum(t.pnl for t in strat_trades),
        )
        report.strategy_breakdown.append(perf)

    report.strategy_breakdown.sort(key=lambda s: s.net_pnl, reverse=True)
    return report


def format_report_telegram(report: DailyReport) -> str:
    """Format a daily report for Telegram."""
    emoji = "🟢" if report.net_pnl >= 0 else "🔴"
    lines = [
        f"*Daily Report — {report.report_date}* {emoji}",
        "",
        f"Total Trades: {report.total_trades}",
        f"Win Rate: {report.win_rate:.0f}%  ({report.winning_trades}W / {report.losing_trades}L)",
        f"Gross P&L: {report.gross_pnl:+,.0f}",
        f"Net P&L: {report.net_pnl:+,.0f}",
    ]

    if report.best_trade:
        lines.append(f"Best: {report.best_trade.symbol} {report.best_trade.pnl:+,.0f}")
    if report.worst_trade:
        lines.append(f"Worst: {report.worst_trade.symbol} {report.worst_trade.pnl:+,.0f}")

    if report.strategy_breakdown:
        lines.append("")
        lines.append("*Strategy Breakdown:*")
        for s in report.strategy_breakdown:
            se = "🟢" if s.net_pnl >= 0 else "🔴"
            lines.append(f"  {se} {s.strategy}: {s.net_pnl:+,.0f} ({s.total_trades} trades, {s.win_rate:.0f}% win)")

    if report.llm_analysis:
        lines.append("")
        lines.append("*AI Analysis:*")
        lines.append(report.llm_analysis)

    return "\n".join(lines)


class PostMarketAnalysis:
    """Automated post-market analysis engine.

    Usage::

        pma = PostMarketAnalysis(telegram_bot=bot, llm_client=llm)
        report = pma.run(trades)
        # Report is stored, Telegram summary sent, optional LLM analysis
    """

    def __init__(
        self,
        telegram_bot: Any | None = None,
        llm_client: Any | None = None,
        duckdb_path: str | None = None,
    ) -> None:
        self._telegram = telegram_bot
        self._llm = llm_client
        self._duckdb_path = duckdb_path
        self._reports: list[DailyReport] = []

    @property
    def reports(self) -> list[DailyReport]:
        return list(self._reports)

    def run(
        self,
        trades: list[TradeEntry],
        report_date: str = "",
        include_llm: bool = True,
    ) -> DailyReport:
        """Run complete post-market analysis.

        1. Build report from trades
        2. Optionally generate LLM analysis
        3. Store in DuckDB
        4. Send Telegram summary
        """
        report = build_report(trades, report_date)

        # LLM analysis
        if include_llm and self._llm and report.total_trades > 0:
            report.llm_analysis = self._generate_llm_analysis(report)

        # Store
        self._store_report(report)
        self._reports.append(report)

        # Send Telegram
        if self._telegram and report.total_trades > 0:
            msg = format_report_telegram(report)
            try:
                if hasattr(self._telegram, "send_message"):
                    self._telegram.send_message(msg)
            except Exception as exc:
                logger.error("Telegram report send failed: %s", exc)

        logger.info(
            "Post-market report for %s: %d trades, P&L=%+.0f",
            report.report_date, report.total_trades, report.net_pnl,
        )
        return report

    def _generate_llm_analysis(self, report: DailyReport) -> str:
        """Use LLM to analyse today's trading performance."""
        try:
            from packages.ai.src.llm_client import LLMMessage

            prompt = (
                f"Analyse this trading day. Date: {report.report_date}. "
                f"Total trades: {report.total_trades}. Win rate: {report.win_rate:.0f}%. "
                f"Net P&L: {report.net_pnl:+,.0f}. "
            )
            if report.best_trade:
                prompt += f"Best trade: {report.best_trade.symbol} ({report.best_trade.pnl:+,.0f}). "
            if report.worst_trade:
                prompt += f"Worst trade: {report.worst_trade.symbol} ({report.worst_trade.pnl:+,.0f}). "

            if report.strategy_breakdown:
                strats = ", ".join(
                    f"{s.strategy}={s.net_pnl:+,.0f}" for s in report.strategy_breakdown
                )
                prompt += f"Strategies: {strats}. "

            prompt += "Be brief (3 sentences): what went right, what went wrong, suggestion for tomorrow."

            response = self._llm.chat([
                LLMMessage(role="system", content="You are a trading performance analyst. Be concise."),
                LLMMessage(role="user", content=prompt),
            ], temperature=0.3, max_tokens=300)

            if response.success:
                return response.content
        except Exception as exc:
            logger.warning("LLM analysis failed: %s", exc)

        return ""

    def _store_report(self, report: DailyReport) -> None:
        """Store report in DuckDB (if configured)."""
        if not self._duckdb_path:
            return

        try:
            import duckdb
            conn = duckdb.connect(self._duckdb_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_reports (
                    report_date DATE,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    losing_trades INTEGER,
                    gross_pnl DOUBLE,
                    net_pnl DOUBLE,
                    fees DOUBLE,
                    win_rate DOUBLE,
                    best_trade_pnl DOUBLE,
                    worst_trade_pnl DOUBLE,
                    strategy_count INTEGER,
                    llm_analysis VARCHAR
                )
            """)
            conn.execute(
                "DELETE FROM daily_reports WHERE report_date = ?",
                [report.report_date],
            )
            conn.execute(
                """INSERT INTO daily_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    report.report_date, report.total_trades,
                    report.winning_trades, report.losing_trades,
                    report.gross_pnl, report.net_pnl, report.fees,
                    report.win_rate,
                    report.best_trade.pnl if report.best_trade else 0,
                    report.worst_trade.pnl if report.worst_trade else 0,
                    len(report.strategy_breakdown),
                    report.llm_analysis,
                ],
            )
            conn.close()
            logger.info("Report stored in DuckDB for %s", report.report_date)
        except Exception as exc:
            logger.error("Failed to store report in DuckDB: %s", exc)
