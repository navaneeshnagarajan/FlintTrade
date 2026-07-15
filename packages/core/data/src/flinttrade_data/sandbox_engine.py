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
import math
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flinttrade_core.db import open_sqlite
from flinttrade_core.symbol_utils import parse_future_symbol, parse_option_symbol

from .sandbox_migration import LegacySandboxConflict, migrate_workspace
from .state_store import IST, ensure_schema, init_capital

logger = logging.getLogger("flinttrade.data.sandbox_engine")

_DEFAULT_CAPITAL = 1_000_000.0  # ₹10,00,000

# ---------------------------------------------------------------------------
# Table name allowlist — prevents SQL injection via dynamic table names
# ---------------------------------------------------------------------------

_VALID_TABLES = frozenset(
    {"capital", "sandbox_config", "orders", "trades", "positions", "pnl", "mtm"}
)


def _validate_table(table: str) -> str:
    """Return *table* unchanged if it is in the allowlist, else raise."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table


@dataclass(slots=True)
class SandboxConfig:
    """Persisted configuration for the single canonical Practice account."""

    starting_capital: float = _DEFAULT_CAPITAL
    equity_leverage: int = 1
    futures_leverage: int = 1
    option_buy_leverage: int = 1
    option_sell_leverage: int = 1
    squareoff_time: str = "15:15"
    mcx_squareoff_time: str = "23:25"


_CONFIG_FIELDS = tuple(field.name for field in fields(SandboxConfig))
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _normalise_config(config: SandboxConfig) -> SandboxConfig:
    """Return a validated, type-normalised sandbox configuration."""
    try:
        starting_capital = float(config.starting_capital)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("starting_capital must be a finite positive number") from exc
    if not math.isfinite(starting_capital) or starting_capital <= 0:
        raise ValueError("starting_capital must be a finite positive number")

    leverage: dict[str, int] = {}
    for name in (
        "equity_leverage",
        "futures_leverage",
        "option_buy_leverage",
        "option_sell_leverage",
    ):
        value = getattr(config, name)
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a positive integer")
        try:
            normalised = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a positive integer") from exc
        if normalised <= 0 or normalised != value:
            raise ValueError(f"{name} must be a positive integer")
        leverage[name] = normalised

    squareoff_time = str(config.squareoff_time).strip()
    mcx_squareoff_time = str(config.mcx_squareoff_time).strip()
    if not _TIME_PATTERN.fullmatch(squareoff_time):
        raise ValueError("squareoff_time must use HH:MM (24-hour) format")
    if not _TIME_PATTERN.fullmatch(mcx_squareoff_time):
        raise ValueError("mcx_squareoff_time must use HH:MM (24-hour) format")

    return SandboxConfig(
        starting_capital=starting_capital,
        squareoff_time=squareoff_time,
        mcx_squareoff_time=mcx_squareoff_time,
        **leverage,
    )


def _default_db_path() -> str:
    """Resolve the canonical Practice database through the workspace authority."""
    from flinttrade_core.workspace import sandbox_state_path  # noqa: PLC0415

    return str(sandbox_state_path())


def _format_ts(value: Any) -> str:
    """Return a stable ISO-ish string for API/export compatibility."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    return str(value)


def _coerce_timestamp(value: Any, default: float) -> float:
    """Normalise numeric or ISO-8601 import timestamps to Unix seconds."""
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("Invalid timestamp")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed_datetime = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid timestamp") from exc
        if parsed_datetime.tzinfo is None:
            parsed_datetime = parsed_datetime.replace(tzinfo=timezone.utc)
        parsed = parsed_datetime.timestamp()
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError("Invalid timestamp")
    return parsed


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
        config: SandboxConfig | None = None,
    ) -> None:
        use_workspace_default = (
            db_path is None
            and not os.getenv("SANDBOX_STATE_PATH")
            and not os.getenv("SANDBOX_DB_PATH")
        )
        self._db_path = db_path or _default_db_path()

        # Ensure parent directory exists for file-based databases
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        if use_workspace_default:
            self._migrate_retired_default_account()

        self._conn = open_sqlite(self._db_path, durability="normal")
        self._lock = threading.RLock()
        self._requested_config = _normalise_config(
            config or SandboxConfig(starting_capital=initial_capital)
        )
        self._initial_capital = self._requested_config.starting_capital
        self.config = self._requested_config
        self._init_db()

    def _migrate_retired_default_account(self) -> None:
        """Best-effort one-shot migration of the retired DuckDB ledger."""
        try:
            from flinttrade_core.workspace import Workspace  # noqa: PLC0415

            migrate_workspace(
                Workspace().workspace_dir,
                state_path=self._db_path,
            )
        except LegacySandboxConflict as exc:
            logger.warning(
                "Retired Practice ledger was preserved for manual review: %s",
                exc,
            )
        except Exception:
            logger.exception(
                "Retired Practice ledger migration failed; source was left untouched"
            )

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
        capital_row = self._conn.execute(
            "SELECT initial FROM capital WHERE id = 'default'"
        ).fetchone()
        seed_config = self._requested_config
        if capital_row is not None and seed_config == SandboxConfig():
            seed_config = SandboxConfig(starting_capital=float(capital_row[0]))
        now = time.time()
        self._conn.execute(
            """INSERT OR IGNORE INTO sandbox_config
               (id, starting_capital, equity_leverage, futures_leverage,
                option_buy_leverage, option_sell_leverage, squareoff_time,
                mcx_squareoff_time, updated_at)
               VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                seed_config.starting_capital,
                seed_config.equity_leverage,
                seed_config.futures_leverage,
                seed_config.option_buy_leverage,
                seed_config.option_sell_leverage,
                seed_config.squareoff_time,
                seed_config.mcx_squareoff_time,
                now,
            ),
        )
        self.config = self._load_config()
        self._initial_capital = self.config.starting_capital
        init_capital(self._conn, self._initial_capital)

    def _load_config(self) -> SandboxConfig:
        row = self._conn.execute(
            """SELECT starting_capital, equity_leverage, futures_leverage,
                      option_buy_leverage, option_sell_leverage, squareoff_time,
                      mcx_squareoff_time
               FROM sandbox_config WHERE id = 'default'"""
        ).fetchone()
        if row is None:  # pragma: no cover - inserted immediately above
            return self._requested_config
        return _normalise_config(SandboxConfig(*row))

    def update_config(self, **changes: Any) -> SandboxConfig:
        """Validate and persist selected Practice configuration fields."""
        with self._lock:
            unknown = sorted(set(changes) - set(_CONFIG_FIELDS))
            if unknown:
                raise ValueError(f"Unknown sandbox config field: {unknown[0]}")
            candidate = asdict(self.config)
            candidate.update(changes)
            updated = _normalise_config(SandboxConfig(**candidate))
            capital = self.get_capital()
            capital_delta = updated.starting_capital - self.config.starting_capital
            proposed_current = capital["current"] + capital_delta
            proposed_margin = self._calculate_used_margin(config=updated)
            if proposed_margin > proposed_current:
                raise ValueError(
                    "Practice policy would reduce capital below committed margin "
                    f"of {proposed_margin:.2f}"
                )

            now = time.time()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """UPDATE sandbox_config
                       SET starting_capital = ?, equity_leverage = ?, futures_leverage = ?,
                           option_buy_leverage = ?, option_sell_leverage = ?,
                           squareoff_time = ?, mcx_squareoff_time = ?, updated_at = ?
                       WHERE id = 'default'""",
                    (
                        updated.starting_capital,
                        updated.equity_leverage,
                        updated.futures_leverage,
                        updated.option_buy_leverage,
                        updated.option_sell_leverage,
                        updated.squareoff_time,
                        updated.mcx_squareoff_time,
                        now,
                    ),
                )
                self._conn.execute(
                    """UPDATE capital
                       SET initial = ?, current = ?, used_margin = ?, updated_at = ?
                       WHERE id = 'default'""",
                    (
                        updated.starting_capital,
                        proposed_current,
                        proposed_margin,
                        now,
                    ),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self.config = updated
            self._initial_capital = updated.starting_capital
            return updated

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

    def get_funds(self) -> dict[str, float]:
        """Return the retired engine's funds shape from canonical state."""
        capital = self.get_capital()
        pnl = self.get_pnl()
        return {
            "starting_capital": capital["initial"],
            "used_margin": capital["used_margin"],
            "realized_pnl": pnl["realised"],
            "available_balance": capital["available"],
            "total_equity": capital["current"] + pnl["unrealised"],
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
        try:
            amount = float(amount)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Capital adjustment must be a finite number") from exc
        if not math.isfinite(amount):
            raise ValueError("Capital adjustment must be a finite number")

        with self._lock:
            cap = self.get_capital()
            new_current = cap["current"] + amount

            if new_current < 0:
                raise ValueError(
                    f"Cannot remove {abs(amount):.2f} — current capital is only {cap['current']:.2f}"
                )
            if new_current < cap["used_margin"]:
                raise ValueError(
                    "Cannot reduce Practice capital below committed margin "
                    f"of {cap['used_margin']:.2f}"
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
        *,
        order_type: str = "MARKET",
        trigger_price: float = 0.0,
        strategy: str = "",
    ) -> dict[str, Any]:
        """Validate a paper order and either fill it or leave it pending.

        MARKET orders fill immediately at ``price``. LIMIT, SL and SL-M orders
        remain pending until :meth:`check_pending_fills` receives a matching
        live tick. Pending buys reserve margin and pending sells reserve covered
        quantity.

        Args:
            symbol: Instrument symbol (e.g. ``"NIFTY"``).
            exchange: Exchange code (e.g. ``"NSE"``, ``"NFO"``).
            action: ``"BUY"`` or ``"SELL"`` (case-insensitive).
            quantity: Number of units / lots.
            price: Market reference price or limit price per unit.
            product: Product type — ``"MIS"``, ``"NRML"``, or ``"CNC"``.
            order_type: ``MARKET``, ``LIMIT``, ``SL`` or ``SL-M``.
            trigger_price: Required positive trigger for stop orders.
            strategy: Optional strategy label retained on the order and trade.

        Returns:
            Dict with keys:

            - ``order_id`` — UUID string
            - ``status`` — ``"PENDING"``, ``"COMPLETE"`` or ``"REJECTED"``
            - ``message`` — human-readable description
        """
        symbol = str(symbol).strip().upper()
        exchange = str(exchange).strip().upper()
        product = str(product).strip().upper() or "MIS"
        strategy = str(strategy).strip()
        action = str(action).strip().upper()
        order_type = str(order_type).strip().upper().replace("SLM", "SL-M")

        if not symbol:
            return {"order_id": "", "status": "REJECTED", "message": "Symbol is required"}
        if not exchange:
            return {"order_id": "", "status": "REJECTED", "message": "Exchange is required"}
        if quantity <= 0:
            return {"order_id": "", "status": "REJECTED", "message": "Quantity must be > 0"}
        if action not in ("BUY", "SELL"):
            return {"order_id": "", "status": "REJECTED", "message": f"Invalid action: {action}"}
        if order_type not in {"MARKET", "LIMIT", "SL", "SL-M"}:
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": f"Invalid order type: {order_type}",
            }
        try:
            price = float(price)
            trigger_price = float(trigger_price)
        except (TypeError, ValueError, OverflowError):
            return {"order_id": "", "status": "REJECTED", "message": "Prices must be numbers"}
        if not math.isfinite(price) or not math.isfinite(trigger_price):
            return {"order_id": "", "status": "REJECTED", "message": "Prices must be finite"}
        if order_type in {"MARKET", "LIMIT", "SL"} and price <= 0:
            if order_type == "MARKET":
                message = "A market fill needs a positive live price; no LTP was available"
            else:
                message = "A limit price must be positive"
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": message,
            }
        if order_type in {"SL", "SL-M"} and trigger_price <= 0:
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": "Stop orders need a positive trigger price",
            }

        margin_price = price if price > 0 else trigger_price
        with self._lock:
            if action == "BUY":
                required_margin = self._estimate_margin(
                    quantity=quantity,
                    price=margin_price,
                    symbol=symbol,
                    exchange=exchange,
                    action=action,
                    product=product,
                )
                cap = self.get_capital()
                if required_margin > cap["available"]:
                    return {
                        "order_id": "",
                        "status": "REJECTED",
                        "message": (
                            f"Insufficient capital: need {required_margin:.2f}, "
                            f"available {cap['available']:.2f}"
                        ),
                    }

            if action == "SELL":
                pos = self._get_position(symbol, exchange, product)
                held = max(int(pos["net_qty"]), 0) if pos else 0
                pending = self._pending_sell_quantity(symbol, exchange, product)
                if quantity > held - pending:
                    detail = f", with {pending} already pending" if pending else ""
                    return {
                        "order_id": "",
                        "status": "REJECTED",
                        "message": (
                            f"Insufficient position: need {quantity}, holding {held}{detail}"
                        ),
                    }

            order_id = str(uuid.uuid4())
            now = time.time()
            status = "COMPLETE" if order_type == "MARKET" else "PENDING"
            fill_price = price if status == "COMPLETE" else None
            fill_time = now if status == "COMPLETE" else None

            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    """INSERT INTO orders
                       (order_id, symbol, exchange, action, quantity, price,
                        trigger_price, pricetype, product, strategy, status,
                        filled_qty, avg_fill_px, fill_time, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        order_id,
                        symbol,
                        exchange,
                        action,
                        quantity,
                        price,
                        trigger_price,
                        order_type,
                        product,
                        strategy,
                        status,
                        quantity if status == "COMPLETE" else 0,
                        fill_price,
                        fill_time,
                        now,
                        now,
                    ),
                )
                if status == "COMPLETE":
                    self._record_trade(
                        order_id=order_id,
                        symbol=symbol,
                        exchange=exchange,
                        action=action,
                        quantity=quantity,
                        price=price,
                        product=product,
                        strategy=strategy,
                        traded_at=now,
                    )
                self._update_used_margin(now)
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

        logger.info(
            "Sandbox order %s: %s %d %s @ %.2f [%s]",
            order_id,
            action,
            quantity,
            symbol,
            fill_price if fill_price is not None else price,
            status,
        )
        message = (
            f"Paper order executed: {action} {quantity} {symbol} @ {price:.2f}"
            if status == "COMPLETE"
            else f"Paper {order_type} order is pending a matching live tick"
        )
        return {"order_id": order_id, "status": status, "message": message}

    def check_pending_fills(self, latest_ticks: dict[str, float]) -> list[str]:
        """Fill pending LIMIT/SL/SL-M orders whose tick condition is met."""
        with self._lock:
            pending = self._conn.execute(
                """SELECT order_id, symbol, exchange, action, quantity, price,
                          trigger_price, stop_triggered, pricetype, product, strategy
                   FROM orders WHERE status = 'PENDING'
                   ORDER BY created_at, order_id"""
            ).fetchall()
            filled: list[str] = []
            for row in pending:
                (
                    order_id,
                    symbol,
                    exchange,
                    action,
                    quantity,
                    limit_price,
                    trigger_price,
                    stop_triggered,
                    order_type,
                    product,
                    strategy,
                ) = row
                raw_ltp = latest_ticks.get(f"{exchange}:{symbol}", latest_ticks.get(symbol))
                try:
                    ltp = float(raw_ltp)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(ltp) or ltp <= 0:
                    continue

                fill_price: float | None = None
                if order_type == "LIMIT":
                    if action == "BUY" and ltp <= limit_price:
                        fill_price = float(limit_price)
                    elif action == "SELL" and ltp >= limit_price:
                        fill_price = float(limit_price)
                elif order_type == "SL":
                    triggered_now = (
                        action == "BUY" and ltp >= trigger_price
                    ) or (
                        action == "SELL" and ltp <= trigger_price
                    )
                    if triggered_now and not stop_triggered:
                        self._conn.execute(
                            """UPDATE orders
                               SET stop_triggered = 1, updated_at = ?
                               WHERE order_id = ? AND status = 'PENDING'""",
                            (time.time(), order_id),
                        )
                    is_triggered = bool(stop_triggered or triggered_now)
                    if action == "BUY" and is_triggered and ltp <= limit_price:
                        fill_price = float(limit_price)
                    elif action == "SELL" and is_triggered and ltp >= limit_price:
                        fill_price = float(limit_price)
                elif order_type == "SL-M":
                    if action == "BUY" and ltp >= trigger_price:
                        fill_price = ltp
                    elif action == "SELL" and ltp <= trigger_price:
                        fill_price = ltp
                if fill_price is None:
                    continue

                now = time.time()
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    rejection_message = ""
                    if action == "BUY":
                        committed_margin = self._calculate_used_margin(
                            exclude_order_id=str(order_id)
                        )
                        proposed_margin = self._estimate_margin(
                            quantity=int(quantity),
                            price=fill_price,
                            symbol=str(symbol),
                            exchange=str(exchange),
                            action=str(action),
                            product=str(product),
                        )
                        if committed_margin + proposed_margin > self.get_capital()["current"]:
                            rejection_message = "Fill exceeds available Practice capital"
                    else:
                        position = self._get_position(str(symbol), str(exchange), str(product))
                        held = max(int(position["net_qty"]), 0) if position else 0
                        if int(quantity) > held:
                            rejection_message = "Fill exceeds the covered Practice position"

                    if rejection_message:
                        self._conn.execute(
                            """UPDATE orders
                               SET status = 'REJECTED', updated_at = ?
                               WHERE order_id = ? AND status = 'PENDING'""",
                            (now, order_id),
                        )
                        self._update_used_margin(now)
                        self._conn.execute("COMMIT")
                        logger.warning(
                            "Practice order %s rejected at fill: %s",
                            order_id,
                            rejection_message,
                        )
                        continue
                    changed = self._conn.execute(
                        """UPDATE orders
                           SET status = 'COMPLETE', filled_qty = quantity,
                               avg_fill_px = ?, fill_time = ?, updated_at = ?
                           WHERE order_id = ? AND status = 'PENDING'""",
                        (fill_price, now, now, order_id),
                    ).rowcount
                    if changed != 1:
                        self._conn.execute("ROLLBACK")
                        continue
                    self._record_trade(
                        order_id=str(order_id),
                        symbol=str(symbol),
                        exchange=str(exchange),
                        action=str(action),
                        quantity=int(quantity),
                        price=fill_price,
                        product=str(product),
                        strategy=str(strategy),
                        traded_at=now,
                    )
                    self._update_used_margin(now)
                    self._conn.execute("COMMIT")
                except BaseException:
                    self._conn.execute("ROLLBACK")
                    raise
                filled.append(str(order_id))
            return filled

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel one pending Practice order."""
        with self._lock:
            now = time.time()
            changed = self._conn.execute(
                """UPDATE orders SET status = 'CANCELLED', updated_at = ?
                   WHERE order_id = ? AND status = 'PENDING'""",
                (now, str(order_id)),
            ).rowcount
            if changed != 1:
                return {
                    "order_id": "",
                    "status": "REJECTED",
                    "message": "Only a pending Practice order can be cancelled",
                }
            self._update_used_margin(now)
            return {
                "order_id": str(order_id),
                "status": "CANCELLED",
                "message": "Practice order cancelled",
            }

    def cancel_pending_orders(self) -> dict[str, Any]:
        """Cancel every pending Practice order."""
        with self._lock:
            now = time.time()
            count = self._conn.execute(
                "UPDATE orders SET status = 'CANCELLED', updated_at = ? WHERE status = 'PENDING'",
                (now,),
            ).rowcount
            self._update_used_margin(now)
            return {
                "status": "CANCELLED",
                "cancelled_count": int(count),
                "message": f"Cancelled {count} pending Practice order(s)",
            }

    def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
        order_type: str | None = None,
    ) -> dict[str, Any]:
        """Modify quantity or prices on one pending Practice order."""
        with self._lock:
            row = self._conn.execute(
                """SELECT symbol, exchange, action, quantity, price, trigger_price,
                          pricetype, product
                   FROM orders WHERE order_id = ? AND status = 'PENDING'""",
                (str(order_id),),
            ).fetchone()
            if row is None:
                return {
                    "order_id": "",
                    "status": "REJECTED",
                    "message": "Only a pending Practice order can be modified",
                }
            symbol, exchange, action, old_qty, old_price, old_trigger, old_type, product = row
            new_qty = int(old_qty if quantity is None else quantity)
            new_price = float(old_price if price is None else price)
            new_trigger = float(old_trigger if trigger_price is None else trigger_price)
            new_type = str(old_type if order_type is None else order_type).strip().upper()
            if new_type == "SLM":
                new_type = "SL-M"
            if new_qty <= 0 or new_type not in {"LIMIT", "SL", "SL-M"}:
                return {"order_id": "", "status": "REJECTED", "message": "Invalid modification"}
            if not all(math.isfinite(value) for value in (new_price, new_trigger)):
                return {"order_id": "", "status": "REJECTED", "message": "Prices must be finite"}
            if new_type in {"LIMIT", "SL"} and new_price <= 0:
                return {"order_id": "", "status": "REJECTED", "message": "Limit price must be positive"}
            if new_type in {"SL", "SL-M"} and new_trigger <= 0:
                return {"order_id": "", "status": "REJECTED", "message": "Trigger price must be positive"}

            if action == "SELL":
                pos = self._get_position(str(symbol), str(exchange), str(product))
                held = max(int(pos["net_qty"]), 0) if pos else 0
                other_pending = self._pending_sell_quantity(
                    str(symbol), str(exchange), str(product), exclude_order_id=str(order_id)
                )
                if new_qty > held - other_pending:
                    return {
                        "order_id": "",
                        "status": "REJECTED",
                        "message": "Modified quantity exceeds the uncovered position",
                    }
            else:
                margin_price = new_price if new_price > 0 else new_trigger
                proposed_margin = self._estimate_margin(
                    quantity=new_qty,
                    price=margin_price,
                    symbol=str(symbol),
                    exchange=str(exchange),
                    action=str(action),
                    product=str(product),
                )
                committed_margin = self._calculate_used_margin(exclude_order_id=str(order_id))
                current_capital = self.get_capital()["current"]
                if committed_margin + proposed_margin > current_capital:
                    return {
                        "order_id": "",
                        "status": "REJECTED",
                        "message": "Modified order exceeds available Practice capital",
                    }

            now = time.time()
            self._conn.execute(
                """UPDATE orders
                   SET quantity = ?, price = ?, trigger_price = ?, pricetype = ?,
                       stop_triggered = 0, updated_at = ?
                   WHERE order_id = ? AND status = 'PENDING'""",
                (new_qty, new_price, new_trigger, new_type, now, str(order_id)),
            )
            self._update_used_margin(now)
            return {
                "order_id": str(order_id),
                "status": "PENDING",
                "message": "Practice order modified",
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
                # Compatibility aliases retained while legacy callers migrate.
                "realized_pnl": r[9],
                "unrealized_pnl": r[10],
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
        today = datetime.now(tz=IST).date().isoformat()
        rows = self._conn.execute(
            """SELECT order_id, symbol, exchange, action, quantity, price,
                      trigger_price, stop_triggered, pricetype, product, strategy, status,
                      filled_qty, avg_fill_px, fill_time, created_at
               FROM orders
               WHERE date(created_at, 'unixepoch', '+5 hours', '+30 minutes') = ?
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
                "trigger_price": r[6],
                "stop_triggered": bool(r[7]),
                "order_type": r[8],
                "pricetype": r[8],
                "product": r[9],
                "strategy": r[10],
                "status": r[11],
                "filled_qty": r[12],
                "avg_fill_px": r[13],
                "fill_price": r[13],
                "fill_time": _format_ts(r[14]) if r[14] is not None else None,
                "created_at": _format_ts(r[15]),
            }
            for r in rows
        ]

    def get_trades(self) -> list[dict[str, Any]]:
        """Return executed Practice fills ordered newest first."""
        rows = self._conn.execute(
            """SELECT trade_id, order_id, symbol, exchange, action, quantity,
                      price, product, strategy, traded_at
               FROM trades ORDER BY traded_at DESC, trade_id DESC"""
        ).fetchall()
        return [
            {
                "trade_id": row[0],
                "order_id": row[1],
                "symbol": row[2],
                "exchange": row[3],
                "action": row[4],
                "quantity": row[5],
                "price": row[6],
                "product": row[7],
                "strategy": row[8],
                "traded_at": _format_ts(row[9]),
            }
            for row in rows
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

    def get_pnl_history(self) -> list[dict[str, Any]]:
        """Return durable daily Practice P&L snapshots, newest first."""
        rows = self._conn.execute(
            """SELECT session_date, realised_total, unrealised_total, gross_pnl,
                      charges, net_pnl, total_trades, high_water_mark,
                      max_drawdown, updated_at
               FROM pnl ORDER BY session_date DESC"""
        ).fetchall()
        return [
            {
                "date": row[0],
                "realised": row[1],
                "unrealised": row[2],
                "gross_pnl": row[3],
                "charges": row[4],
                "net_pnl": row[5],
                "total": row[5],
                "total_trades": row[6],
                "high_water_mark": row[7],
                "max_drawdown": row[8],
                "updated_at": _format_ts(row[9]),
                "recorded_at": _format_ts(row[9]),
                # Temporary compatibility aliases for the retired DuckDB API.
                "realized_pnl": row[1],
                "unrealized_pnl": row[2],
            }
            for row in rows
        ]

    def process_tick(
        self,
        exchange: str,
        symbol: str,
        ltp: float,
        _volume: int = 0,
        _source_timestamp: float | None = None,
    ) -> list[str]:
        """Apply one accepted live tick to marks and pending Practice orders."""
        exchange = str(exchange).strip().upper()
        symbol = str(symbol).strip().upper()
        try:
            ltp = float(ltp)
        except (TypeError, ValueError, OverflowError):
            return []
        if not exchange or not symbol or not math.isfinite(ltp) or ltp <= 0:
            return []
        identity = f"{exchange}:{symbol}"
        with self._lock:
            self._mark_position(exchange, symbol, ltp)
            filled = self.check_pending_fills({identity: ltp})
            if filled:
                self._mark_position(exchange, symbol, ltp)
            return filled

    def square_off_all(self, latest_ticks: dict[str, float]) -> int:
        """Close every open Practice position using explicit current LTPs.

        The operation validates the complete mark set before changing any row,
        then cancels pending orders and closes all positions in one transaction.
        """
        with self._lock:
            positions = self._conn.execute(
                """SELECT symbol, exchange, product, net_qty
                   FROM positions WHERE net_qty != 0
                   ORDER BY exchange, symbol, product"""
            ).fetchall()
            if not positions:
                return 0

            marks: dict[tuple[str, str], float] = {}
            missing: list[str] = []
            for symbol, exchange, _product, _net_qty in positions:
                raw = latest_ticks.get(f"{exchange}:{symbol}", latest_ticks.get(symbol))
                try:
                    mark = float(raw)
                except (TypeError, ValueError, OverflowError):
                    mark = 0.0
                if not math.isfinite(mark) or mark <= 0:
                    missing.append(f"{exchange}:{symbol}")
                else:
                    marks[(str(exchange), str(symbol))] = mark
            if missing:
                raise ValueError(
                    "Current LTP required before Practice square-off: " + ", ".join(missing)
                )

            now = time.time()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "UPDATE orders SET status = 'CANCELLED', updated_at = ? WHERE status = 'PENDING'",
                    (now,),
                )
                for symbol, exchange, product, net_qty in positions:
                    action = "SELL" if int(net_qty) > 0 else "BUY"
                    quantity = abs(int(net_qty))
                    fill_price = marks[(str(exchange), str(symbol))]
                    order_id = str(uuid.uuid4())
                    self._conn.execute(
                        """INSERT INTO orders
                           (order_id, symbol, exchange, action, quantity, price,
                            trigger_price, pricetype, product, strategy, status,
                            filled_qty, avg_fill_px, fill_time, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, 0.0, 'MARKET', ?, 'SQUAREOFF',
                                   'COMPLETE', ?, ?, ?, ?, ?)""",
                        (
                            order_id,
                            symbol,
                            exchange,
                            action,
                            quantity,
                            fill_price,
                            product,
                            quantity,
                            fill_price,
                            now,
                            now,
                            now,
                        ),
                    )
                    self._record_trade(
                        order_id=order_id,
                        symbol=str(symbol),
                        exchange=str(exchange),
                        action=action,
                        quantity=quantity,
                        price=fill_price,
                        product=str(product),
                        strategy="SQUAREOFF",
                        traded_at=now,
                    )
                self._update_used_margin(now)
                self._record_daily_pnl(now)
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            return len(positions)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> dict[str, Any]:
        """Clear all sandbox data and return to initial capital.

        Returns:
            Backup dict of cleared data with keys: capital, positions, orders.
        """
        # Snapshot before clearing
        with self._lock:
            backup: dict[str, Any] = {
                "config": asdict(self.config),
                "capital": self.get_capital(),
                "positions": self.get_all_positions(),
                "orders": self.get_all_orders(),
                "trades": self.get_trades(),
                "pnl_history": self.get_pnl_history(),
                "reset_at": datetime.now(timezone.utc).isoformat(),
            }

            now = time.time()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for table in ("mtm", "trades", "orders", "positions", "pnl", "capital"):
                    self._conn.execute(f"DELETE FROM {_validate_table(table)}")  # noqa: S608
                self._conn.execute(
                    """INSERT INTO capital
                       (id, initial, current, used_margin, updated_at)
                       VALUES ('default', ?, ?, 0.0, ?)""",
                    (self._initial_capital, self._initial_capital, now),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

        logger.info("Sandbox reset — restored to initial capital %.2f", self._initial_capital)
        return backup

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_data(self) -> str:
        """Export all sandbox data as a JSON string.

        Returns:
            Versioned JSON string containing the complete Practice state.
        """
        payload: dict[str, Any] = {
            "schema_version": 2,
            "config": asdict(self.config),
            "capital": self.get_capital(),
            "positions": self.get_all_positions(),
            "orders": self.get_all_orders(),
            "trades": self.get_trades(),
            "pnl_history": self.get_pnl_history(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
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

        schema_version = data.get("schema_version", 1)
        if isinstance(schema_version, bool) or schema_version not in {1, 2}:
            raise ValueError(f"Unsupported sandbox schema version: {schema_version!r}")

        # --- Validate top-level structure ---
        capital_data = data.get("capital", {})
        positions_data = data.get("positions", [])
        orders_data = data.get("orders", [])
        trades_data = data.get("trades", [])
        pnl_data = data.get("pnl_history", [])
        config_data = data.get("config")

        if not isinstance(capital_data, dict):
            raise ValueError("'capital' must be a JSON object")
        if not isinstance(positions_data, list):
            raise ValueError("'positions' must be a JSON array")
        if not isinstance(orders_data, list):
            raise ValueError("'orders' must be a JSON array")
        if not isinstance(trades_data, list):
            raise ValueError("'trades' must be a JSON array")
        if not isinstance(pnl_data, list):
            raise ValueError("'pnl_history' must be a JSON array")
        if config_data is not None and not isinstance(config_data, dict):
            raise ValueError("'config' must be a JSON object")
        if any(not isinstance(row, dict) for row in positions_data + orders_data + trades_data + pnl_data):
            raise ValueError("Sandbox import rows must be JSON objects")

        now = time.time()
        initial = float(capital_data.get("initial", self._initial_capital))
        current = float(capital_data.get("current", initial))
        if not all(math.isfinite(value) for value in (initial, current)) or initial <= 0 or current < 0:
            raise ValueError("Imported capital values are invalid")
        imported_config = _normalise_config(
            SandboxConfig(**(config_data or {"starting_capital": initial}))
        )

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for table in ("mtm", "trades", "orders", "positions", "pnl", "capital", "sandbox_config"):
                    self._conn.execute(f"DELETE FROM {_validate_table(table)}")  # noqa: S608

                self._conn.execute(
                    """INSERT INTO sandbox_config
                       (id, starting_capital, equity_leverage, futures_leverage,
                        option_buy_leverage, option_sell_leverage, squareoff_time,
                        mcx_squareoff_time, updated_at)
                       VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        imported_config.starting_capital,
                        imported_config.equity_leverage,
                        imported_config.futures_leverage,
                        imported_config.option_buy_leverage,
                        imported_config.option_sell_leverage,
                        imported_config.squareoff_time,
                        imported_config.mcx_squareoff_time,
                        now,
                    ),
                )
                self._conn.execute(
                    """INSERT INTO capital
                       (id, initial, current, used_margin, updated_at)
                       VALUES ('default', ?, ?, 0.0, ?)""",
                    (initial, current, now),
                )

                for pos in positions_data:
                    self._conn.execute(
                        """INSERT INTO positions
                           (position_id, symbol, exchange, product, net_qty, avg_price,
                            buy_qty, buy_value, sell_qty, sell_value,
                            realised_pnl, unrealised_pnl, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(pos.get("position_id") or uuid.uuid4()),
                            str(pos.get("symbol", "")).strip().upper(),
                            str(pos.get("exchange", "")).strip().upper(),
                            str(pos.get("product", "MIS")).strip().upper(),
                            int(pos.get("net_qty", 0)),
                            float(pos.get("avg_price", 0.0)),
                            int(pos.get("buy_qty", 0)),
                            float(pos.get("buy_value", 0.0)),
                            int(pos.get("sell_qty", 0)),
                            float(pos.get("sell_value", 0.0)),
                            float(pos.get("realised_pnl", pos.get("realized_pnl", 0.0))),
                            float(pos.get("unrealised_pnl", pos.get("unrealized_pnl", 0.0))),
                            _coerce_timestamp(pos.get("updated_at"), now),
                        ),
                    )

                imported_orders: list[dict[str, Any]] = []
                for order in orders_data:
                    status = str(order.get("status", "COMPLETE")).strip().upper()
                    quantity = int(order.get("quantity", 0))
                    price = float(order.get("price", 0.0))
                    order_id = str(order.get("order_id") or uuid.uuid4())
                    order_type = str(
                        order.get("order_type", order.get("pricetype", "MARKET"))
                    ).strip().upper()
                    created_at = _coerce_timestamp(order.get("created_at"), now)
                    fill_time = (
                        _coerce_timestamp(order.get("fill_time"), created_at)
                        if order.get("fill_time") is not None
                        else (created_at if status == "COMPLETE" else None)
                    )
                    row = {
                        "order_id": order_id,
                        "symbol": str(order.get("symbol", "")).strip().upper(),
                        "exchange": str(order.get("exchange", "")).strip().upper(),
                        "action": str(order.get("action", "BUY")).strip().upper(),
                        "quantity": quantity,
                        "price": price,
                        "trigger_price": float(order.get("trigger_price", 0.0)),
                        "stop_triggered": bool(order.get("stop_triggered", False)),
                        "order_type": order_type,
                        "product": str(order.get("product", "MIS")).strip().upper(),
                        "strategy": str(order.get("strategy", "")),
                        "status": status,
                        "filled_qty": int(
                            order.get("filled_qty", quantity if status == "COMPLETE" else 0)
                        ),
                        "avg_fill_px": order.get(
                            "avg_fill_px", price if status == "COMPLETE" else None
                        ),
                        "fill_time": fill_time,
                        "created_at": created_at,
                    }
                    self._conn.execute(
                        """INSERT INTO orders
                           (order_id, symbol, exchange, action, quantity, price,
                            trigger_price, stop_triggered, pricetype, product, strategy, status,
                            filled_qty, avg_fill_px, fill_time, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            row["order_id"],
                            row["symbol"],
                            row["exchange"],
                            row["action"],
                            row["quantity"],
                            row["price"],
                            row["trigger_price"],
                            int(row["stop_triggered"]),
                            row["order_type"],
                            row["product"],
                            row["strategy"],
                            row["status"],
                            row["filled_qty"],
                            row["avg_fill_px"],
                            row["fill_time"],
                            row["created_at"],
                            _coerce_timestamp(order.get("updated_at"), now),
                        ),
                    )
                    imported_orders.append(row)

                effective_trades = trades_data
                if not effective_trades:
                    effective_trades = [
                        {
                            "trade_id": str(uuid.uuid4()),
                            "order_id": row["order_id"],
                            "symbol": row["symbol"],
                            "exchange": row["exchange"],
                            "action": row["action"],
                            "quantity": row["filled_qty"],
                            "price": row["avg_fill_px"],
                            "product": row["product"],
                            "strategy": row["strategy"],
                            "traded_at": row["fill_time"] or row["created_at"],
                        }
                        for row in imported_orders
                        if row["status"] == "COMPLETE" and row["filled_qty"] > 0
                    ]
                for trade in effective_trades:
                    self._conn.execute(
                        """INSERT INTO trades
                           (trade_id, order_id, symbol, exchange, action, quantity,
                            price, product, strategy, traded_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(trade.get("trade_id") or uuid.uuid4()),
                            str(trade.get("order_id", "")),
                            str(trade.get("symbol", "")).strip().upper(),
                            str(trade.get("exchange", "")).strip().upper(),
                            str(trade.get("action", "BUY")).strip().upper(),
                            int(trade.get("quantity", 0)),
                            float(trade.get("price", 0.0)),
                            str(trade.get("product", "MIS")).strip().upper(),
                            str(trade.get("strategy", "")),
                            _coerce_timestamp(trade.get("traded_at"), now),
                        ),
                    )

                for day in pnl_data:
                    realised = float(day.get("realised", day.get("realized_pnl", 0.0)))
                    unrealised = float(day.get("unrealised", day.get("unrealized_pnl", 0.0)))
                    gross = float(day.get("gross_pnl", realised + unrealised))
                    charges = float(day.get("charges", 0.0))
                    net = float(day.get("net_pnl", day.get("total", gross - charges)))
                    self._conn.execute(
                        """INSERT INTO pnl
                           (session_date, realised_total, unrealised_total, gross_pnl,
                            charges, net_pnl, total_trades, high_water_mark,
                            max_drawdown, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            str(day.get("date")),
                            realised,
                            unrealised,
                            gross,
                            charges,
                            net,
                            int(day.get("total_trades", 0)),
                            float(day.get("high_water_mark", net)),
                            float(day.get("max_drawdown", 0.0)),
                            _coerce_timestamp(day.get("updated_at"), now),
                        ),
                    )

                self.config = imported_config
                self._initial_capital = imported_config.starting_capital
                self._update_used_margin(now)
                if not pnl_data:
                    self._record_daily_pnl(now)
                self._conn.execute("COMMIT")
            except Exception as exc:
                self._conn.execute("ROLLBACK")
                raise ValueError(f"Invalid sandbox import: {exc}") from exc

        logger.info(
            "Sandbox import complete: %d positions, %d orders, %d trades",
            len(positions_data),
            len(orders_data),
            len(effective_trades),
        )
        return {
            "capital_imported": True,
            "positions_imported": len(positions_data),
            "orders_imported": len(orders_data),
            "trades_imported": len(effective_trades),
            "pnl_days_imported": len(pnl_data) if pnl_data else 1,
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
                      trigger_price, stop_triggered, pricetype, product, strategy, status,
                      filled_qty, avg_fill_px, fill_time, created_at
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
                "trigger_price": r[6],
                "stop_triggered": bool(r[7]),
                "order_type": r[8],
                "pricetype": r[8],
                "product": r[9],
                "strategy": r[10],
                "status": r[11],
                "filled_qty": r[12],
                "avg_fill_px": r[13],
                "fill_price": r[13],
                "fill_time": _format_ts(r[14]) if r[14] is not None else None,
                "created_at": _format_ts(r[15]),
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
                "realized_pnl": r[9],
                "unrealized_pnl": r[10],
                "updated_at": _format_ts(r[11]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pending_sell_quantity(
        self,
        symbol: str,
        exchange: str,
        product: str,
        *,
        exclude_order_id: str | None = None,
    ) -> int:
        sql = (
            "SELECT COALESCE(SUM(quantity), 0) FROM orders "
            "WHERE symbol = ? AND exchange = ? AND product = ? "
            "AND action = 'SELL' AND status = 'PENDING'"
        )
        params: list[Any] = [symbol, exchange, product]
        if exclude_order_id is not None:
            sql += " AND order_id != ?"
            params.append(exclude_order_id)
        return int(self._conn.execute(sql, params).fetchone()[0])

    def _record_trade(
        self,
        *,
        order_id: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: int,
        price: float,
        product: str,
        strategy: str,
        traded_at: float,
    ) -> None:
        self._conn.execute(
            """INSERT INTO trades
               (trade_id, order_id, symbol, exchange, action, quantity, price,
                product, strategy, traded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                order_id,
                symbol,
                exchange,
                action,
                quantity,
                price,
                product,
                strategy,
                traded_at,
            ),
        )
        self._update_position(
            symbol=symbol,
            exchange=exchange,
            product=product,
            action=action,
            quantity=quantity,
            price=price,
            now=traded_at,
        )
        self._record_daily_pnl(traded_at)

    def _mark_position(self, exchange: str, symbol: str, ltp: float) -> None:
        """Persist one current mark and refresh daily unrealised P&L."""
        rows = self._conn.execute(
            """SELECT position_id, net_qty, avg_price
               FROM positions
               WHERE exchange = ? AND symbol = ? AND net_qty != 0""",
            (exchange, symbol),
        ).fetchall()
        if not rows:
            return
        now = time.time()
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for position_id, net_qty, avg_price in rows:
                unrealised = (ltp - float(avg_price)) * int(net_qty)
                self._conn.execute(
                    """UPDATE positions SET unrealised_pnl = ?, updated_at = ?
                       WHERE position_id = ?""",
                    (unrealised, now, position_id),
                )
                self._conn.execute(
                    """INSERT INTO mtm (position_id, tick_ts, ltp, qty, unrealised)
                       VALUES (?, ?, ?, ?, ?)""",
                    (position_id, now, ltp, int(net_qty), unrealised),
                )
            self._record_daily_pnl(now)
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def _record_daily_pnl(self, at: float) -> None:
        """Upsert the current IST session's aggregate P&L snapshot."""
        session_date = datetime.fromtimestamp(at, tz=IST).date().isoformat()
        realised, unrealised = self._conn.execute(
            """SELECT COALESCE(SUM(realised_pnl), 0.0),
                      COALESCE(SUM(unrealised_pnl), 0.0)
               FROM positions"""
        ).fetchone()
        total_trades = int(
            self._conn.execute(
                """SELECT COUNT(*) FROM trades
                   WHERE date(traded_at, 'unixepoch', '+5 hours', '+30 minutes') = ?""",
                (session_date,),
            ).fetchone()[0]
        )
        gross = float(realised) + float(unrealised)
        existing = self._conn.execute(
            "SELECT high_water_mark, max_drawdown FROM pnl WHERE session_date = ?",
            (session_date,),
        ).fetchone()
        previous_high = float(existing[0]) if existing else gross
        previous_drawdown = float(existing[1]) if existing else 0.0
        high_water = max(previous_high, gross)
        max_drawdown = max(previous_drawdown, high_water - gross)
        self._conn.execute(
            """INSERT INTO pnl
               (session_date, realised_total, unrealised_total, gross_pnl,
                charges, net_pnl, total_trades, high_water_mark, max_drawdown,
                updated_at)
               VALUES (?, ?, ?, ?, 0.0, ?, ?, ?, ?, ?)
               ON CONFLICT(session_date) DO UPDATE SET
                   realised_total = excluded.realised_total,
                   unrealised_total = excluded.unrealised_total,
                   gross_pnl = excluded.gross_pnl,
                   net_pnl = excluded.net_pnl,
                   total_trades = excluded.total_trades,
                   high_water_mark = excluded.high_water_mark,
                   max_drawdown = excluded.max_drawdown,
                   updated_at = excluded.updated_at""",
            (
                session_date,
                realised,
                unrealised,
                gross,
                gross,
                total_trades,
                high_water,
                max_drawdown,
                at,
            ),
        )

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
                    ((net_qty * avg_price) + notional) / new_net_qty
                    if new_net_qty > 0
                    else price
                )
                new_sell_qty = sell_qty
                new_sell_value = sell_value
                new_realised = realised_pnl
                new_unrealised = (
                    (price - new_avg_price) * new_net_qty if new_net_qty != 0 else 0.0
                )
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
                new_unrealised = (
                    (price - new_avg_price) * new_net_qty if new_net_qty != 0 else 0.0
                )

            self._conn.execute(
                """UPDATE positions
                   SET net_qty = ?, avg_price = ?,
                       buy_qty = ?, buy_value = ?,
                       sell_qty = ?, sell_value = ?,
                       realised_pnl = ?, unrealised_pnl = ?, updated_at = ?
                   WHERE position_id = ?""",
                (
                    new_net_qty, new_avg_price,
                    new_buy_qty, new_buy_value,
                    new_sell_qty, new_sell_value,
                    new_realised, new_unrealised, now,
                    pos_id,
                ),
            )
            realised_delta = new_realised - realised_pnl
            if realised_delta:
                self._conn.execute(
                    """UPDATE capital
                       SET current = current + ?, updated_at = ?
                       WHERE id = 'default'""",
                    (realised_delta, now),
                )

    def _update_used_margin(self, now: float) -> None:
        """Recalculate leverage-aware margin for every open position."""
        total_margin = self._calculate_used_margin()

        self._conn.execute(
            """UPDATE capital
               SET used_margin = ?, updated_at = ?
               WHERE id = 'default'""",
            (total_margin, now),
        )

    def _calculate_used_margin(
        self,
        *,
        exclude_order_id: str | None = None,
        config: SandboxConfig | None = None,
    ) -> float:
        """Return open-position margin plus pending BUY reservations."""
        policy = config or self.config
        rows = self._conn.execute(
            """SELECT symbol, exchange, product, net_qty, avg_price
               FROM positions WHERE net_qty != 0"""
        ).fetchall()
        position_margin = sum(
            self._estimate_margin(
                quantity=abs(int(row[3])),
                price=float(row[4]),
                symbol=str(row[0]),
                exchange=str(row[1]),
                action="BUY" if int(row[3]) > 0 else "SELL",
                product=str(row[2]),
                config=policy,
            )
            for row in rows
        )
        pending_sql = (
            "SELECT order_id, symbol, exchange, product, action, quantity, "
            "price, trigger_price FROM orders WHERE action = 'BUY' AND status = 'PENDING'"
        )
        pending_rows = self._conn.execute(pending_sql).fetchall()
        pending_margin = sum(
            self._estimate_margin(
                quantity=int(row[5]),
                price=float(row[6]) if float(row[6]) > 0 else float(row[7]),
                symbol=str(row[1]),
                exchange=str(row[2]),
                action=str(row[4]),
                product=str(row[3]),
                config=policy,
            )
            for row in pending_rows
            if exclude_order_id is None or str(row[0]) != exclude_order_id
        )
        return position_margin + pending_margin

    def _estimate_margin(
        self,
        *,
        quantity: int,
        price: float,
        symbol: str,
        exchange: str,
        action: str,
        product: str,
        config: SandboxConfig | None = None,
    ) -> float:
        """Estimate Practice margin from the persisted leverage policy."""
        policy = config or self.config
        notional = abs(quantity * price)
        normalised_symbol = symbol.strip().upper()
        normalised_exchange = exchange.strip().upper()
        normalised_product = product.strip().upper()
        is_option = parse_option_symbol(normalised_symbol) is not None
        is_derivative = (
            parse_future_symbol(normalised_symbol) is not None
            or normalised_exchange in {"NFO", "BFO", "MCX", "CDS"}
        )
        if is_option:
            leverage = (
                policy.option_buy_leverage
                if action.strip().upper() == "BUY"
                else policy.option_sell_leverage
            )
        elif is_derivative or normalised_product == "NRML":
            leverage = policy.futures_leverage
        else:
            leverage = policy.equity_leverage
        return notional / leverage

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        try:
            self._conn.close()
        except Exception:  # pragma: no cover
            pass
