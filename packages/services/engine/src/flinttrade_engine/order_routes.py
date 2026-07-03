"""Advanced order execution Flask Blueprint.

Provides REST endpoints for basket orders, split orders, and options
multi-leg strategy execution.  All endpoints live under
``/api/v1/orders/`` and delegate to executor instances stored on
``app.config``.

Config keys expected on ``app.config``:
    ``BASKET_EXECUTOR`` — a :class:`~flinttrade_engine.basket_orders.BasketOrderExecutor`
    ``SPLIT_EXECUTOR``  — a :class:`~flinttrade_engine.split_orders.SplitOrderExecutor`

Both executors are optional; if absent the endpoint returns HTTP 503.

Endpoints
---------
POST /api/v1/orders/basket
    Execute a basket of multi-leg orders atomically.

POST /api/v1/orders/split
    Break a large order into smaller chunks with optional delay.

POST /api/v1/orders/options-strategy
    Build and execute a named options strategy (short_straddle, long_strangle,
    iron_condor, iron_butterfly, bull_call_spread, bear_put_spread).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from flinttrade_core.rate_limiter import rate_limit

from .mode_guard import require_live_unlocked

logger = logging.getLogger("flinttrade.engine.order_routes")

order_bp = Blueprint("advanced_orders", __name__, url_prefix="/api/v1/orders")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_basket_executor() -> Any:
    return current_app.config.get("BASKET_EXECUTOR")


def _get_split_executor() -> Any:
    return current_app.config.get("SPLIT_EXECUTOR")


def _basket_required() -> tuple[Any, Response | None]:
    ex = _get_basket_executor()
    if ex is None:
        return None, (
            jsonify({"status": "error", "message": "Basket executor not configured"}),
            503,
        )
    return ex, None


def _split_required() -> tuple[Any, Response | None]:
    ex = _get_split_executor()
    if ex is None:
        return None, (
            jsonify({"status": "error", "message": "Split executor not configured"}),
            503,
        )
    return ex, None


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a synchronous Flask view.

    Creates a new event loop if none is running (typical in Flask dev/WSGI).
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# POST /api/v1/orders/basket
# ---------------------------------------------------------------------------


@order_bp.route("/basket", methods=["POST"])
@require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def place_basket() -> Response:
    """Execute a basket of multi-leg orders atomically.

    Request body (JSON):

    .. code-block:: json

        {
            "strategy": "my_basket",
            "legs": [
                {
                    "symbol": "NIFTY25MAYFUT",
                    "exchange": "NFO",
                    "action": "BUY",
                    "quantity": 50,
                    "order_type": "MARKET",
                    "product": "NRML"
                },
                {
                    "symbol": "BANKNIFTY25MAYFUT",
                    "exchange": "NFO",
                    "action": "SELL",
                    "quantity": 25,
                    "order_type": "LIMIT",
                    "price": 52000.0,
                    "product": "NRML"
                }
            ]
        }

    Returns:
        201 on full success, 422 on partial/total failure, 400 on bad input.
    """
    executor, err = _basket_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    legs_raw = body.get("legs")
    if not legs_raw or not isinstance(legs_raw, list):
        return jsonify({"status": "error", "message": "'legs' array is required"}), 400

    strategy: str = str(body.get("strategy", "basket"))

    from flinttrade_engine.basket_orders import BasketLeg

    legs: list[BasketLeg] = []
    for i, raw in enumerate(legs_raw):
        if not isinstance(raw, dict):
            return jsonify(
                {"status": "error", "message": f"Leg {i} must be an object"}
            ), 400
        try:
            legs.append(
                BasketLeg(
                    symbol=str(raw.get("symbol", "")),
                    exchange=str(raw.get("exchange", "NFO")),
                    action=str(raw.get("action", "BUY")).upper(),
                    quantity=int(raw.get("quantity", 0)),
                    order_type=str(raw.get("order_type", "MARKET")).upper(),
                    price=float(raw["price"]) if "price" in raw else None,
                    trigger_price=float(raw["trigger_price"]) if "trigger_price" in raw else None,
                    product=str(raw.get("product", "MIS")).upper(),
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Basket leg %s parse error: %s", i, exc)
            return jsonify(
                {"status": "error", "message": f"Leg {i} parse error"}
            ), 400

    result = _run_async(executor.execute(legs, strategy=strategy))

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "strategy": result.strategy,
        "timestamp": result.timestamp,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "rolled_back": result.rolled_back,
        "order_ids": result.order_ids,
        "legs": [
            {
                "leg_index": r.leg_index,
                "symbol": r.symbol,
                "action": r.action,
                "quantity": r.quantity,
                "success": r.success,
                "order_id": r.order_id,
                "error": r.error,
                "rolled_back": r.rolled_back,
                "rollback_order_id": r.rollback_order_id,
            }
            for r in result.legs
        ],
    }
    if not result.success:
        response_data["message"] = result.error
        response_data["failed_leg_index"] = result.failed_leg_index

    http_status = 201 if result.success else 422
    return jsonify(response_data), http_status


# ---------------------------------------------------------------------------
# POST /api/v1/orders/split
# ---------------------------------------------------------------------------


@order_bp.route("/split", methods=["POST"])
@require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def place_split() -> Response:
    """Break a large order into smaller chunks and place with a delay.

    Request body (JSON):

    .. code-block:: json

        {
            "symbol": "NIFTY25MAYFUT",
            "exchange": "NFO",
            "action": "BUY",
            "total_qty": 300,
            "chunk_size": 75,
            "delay_seconds": 0.5,
            "order_type": "MARKET",
            "product": "NRML",
            "strategy": "impact_reducer"
        }

    Returns:
        201 on full success, 422 on partial/total failure, 400 on bad input.
    """
    executor, err = _split_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    required_fields = ["symbol", "exchange", "action", "total_qty", "chunk_size"]
    for field_name in required_fields:
        if field_name not in body:
            return jsonify(
                {"status": "error", "message": f"'{field_name}' is required"}
            ), 400

    try:
        symbol: str = str(body["symbol"])
        exchange: str = str(body["exchange"])
        action: str = str(body["action"]).upper()
        total_qty: int = int(body["total_qty"])
        chunk_size: int = int(body["chunk_size"])
        delay_seconds: float = float(body.get("delay_seconds", 1.0))
        order_type: str = str(body.get("order_type", "MARKET")).upper()
        price: float = float(body.get("price", 0.0))
        trigger_price: float = float(body.get("trigger_price", 0.0))
        product: str = str(body.get("product", "MIS")).upper()
        strategy: str = str(body.get("strategy", "split"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Parameter parse error"}), 400

    result = _run_async(
        executor.execute_split(
            symbol=symbol,
            exchange=exchange,
            total_quantity=total_qty,
            chunk_size=chunk_size,
            action=action,  # type: ignore[arg-type]
            delay_seconds=delay_seconds,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            product=product,
            strategy=strategy,
        )
    )

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "symbol": result.symbol,
        "exchange": result.exchange,
        "action": result.action,
        "total_quantity": result.total_quantity,
        "chunk_size": result.chunk_size,
        "placed_quantity": result.placed_quantity,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "strategy": result.strategy,
        "timestamp": result.timestamp,
        "order_ids": result.order_ids,
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "quantity": c.quantity,
                "success": c.success,
                "order_id": c.order_id,
                "error": c.error,
            }
            for c in result.chunks
        ],
    }
    if not result.success:
        response_data["message"] = result.error

    http_status = 201 if result.success else 422
    return jsonify(response_data), http_status


# ---------------------------------------------------------------------------
# POST /api/v1/orders/options-strategy
# ---------------------------------------------------------------------------


_STRATEGY_MAP = {
    "short_straddle",
    "long_strangle",
    "iron_condor",
    "iron_butterfly",
    "bull_call_spread",
    "bear_put_spread",
}


@order_bp.route("/options-strategy", methods=["POST"])
@require_live_unlocked
@rate_limit("smart_orders", user_rate=2, global_rate=20)
def place_options_strategy() -> Response:
    """Build and execute a named options strategy.

    Request body (JSON) — common fields:

    .. code-block:: json

        {
            "strategy_name": "iron_condor",
            "underlying": "NIFTY",
            "expiry": "25MAY25",
            "lots": 1,
            "lot_size": 50,
            "exchange": "NFO",
            "product": "NRML",
            "strategy": "my_iron_condor"
        }

    Strategy-specific extra fields:

    - ``short_straddle``: ``strike``
    - ``long_strangle``: ``call_strike``, ``put_strike``
    - ``iron_condor``: ``put_short``, ``put_long``, ``call_short``, ``call_long``
    - ``iron_butterfly``: ``atm``, ``wing``
    - ``bull_call_spread``: ``long_strike``, ``short_strike``
    - ``bear_put_spread``: ``long_strike``, ``short_strike``

    Returns:
        201 on full success, 422 on execution failure, 400 on bad input.
    """
    executor, err = _basket_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    strategy_name: str = str(body.get("strategy_name", "")).lower()
    if strategy_name not in _STRATEGY_MAP:
        return jsonify(
            {
                "status": "error",
                "message": (
                    f"Unknown strategy_name '{strategy_name}'. "
                    f"Must be one of: {sorted(_STRATEGY_MAP)}"
                ),
            }
        ), 400

    underlying: str = str(body.get("underlying", ""))
    expiry: str = str(body.get("expiry", ""))
    if not underlying:
        return jsonify({"status": "error", "message": "'underlying' is required"}), 400
    if not expiry:
        return jsonify({"status": "error", "message": "'expiry' is required"}), 400

    try:
        lots: int = int(body.get("lots", 1))
        lot_size: int = int(body.get("lot_size", 50))
        exchange: str = str(body.get("exchange", "NFO"))
        product: str = str(body.get("product", "NRML"))
        basket_strategy: str = str(body.get("strategy", strategy_name))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Parameter parse error"}), 400

    from flinttrade_engine.options_multi_order import OptionsStrategyBuilder

    try:
        legs = _build_strategy_legs(
            builder=OptionsStrategyBuilder,
            strategy_name=strategy_name,
            underlying=underlying,
            expiry=expiry,
            body=body,
            lots=lots,
            lot_size=lot_size,
            exchange=exchange,
            product=product,
        )
    except (KeyError, ValueError, TypeError):
        return jsonify({"status": "error", "message": "Strategy build error"}), 400

    result = _run_async(executor.execute(legs, strategy=basket_strategy))

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "strategy_name": strategy_name,
        "strategy": result.strategy,
        "underlying": underlying,
        "expiry": expiry,
        "lots": lots,
        "timestamp": result.timestamp,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "rolled_back": result.rolled_back,
        "order_ids": result.order_ids,
        "legs": [
            {
                "leg_index": r.leg_index,
                "symbol": r.symbol,
                "action": r.action,
                "quantity": r.quantity,
                "success": r.success,
                "order_id": r.order_id,
                "error": r.error,
            }
            for r in result.legs
        ],
    }
    if not result.success:
        response_data["message"] = result.error

    http_status = 201 if result.success else 422
    return jsonify(response_data), http_status


# ---------------------------------------------------------------------------
# Internal strategy leg builder
# ---------------------------------------------------------------------------


def _build_strategy_legs(
    builder: type,
    strategy_name: str,
    underlying: str,
    expiry: str,
    body: dict[str, Any],
    lots: int,
    lot_size: int,
    exchange: str,
    product: str,
) -> list:
    """Dispatch to the correct :class:`OptionsStrategyBuilder` method.

    Args:
        builder: The :class:`OptionsStrategyBuilder` class.
        strategy_name: Validated strategy name string.
        underlying: Underlying symbol.
        expiry: Expiry string.
        body: Full request body for strategy-specific params.
        lots: Number of lots.
        lot_size: Units per lot.
        exchange: Derivatives exchange.
        product: Product type.

    Returns:
        List of :class:`~flinttrade_engine.basket_orders.BasketLeg`.

    Raises:
        KeyError: When a required strategy-specific parameter is missing.
        ValueError: When parameter values are invalid.
    """
    kwargs = dict(
        underlying=underlying,
        expiry=expiry,
        lots=lots,
        lot_size=lot_size,
        exchange=exchange,
        product=product,
    )

    if strategy_name == "short_straddle":
        return builder.short_straddle(strike=float(body["strike"]), **kwargs)

    if strategy_name == "long_strangle":
        return builder.long_strangle(
            call_strike=float(body["call_strike"]),
            put_strike=float(body["put_strike"]),
            **kwargs,
        )

    if strategy_name == "iron_condor":
        return builder.iron_condor(
            put_short=float(body["put_short"]),
            put_long=float(body["put_long"]),
            call_short=float(body["call_short"]),
            call_long=float(body["call_long"]),
            **kwargs,
        )

    if strategy_name == "iron_butterfly":
        return builder.iron_butterfly(
            atm=float(body["atm"]),
            wing=float(body["wing"]),
            **kwargs,
        )

    if strategy_name == "bull_call_spread":
        return builder.bull_call_spread(
            long_strike=float(body["long_strike"]),
            short_strike=float(body["short_strike"]),
            **kwargs,
        )

    if strategy_name == "bear_put_spread":
        return builder.bear_put_spread(
            long_strike=float(body["long_strike"]),
            short_strike=float(body["short_strike"]),
            **kwargs,
        )

    raise ValueError(f"Unhandled strategy_name: {strategy_name}")  # pragma: no cover
