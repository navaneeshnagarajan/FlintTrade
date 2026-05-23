"""Trade logger — records executed trades with P&L, slippage, daily summaries.

Stores in DuckDB via StorageManager for fast analytical queries.
Exports to CSV for external tools / regulatory reporting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from flinttrade_data.storage import StorageManager

logger = logging.getLogger("flinttrade.journal.trade_logger")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class TradeSummary:
    """Daily trade summary for a single strategy."""

    trade_date: date
    strategy: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_pnl: float = 0.0
    fees: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def avg_pnl_per_trade(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.net_pnl / self.total_trades


class TradeLogger:
    """Logs executed trades and computes daily summaries.

    Usage::

        trade_logger = TradeLogger(storage)
        trade_logger.log_trade(
            orderid="123", symbol="RELIANCE", exchange="NSE",
            action="BUY", quantity=10, price=2500.0,
            strategy="Flint",
        )
        # After a round-trip, log the exit with P&L:
        trade_logger.log_trade(
            orderid="456", symbol="RELIANCE", exchange="NSE",
            action="SELL", quantity=10, price=2520.0,
            strategy="Flint", entry_price=2500.0, exit_price=2520.0,
        )
        summary = trade_logger.compute_daily_summary("2026-03-16", "Flint")
    """

    def __init__(self, storage: StorageManager) -> None:
        self._storage = storage

    def log_trade(
        self,
        *,
        orderid: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        product: str = "",
        strategy: str = "",
        entry_price: float | None = None,
        exit_price: float | None = None,
        expected_price: float | None = None,
        fees: float | None = None,
    ) -> None:
        """Record a single executed trade.

        If entry_price and exit_price are provided, P&L is computed automatically.
        Slippage = |actual_fill - expected_price| if expected_price given.
        """
        pnl = None
        if entry_price is not None and exit_price is not None:
            pnl = self.calculate_pnl(
                action=action,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
            )

        slippage = None
        if expected_price is not None and price > 0:
            slippage = abs(price - expected_price)

        ts = datetime.now(IST)

        self._storage.insert_trade(
            ts=ts,
            orderid=orderid,
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price=price,
            product=product,
            strategy=strategy,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            slippage=slippage,
            fees=fees,
        )
        logger.info(
            "Trade logged: %s %s %s qty=%d @ %.2f pnl=%s",
            action, symbol, exchange, quantity, price,
            f"{pnl:.2f}" if pnl is not None else "N/A",
        )

    @staticmethod
    def calculate_pnl(
        action: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
    ) -> float:
        """Calculate P&L for a closed trade.

        For a BUY entry: pnl = (exit - entry) * qty
        For a SELL entry (short): pnl = (entry - exit) * qty
        """
        if action.upper() == "BUY":
            return (exit_price - entry_price) * quantity
        else:
            return (entry_price - exit_price) * quantity

    def compute_daily_summary(
        self, trade_date: str, strategy: str,
    ) -> TradeSummary:
        """Compute and persist a daily trade summary for a given strategy.

        Args:
            trade_date: YYYY-MM-DD
            strategy: strategy name
        """
        trades = self._storage.get_trades_by_strategy(strategy, trade_date, trade_date)

        total = len(trades)
        winning = 0
        losing = 0
        gross_pnl = 0.0
        total_fees = 0.0

        # Track running P&L for drawdown calculation
        running_pnl = 0.0
        peak_pnl = 0.0
        max_dd = 0.0

        for t in trades:
            pnl = t.get("pnl")
            if pnl is not None:
                if pnl > 0:
                    winning += 1
                elif pnl < 0:
                    losing += 1
                gross_pnl += pnl

                running_pnl += pnl
                if running_pnl > peak_pnl:
                    peak_pnl = running_pnl
                dd = peak_pnl - running_pnl
                if dd > max_dd:
                    max_dd = dd

            fees = t.get("fees")
            if fees is not None:
                total_fees += fees

        net_pnl = gross_pnl - total_fees
        d = date.fromisoformat(trade_date)

        summary = TradeSummary(
            trade_date=d,
            strategy=strategy,
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            gross_pnl=gross_pnl,
            fees=total_fees,
            net_pnl=net_pnl,
            max_drawdown=max_dd,
        )

        # Persist to DuckDB
        self._storage.upsert_daily_summary(
            trade_date=d,
            strategy=strategy,
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            gross_pnl=gross_pnl,
            fees=total_fees,
            net_pnl=net_pnl,
            max_drawdown=max_dd,
        )
        logger.info(
            "Daily summary for %s/%s: %d trades, net P&L=%.2f, win_rate=%.1f%%",
            trade_date, strategy, total, net_pnl, summary.win_rate,
        )
        return summary

    def export_csv(
        self,
        start_date: str,
        end_date: str,
        strategy: str | None = None,
    ) -> str:
        """Export trades to CSV string. Delegates to StorageManager."""
        return self._storage.export_trades_csv(start_date, end_date, strategy)

    def get_trades(
        self,
        start_date: str,
        end_date: str,
        strategy: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get trades for a date range, optionally filtered by strategy."""
        if strategy:
            return self._storage.get_trades_by_strategy(strategy, start_date, end_date)
        return self._storage.get_trades_by_date(start_date)
