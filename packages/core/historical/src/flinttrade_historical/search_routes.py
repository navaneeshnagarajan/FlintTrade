"""Flask Blueprint for symbol search.

Endpoint
--------
GET /api/v1/search  — search for trading symbols with optional exchange filter

Proxies through :class:`flinttrade_core.openalgo_client.OpenAlgoClient`
``search()`` endpoint and applies optional exchange + limit filtering
on the results.

Register in ``create_flask_app()``::

    from flinttrade_historical.search_routes import search_bp
    app.register_blueprint(search_bp)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.historical.search_routes")

# Module-level imports so tests can patch at the correct namespace.
try:
    from flinttrade_core.openalgo_client import OpenAlgoClient
    from flinttrade_core.config import Settings
except Exception:  # pragma: no cover
    OpenAlgoClient = None  # type: ignore[assignment,misc]
    Settings = None  # type: ignore[assignment,misc]

search_bp = Blueprint("search", __name__, url_prefix="/api/v1")

#: Maximum results that can be requested in a single query.
_MAX_LIMIT = 200

#: Default number of results when ?limit is not specified.
_DEFAULT_LIMIT = 20


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


@search_bp.route("/search", methods=["GET"])
def search_symbols() -> tuple[Any, int]:
    """Search for trading symbols by name or code.

    Query parameters:
        q (str, required): Search query, e.g. ``RELI``, ``NIFTY``.
        exchange (str, optional): Filter results to this exchange, e.g. ``NSE``.
        limit (int, optional): Maximum number of results to return.
            Capped at 200.  Defaults to 20.

    Returns:
        JSON ``{"status": "success", "query": "RELI", "exchange": "NSE",
        "count": N, "results": [{"symbol": ..., "exchange": ..., ...}, ...]}``.

    Raises:
        HTTP 400 when ``?q`` is missing or empty.
        HTTP 503 when OpenAlgo is unreachable.
    """
    query: str = request.args.get("q", "").strip()
    if not query:
        return (
            jsonify({"status": "error", "message": "Query parameter 'q' is required"}),
            400,
        )

    exchange_filter: str = request.args.get("exchange", "").strip().upper()

    limit_raw: str = request.args.get("limit", str(_DEFAULT_LIMIT))
    try:
        limit = max(1, min(int(limit_raw), _MAX_LIMIT))
    except ValueError:
        return (
            jsonify({"status": "error", "message": "limit must be a positive integer"}),
            400,
        )

    try:
        if OpenAlgoClient is None or Settings is None:
            raise ImportError("OpenAlgoClient or Settings not available")

        client = OpenAlgoClient(Settings.from_env())
        raw = _run_async(client.search(query=query))
        _run_async(client.close())

        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        results: list[dict[str, Any]] = data if isinstance(data, list) else []

        # Apply exchange filter if provided
        if exchange_filter:
            results = [
                r for r in results
                if str(r.get("exchange", "")).upper() == exchange_filter
            ]

        # Apply limit
        results = results[:limit]

        return (
            jsonify(
                {
                    "status": "success",
                    "query": query,
                    "exchange": exchange_filter or None,
                    "count": len(results),
                    "results": results,
                }
            ),
            200,
        )
    except Exception as exc:
        logger.warning("Symbol search failed for %r: %s", query, exc)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not fetch search results from OpenAlgo",
                    "detail": "search request failed",
                }
            ),
            503,
        )
