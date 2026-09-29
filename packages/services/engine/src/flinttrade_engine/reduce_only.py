"""Decide whether a place only reduces an open position.

The place pipeline calls this. A client flag is not an input. Live also
counts the broker order book. When that book cannot be read, the order
does not qualify and the caller runs a full admit.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_EXIT_OPEN = frozenset({
    "PENDING",
    "OPEN",
    "TRIGGER PENDING",
    "TRIGGER_PENDING",
    "VALIDATION PENDING",
    "OPEN PENDING",
    "MODIFY PENDING",
    "MODIFICATION PENDING",
    "AMO REQ RECEIVED",
    "PUT ORDER REQ RECEIVED",
    "AFTER MARKET ORDER REQ RECEIVED",
})
_EXIT_CLOSED = frozenset({
    "COMPLETE",
    "COMPLETED",
    "FILLED",
    "CANCELLED",
    "CANCELED",
    "REJECTED",
    "TRADED",
    "EXPIRED",
})


@dataclass(frozen=True, slots=True)
class ReduceOnlyDecision:
    """Whether one place is only a reduction of an open position.

    Attributes:
        qualifies: True when the order is the opposite side and within the cap.
        open_quantity: Absolute open quantity on the contract. ``0`` when none.
        pending_exits: Unfilled opposite quantity already counted against the cap.
        cap: Quantity still allowed as a reduce-only exit.
    """

    qualifies: bool
    open_quantity: int
    pending_exits: int
    cap: int


def _norm(value: object) -> str:
    return str(value or "").strip().upper()


def _whole(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if not number.is_integer():
            return None
        return int(number)
    return None


def _row_text(row: Mapping[str, object], *names: str) -> str:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return _norm(row[name])
    return ""


def _same_contract(row: Mapping[str, object], symbol: str, exchange: str, product: str) -> bool:
    row_product = _row_text(row, "product") or "MIS"
    return (
        _row_text(row, "symbol", "trading_symbol", "tradingsymbol") == symbol
        and _row_text(row, "exchange") == exchange
        and row_product == product
    )


def _position_quantity(row: Mapping[str, object]) -> int | None:
    raw = None
    for name in ("net_qty", "netQty", "net_quantity", "quantity", "qty"):
        if name in row and row[name] not in (None, ""):
            raw = row[name]
            break
    qty = _whole(raw)
    if qty is None:
        return None
    side = _row_text(row, "side", "transaction_type", "action")
    if side == "SELL" and qty > 0 and "net_qty" not in row and "netQty" not in row and "net_quantity" not in row:
        return -qty
    return qty


def _remaining_quantity(row: Mapping[str, object]) -> int:
    quantity = _whole(row.get("quantity") if "quantity" in row else row.get("qty"))
    if quantity is None or quantity < 1:
        return 0
    filled_raw = None
    for name in ("filled_qty", "filled_quantity", "filledQty", "tradedQty"):
        if name in row and row[name] not in (None, ""):
            filled_raw = row[name]
            break
    filled = _whole(filled_raw) if filled_raw is not None else 0
    if filled is None or filled < 0:
        filled = 0
    remaining = quantity - filled
    return max(0, remaining)


def _order_is_open(row: Mapping[str, object]) -> bool:
    status = _row_text(row, "status", "order_status", "orderStatus")
    if not status:
        return True
    if status in _EXIT_CLOSED:
        return False
    if status in _EXIT_OPEN:
        return True
    return "CANCEL" not in status and "REJECT" not in status and "COMPLETE" not in status


def _order_id(row: Mapping[str, object]) -> str:
    for name in ("order_id", "orderid", "orderId", "broker_order_id"):
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
    return ""


def pending_exit_quantity(
    orders: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    exchange: str,
    product: str,
    exit_action: str,
    seen_ids: set[str] | None = None,
) -> int:
    """Sum unfilled opposite quantity on one contract.

    Orders whose id was already counted are skipped, so a broker row that
    repeats one of our own orders is not added twice.
    """
    seen = seen_ids if seen_ids is not None else set()
    total = 0
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        if not _same_contract(order, symbol, exchange, product):
            continue
        action = _row_text(order, "action", "transaction_type")
        if action != exit_action:
            continue
        if not _order_is_open(order):
            continue
        order_id = _order_id(order)
        if order_id and order_id in seen:
            continue
        if order_id:
            seen.add(order_id)
        total += _remaining_quantity(order)
    return total


def classify_reduce_only(
    *,
    symbol: str,
    exchange: str,
    product: str,
    action: str,
    quantity: int,
    positions: Sequence[Mapping[str, object]],
    our_orders: Sequence[Mapping[str, object]],
    broker_orders: Sequence[Mapping[str, object]] | None,
    live: bool,
    extra_pending: int = 0,
) -> ReduceOnlyDecision:
    """Return whether this order only reduces one open contract.

    ``broker_orders is None`` on a live order means the broker book could
    not be read. The order does not qualify. ``extra_pending`` is in-flight
    exit quantity reserved by this process and not yet visible on a book.
    """
    empty = ReduceOnlyDecision(False, 0, 0, 0)
    if live and broker_orders is None:
        return empty
    symbol_n = _norm(symbol)
    exchange_n = _norm(exchange)
    product_n = _norm(product) or "MIS"
    action_n = _norm(action)
    if action_n not in {"BUY", "SELL"}:
        return empty
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        return empty

    net: int | None = None
    for row in positions:
        if not isinstance(row, Mapping) or not _same_contract(row, symbol_n, exchange_n, product_n):
            continue
        net = _position_quantity(row)
        break
    if net is None or net == 0:
        return empty
    exit_action = "SELL" if net > 0 else "BUY"
    if action_n != exit_action:
        return empty
    open_quantity = abs(net)
    seen: set[str] = set()
    pending = pending_exit_quantity(
        our_orders,
        symbol=symbol_n,
        exchange=exchange_n,
        product=product_n,
        exit_action=exit_action,
        seen_ids=seen,
    )
    if live and broker_orders is not None:
        pending += pending_exit_quantity(
            broker_orders,
            symbol=symbol_n,
            exchange=exchange_n,
            product=product_n,
            exit_action=exit_action,
            seen_ids=seen,
        )
    if extra_pending > 0:
        pending += extra_pending
    cap = open_quantity - pending
    if cap < 1 or quantity > cap:
        return ReduceOnlyDecision(False, open_quantity, pending, max(cap, 0))
    return ReduceOnlyDecision(True, open_quantity, pending, cap)


def contract_key(
    *,
    mode: str,
    account: str,
    symbol: str,
    exchange: str,
    product: str,
) -> tuple[str, str, str, str, str]:
    """Identity of one contract for the reduce-only lock and reservation."""
    return (
        _norm(mode),
        _norm(account) or "default",
        _norm(symbol),
        _norm(exchange),
        _norm(product) or "MIS",
    )


_lock_guard = threading.Lock()
_contract_locks: dict[tuple[str, str, str, str, str], threading.Lock] = {}
_reserved: dict[tuple[str, str, str, str, str], int] = {}


def contract_lock(key: tuple[str, str, str, str, str]) -> threading.Lock:
    """Return the lock that serialises reduce-only decisions for one contract."""
    with _lock_guard:
        lock = _contract_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _contract_locks[key] = lock
        return lock


def reserved_exit(key: tuple[str, str, str, str, str]) -> int:
    """In-flight reduce-only quantity not yet released for ``key``."""
    with _lock_guard:
        return _reserved.get(key, 0)


def reserve_exit(key: tuple[str, str, str, str, str], quantity: int) -> None:
    """Hold ``quantity`` against the cap until the place finishes or is visible."""
    if quantity < 1:
        return
    with _lock_guard:
        _reserved[key] = _reserved.get(key, 0) + quantity


def release_exit(key: tuple[str, str, str, str, str], quantity: int) -> None:
    """Return a reserved exit quantity to the cap."""
    if quantity < 1:
        return
    with _lock_guard:
        left = _reserved.get(key, 0) - quantity
        if left <= 0:
            _reserved.pop(key, None)
        else:
            _reserved[key] = left


def cover_reserved_exit(key: tuple[str, str, str, str, str], covered: int) -> None:
    """Drop reserved quantity the broker book already shows as an open exit."""
    if covered < 1:
        return
    release_exit(key, covered)


def reset_reduce_only_for_tests() -> None:
    """Drop in-flight reservations. Locks stay so a waiter cannot miss one."""
    with _lock_guard:
        _reserved.clear()
