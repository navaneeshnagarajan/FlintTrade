"""One-shot migration from the retired DuckDB Practice engine to SQLite."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import time
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from flinttrade_core.db import open_sqlite

from .state_store import ensure_schema, init_capital

logger = logging.getLogger("flinttrade.data.sandbox_migration")

_LEGACY_TABLES = (
    "sandbox_funds",
    "sandbox_orders",
    "sandbox_trades",
    "sandbox_positions",
    "sandbox_daily_pnl",
)
_SESSION_TABLES = (
    "sandbox_orders",
    "sandbox_trades",
    "sandbox_positions",
    "sandbox_daily_pnl",
)


class LegacySandboxConflict(RuntimeError):
    """Raised when two independent Practice ledgers cannot be merged safely."""


def _epoch(value: Any, *, default: float | None = None) -> float:
    """Convert DuckDB timestamps and ISO values to Unix seconds."""
    if value is None:
        return time.time() if default is None else default
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _read_table(connection: Any, table: str, present: set[str]) -> list[dict[str, Any]]:
    if table not in present:
        return []
    columns = [row[0] for row in connection.execute(f"DESCRIBE {table}").fetchall()]
    return [
        dict(zip(columns, row))
        for row in connection.execute(f"SELECT * FROM {table}").fetchall()
    ]


def _archive_legacy(source: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = archive_dir / f"engine-sandbox-{source.stem}.migrated.duckdb"
    counter = 1
    while destination.exists():
        destination = archive_dir / (
            f"engine-sandbox-{source.stem}.migrated.{counter}.duckdb"
        )
        counter += 1
    source.replace(destination)
    for suffix in (".wal", "-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            sidecar.replace(destination.with_name(destination.name + suffix))
    return destination


def _source_key(source: Path) -> str:
    """Bind a migration marker to both the source path and file contents."""
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"{source}:{digest.hexdigest()}"


def _normalise_status(value: Any) -> str:
    status = str(value or "PENDING").upper()
    aliases = {"FILLED": "COMPLETE", "OPEN": "PENDING"}
    status = aliases.get(status, status)
    allowed = {"PENDING", "COMPLETE", "CANCELLED", "REJECTED", "PARTIAL"}
    if status not in allowed:
        raise LegacySandboxConflict(f"unsupported legacy order status: {status}")
    return status


def _validate_default_account(rows_by_table: dict[str, list[dict[str, Any]]]) -> None:
    account_ids = {
        str(row["account_id"])
        for rows in rows_by_table.values()
        for row in rows
        if row.get("account_id") is not None
    }
    unsupported = account_ids - {"default"}
    if unsupported:
        raise LegacySandboxConflict(
            "legacy sandbox contains non-default accounts; per-account migration is deferred"
        )


def _target_has_session_state(connection: Any) -> bool:
    return any(
        connection.execute(f"SELECT EXISTS(SELECT 1 FROM {table})").fetchone()[0]
        for table in ("orders", "trades", "positions", "pnl", "mtm")
    )


def migrate_legacy_sandbox(
    legacy_path: str | os.PathLike[str],
    state_path: str | os.PathLike[str],
    archive_dir: str | os.PathLike[str],
) -> dict[str, Any]:
    """Migrate one default-account DuckDB ledger into a pristine SQLite store.

    The source is archived only after the SQLite transaction commits. If both
    stores contain session state, the function leaves both untouched and raises
    :class:`LegacySandboxConflict` rather than combining unrelated portfolios.
    """
    legacy = Path(legacy_path).expanduser().resolve()
    target = Path(state_path).expanduser().resolve()
    archive = Path(archive_dir).expanduser().resolve()
    if not legacy.exists():
        return {"status": "no-source", "counts": {}}

    target.parent.mkdir(parents=True, exist_ok=True)
    source_key = _source_key(legacy)
    with closing(open_sqlite(str(target), durability="full")) as sqlite:
        ensure_schema(sqlite)
        init_capital(sqlite, 1_000_000.0)
        marker = sqlite.execute(
            "SELECT row_counts FROM sandbox_migrations WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        if marker is not None:
            archived_to = _archive_legacy(legacy, archive)
            return {
                "status": "already-migrated",
                "counts": json.loads(marker[0]),
                "archive_path": str(archived_to),
            }

        with duckdb.connect(str(legacy), read_only=True) as source:
            present = {row[0] for row in source.execute("SHOW TABLES").fetchall()}
            rows_by_table = {
                table: _read_table(source, table, present)
                for table in _LEGACY_TABLES
            }

        _validate_default_account(rows_by_table)
        counts = {table: len(rows) for table, rows in rows_by_table.items()}
        funds = rows_by_table["sandbox_funds"]
        meaningful_funds = any(
            float(row.get("starting_capital") or 1_000_000.0) != 1_000_000.0
            or float(row.get("used_margin") or 0.0) != 0.0
            or float(row.get("realized_pnl") or 0.0) != 0.0
            for row in funds
        )
        has_legacy_state = (
            any(rows_by_table[table] for table in _SESSION_TABLES)
            or meaningful_funds
        )
        if has_legacy_state and _target_has_session_state(sqlite):
            raise LegacySandboxConflict(
                "legacy DuckDB and canonical SQLite both contain session state"
            )

        orders = list(rows_by_table["sandbox_orders"])
        trades = rows_by_table["sandbox_trades"]
        positions = rows_by_table["sandbox_positions"]
        daily_pnl = rows_by_table["sandbox_daily_pnl"]
        if any(int(row.get("net_qty") or 0) < 0 for row in positions):
            raise LegacySandboxConflict(
                "legacy sandbox contains a short position; source preserved for manual recovery"
            )

        known_order_ids = {str(row.get("order_id")) for row in orders}
        for trade in trades:
            order_id = str(trade.get("order_id") or trade.get("trade_id"))
            if order_id in known_order_ids:
                continue
            traded_at = trade.get("traded_at")
            orders.append({
                "order_id": order_id,
                "symbol": trade.get("symbol", ""),
                "exchange": trade.get("exchange", "NSE"),
                "action": trade.get("action", "BUY"),
                "quantity": trade.get("quantity", 0),
                "price": trade.get("price", 0.0),
                "trigger_price": 0.0,
                "pricetype": "MARKET",
                "product": trade.get("product", "MIS"),
                "strategy": trade.get("strategy", ""),
                "status": "COMPLETE",
                "fill_price": trade.get("price", 0.0),
                "fill_time": traded_at,
                "created_at": traded_at,
                "updated_at": traded_at,
            })
            known_order_ids.add(order_id)

        now = time.time()
        sqlite.execute("BEGIN IMMEDIATE")
        try:
            if funds and has_legacy_state:
                fund = funds[0]
                starting = float(fund.get("starting_capital") or 1_000_000.0)
                used = float(fund.get("used_margin") or 0.0)
                realised = float(fund.get("realized_pnl") or 0.0)
                sqlite.execute(
                    """INSERT INTO sandbox_config
                       (id, starting_capital, equity_leverage, futures_leverage,
                        option_buy_leverage, option_sell_leverage, squareoff_time,
                        mcx_squareoff_time, updated_at)
                       VALUES ('default', ?, 1, 1, 1, 1, '15:15', '23:25', ?)
                       ON CONFLICT (id) DO UPDATE SET
                       starting_capital = excluded.starting_capital,
                       updated_at = excluded.updated_at""",
                    (starting, now),
                )
                sqlite.execute(
                    """UPDATE capital
                       SET initial = ?, current = ?, used_margin = ?, updated_at = ?
                       WHERE id = 'default'""",
                    (starting, starting + realised, used, now),
                )

            for row in orders:
                quantity = int(row.get("quantity") or 0)
                status = _normalise_status(row.get("status"))
                fill_price = row.get("fill_price")
                created_at = _epoch(row.get("created_at"), default=now)
                updated_at = _epoch(row.get("updated_at"), default=created_at)
                sqlite.execute(
                    """INSERT INTO orders
                       (order_id, symbol, exchange, action, quantity, price,
                        trigger_price, pricetype, product, strategy, status,
                        filled_qty, avg_fill_px, fill_time, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(row.get("order_id")),
                        str(row.get("symbol") or ""),
                        str(row.get("exchange") or "NSE"),
                        str(row.get("action") or "BUY").upper(),
                        quantity,
                        float(row.get("price") or 0.0),
                        float(row.get("trigger_price") or 0.0),
                        str(row.get("pricetype") or "MARKET").upper(),
                        str(row.get("product") or "MIS").upper(),
                        str(row.get("strategy") or ""),
                        status,
                        quantity if status == "COMPLETE" else 0,
                        float(fill_price) if fill_price is not None else None,
                        _epoch(row.get("fill_time"), default=updated_at)
                        if row.get("fill_time") is not None
                        else None,
                        created_at,
                        updated_at,
                    ),
                )

            for row in positions:
                sqlite.execute(
                    """INSERT INTO positions
                       (position_id, symbol, exchange, product, net_qty, avg_price,
                        buy_qty, buy_value, sell_qty, sell_value, realised_pnl,
                        unrealised_pnl, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(row.get("position_id")),
                        str(row.get("symbol") or ""),
                        str(row.get("exchange") or "NSE"),
                        str(row.get("product") or "MIS").upper(),
                        int(row.get("net_qty") or 0),
                        float(row.get("avg_price") or 0.0),
                        int(row.get("buy_qty") or 0),
                        float(row.get("buy_value") or 0.0),
                        int(row.get("sell_qty") or 0),
                        float(row.get("sell_value") or 0.0),
                        float(row.get("realized_pnl") or 0.0),
                        float(row.get("unrealized_pnl") or 0.0),
                        _epoch(row.get("updated_at"), default=now),
                    ),
                )

            for row in trades:
                sqlite.execute(
                    """INSERT INTO trades
                       (trade_id, order_id, symbol, exchange, action, quantity,
                        price, product, strategy, traded_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(row.get("trade_id")),
                        str(row.get("order_id") or row.get("trade_id")),
                        str(row.get("symbol") or ""),
                        str(row.get("exchange") or "NSE"),
                        str(row.get("action") or "BUY").upper(),
                        int(row.get("quantity") or 0),
                        float(row.get("price") or 0.0),
                        str(row.get("product") or "MIS").upper(),
                        str(row.get("strategy") or ""),
                        _epoch(row.get("traded_at"), default=now),
                    ),
                )

            for row in daily_pnl:
                realised = float(row.get("realized_pnl") or 0.0)
                unrealised = float(row.get("unrealized_pnl") or 0.0)
                total = realised + unrealised
                sqlite.execute(
                    """INSERT INTO pnl
                       (session_date, realised_total, unrealised_total, gross_pnl,
                        charges, net_pnl, total_trades, high_water_mark,
                        max_drawdown, updated_at)
                       VALUES (?, ?, ?, ?, 0.0, ?, ?, ?, 0.0, ?)""",
                    (
                        str(row.get("date")),
                        realised,
                        unrealised,
                        total,
                        total,
                        int(row.get("total_trades") or 0),
                        max(total, 0.0),
                        _epoch(row.get("recorded_at"), default=now),
                    ),
                )

            sqlite.execute(
                "INSERT INTO sandbox_migrations (source_key, row_counts, migrated_at) "
                "VALUES (?, ?, ?)",
                (source_key, json.dumps(counts, sort_keys=True), now),
            )
            sqlite.execute("COMMIT")
        except BaseException:
            sqlite.execute("ROLLBACK")
            raise

    archived_to = _archive_legacy(legacy, archive)
    logger.info("Migrated retired Practice sandbox %s to %s", legacy, target)
    return {
        "status": "migrated" if has_legacy_state else "archived-empty",
        "counts": counts,
        "archive_path": str(archived_to),
    }


def _legacy_candidates(workspace: Path, explicit: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    env_path = os.getenv("SANDBOX_ENGINE_DB_PATH")
    if env_path and env_path != ":memory:":
        candidates.append(Path(env_path).expanduser())
    candidates.extend((
        workspace / "data" / "engine-sandbox" / "default.duckdb",
        workspace / "sandbox" / "default.duckdb",
        workspace / "data" / "sandbox.duckdb",
    ))
    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def migrate_workspace(
    workspace_dir: str | os.PathLike[str],
    *,
    legacy_path: str | os.PathLike[str] | None = None,
    state_path: str | os.PathLike[str] | None = None,
) -> list[dict[str, Any]]:
    """Discover and migrate the retired default-account database in a workspace."""
    workspace = Path(workspace_dir).expanduser().resolve()
    target = Path(state_path).expanduser().resolve() if state_path else (
        workspace / "sandbox" / "state.sqlite"
    )
    archive = workspace / "archive" / "migrations"
    explicit = Path(legacy_path).expanduser() if legacy_path else None
    sources = [path for path in _legacy_candidates(workspace, explicit) if path.exists()]
    if not sources:
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(open_sqlite(str(target), durability="normal")) as sqlite:
            ensure_schema(sqlite)
            init_capital(sqlite, 1_000_000.0)
        return [{"status": "no-source", "counts": {}}]
    return [migrate_legacy_sandbox(source, target, archive) for source in sources]
