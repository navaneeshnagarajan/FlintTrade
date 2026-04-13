"""Reconciliation engine — compare broker state vs local state to detect drift.

Absorbed from openalgo-execution-system audit: in live trading, the local
in-memory view of positions and orders can diverge from the broker's actual
state due to network failures, race conditions, partial fills, or broker-side
modifications. Detecting this drift early prevents acting on stale data.

The :class:`ReconciliationEngine` is designed to run periodically (e.g., every
30 seconds or on reconnect) and reports mismatches without taking action —
resolution is left to the caller or a higher-level recovery strategy.

The :class:`BackgroundReconciler` wraps :class:`ReconciliationEngine` in an
asyncio task that polls every 60 s and logs all discrepancies.  It also
detects :data:`MismatchKind.CLOSED_MANUAL` — positions that were open in the
local DB but have disappeared from the broker's positionbook (externally
closed by the trader or broker system).

Typical usage::

    engine = ReconciliationEngine()
    result = engine.reconcile_positions(broker_positions, local_positions)
    if result.has_mismatches:
        for m in result.mismatches:
            logger.warning("Drift: %s", m)

Background reconciliation::

    reconciler = BackgroundReconciler(
        openalgo_client=client,
        get_local_positions=my_store.get_positions,
    )
    await reconciler.start()          # fire-and-forget asyncio task
    # ...
    await reconciler.stop()
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Coroutine

logger = logging.getLogger("flinttrade.engine.reconciliation")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class MismatchKind(StrEnum):
    """The type of discrepancy found during reconciliation."""

    MISSING_IN_LOCAL = "missing_in_local"
    """Broker has a position/order that local state does not know about."""

    MISSING_IN_BROKER = "missing_in_broker"
    """Local state has a position/order the broker does not recognise."""

    QUANTITY_MISMATCH = "quantity_mismatch"
    """Both sides know the symbol/order but disagree on quantity."""

    STATUS_MISMATCH = "status_mismatch"
    """Both sides know the order but disagree on its status."""

    PRICE_MISMATCH = "price_mismatch"
    """Both sides agree on quantity but differ on average price beyond tolerance."""

    CLOSED_MANUAL = "closed_manual"
    """Position was open in local state but broker reports zero or missing quantity —
    the position was closed externally (manually by the trader or by the broker's
    risk system).  Absorbed from openalgo-execution-system reconciliation loop."""


@dataclass
class Mismatch:
    """A single reconciliation discrepancy."""

    kind: MismatchKind
    symbol: str = ""
    order_id: str = ""
    broker_value: Any = None
    local_value: Any = None
    detail: str = ""

    def __str__(self) -> str:
        parts = [self.kind.value]
        if self.symbol:
            parts.append(f"symbol={self.symbol}")
        if self.order_id:
            parts.append(f"order_id={self.order_id}")
        if self.broker_value is not None:
            parts.append(f"broker={self.broker_value!r}")
        if self.local_value is not None:
            parts.append(f"local={self.local_value!r}")
        if self.detail:
            parts.append(self.detail)
        return " | ".join(parts)


@dataclass
class ReconciliationResult:
    """The outcome of a single reconciliation pass.

    Attributes:
        mismatches:    List of detected discrepancies.
        checked_count: How many items were compared on the broker side.
        clean:         True if zero mismatches were found.
    """

    mismatches: list[Mismatch] = field(default_factory=list)
    checked_count: int = 0

    @property
    def has_mismatches(self) -> bool:
        """True if any discrepancy was detected."""
        return bool(self.mismatches)

    @property
    def clean(self) -> bool:
        """True when broker and local state are fully aligned."""
        return not self.mismatches

    @property
    def mismatch_count(self) -> int:
        """Number of discrepancies found."""
        return len(self.mismatches)

    def summary(self) -> str:
        """One-line summary suitable for logging."""
        if self.clean:
            return f"clean — {self.checked_count} items checked"
        kinds = {}
        for m in self.mismatches:
            kinds[m.kind] = kinds.get(m.kind, 0) + 1
        detail = ", ".join(f"{k}={v}" for k, v in kinds.items())
        return f"{self.mismatch_count} mismatch(es) in {self.checked_count} items: {detail}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    """Parse a quantity that may arrive as str, int, or float."""
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a price that may arrive as str or float."""
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _position_key(pos: Any) -> str:
    """Derive a unique key for a position dict or Position model."""
    if isinstance(pos, dict):
        sym = pos.get("symbol", "")
        exch = pos.get("exchange", "")
        prod = pos.get("product", "")
    else:
        # Pydantic Position model or duck-typed object
        sym = getattr(pos, "symbol", "")
        exch = getattr(pos, "exchange", "")
        prod = getattr(pos, "product", "")
    return f"{sym}:{exch}:{prod}".upper()


def _order_key(order: Any) -> str:
    """Derive a unique key for an order, preferring order_id."""
    if isinstance(order, dict):
        return str(order.get("orderid") or order.get("order_id") or "")
    return str(getattr(order, "orderid", "") or getattr(order, "order_id", ""))


def _order_status(order: Any) -> str:
    if isinstance(order, dict):
        return str(order.get("status", "")).upper()
    return str(getattr(order, "status", "")).upper()


def _order_qty(order: Any) -> int:
    if isinstance(order, dict):
        raw = order.get("quantity") or order.get("qty") or "0"
    else:
        raw = getattr(order, "quantity", "0") or getattr(order, "qty", "0")
    return _safe_int(raw)


def _position_qty(pos: Any) -> int:
    if isinstance(pos, dict):
        raw = pos.get("quantity") or pos.get("qty") or "0"
    else:
        raw = getattr(pos, "quantity", "0") or getattr(pos, "qty", "0")
    return _safe_int(raw)


def _position_avg_price(pos: Any) -> float:
    if isinstance(pos, dict):
        raw = pos.get("average_price") or pos.get("avg_price") or "0"
    else:
        raw = getattr(pos, "average_price", "0") or getattr(pos, "avg_price", "0")
    return _safe_float(raw)


# ---------------------------------------------------------------------------
# ReconciliationEngine
# ---------------------------------------------------------------------------


class ReconciliationEngine:
    """Compares broker state vs local state to detect drift.

    All methods are synchronous and stateless — they operate purely on the
    lists passed in and return a :class:`ReconciliationResult`. The engine
    does NOT call any broker APIs or mutate any state.

    Args:
        price_tolerance_pct: Maximum allowed % difference in average price
            before a PRICE_MISMATCH is raised.  Default is 0.1 % (i.e. one
            basis point of slippage is acceptable, 10 bps triggers a flag).
    """

    def __init__(self, price_tolerance_pct: float = 0.1) -> None:
        self._price_tol = price_tolerance_pct / 100.0  # convert to fraction

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile_positions(
        self,
        broker_positions: list[Any],
        local_positions: list[Any],
    ) -> ReconciliationResult:
        """Compare broker position list vs local position list.

        Checks:
        - Positions present on broker but missing locally.
        - Positions present locally but missing from broker.
        - Quantity mismatches for positions present on both sides.
        - Average price mismatches beyond ``price_tolerance_pct``.

        Args:
            broker_positions: Live position list from the broker (dicts or
                Pydantic :class:`~packages.core.src.models.Position` objects).
            local_positions:  Local in-memory position list (same shapes).

        Returns:
            :class:`ReconciliationResult` describing any discrepancies found.
        """
        result = ReconciliationResult()
        mismatches: list[Mismatch] = []

        broker_map: dict[str, Any] = {_position_key(p): p for p in broker_positions}
        local_map: dict[str, Any] = {_position_key(p): p for p in local_positions}
        result.checked_count = len(broker_map)

        # 1. Present in broker, missing locally
        for key, bp in broker_map.items():
            sym = key.split(":")[0]
            if key not in local_map:
                mismatches.append(Mismatch(
                    kind=MismatchKind.MISSING_IN_LOCAL,
                    symbol=sym,
                    broker_value=_position_qty(bp),
                    detail=f"key={key}",
                ))
                continue

            lp = local_map[key]
            bq = _position_qty(bp)
            lq = _position_qty(lp)

            # 2. Quantity mismatch
            if bq != lq:
                mismatches.append(Mismatch(
                    kind=MismatchKind.QUANTITY_MISMATCH,
                    symbol=sym,
                    broker_value=bq,
                    local_value=lq,
                ))

            # 3. Average price mismatch (only when both have non-zero quantity)
            elif bq != 0:
                bp_price = _position_avg_price(bp)
                lp_price = _position_avg_price(lp)
                if bp_price > 0 and lp_price > 0:
                    diff_pct = abs(bp_price - lp_price) / bp_price
                    if diff_pct > self._price_tol:
                        mismatches.append(Mismatch(
                            kind=MismatchKind.PRICE_MISMATCH,
                            symbol=sym,
                            broker_value=bp_price,
                            local_value=lp_price,
                            detail=f"diff={diff_pct*100:.3f}%",
                        ))

        # 4. Present locally, missing from broker — distinguish CLOSED_MANUAL
        for key, lp in local_map.items():
            sym = key.split(":")[0]
            if key not in broker_map:
                lq = _position_qty(lp)
                # Ignore stale zero-quantity local positions — these are
                # expected after a position is closed.
                if lq == 0:
                    continue

                # Non-zero local position not found in broker positionbook —
                # the position was closed externally (manually or by broker
                # risk system).  Absorbed from openalgo-execution-system.
                mismatches.append(Mismatch(
                    kind=MismatchKind.CLOSED_MANUAL,
                    symbol=sym,
                    local_value=lq,
                    detail=f"key={key} — position closed externally",
                ))

        result.mismatches = mismatches
        if mismatches:
            logger.warning(
                "Position reconciliation found %d mismatch(es): %s",
                len(mismatches),
                result.summary(),
            )
        else:
            logger.info("Position reconciliation clean — %d positions checked", result.checked_count)

        return result

    def reconcile_orders(
        self,
        broker_orders: list[Any],
        local_orders: list[Any],
    ) -> ReconciliationResult:
        """Compare broker order list vs local order list.

        Checks:
        - Orders present on broker but missing locally (by order_id).
        - Orders present locally but missing from broker.
        - Status mismatches for orders present on both sides.
        - Quantity mismatches.

        Args:
            broker_orders: Live order list from the broker (dicts or Pydantic
                :class:`~packages.core.src.models.OrderStatus` objects).
            local_orders:  Local in-memory order list (same shapes).

        Returns:
            :class:`ReconciliationResult` describing any discrepancies found.
        """
        result = ReconciliationResult()
        mismatches: list[Mismatch] = []

        broker_map: dict[str, Any] = {}
        for o in broker_orders:
            k = _order_key(o)
            if k:
                broker_map[k] = o

        local_map: dict[str, Any] = {}
        for o in local_orders:
            k = _order_key(o)
            if k:
                local_map[k] = o

        result.checked_count = len(broker_map)

        # 1. Present in broker, missing locally
        for oid, bo in broker_map.items():
            if oid not in local_map:
                mismatches.append(Mismatch(
                    kind=MismatchKind.MISSING_IN_LOCAL,
                    order_id=oid,
                    broker_value=_order_status(bo),
                ))
                continue

            lo = local_map[oid]
            b_status = _order_status(bo)
            l_status = _order_status(lo)
            b_qty = _order_qty(bo)
            l_qty = _order_qty(lo)

            # 2. Status mismatch
            if b_status != l_status:
                mismatches.append(Mismatch(
                    kind=MismatchKind.STATUS_MISMATCH,
                    order_id=oid,
                    broker_value=b_status,
                    local_value=l_status,
                ))

            # 3. Quantity mismatch
            if b_qty != l_qty:
                mismatches.append(Mismatch(
                    kind=MismatchKind.QUANTITY_MISMATCH,
                    order_id=oid,
                    broker_value=b_qty,
                    local_value=l_qty,
                ))

        # 4. Present locally, missing from broker
        for oid in local_map:
            if oid not in broker_map:
                l_status = _order_status(local_map[oid])
                # Only flag open orders — completed/cancelled orders
                # being absent from broker is expected after archival.
                if l_status not in ("COMPLETE", "CANCELLED", "REJECTED", "EXPIRED"):
                    mismatches.append(Mismatch(
                        kind=MismatchKind.MISSING_IN_BROKER,
                        order_id=oid,
                        local_value=l_status,
                    ))

        result.mismatches = mismatches
        if mismatches:
            logger.warning(
                "Order reconciliation found %d mismatch(es): %s",
                len(mismatches),
                result.summary(),
            )
        else:
            logger.info("Order reconciliation clean — %d orders checked", result.checked_count)

        return result


# ---------------------------------------------------------------------------
# BackgroundReconciler — async periodic background check
# ---------------------------------------------------------------------------


class BackgroundReconciler:
    """Runs :class:`ReconciliationEngine` as a periodic asyncio background task.

    Polls every :attr:`interval_seconds` (default 60), fetches live broker
    positions, compares against the locally tracked state, and logs all
    discrepancies.  Specially highlights :data:`MismatchKind.CLOSED_MANUAL`
    events — positions closed externally without FlintTrade's knowledge.

    Absorbed from the 60-second reconciliation loop in
    ``openalgo-execution-system/backend/engine/reconciliation.py``.

    Args:
        get_broker_positions:  Async callable returning the live broker
            position list (dicts or Pydantic models).
        get_local_positions:   Sync or async callable returning the local
            in-memory position list.
        on_closed_manual:      Optional async callback invoked with
            ``(symbol, local_qty)`` whenever a CLOSED_MANUAL event is detected.
            Use this to update your DB or notify strategies.
        interval_seconds:      Polling interval in seconds.  Default 60.
        price_tolerance_pct:   Passed to :class:`ReconciliationEngine`.

    Example::

        async def fetch_broker():
            resp = await client.positionbook()
            return resp.get("data", [])

        reconciler = BackgroundReconciler(
            get_broker_positions=fetch_broker,
            get_local_positions=my_store.positions,
            on_closed_manual=handle_closed_manual,
        )
        await reconciler.start()
    """

    def __init__(
        self,
        get_broker_positions: Callable[[], Coroutine[Any, Any, list[Any]]],
        get_local_positions: Callable[[], list[Any]],
        on_closed_manual: Callable[[str, int], Coroutine[Any, Any, None]] | None = None,
        interval_seconds: int = 60,
        price_tolerance_pct: float = 0.1,
    ) -> None:
        self._get_broker = get_broker_positions
        self._get_local = get_local_positions
        self._on_closed_manual = on_closed_manual
        self._interval = interval_seconds
        self._engine = ReconciliationEngine(price_tolerance_pct=price_tolerance_pct)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background reconciliation loop.

        Safe to call multiple times — subsequent calls are no-ops if already
        running.
        """
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="flinttrade.reconciliation")
        logger.info(
            "BackgroundReconciler started — polling every %ds",
            self._interval,
        )

    async def stop(self) -> None:
        """Stop the background reconciliation loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BackgroundReconciler stopped")

    @property
    def is_running(self) -> bool:
        """True while the background task is active."""
        return self._running

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main reconciliation loop — runs until :meth:`stop` is called."""
        while self._running:
            try:
                await self._run_once()
            except Exception as exc:
                logger.error("BackgroundReconciler: unhandled error: %s", exc)
            await asyncio.sleep(self._interval)

    async def _run_once(self) -> ReconciliationResult:
        """Execute a single reconciliation pass and log results.

        Returns the :class:`ReconciliationResult` (useful for testing).
        """
        try:
            broker_positions = await self._get_broker()
        except Exception as exc:
            logger.error("BackgroundReconciler: failed to fetch broker positions: %s", exc)
            return ReconciliationResult()

        # Support both sync and async get_local_positions callables
        local_raw = self._get_local()
        if asyncio.iscoroutine(local_raw):
            local_positions = await local_raw  # type: ignore[assignment]
        else:
            local_positions = local_raw  # type: ignore[assignment]

        result = self._engine.reconcile_positions(broker_positions, local_positions)

        # Log and dispatch CLOSED_MANUAL events
        for mismatch in result.mismatches:
            if mismatch.kind == MismatchKind.CLOSED_MANUAL:
                logger.warning(
                    "CLOSED_MANUAL detected: symbol=%s local_qty=%s — "
                    "position closed externally (manual/broker risk system)",
                    mismatch.symbol,
                    mismatch.local_value,
                )
                if self._on_closed_manual is not None:
                    try:
                        await self._on_closed_manual(
                            mismatch.symbol,
                            int(mismatch.local_value or 0),
                        )
                    except Exception as exc:
                        logger.error(
                            "BackgroundReconciler: on_closed_manual callback failed: %s", exc,
                        )

        return result
