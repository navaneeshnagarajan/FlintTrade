"""Sandbox paper trading engine — virtual capital, paper orders, SQLite state.

Provides a simple, direct interface for the Sandbox execution mode.
Data is stored in the canonical data-layer ``state.sqlite`` schema
(``capital``, ``orders``, ``positions``, ``pnl``, and ``mtm`` tables),
completely separate from real trade data.

Usage::

    engine = SandboxEngine()
    engine.place_order("NIFTY", "NSE_INDEX", "BUY", 50, 24000.0)
    print(engine.get_capital())
    print(engine.get_positions())
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from flinttrade_core.db import open_sqlite

from .state_store import ensure_schema, init_capital

logger = logging.getLogger("flinttrade.data.sandbox_engine")

_DEFAULT_CAPITAL = 1_000_000.0  # ₹10,00,000

# ---------------------------------------------------------------------------
# Table name allowlist — prevents SQL injection via dynamic table names
# ---------------------------------------------------------------------------

_VALID_TABLES = frozenset({"capital", "orders", "positions", "pnl", "mtm"})


def _validate_table(table: str) -> str:
    """Return *table* unchanged if it is in the allowlist, else raise."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table

def _default_db_path() -> str:
    """Resolve sandbox SQLite path: env override > workspace > fallback."""

    env = os.getenv("SANDBOX_STATE_PATH") or os.getenv("SANDBOX_DB_PATH")
    if env:
        return env
    try:
        from flinttrade_core.workspace import Workspace  # noqa: PLC0415

        return str(Workspace().workspace_dir / "sandbox" / "state.sqlite")
    except Exception:
        return str(Path.home() / ".flinttrade" / "sandbox" / "state.sqlite")


def _format_ts(value: Any) -> str:
    """Return a stable ISO-ish string for API/export compatibility."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# SandboxEngine
# ---------------------------------------------------------------------------


class SandboxEngine:
    """Virtual paper trading engine backed by SQLite ``state.sqlite``.

    Tracks virtual capital, paper orders, and positions entirely in a
    separate SQLite WAL file so sandbox data never mingles with real trades.

    Args:
        db_path: Path to the SQLite state file. Defaults to
            ``<workspace>/sandbox/state.sqlite``.
            directory.  Pass ``":memory:"`` for in-memory use in tests.
        initial_capital: Starting virtual capital in rupees.
            Ignored if the database already contains a capital row.
    """

    def __init__(
        self,
        db_path: str | None = None,
        initial_capital: float = _DEFAULT_CAPITAL,
    ) -> None:
        self._db_path = db_path or _default_db_path()

        # Ensure parent directory exists for file-based databases
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = open_sqlite(self._db_path, durability="normal")
        self._initial_capital = initial_capital
        self._init_db()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __enter__(self) -> SandboxEngine:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _init_db(self) -> None:
        """Create tables, indexes, and seed the capital row if missing."""
        ensure_schema(self._conn)
        init_capital(self._conn, self._initial_capital)

    # ------------------------------------------------------------------
    # Capital
    # ------------------------------------------------------------------

    def get_capital(self) -> dict[str, float]:
        """Return the current capital state.

        Returns:
            Dict with keys:

            - ``initial`` — original capital amount
            - ``current`` — current total capital (initial + realised P&L adjustments)
            - ``available`` — capital available for new orders
            - ``used_margin`` — capital currently tied up in open positions
        """
        row = self._conn.execute(
            "SELECT initial, current, used_margin FROM capital WHERE id = 'default'"
        ).fetchone()

        if not row:  # Should never happen after _init_db, but guard anyway
            return {
                "initial": self._initial_capital,
                "current": self._initial_capital,
                "available": self._initial_capital,
                "used_margin": 0.0,
            }

        initial, current, used_margin = row
        available = current - used_margin

        return {
            "initial": initial,
            "current": current,
            "available": max(available, 0.0),
            "used_margin": used_margin,
        }

    def adjust_capital(self, amount: float) -> dict[str, float]:
        """Add or remove virtual capital.

        Args:
            amount: Positive to add, negative to remove.  Removal that
                would make current capital negative raises ``ValueError``.

        Returns:
            Updated capital dict (same structure as :meth:`get_capital`).

        Raises:
            ValueError: If the adjustment would make current capital negative.
        """
        cap = self.get_capital()
        new_current = cap["current"] + amount

        if new_current < 0:
            raise ValueError(
                f"Cannot remove {abs(amount):.2f} — current capital is only {cap['current']:.2f}"
            )

        now = time.time()
        self._conn.execute(
            """UPDATE capital
               SET current = ?, updated_at = ?
               WHERE id = 'default'""",
            (new_current, now),
        )
        logger.info("Sandbox capital adjusted by %.2f → %.2f", amount, new_current)
        return self.get_capital()

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        product: str = "MIS",
    ) -> dict[str, Any]:
        """Validate and execute a paper order immediately at the given price.

        For SELL orders the position must exist; the engine validates that
        ``quantity`` does not exceed the open net quantity.  For BUY orders
        the engine validates available capital.

        Args:
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            exchange: Exchange code (e.g. ``"NSE"``, ``"NFO"``).
            action: ``"BUY"`` or ``"SELL"`` (case-insensitive).
            quantity: Number of units / lots.
            price: Execution price per unit.
            product: Product type — ``"MIS"``, ``"NRML"``, or ``"CNC"``.

        Returns:
            Dict with keys:

            - ``order_id`` — UUID string
            - ``status`` — ``"COMPLETE"`` or ``"REJECTED"``
            - ``message`` — human-readable description
        """
        if not symbol:
            return {"order_id": "", "status": "REJECTED", "message": "Symbol is required"}
        if quantity <= 0:
            return {"order_id": "", "status": "REJECTED", "message": "Quantity must be > 0"}

        action = action.upper()
        if action not in ("BUY", "SELL"):
            return {"order_id": "", "status": "REJECTED", "message": f"Invalid action: {action}"}

        # A paper fill must use a real price. A zero/negative price fabricates a
        # position at 0.0 (and a 0-notional order that skips the capital check),
        # so reject it rather than book a fictitious fill — the caller must
        # supply the live LTP for a market order.
        if price <= 0:
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": "A market fill needs a live price; no LTP was available",
            }

        product = product.upper()
        notional = quantity * price

        # Validate capital for BUY
        if action == "BUY":
            cap = self.get_capital()
            if notional > cap["available"]:
                return {
                    "order_id": "",
                    "status": "REJECTED",
                    "message": (
                        f"Insufficient capital: need {notional:.2f}, "
                        f"available {cap['available']:.2f}"
                    ),
                }

        # Validate position for SELL
        if action == "SELL":
            pos = self._get_position(symbol, exchange, product)
            if pos is None or pos["net_qty"] < quantity:
                held = pos["net_qty"] if pos else 0
                return {
                    "order_id": "",
                    "status": "REJECTED",
                    "message": (
                        f"Insufficient position: need {quantity}, holding {held}"
                    ),
                }

        order_id = str(uuid.uuid4())
        now = time.time()

        self._conn.execute(
            """INSERT INTO orders
               (order_id, symbol, exchange, action, quantity, price, product,
                status, filled_qty, avg_fill_px, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'COMPLETE', ?, ?, ?, ?)""",
            (order_id, symbol, exchange, action, quantity, price, product, quantity, price, now, now),
        )

        self._update_position(
            symbol=symbol,
            exchange=exchange,
            product=product,
            action=action,
            quantity=quantity,
            price=price,
            now=now,
        )
        self._update_used_margin(now)

        logger.info(
            "Sandbox order %s: %s %d %s @ %.2f [COMPLETE]",
            order_id, action, quantity, symbol, price,
        )
        return {
            "order_id": order_id,
            "status": "COMPLETE",
            "message": f"Paper order executed: {action} {quantity} {symbol} @ {price:.2f}",
        }

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all open sandbox positions (net_qty != 0).

        Returns:
            List of position dicts with keys: symbol, exchange, product,
            net_qty, avg_price, realised_pnl, unrealised_pnl, updated_at.
        """
        rows = self._conn.execute(
            """SELECT symbol, exchange, product, net_qty, avg_price,
                      buy_qty, buy_value, sell_qty, sell_value,
                      realised_pnl, unrealised_pnl, updated_at
               FROM positions
               WHERE net_qty != 0
               ORDER BY updated_at DESC"""
        ).fetchall()

        return [
            {
                "symbol": r[0],
                "exchange": r[1],
                "product": r[2],
                "net_qty": r[3],
                "avg_price": r[4],
                "buy_qty": r[5],
                "buy_value": r[6],
                "sell_qty": r[7],
                "sell_value": r[8],
                "realised_pnl": r[9],
                "unrealised_pnl": r[10],
                "updated_at": _format_ts(r[11]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def get_orders(self) -> list[dict[str, Any]]:
        """Return all sandbox orders for today (IST date).

        Returns:
            List of order dicts ordered by created_at descending.
        """
        today = date.today().isoformat()
        rows = self._conn.execute(
            """SELECT order_id, symbol, exchange, action, quantity, price,
                      product, status, created_at
               FROM orders
               WHERE date(created_at, 'unixepoch', 'localtime') = ?
               ORDER BY created_at DESC""",
            (today,),
        ).fetchall()

        return [
            {
                "order_id": r[0],
                "symbol": r[1],
                "exchange": r[2],
                "action": r[3],
                "quantity": r[4],
                "price": r[5],
                "product": r[6],
                "status": r[7],
                "created_at": _format_ts(r[8]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # P&L
    # ------------------------------------------------------------------

    def get_pnl(self) -> dict[str, float]:
        """Return aggregate P&L across all sandbox positions.

        Returns:
            Dict with keys:

            - ``realised`` — sum of realised P&L from closed legs
            - ``unrealised`` — sum of unrealised P&L on open positions
            - ``total`` — realised + unrealised
        """
        row = self._conn.execute(
               """SELECT
                   COALESCE(SUM(realised_pnl), 0.0),
                   COALESCE(SUM(unrealised_pnl), 0.0)
               FROM positions"""
        ).fetchone()

        realised, unrealised = row if row else (0.0, 0.0)
        return {
            "realised": realised,
            "unrealised": unrealised,
            "total": realised + unrealised,
        }

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> dict[str, Any]:
        """Clear all sandbox data and return to initial capital.

        Returns:
            Backup dict of cleared data with keys: capital, positions, orders.
        """
        # Snapshot before clearing
        backup: dict[str, Any] = {
            "capital": self.get_capital(),
            "positions": self.get_all_positions(),
            "orders": self.get_all_orders(),
            "reset_at": datetime.now(timezone.utc).isoformat(),
        }

        for table in ("orders", "positions", "capital"):
            self._conn.execute(f"DELETE FROM {_validate_table(table)}")  # noqa: S608

        # Re-seed capital
        now = time.time()
        self._conn.execute(
            """INSERT INTO capital
               (id, initial, current, used_margin, updated_at)
               VALUES ('default', ?, ?, 0.0, ?)""",
            (self._initial_capital, self._initial_capital, now),
        )

        logger.info("Sandbox reset — restored to initial capital %.2f", self._initial_capital)
        return backup

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_data(self) -> str:
        """Export all sandbox data as a JSON string.

        Returns:
            JSON string with keys: capital, positions, orders, exported_at.
        """
        payload: dict[str, Any] = {
            "capital": self.get_capital(),
            "positions": self.get_all_positions(),
            "orders": self.get_all_orders(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": 1,
        }
        return json.dumps(payload, default=str)

    def import_data(self, json_str: str) -> dict[str, Any]:
        """Import sandbox data from a previously exported JSON string.

        Clears all existing data before importing.  The import is applied
        in a single transaction — either everything succeeds or nothing is
        committed (the original state is preserved on failure).

        Args:
            json_str: JSON string produced by :meth:`export_data`.

        Returns:
            Import statistics dict with keys:
            positions_imported, orders_imported, capital_imported.

        Raises:
            ValueError: If the JSON is malformed or missing required keys.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("Import data must be a JSON object")

        # --- Validate structure ---
        capital_data = data.get("capital", {})
        positions_data = data.get("positions", [])
        orders_data = data.get("orders", [])

        if not isinstance(capital_data, dict):
            raise ValueError("'capital' must be a JSON object")
        if not isinstance(positions_data, list):
            raise ValueError("'positions' must be a JSON array")
        if not isinstance(orders_data, list):
            raise ValueError("'orders' must be a JSON array")

        # --- Clear and restore ---
        for table in ("orders", "positions", "capital"):
            self._conn.execute(f"DELETE FROM {_validate_table(table)}")  # noqa: S608

        now = time.time()

        # Restore capital
        initial = float(capital_data.get("initial", self._initial_capital))
        current = float(capital_data.get("current", initial))
        used_margin = float(capital_data.get("used_margin", 0.0))
        self._conn.execute(
            """INSERT INTO capital
               (id, initial, current, used_margin, updated_at)
               VALUES ('default', ?, ?, ?, ?)""",
            (initial, current, used_margin, now),
        )

        # Restore positions
        for pos in positions_data:
            self._conn.execute(
                """INSERT OR IGNORE INTO positions
                   (position_id, symbol, exchange, product, net_qty, avg_price,
                    buy_qty, buy_value, sell_qty, sell_value,
                    realised_pnl, unrealised_pnl, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    str(pos.get("symbol", "")),
                    str(pos.get("exchange", "")),
                    str(pos.get("product", "MIS")),
                    int(pos.get("net_qty", 0)),
                    float(pos.get("avg_price", 0.0)),
                    int(pos.get("buy_qty", 0)),
                    float(pos.get("buy_value", 0.0)),
                    int(pos.get("sell_qty", 0)),
                    float(pos.get("sell_value", 0.0)),
                    float(pos.get("realised_pnl", 0.0)),
                    float(pos.get("unrealised_pnl", 0.0)),
                    now,
                ),
            )

        # Restore orders
        for order in orders_data:
            status = str(order.get("status", "COMPLETE"))
            quantity = int(order.get("quantity", 0))
            price = float(order.get("price", 0.0))
            self._conn.execute(
                """INSERT OR IGNORE INTO orders
                   (order_id, symbol, exchange, action, quantity, price,
                    product, status, filled_qty, avg_fill_px, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(order.get("order_id", uuid.uuid4())),
                    str(order.get("symbol", "")),
                    str(order.get("exchange", "")),
                    str(order.get("action", "BUY")),
                    quantity,
                    price,
                    str(order.get("product", "MIS")),
                    status,
                    quantity if status == "COMPLETE" else 0,
                    price if status == "COMPLETE" else None,
                    now,
                    now,
                ),
            )

        logger.info(
            "Sandbox import complete: %d positions, %d orders",
            len(positions_data), len(orders_data),
        )
        return {
            "capital_imported": True,
            "positions_imported": len(positions_data),
            "orders_imported": len(orders_data),
        }

    # ------------------------------------------------------------------
    # Helper queries (return all rows regardless of date)
    # ------------------------------------------------------------------

    def get_all_orders(self) -> list[dict[str, Any]]:
        """Return all sandbox orders (all dates, all statuses).

        Returns:
            List of order dicts ordered by created_at descending.
        """
        rows = self._conn.execute(
            """SELECT order_id, symbol, exchange, action, quantity, price,
                      product, status, created_at
               FROM orders
               ORDER BY created_at DESC"""
        ).fetchall()

        return [
            {
                "order_id": r[0],
                "symbol": r[1],
                "exchange": r[2],
                "action": r[3],
                "quantity": r[4],
                "price": r[5],
                "product": r[6],
                "status": r[7],
                "created_at": _format_ts(r[8]),
            }
            for r in rows
        ]

    def get_all_positions(self) -> list[dict[str, Any]]:
        """Return all sandbox positions including closed (net_qty == 0).

        Returns:
            List of position dicts ordered by updated_at descending.
        """
        rows = self._conn.execute(
            """SELECT symbol, exchange, product, net_qty, avg_price,
                      buy_qty, buy_value, sell_qty, sell_value,
                      realised_pnl, unrealised_pnl, updated_at
               FROM positions
               ORDER BY updated_at DESC"""
        ).fetchall()

        return [
            {
                "symbol": r[0],
                "exchange": r[1],
                "product": r[2],
                "net_qty": r[3],
                "avg_price": r[4],
                "buy_qty": r[5],
                "buy_value": r[6],
                "sell_qty": r[7],
                "sell_value": r[8],
                "realised_pnl": r[9],
                "unrealised_pnl": r[10],
                "updated_at": _format_ts(r[11]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_position(
        self, symbol: str, exchange: str, product: str
    ) -> dict[str, Any] | None:
        """Fetch a single position row or None if not found."""
        row = self._conn.execute(
            """SELECT position_id, net_qty, avg_price, buy_qty, buy_value,
                      sell_qty, sell_value, realised_pnl, unrealised_pnl
               FROM positions
               WHERE symbol = ? AND exchange = ? AND product = ?""",
            (symbol, exchange, product),
        ).fetchone()

        if row is None:
            return None

        return {
            "position_id": row[0],
            "net_qty": row[1],
            "avg_price": row[2],
            "buy_qty": row[3],
            "buy_value": row[4],
            "sell_qty": row[5],
            "sell_value": row[6],
            "realised_pnl": row[7],
            "unrealised_pnl": row[8],
        }

    def _update_position(
        self,
        *,
        symbol: str,
        exchange: str,
        product: str,
        action: str,
        quantity: int,
        price: float,
        now: float,
    ) -> None:
        """Upsert a position row after a fill."""
        notional = quantity * price
        existing = self._get_position(symbol, exchange, product)

        if existing is None:
            pos_id = str(uuid.uuid4())
            net_qty = quantity if action == "BUY" else -quantity
            avg_price = price
            buy_qty = quantity if action == "BUY" else 0
            buy_value = notional if action == "BUY" else 0.0
            sell_qty = quantity if action == "SELL" else 0
            sell_value = notional if action == "SELL" else 0.0

            self._conn.execute(
                """INSERT INTO positions
                   (position_id, symbol, exchange, product,
                    net_qty, avg_price, buy_qty, buy_value,
                    sell_qty, sell_value, realised_pnl, unrealised_pnl, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, ?)""",
                (
                    pos_id, symbol, exchange, product,
                    net_qty, avg_price, buy_qty, buy_value,
                    sell_qty, sell_value, now,
                ),
            )
        else:
            pos_id = existing["position_id"]
            net_qty = existing["net_qty"]
            avg_price = existing["avg_price"]
            buy_qty = existing["buy_qty"]
            buy_value = existing["buy_value"]
            sell_qty = existing["sell_qty"]
            sell_value = existing["sell_value"]
            realised_pnl = existing["realised_pnl"]

            if action == "BUY":
                new_buy_qty = buy_qty + quantity
                new_buy_value = buy_value + notional
                new_net_qty = net_qty + quantity
                new_avg_price = (
                    new_buy_value / new_buy_qty if new_buy_qty > 0 else avg_price
                )
                new_sell_qty = sell_qty
                new_sell_value = sell_value
                new_realised = realised_pnl
            else:  # SELL
                new_sell_qty = sell_qty + quantity
                new_sell_value = sell_value + notional
                new_net_qty = net_qty - quantity
                new_buy_qty = buy_qty
                new_buy_value = buy_value
                new_avg_price = avg_price
                # Realise P&L when closing a long
                if net_qty > 0:
                    close_qty = min(quantity, net_qty)
                    new_realised = realised_pnl + close_qty * (price - avg_price)
                else:
                    new_realised = realised_pnl

            self._conn.execute(
                """UPDATE positions
                   SET net_qty = ?, avg_price = ?,
                       buy_qty = ?, buy_value = ?,
                       sell_qty = ?, sell_value = ?,
                       realised_pnl = ?, updated_at = ?
                   WHERE position_id = ?""",
                (
                    new_net_qty, new_avg_price,
                    new_buy_qty, new_buy_value,
                    new_sell_qty, new_sell_value,
                    new_realised, now,
                    pos_id,
                ),
            )

    def _update_used_margin(self, now: float) -> None:
        """Recalculate used_margin as sum of abs(net_qty * avg_price) for open positions."""
        total_margin = self._conn.execute(
            """SELECT COALESCE(SUM(ABS(net_qty) * avg_price), 0.0)
               FROM positions
               WHERE net_qty != 0"""
        ).fetchone()[0]

        self._conn.execute(
            """UPDATE capital
               SET used_margin = ?, updated_at = ?
               WHERE id = 'default'""",
            (total_margin, now),
        )

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass
