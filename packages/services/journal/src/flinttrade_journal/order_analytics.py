"""Order Execution Analytics — quality metrics for historical order data.

Analyses fill rates, slippage, execution speed, rejection patterns, and
per-hour / per-symbol breakdowns from a list of order records sourced
from the tradebook or trade journal.

Example::

    from flinttrade_journal.order_analytics import OrderAnalytics

    analytics = OrderAnalytics(orders)
    summary = analytics.summary()
    print(f"Fill rate: {summary.fill_rate_pct:.1f}%")
    print(f"Avg slippage: {summary.avg_slippage_bps:.2f} bps")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import numpy as np
from flask import Blueprint, jsonify, request
from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.journal.order_analytics")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_FILLED = {"complete", "filled", "traded"}
_STATUS_REJECTED = {"rejected", "cancelled_by_exchange", "error"}
_STATUS_CANCELLED = {"cancelled"}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OrderExecutionSummary(BaseModel):
    """Full execution quality summary report.

    Attributes:
        total_orders: Total number of orders analysed.
        filled: Number of fully filled orders.
        rejected: Number of rejected orders.
        cancelled: Number of cancelled orders (by user).
        fill_rate_pct: Percentage of orders that received a complete fill.
        avg_slippage_bps: Average slippage in basis points (actual fill vs
            intended price). Positive = filled worse than intended.
        median_execution_ms: Median order-placement-to-fill time in milliseconds.
        p95_execution_ms: 95th-percentile execution time in milliseconds.
        best_hour: Hour of day (0-23 IST) with the highest fill rate.
        worst_hour: Hour of day (0-23 IST) with the lowest fill rate.
        top_rejection_reasons: Up to 5 most common rejection reasons with counts.
    """

    total_orders: int
    filled: int
    rejected: int
    cancelled: int
    fill_rate_pct: float = Field(ge=0.0, le=100.0)
    avg_slippage_bps: float
    median_execution_ms: float = Field(ge=0.0)
    p95_execution_ms: float = Field(ge=0.0)
    best_hour: int = Field(ge=0, le=23)
    worst_hour: int = Field(ge=0, le=23)
    top_rejection_reasons: list[tuple[str, int]]


# ---------------------------------------------------------------------------
# Analytics engine
# ---------------------------------------------------------------------------


class OrderAnalytics:
    """Compute execution quality metrics from historical order records.

    Each order dict may contain the following keys (all optional unless stated):

    - ``status`` (str): Order status — "complete"/"filled"/"rejected"/"cancelled".
    - ``price`` (float): Intended order price (limit price or market reference).
    - ``average_price`` (float): Actual fill price.
    - ``quantity`` (int/float): Ordered quantity.
    - ``filled_quantity`` (int/float): Actual filled quantity.
    - ``order_timestamp`` (str | float): ISO-8601 string or Unix epoch (seconds).
    - ``fill_timestamp``  (str | float): ISO-8601 string or Unix epoch (seconds).
    - ``symbol`` (str): Instrument symbol.
    - ``rejection_reason`` (str): Reason text when status is "rejected".
    - ``exchange_order_id`` (str): Exchange-assigned order identifier.

    Args:
        orders: List of order record dicts.

    Example::

        analytics = OrderAnalytics(orders)
        print(analytics.fill_rate())
        print(analytics.average_slippage())
    """

    def __init__(self, orders: list[dict[str, Any]]) -> None:
        self._orders = orders

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_status(raw: str) -> str:
        """Normalise status string to lowercase."""
        return str(raw).strip().lower()

    @staticmethod
    def _ts_to_epoch(value: Any) -> float | None:
        """Convert a timestamp value to Unix epoch seconds.

        Accepts:
        - float / int epoch directly
        - ISO-8601 string ("2026-04-09T09:15:00", "2026-04-09 09:15:00")
        - Returns None if conversion fails.
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return None
        # Try common ISO formats
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                import datetime as _dt
                return _dt.datetime.strptime(s, fmt).timestamp()
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_hour(order: dict[str, Any]) -> int | None:
        """Extract IST hour (0-23) from order_timestamp or fill_timestamp."""
        import datetime as _dt

        for key in ("order_timestamp", "fill_timestamp"):
            epoch = OrderAnalytics._ts_to_epoch(order.get(key))
            if epoch is not None:
                # Convert to IST (UTC+5:30)
                ist_offset = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
                dt = _dt.datetime.fromtimestamp(epoch, tz=ist_offset)
                return dt.hour
        return None

    @staticmethod
    def _slippage_bps(order: dict[str, Any]) -> float | None:
        """Compute slippage in basis points for a single order.

        Slippage = (fill_price - intended_price) / intended_price * 10_000
        Positive means filled at a worse price for a BUY, negative for SELL.
        Direction is ignored here; we return the signed difference which the
        caller can choose to use as absolute or directional.
        """
        intended = order.get("price")
        actual = order.get("average_price")
        if intended is None or actual is None:
            return None
        intended_f = float(intended)
        actual_f = float(actual)
        if intended_f == 0.0:
            return None
        action = str(order.get("action", order.get("transaction_type", "BUY"))).upper()
        if action in ("BUY", "B"):
            return (actual_f - intended_f) / intended_f * 10_000.0
        # SELL: negative fill price delta is worse for seller → flip sign
        return (intended_f - actual_f) / intended_f * 10_000.0

    @staticmethod
    def _execution_ms(order: dict[str, Any]) -> float | None:
        """Execution latency in milliseconds from placement to fill."""
        t_place = OrderAnalytics._ts_to_epoch(order.get("order_timestamp"))
        t_fill = OrderAnalytics._ts_to_epoch(order.get("fill_timestamp"))
        if t_place is None or t_fill is None:
            return None
        delta = t_fill - t_place
        if delta < 0:
            return None
        return delta * 1_000.0  # seconds → milliseconds

    def _is_filled(self, order: dict[str, Any]) -> bool:
        """Return True if the order was fully filled."""
        status = self._normalise_status(order.get("status", ""))
        if status in _STATUS_FILLED:
            return True
        # Treat as filled if filled_quantity >= quantity (regardless of status label)
        qty = float(order.get("quantity", 0))
        filled = float(order.get("filled_quantity", order.get("fill_quantity", 0)))
        if qty > 0 and filled >= qty:
            return True
        return False

    def _is_rejected(self, order: dict[str, Any]) -> bool:
        return self._normalise_status(order.get("status", "")) in _STATUS_REJECTED

    def _is_cancelled(self, order: dict[str, Any]) -> bool:
        return self._normalise_status(order.get("status", "")) in _STATUS_CANCELLED

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fill_rate(self) -> float:
        """Compute the percentage of orders that received a complete fill.

        Returns:
            Fill rate as a percentage (0.0–100.0). Returns 0.0 for an empty
            order list.
        """
        if not self._orders:
            return 0.0
        filled = sum(1 for o in self._orders if self._is_filled(o))
        return filled / len(self._orders) * 100.0

    def average_slippage(self) -> float:
        """Compute average slippage in basis points across all filled orders.

        Slippage is only measured for orders that have both an intended price
        (``price``) and an actual fill price (``average_price``).

        Returns:
            Average slippage in basis points. Positive means fills were
            worse than the intended price. Returns 0.0 when no slippage
            data is available.
        """
        slippages = [
            s
            for o in self._orders
            if self._is_filled(o) and (s := self._slippage_bps(o)) is not None
        ]
        if not slippages:
            return 0.0
        return float(np.mean(slippages))

    def execution_speed(self) -> dict[str, float]:
        """Compute execution latency percentile statistics.

        Only filled orders with both ``order_timestamp`` and ``fill_timestamp``
        are included.

        Returns:
            Dict with keys ``average_ms``, ``p50_ms``, ``p95_ms``, ``p99_ms``,
            all in milliseconds. All values are 0.0 when no timing data is
            available.
        """
        times: list[float] = [
            ms
            for o in self._orders
            if self._is_filled(o) and (ms := self._execution_ms(o)) is not None
        ]
        if not times:
            return {"average_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

        arr = np.array(times, dtype=float)
        return {
            "average_ms": float(np.mean(arr)),
            "p50_ms": float(np.percentile(arr, 50)),
            "p95_ms": float(np.percentile(arr, 95)),
            "p99_ms": float(np.percentile(arr, 99)),
        }

    def rejection_analysis(self) -> dict[str, int]:
        """Count rejected orders grouped by rejection reason.

        Returns:
            Dict mapping rejection reason string to count, sorted descending
            by count. Returns an empty dict when no rejections are present.
        """
        counts: dict[str, int] = defaultdict(int)
        for o in self._orders:
            if self._is_rejected(o):
                reason = str(o.get("rejection_reason", o.get("status_message", "Unknown"))).strip()
                counts[reason] += 1
        return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))

    def by_hour(self) -> dict[int, dict[str, float]]:
        """Compute fill rate and average slippage broken down by hour of day.

        Uses IST (UTC+5:30) hour from ``order_timestamp`` or ``fill_timestamp``.

        Returns:
            Dict mapping hour (0-23) to a sub-dict with keys:
            ``fill_rate_pct``, ``avg_slippage_bps``, ``order_count``.
            Only hours that appear in the data are included.
        """
        bucket_orders: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for o in self._orders:
            hour = self._extract_hour(o)
            if hour is not None:
                bucket_orders[hour].append(o)

        result: dict[int, dict[str, float]] = {}
        for hour, hour_orders in sorted(bucket_orders.items()):
            filled = sum(1 for o in hour_orders if self._is_filled(o))
            slippages = [
                s
                for o in hour_orders
                if self._is_filled(o) and (s := self._slippage_bps(o)) is not None
            ]
            result[hour] = {
                "fill_rate_pct": filled / len(hour_orders) * 100.0,
                "avg_slippage_bps": float(np.mean(slippages)) if slippages else 0.0,
                "order_count": float(len(hour_orders)),
            }
        return result

    def by_symbol(self) -> dict[str, dict[str, float]]:
        """Compute fill rate, slippage, and volume broken down by symbol.

        Returns:
            Dict mapping symbol string to a sub-dict with keys:
            ``fill_rate_pct``, ``avg_slippage_bps``, ``total_volume``,
            ``order_count``.
        """
        bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for o in self._orders:
            sym = str(o.get("symbol", o.get("tradingsymbol", "UNKNOWN"))).upper().strip()
            bucket[sym].append(o)

        result: dict[str, dict[str, float]] = {}
        for sym, sym_orders in sorted(bucket.items()):
            filled_orders = [o for o in sym_orders if self._is_filled(o)]
            slippages = [
                s
                for o in filled_orders
                if (s := self._slippage_bps(o)) is not None
            ]
            total_vol = sum(
                float(o.get("filled_quantity", o.get("quantity", 0)))
                for o in filled_orders
            )
            result[sym] = {
                "fill_rate_pct": len(filled_orders) / len(sym_orders) * 100.0,
                "avg_slippage_bps": float(np.mean(slippages)) if slippages else 0.0,
                "total_volume": total_vol,
                "order_count": float(len(sym_orders)),
            }
        return result

    def summary(self) -> OrderExecutionSummary:
        """Produce a full execution quality summary report.

        Returns:
            :class:`OrderExecutionSummary` Pydantic model with all key metrics.
        """
        total = len(self._orders)
        filled_count = sum(1 for o in self._orders if self._is_filled(o))
        rejected_count = sum(1 for o in self._orders if self._is_rejected(o))
        cancelled_count = sum(1 for o in self._orders if self._is_cancelled(o))

        fill_rate_pct = filled_count / total * 100.0 if total else 0.0

        # Slippage
        avg_slippage = self.average_slippage()

        # Execution speed
        speed = self.execution_speed()

        # Best / worst hour by fill rate
        hourly = self.by_hour()
        best_hour = 9  # Default to 9 AM IST market open
        worst_hour = 9
        if hourly:
            best_hour = max(hourly, key=lambda h: hourly[h]["fill_rate_pct"])
            worst_hour = min(hourly, key=lambda h: hourly[h]["fill_rate_pct"])

        # Top rejection reasons (up to 5)
        rejections = self.rejection_analysis()
        top_reasons: list[tuple[str, int]] = list(rejections.items())[:5]

        return OrderExecutionSummary(
            total_orders=total,
            filled=filled_count,
            rejected=rejected_count,
            cancelled=cancelled_count,
            fill_rate_pct=round(fill_rate_pct, 4),
            avg_slippage_bps=round(avg_slippage, 4),
            median_execution_ms=round(speed["p50_ms"], 4),
            p95_execution_ms=round(speed["p95_ms"], 4),
            best_hour=best_hour,
            worst_hour=worst_hour,
            top_rejection_reasons=top_reasons,
        )


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

order_analytics_bp = Blueprint("order_analytics", __name__)


@order_analytics_bp.route("/analytics/execution", methods=["POST"])
def execution_analytics_endpoint() -> tuple[Any, int]:
    """Analyse execution quality for a provided list of order records.

    Request body (JSON):
        orders (list[dict]): List of order records.  Each record should
            include ``status``, ``price``, ``average_price``,
            ``order_timestamp``, ``fill_timestamp``, ``symbol``.

    Returns:
        JSON with ``status`` and ``data`` keys.  ``data`` contains the full
        :class:`OrderExecutionSummary` serialised as a dict.

    Status codes:
        200: Success.
        400: Missing or malformed ``orders`` field.
        500: Internal processing error.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    orders = payload.get("orders")
    if orders is None:
        return jsonify({"status": "error", "message": "'orders' field required"}), 400
    if not isinstance(orders, list):
        return jsonify({"status": "error", "message": "'orders' must be a list"}), 400

    try:
        analytics = OrderAnalytics(orders)
        summary = analytics.summary()
        return jsonify({
            "status": "success",
            "data": summary.model_dump(),
        }), 200
    except Exception as exc:
        logger.exception("Execution analytics failed: %s", exc)
        return jsonify({"status": "error", "message": "Internal server error"}), 500
