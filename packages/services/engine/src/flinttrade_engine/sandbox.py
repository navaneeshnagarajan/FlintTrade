"""Sandbox: virtual paper trading engine.

Per-account paper trading with configurable capital, leverage, and
auto square-off. Uses DuckDB for storage (consistent with analytics stack).

One SandboxEngine instance per account. Each account's data lives in a
separate DuckDB file at ``~/.flinttrade/sandbox/{account_id}.duckdb``.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.engine.sandbox")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# DuckDB import — soft-fail so the module is importable without duckdb
# ---------------------------------------------------------------------------

try:
    import duckdb  # type: ignore[import]

    _DUCKDB_AVAILABLE = True
except ImportError:  # pragma: no cover
    _DUCKDB_AVAILABLE = False
    duckdb = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class SandboxConfig:
    """Configuration for a virtual paper-trading account.

    Attributes:
        starting_capital: Virtual starting balance in rupees.
        equity_leverage: Leverage multiplier for equity positions (1 = no leverage).
        futures_leverage: Leverage multiplier for futures positions.
        option_buy_leverage: Leverage multiplier for option buy positions.
        option_sell_leverage: Leverage multiplier for option sell / write positions.
        squareoff_time: Auto square-off time (IST, HH:MM) for equity/F&O/CDS.
        mcx_squareoff_time: Auto square-off time (IST, HH:MM) for MCX.
    """

    starting_capital: float = 1_000_000.0
    equity_leverage: int = 1
    futures_leverage: int = 1
    option_buy_leverage: int = 1
    option_sell_leverage: int = 1
    squareoff_time: str = "15:15"
    mcx_squareoff_time: str = "23:25"


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS sandbox_orders (
    order_id      VARCHAR PRIMARY KEY,
    account_id    VARCHAR NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    action        VARCHAR NOT NULL,   -- BUY / SELL
    quantity      INTEGER NOT NULL,
    price         DOUBLE NOT NULL,    -- limit price (0 for MARKET)
    trigger_price DOUBLE NOT NULL DEFAULT 0.0,
    pricetype     VARCHAR NOT NULL,   -- MARKET / LIMIT / SL / SL-M
    product       VARCHAR NOT NULL,   -- MIS / NRML / CNC
    strategy      VARCHAR NOT NULL DEFAULT '',
    status        VARCHAR NOT NULL,   -- PENDING / COMPLETE / CANCELLED / REJECTED
    fill_price    DOUBLE,
    fill_time     TIMESTAMP,
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_trades (
    trade_id      VARCHAR PRIMARY KEY,
    order_id      VARCHAR NOT NULL,
    account_id    VARCHAR NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    action        VARCHAR NOT NULL,
    quantity      INTEGER NOT NULL,
    price         DOUBLE NOT NULL,
    product       VARCHAR NOT NULL,
    strategy      VARCHAR NOT NULL DEFAULT '',
    traded_at     TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_positions (
    position_id   VARCHAR PRIMARY KEY,
    account_id    VARCHAR NOT NULL,
    symbol        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    product       VARCHAR NOT NULL,
    net_qty       INTEGER NOT NULL DEFAULT 0,
    avg_price     DOUBLE NOT NULL DEFAULT 0.0,
    buy_qty       INTEGER NOT NULL DEFAULT 0,
    buy_value     DOUBLE NOT NULL DEFAULT 0.0,
    sell_qty      INTEGER NOT NULL DEFAULT 0,
    sell_value    DOUBLE NOT NULL DEFAULT 0.0,
    unrealized_pnl DOUBLE NOT NULL DEFAULT 0.0,
    realized_pnl  DOUBLE NOT NULL DEFAULT 0.0,
    updated_at    TIMESTAMP NOT NULL,
    UNIQUE (account_id, symbol, exchange, product)
);

CREATE TABLE IF NOT EXISTS sandbox_funds (
    account_id       VARCHAR PRIMARY KEY,
    starting_capital DOUBLE NOT NULL,
    used_margin      DOUBLE NOT NULL DEFAULT 0.0,
    realized_pnl     DOUBLE NOT NULL DEFAULT 0.0,
    updated_at       TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sandbox_daily_pnl (
    record_id     VARCHAR PRIMARY KEY,
    account_id    VARCHAR NOT NULL,
    date          DATE NOT NULL,
    realized_pnl  DOUBLE NOT NULL DEFAULT 0.0,
    unrealized_pnl DOUBLE NOT NULL DEFAULT 0.0,
    total_trades  INTEGER NOT NULL DEFAULT 0,
    recorded_at   TIMESTAMP NOT NULL,
    UNIQUE (account_id, date)
);
"""


_SANDBOX_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sb_orders_account ON sandbox_orders (account_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_sb_trades_account ON sandbox_trades (account_id, traded_at)",
    "CREATE INDEX IF NOT EXISTS idx_sb_positions_account ON sandbox_positions (account_id, symbol, exchange, product)",
    "CREATE INDEX IF NOT EXISTS idx_sb_daily_pnl_account ON sandbox_daily_pnl (account_id, date)",
]


def _default_db_path(account_id: str) -> str | Path:
    """Resolve engine sandbox storage without leaking tests into user state."""
    env = os.getenv("SANDBOX_ENGINE_DB_PATH")
    if env:
        return env if env == ":memory:" else Path(env).expanduser()

    try:
        from flinttrade_core.workspace import Workspace  # noqa: PLC0415

        sandbox_dir = Workspace().fast_data_dir / "engine-sandbox"
    except Exception:
        sandbox_dir = Path.home() / ".flinttrade" / "sandbox"

    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return sandbox_dir / f"{account_id}.duckdb"


# ---------------------------------------------------------------------------
# SandboxEngine
# ---------------------------------------------------------------------------


class SandboxEngine:
    """Virtual paper trading engine backed by DuckDB.

    Args:
        account_id: Unique identifier for this sandbox account.
        config: Trading configuration (capital, leverage, square-off times).
        db_path: Path to the DuckDB file. Defaults to the active FlintTrade
            workspace, then falls back to ``~/.flinttrade/sandbox``.
            Pass ``":memory:"`` for an in-memory database (useful in tests).
    """

    def __init__(
        self,
        account_id: str,
        config: SandboxConfig | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        if not _DUCKDB_AVAILABLE:  # pragma: no cover
            raise ImportError(
                "duckdb is required for SandboxEngine. "
                "Install it with: pip install duckdb"
            )

        self.account_id = account_id
        self.config = config or SandboxConfig()

        if db_path is None:
            db_path = _default_db_path(account_id)

        self._db_path = str(db_path)
        self._conn = duckdb.connect(self._db_path)
        self._init_db()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __enter__(self) -> SandboxEngine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _init_db(self) -> None:
        """Create DuckDB tables, indexes, and seed the funds row if missing."""
        self._conn.execute(_DDL)
        for idx in _SANDBOX_INDEXES:
            self._conn.execute(idx)
        # Ensure the funds row exists
        existing = self._conn.execute(
            "SELECT account_id FROM sandbox_funds WHERE account_id = ?",
            [self.account_id],
        ).fetchone()
        if not existing:
            now = datetime.now(timezone.utc)
            self._conn.execute(
                """INSERT INTO sandbox_funds
                   (account_id, starting_capital, used_margin, realized_pnl, updated_at)
                   VALUES (?, ?, 0.0, 0.0, ?)""",
                [self.account_id, self.config.starting_capital, now],
            )

    # ------------------------------------------------------------------
    # Order placement
    # ------------------------------------------------------------------

    def place_order(self, order_data: dict[str, Any]) -> dict[str, Any]:
        """Place a virtual order.

        For MARKET orders the order is filled immediately at the provided LTP
        (``order_data["price"]`` if non-zero, else a synthetic fill at 0.0 for
        tests).  LIMIT / SL / SL-M orders are queued with status PENDING and
        filled later via :meth:`check_pending_fills`.

        Args:
            order_data: Dict with keys: symbol, exchange, action, quantity,
                price, pricetype (MARKET/LIMIT/SL/SL-M), product (MIS/NRML/CNC),
                trigger_price (optional), strategy (optional).

        Returns:
            Dict with ``order_id``, ``status``, ``message``.
        """
        symbol = order_data.get("symbol", "")
        exchange = order_data.get("exchange", "NSE")
        action = str(order_data.get("action", "BUY")).upper()
        quantity = int(order_data.get("quantity", 0))
        price = float(order_data.get("price", 0.0))
        trigger_price = float(order_data.get("trigger_price", 0.0))
        pricetype = str(order_data.get("pricetype", "MARKET")).upper()
        product = str(order_data.get("product", "MIS")).upper()
        strategy = str(order_data.get("strategy", ""))

        # Basic validation
        if not symbol:
            return {"order_id": "", "status": "REJECTED", "message": "Symbol is required"}
        if quantity <= 0:
            return {"order_id": "", "status": "REJECTED", "message": "Quantity must be > 0"}
        if action not in ("BUY", "SELL"):
            return {"order_id": "", "status": "REJECTED", "message": f"Invalid action: {action}"}

        # Margin check: simplified — require available_balance >= quantity * price
        funds = self.get_funds()
        available = funds["available_balance"]
        required_margin = self._estimate_margin(quantity, price, pricetype, product)
        if required_margin > available:
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": f"Insufficient margin: required {required_margin:.2f}, available {available:.2f}",
            }

        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        if pricetype == "MARKET":
            fill_price = price if price > 0 else 0.0
            status = "COMPLETE"
            fill_time = now
        else:
            fill_price = None
            status = "PENDING"
            fill_time = None

        self._conn.execute(
            """INSERT INTO sandbox_orders
               (order_id, account_id, symbol, exchange, action, quantity, price,
                trigger_price, pricetype, product, strategy, status, fill_price,
                fill_time, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                order_id, self.account_id, symbol, exchange, action, quantity,
                price, trigger_price, pricetype, product, strategy, status,
                fill_price, fill_time, now, now,
            ],
        )

        if status == "COMPLETE":
            self._record_trade(
                order_id=order_id,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                fill_price=fill_price,
                product=product,
                strategy=strategy,
                traded_at=now,
            )

        logger.info(
            "Sandbox order %s: %s %d %s @ %s [%s]",
            order_id, action, quantity, symbol, fill_price or price, status,
        )
        return {"order_id": order_id, "status": status, "message": ""}

    # ------------------------------------------------------------------
    # Fill simulation
    # ------------------------------------------------------------------

    def check_pending_fills(self, latest_ticks: dict[str, float]) -> list[str]:
        """Check pending LIMIT/SL orders and fill those whose conditions are met.

        Args:
            latest_ticks: Dict mapping symbol → LTP (last traded price).

        Returns:
            List of order_ids that were filled.
        """
        pending = self._conn.execute(
            """SELECT order_id, symbol, exchange, action, quantity, price,
                      trigger_price, pricetype, product, strategy
               FROM sandbox_orders
               WHERE account_id = ? AND status = 'PENDING'""",
            [self.account_id],
        ).fetchall()

        filled: list[str] = []
        now = datetime.now(timezone.utc)

        for row in pending:
            (
                order_id, symbol, exchange, action, quantity, limit_price,
                trigger_price, pricetype, product, strategy,
            ) = row

            ltp = latest_ticks.get(symbol)
            if ltp is None:
                continue

            should_fill = False
            fill_price = ltp

            if pricetype == "LIMIT":
                if action == "BUY" and ltp <= limit_price:
                    should_fill = True
                    fill_price = limit_price
                elif action == "SELL" and ltp >= limit_price:
                    should_fill = True
                    fill_price = limit_price

            elif pricetype == "SL":
                # Stop-loss: trigger fires and then fills at limit_price
                if action == "BUY" and ltp >= trigger_price:
                    should_fill = True
                    fill_price = limit_price if limit_price > 0 else ltp
                elif action == "SELL" and ltp <= trigger_price:
                    should_fill = True
                    fill_price = limit_price if limit_price > 0 else ltp

            elif pricetype == "SL-M":
                # Stop-loss market: trigger fires, fill at market
                if action == "BUY" and ltp >= trigger_price:
                    should_fill = True
                    fill_price = ltp
                elif action == "SELL" and ltp <= trigger_price:
                    should_fill = True
                    fill_price = ltp

            if should_fill:
                self._conn.execute(
                    """UPDATE sandbox_orders
                       SET status = 'COMPLETE', fill_price = ?, fill_time = ?, updated_at = ?
                       WHERE order_id = ?""",
                    [fill_price, now, now, order_id],
                )
                self._record_trade(
                    order_id=order_id,
                    symbol=symbol,
                    exchange=exchange,
                    action=action,
                    quantity=quantity,
                    fill_price=fill_price,
                    product=product,
                    strategy=strategy,
                    traded_at=now,
                )
                filled.append(order_id)
                logger.info(
                    "Sandbox fill: order %s %s %d %s @ %.2f",
                    order_id, action, quantity, symbol, fill_price,
                )

        return filled

    # ------------------------------------------------------------------
    # Position book
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all open positions for this account.

        Returns:
            List of position dicts with keys: symbol, exchange, product,
            net_qty, avg_price, unrealized_pnl, realized_pnl, etc.
        """
        rows = self._conn.execute(
            """SELECT symbol, exchange, product, net_qty, avg_price,
                      buy_qty, buy_value, sell_qty, sell_value,
                      unrealized_pnl, realized_pnl, updated_at
               FROM sandbox_positions
               WHERE account_id = ? AND net_qty != 0""",
            [self.account_id],
        ).fetchall()

        positions = []
        for row in rows:
            (
                symbol, exchange, product, net_qty, avg_price,
                buy_qty, buy_value, sell_qty, sell_value,
                unrealized_pnl, realized_pnl, updated_at,
            ) = row
            positions.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "product": product,
                    "net_qty": net_qty,
                    "avg_price": avg_price,
                    "buy_qty": buy_qty,
                    "buy_value": buy_value,
                    "sell_qty": sell_qty,
                    "sell_value": sell_value,
                    "unrealized_pnl": unrealized_pnl,
                    "realized_pnl": realized_pnl,
                    "updated_at": str(updated_at),
                }
            )
        return positions

    # ------------------------------------------------------------------
    # Order book
    # ------------------------------------------------------------------

    def get_orders(self) -> list[dict[str, Any]]:
        """Return all orders (all statuses) for this account.

        Returns:
            List of order dicts ordered by created_at descending.
        """
        rows = self._conn.execute(
            """SELECT order_id, symbol, exchange, action, quantity, price,
                      trigger_price, pricetype, product, strategy, status,
                      fill_price, fill_time, created_at
               FROM sandbox_orders
               WHERE account_id = ?
               ORDER BY created_at DESC""",
            [self.account_id],
        ).fetchall()

        return [
            {
                "order_id": r[0],
                "symbol": r[1],
                "exchange": r[2],
                "action": r[3],
                "quantity": r[4],
                "price": r[5],
                "trigger_price": r[6],
                "pricetype": r[7],
                "product": r[8],
                "strategy": r[9],
                "status": r[10],
                "fill_price": r[11],
                "fill_time": str(r[12]) if r[12] else None,
                "created_at": str(r[13]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Trade book
    # ------------------------------------------------------------------

    def get_trades(self) -> list[dict[str, Any]]:
        """Return all executed trades for this account.

        Returns:
            List of trade dicts ordered by traded_at descending.
        """
        rows = self._conn.execute(
            """SELECT trade_id, order_id, symbol, exchange, action,
                      quantity, price, product, strategy, traded_at
               FROM sandbox_trades
               WHERE account_id = ?
               ORDER BY traded_at DESC""",
            [self.account_id],
        ).fetchall()

        return [
            {
                "trade_id": r[0],
                "order_id": r[1],
                "symbol": r[2],
                "exchange": r[3],
                "action": r[4],
                "quantity": r[5],
                "price": r[6],
                "product": r[7],
                "strategy": r[8],
                "traded_at": str(r[9]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Funds
    # ------------------------------------------------------------------

    def get_funds(self) -> dict[str, float]:
        """Return virtual fund balance.

        Returns:
            Dict with keys: starting_capital, used_margin, realized_pnl,
            available_balance, total_equity.
        """
        row = self._conn.execute(
            """SELECT starting_capital, used_margin, realized_pnl
               FROM sandbox_funds
               WHERE account_id = ?""",
            [self.account_id],
        ).fetchone()

        if not row:
            return {
                "starting_capital": self.config.starting_capital,
                "used_margin": 0.0,
                "realized_pnl": 0.0,
                "available_balance": self.config.starting_capital,
                "total_equity": self.config.starting_capital,
            }

        starting_capital, used_margin, realized_pnl = row
        available_balance = starting_capital - used_margin + realized_pnl
        total_equity = starting_capital + realized_pnl

        return {
            "starting_capital": starting_capital,
            "used_margin": used_margin,
            "realized_pnl": realized_pnl,
            "available_balance": available_balance,
            "total_equity": total_equity,
        }

    # ------------------------------------------------------------------
    # P&L history
    # ------------------------------------------------------------------

    def get_pnl_history(self) -> list[dict[str, Any]]:
        """Return daily settled P&L history.

        Returns:
            List of daily P&L records ordered by date descending.
        """
        rows = self._conn.execute(
            """SELECT date, realized_pnl, unrealized_pnl, total_trades, recorded_at
               FROM sandbox_daily_pnl
               WHERE account_id = ?
               ORDER BY date DESC""",
            [self.account_id],
        ).fetchall()

        return [
            {
                "date": str(r[0]),
                "realized_pnl": r[1],
                "unrealized_pnl": r[2],
                "total_trades": r[3],
                "recorded_at": str(r[4]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Square-off
    # ------------------------------------------------------------------

    def square_off_all(self) -> int:
        """Close all open positions at current mark-to-market.

        In a real implementation this would use the latest LTP; here we use
        the average price (zero P&L) so the engine works without a price feed.

        Returns:
            Number of positions closed.
        """
        positions = self._conn.execute(
            """SELECT position_id, symbol, exchange, product, net_qty, avg_price
               FROM sandbox_positions
               WHERE account_id = ? AND net_qty != 0""",
            [self.account_id],
        ).fetchall()

        now = datetime.now(timezone.utc)
        count = 0

        for pos_id, symbol, exchange, product, net_qty, avg_price in positions:
            # Place a closing order at avg_price (zero P&L square-off)
            action = "SELL" if net_qty > 0 else "BUY"
            qty = abs(net_qty)
            order_id = str(uuid.uuid4())

            self._conn.execute(
                """INSERT INTO sandbox_orders
                   (order_id, account_id, symbol, exchange, action, quantity, price,
                    trigger_price, pricetype, product, strategy, status, fill_price,
                    fill_time, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    order_id, self.account_id, symbol, exchange, action, qty,
                    avg_price, 0.0, "MARKET", product, "SQUAREOFF", "COMPLETE",
                    avg_price, now, now, now,
                ],
            )
            self._record_trade(
                order_id=order_id,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=qty,
                fill_price=avg_price,
                product=product,
                strategy="SQUAREOFF",
                traded_at=now,
            )
            count += 1

        if count:
            # Record daily P&L snapshot
            self._record_daily_pnl(now)
            logger.info("Sandbox square-off: closed %d positions for account %s", count, self.account_id)

        return count

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Delete all sandbox data and reset to starting capital."""
        tables = [
            "sandbox_orders",
            "sandbox_trades",
            "sandbox_positions",
            "sandbox_funds",
            "sandbox_daily_pnl",
        ]
        for table in tables:
            self._conn.execute(
                f"DELETE FROM {table} WHERE account_id = ?",  # noqa: S608
                [self.account_id],
            )
        # Re-seed funds
        now = datetime.now(timezone.utc)
        self._conn.execute(
            """INSERT INTO sandbox_funds
               (account_id, starting_capital, used_margin, realized_pnl, updated_at)
               VALUES (?, ?, 0.0, 0.0, ?)""",
            [self.account_id, self.config.starting_capital, now],
        )
        logger.info("Sandbox reset for account %s", self.account_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimate_margin(
        self,
        quantity: int,
        price: float,
        pricetype: str,
        product: str,
    ) -> float:
        """Estimate margin required for an order.

        Uses a simplified model:
        - CNC / NRML: full notional value / equity_leverage
        - MIS: notional / (equity_leverage * futures_leverage)
        - Zero margin for MARKET orders with zero price (tests)
        """
        if price <= 0 and pricetype == "MARKET":
            return 0.0
        notional = quantity * price
        if product == "CNC":
            return notional / max(self.config.equity_leverage, 1)
        if product == "NRML":
            return notional / max(self.config.futures_leverage, 1)
        # MIS — intraday
        intraday_leverage = self.config.equity_leverage * max(self.config.futures_leverage, 1)
        return notional / max(intraday_leverage, 1)

    def _record_trade(
        self,
        *,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        fill_price: float | None,
        product: str,
        strategy: str,
        traded_at: datetime,
    ) -> None:
        """Insert a trade record and update the position book."""
        trade_id = str(uuid.uuid4())
        actual_price = fill_price or 0.0

        self._conn.execute(
            """INSERT INTO sandbox_trades
               (trade_id, order_id, account_id, symbol, exchange, action,
                quantity, price, product, strategy, traded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [
                trade_id, order_id, self.account_id, symbol, exchange,
                action, quantity, actual_price, product, strategy, traded_at,
            ],
        )

        self._update_position(
            symbol=symbol,
            exchange=exchange,
            product=product,
            action=action,
            quantity=quantity,
            price=actual_price,
            updated_at=traded_at,
        )

    def _update_position(
        self,
        *,
        symbol: str,
        exchange: str,
        product: str,
        action: str,
        quantity: int,
        price: float,
        updated_at: datetime,
    ) -> None:
        """Upsert position row and update funds margin/realized P&L."""
        existing = self._conn.execute(
            """SELECT position_id, net_qty, avg_price, buy_qty, buy_value,
                      sell_qty, sell_value, realized_pnl
               FROM sandbox_positions
               WHERE account_id = ? AND symbol = ? AND exchange = ? AND product = ?""",
            [self.account_id, symbol, exchange, product],
        ).fetchone()

        notional = quantity * price

        if existing is None:
            pos_id = str(uuid.uuid4())
            net_qty = quantity if action == "BUY" else -quantity
            avg_price = price if price > 0 else 0.0
            buy_qty = quantity if action == "BUY" else 0
            buy_value = notional if action == "BUY" else 0.0
            sell_qty = quantity if action == "SELL" else 0
            sell_value = notional if action == "SELL" else 0.0

            self._conn.execute(
                """INSERT INTO sandbox_positions
                   (position_id, account_id, symbol, exchange, product,
                    net_qty, avg_price, buy_qty, buy_value, sell_qty, sell_value,
                    unrealized_pnl, realized_pnl, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,0.0,0.0,?)""",
                [
                    pos_id, self.account_id, symbol, exchange, product,
                    net_qty, avg_price, buy_qty, buy_value, sell_qty, sell_value,
                    updated_at,
                ],
            )
        else:
            (
                pos_id, net_qty, avg_price, buy_qty, buy_value,
                sell_qty, sell_value, realized_pnl,
            ) = existing

            if action == "BUY":
                new_buy_qty = buy_qty + quantity
                new_buy_value = buy_value + notional
                new_net_qty = net_qty + quantity
                # Update avg_price for long additions
                if new_net_qty != 0:
                    new_avg_price = new_buy_value / new_buy_qty if new_buy_qty > 0 else avg_price
                else:
                    new_avg_price = 0.0
                new_realized_pnl = realized_pnl
                new_sell_qty = sell_qty
                new_sell_value = sell_value
            else:  # SELL
                new_sell_qty = sell_qty + quantity
                new_sell_value = sell_value + notional
                new_net_qty = net_qty - quantity
                new_buy_qty = buy_qty
                new_buy_value = buy_value
                new_avg_price = avg_price
                # Realize P&L for closing a long position
                if net_qty > 0:
                    close_qty = min(quantity, net_qty)
                    realized_gain = close_qty * (price - avg_price)
                    new_realized_pnl = realized_pnl + realized_gain
                else:
                    new_realized_pnl = realized_pnl

            self._conn.execute(
                """UPDATE sandbox_positions
                   SET net_qty = ?, avg_price = ?, buy_qty = ?, buy_value = ?,
                       sell_qty = ?, sell_value = ?, realized_pnl = ?, updated_at = ?
                   WHERE position_id = ?""",
                [
                    new_net_qty, new_avg_price, new_buy_qty, new_buy_value,
                    new_sell_qty, new_sell_value, new_realized_pnl,
                    updated_at, pos_id,
                ],
            )

        # Update funds: recalculate used_margin and realized_pnl
        total_realized = self._conn.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0.0) FROM sandbox_positions WHERE account_id = ?",
            [self.account_id],
        ).fetchone()[0]

        # Simple margin: sum of abs(net_qty * avg_price) for open positions
        total_margin = self._conn.execute(
            """SELECT COALESCE(SUM(ABS(net_qty) * avg_price), 0.0)
               FROM sandbox_positions
               WHERE account_id = ? AND net_qty != 0""",
            [self.account_id],
        ).fetchone()[0]

        self._conn.execute(
            """UPDATE sandbox_funds
               SET used_margin = ?, realized_pnl = ?, updated_at = ?
               WHERE account_id = ?""",
            [total_margin, total_realized, updated_at, self.account_id],
        )

    def _record_daily_pnl(self, at: datetime) -> None:
        """Upsert today's daily P&L snapshot."""
        today = at.date()
        funds = self.get_funds()
        trade_count = self._conn.execute(
            "SELECT COUNT(*) FROM sandbox_trades WHERE account_id = ?",
            [self.account_id],
        ).fetchone()[0]

        existing = self._conn.execute(
            "SELECT record_id FROM sandbox_daily_pnl WHERE account_id = ? AND date = ?",
            [self.account_id, today],
        ).fetchone()

        if existing:
            self._conn.execute(
                """UPDATE sandbox_daily_pnl
                   SET realized_pnl = ?, total_trades = ?, recorded_at = ?
                   WHERE account_id = ? AND date = ?""",
                [funds["realized_pnl"], trade_count, at, self.account_id, today],
            )
        else:
            self._conn.execute(
                """INSERT INTO sandbox_daily_pnl
                   (record_id, account_id, date, realized_pnl, unrealized_pnl,
                    total_trades, recorded_at)
                   VALUES (?,?,?,?,0.0,?,?)""",
                [
                    str(uuid.uuid4()), self.account_id, today,
                    funds["realized_pnl"], trade_count, at,
                ],
            )

    def close(self) -> None:
        """Close the DuckDB connection."""
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass
