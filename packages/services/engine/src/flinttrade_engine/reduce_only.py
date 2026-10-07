"""Decide whether a place only reduces an open position.

The place pipeline calls this. A client flag is not an input. Live requires
a readable broker order book. Missing or ambiguous quantity evidence refuses
qualification with a zero cap. These legacy inputs do not establish coherent
account-wide evidence or restart safety. A second exit while one of ours is
already unfilled is refused by the caller.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

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

def exit_already_pending_message(contract: str) -> str:
    """Copy when this desk's exit on ``contract`` is still unfilled.

    The Positions row keeps its Exit pending tag for this case.
    """
    label = str(contract or "").strip() or "this contract"
    return (
        f"Not placed. An exit for {label} is already pending. "
        "Wait for it to fill, or cancel it and try again."
    )


def exit_orders_unreadable_message(contract: str) -> str:
    """Copy when a further exit must wait because the broker book cannot be read."""
    label = str(contract or "").strip() or "this contract"
    return (
        f"Not placed. Broker orders for {label} are unavailable. Reconcile them before another exit."
    )


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
    return True


def _order_id(row: Mapping[str, object]) -> str:
    for name in ("order_id", "orderid", "orderId", "broker_order_id"):
        if name in row and row[name] not in (None, ""):
            return str(row[name]).strip()
    return ""


def _quantity_aliases(
    row: Mapping[str, object], *names: str, default: int | None = None,
) -> int | None:
    """Read agreeing whole-number aliases without a malformed-value fallback."""
    values = []
    for name in names:
        if name not in row:
            continue
        raw = row[name]
        value = _whole(raw)
        if value is None:
            return None
        if isinstance(raw, str):
            try:
                exact = Decimal(raw.strip())
            except InvalidOperation:
                return None
            # Float parsing must not hide a fractional value or round an integer.
            if not exact.is_finite() or exact != value:
                return None
        values.append(value)
    if not values:
        return default
    if any(value != values[0] for value in values):
        return None
    return values[0]


def _text_aliases_agree(row: Mapping[str, object], *names: str) -> bool:
    """Require supplied non-empty aliases to agree after existing normalisation."""
    values = {_norm(row[name]) for name in names if name in row and row[name] not in (None, "")}
    return len(values) <= 1


def _order_identity_aliases_agree(row: Mapping[str, object], order_id: str) -> bool:
    """Require every supplied identity alias to name the same case-sensitive ID."""
    return all(
        not isinstance(row[name], bool)
        and isinstance(row[name], (str, int))
        and str(row[name]).strip() == order_id
        for name in ("order_id", "orderid", "orderId", "broker_order_id") if name in row
    )


def _could_match_contract(row: Mapping[str, object], symbol: str, exchange: str, product: str) -> bool:
    """Do not let an earlier symbol alias hide potentially matching evidence."""
    return (
        any(_norm(row.get(name)) == symbol for name in ("symbol", "trading_symbol", "tradingsymbol"))
        and _row_text(row, "exchange") == exchange
        and (_row_text(row, "product") or "MIS") == product
    )


def _quantity_evidence_is_valid(
    positions: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    exchange: str,
    product: str,
    exit_action: str,
) -> bool:
    """Refuse ambiguous matching exposure, exit quantities or order identity.

    Multiple matching position rows have no uniqueness proof in this interface.
    Copies of an executable exit must agree on their normalised execution
    evidence, including status. A missing filled field counts the entire total
    as remaining; it is not evidence that no fills occurred.
    """
    matching_positions = [
        row for row in positions
        if isinstance(row, Mapping) and _could_match_contract(row, symbol, exchange, product)
    ]
    if len(matching_positions) > 1:
        return False
    for row in matching_positions:
        if (
            not _text_aliases_agree(row, "symbol", "trading_symbol", "tradingsymbol")
            or not _text_aliases_agree(row, "side", "transaction_type", "action")
            or _quantity_aliases(row, "net_qty", "netQty", "net_quantity", "quantity", "qty") is None
        ):
            return False

    by_id: dict[str, list[Mapping[str, object]]] = {}
    executable_ids: set[str] = set()
    for order in orders:
        if not isinstance(order, Mapping):
            continue
        order_id = _order_id(order)
        order_ids = {
            str(order[name]).strip()
            for name in ("order_id", "orderid", "orderId", "broker_order_id")
            if name in order and order[name] not in (None, "")
        }
        order_ids.discard("")
        for identity in order_ids:
            by_id.setdefault(identity, []).append(order)
        if not _could_match_contract(order, symbol, exchange, product):
            continue
        if not _text_aliases_agree(order, "symbol", "trading_symbol", "tradingsymbol"):
            return False
        # An executable row with no confirmed side may be another exit. Validate
        # it before excluding confirmed same-direction orders from exit totals.
        if (
            _order_is_open(order)
            or not _text_aliases_agree(order, "status", "order_status", "orderStatus")
        ) and (
            not _text_aliases_agree(order, "action", "transaction_type")
            or _row_text(order, "action", "transaction_type") not in {"BUY", "SELL"}
        ):
            return False
        if not any(_norm(order.get(name)) == exit_action for name in ("action", "transaction_type")):
            continue
        if (
            not _text_aliases_agree(order, "action", "transaction_type")
            or not _text_aliases_agree(order, "status", "order_status", "orderStatus")
            or (order_ids and not _order_identity_aliases_agree(order, order_id))
        ):
            return False
        if _order_is_open(order):
            if not order_id:
                return False
            executable_ids.add(order_id)

    for order_id in executable_ids:
        evidence = None
        for order in by_id[order_id]:
            if (
                not _text_aliases_agree(order, "symbol", "trading_symbol", "tradingsymbol")
                or not _text_aliases_agree(order, "action", "transaction_type")
                or not _text_aliases_agree(order, "status", "order_status", "orderStatus")
            ):
                return False
            if not _order_identity_aliases_agree(order, order_id):
                return False
            total = _quantity_aliases(order, "quantity", "qty")
            filled = _quantity_aliases(order, "filled_qty", "filled_quantity", "filledQty", "tradedQty", default=0)
            if total is None or total < 0 or filled is None or filled < 0 or filled > total:
                return False
            current = (
                _row_text(order, "symbol", "trading_symbol", "tradingsymbol"),
                _row_text(order, "exchange"),
                _row_text(order, "product") or "MIS",
                _row_text(order, "action", "transaction_type"),
                _row_text(order, "status", "order_status", "orderStatus"),
                total,
                filled,
            )
            if evidence is not None and current != evidence:
                return False
            evidence = current
    return True


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
    not be read, so qualification is refused with a zero cap. Ambiguous
    matching evidence also refuses. ``extra_pending`` is non-negative whole
    in-flight exit quantity reserved by this process and not yet visible on
    a book; it does not establish durable or account-wide coordination.
    """
    empty = ReduceOnlyDecision(False, 0, 0, 0)
    symbol_n = _norm(symbol)
    exchange_n = _norm(exchange)
    product_n = _norm(product) or "MIS"
    action_n = _norm(action)
    if action_n not in {"BUY", "SELL"}:
        return empty
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        return empty
    if isinstance(extra_pending, bool) or not isinstance(extra_pending, int) or extra_pending < 0:
        return empty
    if live and broker_orders is None:
        return empty
    orders = (*our_orders, *broker_orders) if live and broker_orders is not None else our_orders
    if not _quantity_evidence_is_valid(
        positions, orders, symbol=symbol_n, exchange=exchange_n, product=product_n, exit_action=action_n,
    ):
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


def own_exit_already_pending(
    *,
    symbol: str,
    exchange: str,
    product: str,
    action: str,
    positions: Sequence[Mapping[str, object]],
    our_orders: Sequence[Mapping[str, object]],
    extra_pending: int = 0,
) -> bool:
    """True when this order is another exit and one of ours is already unfilled.

    Broker orders are not an input. An unreadable broker book does not
    invent a pending exit, and a broker exit that is not ours does not
    block the remainder on its own.
    """
    symbol_n = _norm(symbol)
    exchange_n = _norm(exchange)
    product_n = _norm(product) or "MIS"
    action_n = _norm(action)
    if action_n not in {"BUY", "SELL"}:
        return False
    net: int | None = None
    for row in positions:
        if not isinstance(row, Mapping) or not _same_contract(row, symbol_n, exchange_n, product_n):
            continue
        net = _position_quantity(row)
        break
    if net is None or net == 0:
        return False
    exit_action = "SELL" if net > 0 else "BUY"
    if action_n != exit_action:
        return False
    pending = pending_exit_quantity(
        our_orders,
        symbol=symbol_n,
        exchange=exchange_n,
        product=product_n,
        exit_action=exit_action,
    )
    if extra_pending > 0:
        pending += extra_pending
    return pending > 0


ContractKey = tuple[str, str, str, str, str, str]


def contract_key(
    *,
    mode: str,
    adapter: str,
    account: str,
    symbol: str,
    exchange: str,
    product: str,
) -> ContractKey:
    """Identity of one contract for the reduce-only lock and reservation.

    ``adapter`` is its own slot. Two brokers that both use account ``default``
    do not share a reservation.
    """
    from flinttrade_core.broker_identity import BrokerSelector  # noqa: PLC0415

    # Account IDs are opaque. Validate before using a lock/store key; never
    # trim, case-fold or turn a malformed supplied ID into another account.
    selector = BrokerSelector(str(adapter).strip().lower(), account)
    return (
        _norm(mode),
        _norm(selector.adapter_id),
        selector.account_id,
        _norm(symbol),
        _norm(exchange),
        _norm(product) or "MIS",
    )


@dataclass(frozen=True, slots=True)
class _BoundExit:
    """One successful reduce-only place still holding reserved quantity."""

    order_id: str
    quantity: int
    position_net: int
    covered: bool = False


_lock_guard = threading.Lock()
_contract_locks: dict[ContractKey, threading.Lock] = {}
_reserved: dict[ContractKey, int] = {}
_bound_exits: dict[ContractKey, list[_BoundExit]] = {}


def contract_lock(key: ContractKey) -> threading.Lock:
    """Return the lock that serialises reduce-only decisions for one contract."""
    with _lock_guard:
        lock = _contract_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _contract_locks[key] = lock
        return lock


def reserved_exit(key: ContractKey) -> int:
    """In-flight reduce-only quantity not yet released for ``key``."""
    with _lock_guard:
        return _reserved.get(key, 0)


def reserve_exit(key: ContractKey, quantity: int) -> None:
    """Hold ``quantity`` against the cap until the place finishes or is visible."""
    if quantity < 1:
        return
    with _lock_guard:
        _reserved[key] = _reserved.get(key, 0) + quantity


def release_exit(key: ContractKey, quantity: int) -> None:
    """Return a reserved exit quantity to the cap."""
    if quantity < 1:
        return
    with _lock_guard:
        left = _reserved.get(key, 0) - quantity
        if left <= 0:
            _reserved.pop(key, None)
        else:
            _reserved[key] = left


def cover_reserved_exit(
    key: ContractKey, orders: Sequence[Mapping[str, object]], *, position_net: int,
) -> None:
    """Cover only exact scoped acknowledged observations, never book totals."""
    reconcile_reserved_exit(key, orders=orders, position_net=position_net)


def note_reserved_order(
    key: ContractKey,
    order_id: str,
    quantity: int,
    position_net: int,
) -> None:
    """Remember an ACK or uncertain invocation against its existing local hold.

    An empty ID is unresolved, not evidence of non-execution. Position movement
    and unrelated book totals cannot identify or release any such hold.
    """
    if quantity < 1:
        return
    bound = _BoundExit(str(order_id or "").strip(), quantity, position_net)
    with _lock_guard:
        _bound_exits.setdefault(key, []).append(bound)


def _bound_exit_observation(
    key: ContractKey, item: _BoundExit, orders: Sequence[Mapping[str, object]],
) -> str | None:
    """Return a coherent exact ACK's lifecycle state, or no coverage proof."""
    if not item.order_id:
        return None
    rows = [row for row in orders if isinstance(row, Mapping) and any(
        type(row.get(name)) is str and row[name] == item.order_id
        for name in ("order_id", "orderid", "orderId", "broker_order_id")
    )]
    if not rows:
        return None
    _mode, adapter, account, symbol, exchange, product = key
    action = "SELL" if item.position_net > 0 else "BUY"
    observed = None
    for row in rows:
        if (
            not _same_contract(row, symbol, exchange, product)
            or _row_text(row, "action", "transaction_type") != action
            or not all(_text_aliases_agree(row, *names) for names in (
                ("symbol", "trading_symbol", "tradingsymbol"), ("action", "transaction_type"),
                ("status", "order_status", "orderStatus"),
            ))
            or not all(type(row[name]) is str and row[name] == item.order_id for name in (
                "order_id", "orderid", "orderId", "broker_order_id",
            ) if name in row)
            or any(row[name] != account for name in ("account_id", "accountId") if name in row)
            or any(_norm(row[name]) != adapter for name in ("broker", "broker_id", "adapter_id") if name in row)
        ):
            return None
        total = _quantity_aliases(row, "quantity", "qty")
        filled = _quantity_aliases(row, "filled_qty", "filled_quantity", "filledQty", "tradedQty", default=0)
        status = _row_text(row, "status", "order_status", "orderStatus")
        if total is None or total != item.quantity or filled is None or not 0 <= filled <= total:
            return None
        if status in {"COMPLETE", "COMPLETED", "FILLED", "TRADED"} and any(
            name in row for name in ("filled_qty", "filled_quantity", "filledQty", "tradedQty")
        ) and filled != total:
            # An explicit partial/unfilled quantity contradicts full completion.
            # No terminal coverage proof may come from this inconsistent row.
            return None
        # Unknown lifecycle state is still possible exposure, not permission
        # to transfer a hold. Missing fills on an open row count its full total.
        if status not in _EXIT_OPEN | _EXIT_CLOSED | {
            "CANCEL_PENDING", "CANCEL_REQUESTED", "CANCEL PENDING", "PENDING_CANCEL",
        }:
            return None
        current = (status, total, filled)
        if observed is not None and current != observed:
            return None
        observed = current
    return observed[0] if observed is not None else None


def reconcile_reserved_exit(
    key: ContractKey,
    *,
    orders: Sequence[Mapping[str, object]] | None,
    position_net: int,
) -> None:
    """Reconcile existing process-local holds against exact single ACKs only.

    A coherent scoped open row represents that exact hold on this read; a
    coherent terminal row terminates it. If representation disappears or turns
    malformed, restore the local hold. Missing/unknown IDs and aggregate
    position movement are never coverage proof. Call under ``contract_lock``;
    these observations establish neither provider coherence nor restart safety.
    """
    with _lock_guard:
        bound = list(_bound_exits.get(key, ()))
    kept: list[_BoundExit] = []
    for item in bound:
        status = _bound_exit_observation(key, item, orders) if orders is not None else None
        if status in _EXIT_CLOSED:
            if not item.covered:
                release_exit(key, item.quantity)
            continue
        covered = status is not None
        if covered and not item.covered:
            release_exit(key, item.quantity)
        elif not covered and item.covered:
            reserve_exit(key, item.quantity)
        kept.append(replace(item, covered=covered))
    with _lock_guard:
        if kept:
            _bound_exits[key] = kept
        else:
            _bound_exits.pop(key, None)


def reset_reduce_only_for_tests() -> None:
    """Drop in-flight reservations. Locks stay so a waiter cannot miss one."""
    with _lock_guard:
        _reserved.clear()
        _bound_exits.clear()
