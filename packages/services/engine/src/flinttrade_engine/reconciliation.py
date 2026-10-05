"""Read-only comparison of native broker snapshots and local observations.

Comparison uses immutable normalised rows and a deterministic union of keys.
It never repairs positions or submits orders; callers own any admitted action.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Awaitable, Callable

logger = logging.getLogger("flinttrade.engine.reconciliation")


class MismatchKind(StrEnum):
    MISSING_IN_LOCAL = "missing_in_local"
    MISSING_IN_BROKER = "missing_in_broker"
    QUANTITY_MISMATCH = "quantity_mismatch"
    STATUS_MISMATCH = "status_mismatch"
    PRICE_MISMATCH = "price_mismatch"
    CLOSED_MANUAL = "closed_manual"


@dataclass
class Mismatch:
    kind: MismatchKind
    symbol: str = ""
    order_id: str = ""
    broker_value: Any = None
    local_value: Any = None
    detail: str = ""

    def __str__(self) -> str:
        values = {"symbol": self.symbol, "order_id": self.order_id,
                  "broker": self.broker_value, "local": self.local_value}
        fields = [f"{key}={value!r}" for key, value in values.items() if value is not None and value != ""]
        return " | ".join([self.kind.value, *fields, *([self.detail] if self.detail else [])])


@dataclass
class ReconciliationResult:
    mismatches: list[Mismatch] = field(default_factory=list)
    checked_count: int = 0
    error: str = ""

    @property
    def has_mismatches(self) -> bool:
        return bool(self.mismatches)

    @property
    def clean(self) -> bool:
        return not (self.mismatches or self.error)

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)

    def summary(self) -> str:
        if self.error:
            return f"comparison unavailable: {self.error}"
        counts = Counter(item.kind.value for item in self.mismatches)
        details = ", ".join(f"{kind}={count}" for kind, count in sorted(counts.items()))
        return (f"{self.mismatch_count} mismatch(es) in {self.checked_count} items: {details}"
                if counts else f"clean — {self.checked_count} items checked")


def _field(row: Any, *names: str, default: Any = "") -> Any:
    for name in names:
        value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
        if value is not None and value != "":
            return value
    return default


def _number(row: Any, *names: str) -> float:
    raw = _field(row, *names, default=0)
    if isinstance(raw, bool):
        raise ValueError("snapshot contains an invalid number")
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("snapshot contains an invalid number") from exc
    if not math.isfinite(value):
        raise ValueError("snapshot contains a non-finite number")
    return value


def _quantity(row: Any) -> int:
    raw = _field(row, "quantity", "qty", default=0)
    if isinstance(raw, bool):
        raise ValueError("snapshot quantity must be an integer")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("snapshot quantity must be an integer") from exc
    if not value.is_finite() or value != value.to_integral_value():
        raise ValueError("snapshot quantity must be a finite integer")
    return int(value)


@dataclass(frozen=True)
class _Observation:
    identity: str
    symbol: str
    quantity: int
    price: float = 0.0
    status: str = ""


def _project(rows: list[Any], *, positions: bool) -> dict[str, _Observation]:
    projected: dict[str, _Observation] = {}
    for row in rows:
        symbol = str(_field(row, "symbol")).strip().upper()
        if positions:
            if not symbol:
                raise ValueError("snapshot position requires a symbol")
            parts = (symbol, str(_field(row, "exchange")).upper(), str(_field(row, "product")).upper())
            identity = ":".join(parts)
        else:
            identity = str(_field(row, "orderid", "order_id")).strip()
            if not identity:
                raise ValueError("snapshot order requires an order identity")
        if identity in projected:
            raise ValueError("snapshot contains a duplicate position or order identity")
        projected[identity] = _Observation(
            identity=identity, symbol=symbol, quantity=_quantity(row),
            price=_number(row, "average_price", "avg_price") if positions else 0.0,
            status="" if positions else str(_field(row, "status")).upper(),
        )
    return projected


class ReconciliationEngine:
    """Compare admitted snapshots using caller-selected price tolerance."""

    def __init__(self, price_tolerance_pct: float = 0.1) -> None:
        if not math.isfinite(price_tolerance_pct) or price_tolerance_pct < 0:
            raise ValueError("price tolerance must be finite and non-negative")
        self._price_tol = price_tolerance_pct / 100

    def _compare(self, broker: list[Any], local: list[Any], *, positions: bool) -> ReconciliationResult:
        actual, recorded = _project(broker, positions=positions), _project(local, positions=positions)
        result = ReconciliationResult(checked_count=len(actual))
        terminal = {"COMPLETE", "CANCELLED", "REJECTED", "EXPIRED"}
        for identity in sorted(actual.keys() | recorded.keys()):
            left, right = actual.get(identity), recorded.get(identity)
            label = {"symbol": (left or right).symbol} if positions else {"order_id": identity}
            if left is None:
                if positions and right.quantity:
                    result.mismatches.append(Mismatch(MismatchKind.CLOSED_MANUAL, **label,
                                                       local_value=right.quantity, detail=f"key={identity}"))
                elif not positions and right.status not in terminal:
                    result.mismatches.append(Mismatch(MismatchKind.MISSING_IN_BROKER, **label,
                                                       local_value=right.status))
                continue
            if right is None:
                result.mismatches.append(Mismatch(MismatchKind.MISSING_IN_LOCAL, **label,
                                                   broker_value=left.quantity if positions else left.status,
                                                   detail=f"key={identity}"))
                continue
            comparisons = [(MismatchKind.QUANTITY_MISMATCH, left.quantity, right.quantity)]
            if not positions:
                comparisons.insert(0, (MismatchKind.STATUS_MISMATCH, left.status, right.status))
            for kind, expected, observed in comparisons:
                if expected != observed:
                    result.mismatches.append(Mismatch(kind, **label, broker_value=expected, local_value=observed))
            if positions and left.quantity == right.quantity != 0 and left.price > 0 and right.price > 0:
                difference = abs(left.price - right.price) / left.price
                if difference > self._price_tol:
                    result.mismatches.append(Mismatch(MismatchKind.PRICE_MISMATCH, **label,
                                                       broker_value=left.price, local_value=right.price,
                                                       detail=f"difference={difference:.6f}"))
        logger.log(logging.INFO if result.clean else logging.WARNING, "%s", result.summary())
        return result

    def reconcile_positions(self, broker_positions: list[Any], local_positions: list[Any]) -> ReconciliationResult:
        return self._compare(broker_positions, local_positions, positions=True)

    def reconcile_orders(self, broker_orders: list[Any], local_orders: list[Any]) -> ReconciliationResult:
        return self._compare(broker_orders, local_orders, positions=False)


class BackgroundReconciler:
    """Poll injected, account-bound readers and emit observation callbacks.

    The caller supplies broker authority. Failed reads are unavailable results,
    never empty successful broker snapshots. Cancellation does not emit closes.
    """

    def __init__(
        self,
        get_broker_positions: Callable[[], Awaitable[list[Any]]],
        get_local_positions: Callable[[], list[Any] | Awaitable[list[Any]]],
        on_closed_manual: Callable[[str, int], Awaitable[None]] | None = None,
        interval_seconds: int = 60,
        price_tolerance_pct: float = 0.1,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("reconciliation interval must be positive")
        self._get_broker, self._get_local = get_broker_positions, get_local_positions
        self._on_closed_manual, self._interval = on_closed_manual, interval_seconds
        self._engine = ReconciliationEngine(price_tolerance_pct)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if not self.is_running:
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="flinttrade.reconciliation")

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            while self.is_running:
                await self._run_once()
                await asyncio.sleep(self._interval)
        finally:
            self._running = False

    async def _run_once(self) -> ReconciliationResult:
        try:
            broker = await self._get_broker()
            local = self._get_local()
            if inspect.isawaitable(local):
                local = await local
            result = self._engine.reconcile_positions(broker, local)
        except Exception as exc:
            logger.warning("Snapshot comparison unavailable: %s", type(exc).__name__)
            return ReconciliationResult(error="snapshot read or validation failed")
        if self._on_closed_manual is not None:
            for mismatch in result.mismatches:
                if mismatch.kind is MismatchKind.CLOSED_MANUAL:
                    try:
                        await self._on_closed_manual(mismatch.symbol, int(mismatch.local_value))
                    except Exception:
                        logger.exception("External close observation callback failed")
        return result
