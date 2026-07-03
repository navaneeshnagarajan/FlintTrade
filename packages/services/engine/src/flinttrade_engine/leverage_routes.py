"""Flask Blueprint for current leverage / margin utilisation.

Endpoint
--------
GET /api/v1/leverage/margin/current  — current margin: available, used, total,
                                       leverage_ratio

Proxies through :class:`flinttrade_core.openalgo_client.OpenAlgoClient`
``margin()`` using an empty positions list to fetch account-level margin info.

Register in ``create_flask_app()``::

    from flinttrade_engine.leverage_routes import leverage_bp
    app.register_blueprint(leverage_bp)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from flask import Blueprint, jsonify

logger = logging.getLogger("flinttrade.engine.leverage_routes")

# Module-level imports so tests can patch at the correct namespace.
try:
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_core.config import Settings
except Exception:  # pragma: no cover
    OpenAlgoClient = None  # type: ignore[assignment,misc]
    Settings = None  # type: ignore[assignment,misc]

leverage_bp = Blueprint("leverage", __name__, url_prefix="/api/v1")


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously from a Flask route.

    Args:
        coro: Awaitable coroutine to execute.

    Returns:
        The return value of the coroutine.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@leverage_bp.route("/leverage/margin/current", methods=["GET"])
def get_current_margin() -> tuple[Any, int]:
    """Return current margin utilisation from OpenAlgo.

    Calls the OpenAlgo ``/api/v1/margin`` endpoint with an empty positions
    list to retrieve account-level margin figures.

    Returns:
        JSON ``{"status": "success", "available": <float>, "used": <float>,
        "total": <float>, "leverage_ratio": <float>}`` on success.

        Returns HTTP 503 when OpenAlgo is unreachable or not configured.

    Notes:
        ``leverage_ratio`` is ``used / total`` when ``total > 0``,
        otherwise ``0.0``.
    """
    try:
        if OpenAlgoClient is None or Settings is None:
            raise ImportError("OpenAlgoClient or Settings not available")

        client = OpenAlgoClient(Settings.from_env())

        # Call margin with an empty positions list — returns account-level margin
        raw = _run_async(client.margin(positions=[]))
        _run_async(client.close())

        data: dict[str, Any] = raw.get("data", raw) if isinstance(raw, dict) else {}

        # Normalise field names — OpenAlgo uses both snake_case and flat names
        available = float(
            data.get("available", data.get("availablecash", data.get("available_balance", 0)))
        )
        used = float(
            data.get("used", data.get("usedmargin", data.get("used_margin", 0)))
        )
        total = float(
            data.get("total", data.get("totalbalance", data.get("total_balance", available + used)))
        )
        leverage_ratio = round(used / total, 4) if total > 0 else 0.0

        return (
            jsonify(
                {
                    "status": "success",
                    "available": available,
                    "used": used,
                    "total": total,
                    "leverage_ratio": leverage_ratio,
                }
            ),
            200,
        )
    except Exception as exc:
        logger.warning("OpenAlgo margin fetch failed: %s", exc)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not fetch margin from OpenAlgo",
                    "detail": "margin fetch failed",
                }
            ),
            503,
        )
