"""Forward trade log — persists trades executed by forward-test strategies.

Each strategy gets its own JSON-lines file under a configurable directory.
Simple, append-only, easy to inspect and debug.

Usage::

    log = ForwardTradeLog(log_dir=Path("~/.flinttrade/forward_trades"))
    log.log_trade("abc-123", {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "price": 2500.0,
        "order_id": "ORD-456",
    })
    trades = log.get_trades("abc-123")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.engine.forward_trade_log")

IST = timezone(timedelta(hours=5, minutes=30))


class ForwardTradeLog:
    """Append-only JSON-lines trade log, one file per strategy.

    Args:
        log_dir: Directory where ``<strategy_id>.jsonl`` files are stored.
            Created automatically if it does not exist.
    """

    def __init__(self, log_dir: Path | str) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _strategy_path(self, strategy_id: str) -> Path:
        """Return the JSONL file path for a given strategy."""
        # Sanitise strategy_id to prevent path traversal
        safe_id = strategy_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._log_dir / f"{safe_id}.jsonl"

    def log_trade(self, strategy_id: str, trade_data: dict[str, Any]) -> dict[str, Any]:
        """Append a trade record for a strategy.

        Adds a timestamp if one is not already present. Returns the full
        record that was written (including the generated timestamp).

        Args:
            strategy_id: UUID of the strategy that placed the order.
            trade_data: Trade fields — symbol, exchange, action, quantity,
                price, order_id, status, etc.

        Returns:
            The complete trade record as written to disc.
        """
        record: dict[str, Any] = {
            "strategy_id": strategy_id,
            "timestamp": trade_data.get(
                "timestamp",
                datetime.now(IST).isoformat(),
            ),
        }
        # Merge caller-supplied fields (excluding strategy_id/timestamp
        # which we already set above)
        for key, value in trade_data.items():
            if key not in ("strategy_id", "timestamp"):
                record[key] = value

        path = self._strategy_path(strategy_id)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

        logger.info(
            "Forward trade logged: strategy=%s symbol=%s action=%s qty=%s",
            strategy_id,
            record.get("symbol", "?"),
            record.get("action", "?"),
            record.get("quantity", "?"),
        )
        return record

    def get_trades(self, strategy_id: str) -> list[dict[str, Any]]:
        """Return all trades for a strategy, oldest first.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            List of trade dicts. Empty list if no trades exist.
        """
        path = self._strategy_path(strategy_id)
        if not path.exists():
            return []

        trades: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "Corrupt line %d in %s — skipping", line_no, path,
                    )
        return trades

    def clear_trades(self, strategy_id: str) -> int:
        """Delete all forward trades for a strategy.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Number of trades that were deleted.
        """
        path = self._strategy_path(strategy_id)
        if not path.exists():
            return 0

        count = sum(1 for line in open(path, encoding="utf-8") if line.strip())
        path.unlink()
        logger.info("Cleared %d forward trades for strategy %s", count, strategy_id)
        return count

    def trade_count(self, strategy_id: str) -> int:
        """Return the number of trades logged for a strategy.

        Args:
            strategy_id: UUID of the strategy.

        Returns:
            Trade count (0 if no file exists).
        """
        path = self._strategy_path(strategy_id)
        if not path.exists():
            return 0
        return sum(1 for line in open(path, encoding="utf-8") if line.strip())
