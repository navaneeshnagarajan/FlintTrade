"""Flask Blueprint for bulk instruments download.

Endpoint
--------
GET /api/v1/instruments  — download all instruments for an exchange

Proxies through :class:`flinttrade_core.openalgo_client.OpenAlgoClient`
``instruments()`` endpoint.  Streams the response as newline-delimited JSON
when the result set exceeds 10,000 rows so the frontend can process large
master-contract files without buffering the entire payload in memory.

Register in ``create_flask_app()``::

    from flinttrade_historical.instruments_routes import instruments_bp
    app.register_blueprint(instruments_bp)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Generator

from flask import Blueprint, Response, jsonify, request, stream_with_context

logger = logging.getLogger("flinttrade.historical.instruments_routes")

# Module-level imports so tests can patch at the correct namespace.
try:
    from flinttrade_core.openalgo_client import (
        client_call_sync,
        client_close_sync,
        resolve_openalgo_client,
    )
except Exception:  # pragma: no cover
    resolve_openalgo_client = None  # type: ignore[assignment,misc]
    client_call_sync = None  # type: ignore[assignment,misc]
    client_close_sync = None  # type: ignore[assignment,misc]

instruments_bp = Blueprint("instruments", __name__, url_prefix="/api/v1")

#: Row threshold above which the response switches to streaming NDJSON.
_STREAM_THRESHOLD = 10_000


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


def _ndjson_stream(rows: list[Any]) -> Generator[str, None, None]:
    """Yield rows as newline-delimited JSON strings.

    Args:
        rows: List of JSON-serialisable objects.

    Yields:
        Each object serialised as a JSON string followed by ``\\n``.
    """
    for row in rows:
        yield json.dumps(row, ensure_ascii=False) + "\n"


@instruments_bp.route("/instruments", methods=["GET"])
def get_instruments() -> tuple[Any, int] | Response:
    """Return all instruments for an exchange.

    Query parameters:
        exchange (str, optional): Exchange code, e.g. ``NSE``.  Defaults to ``NSE``.

    Returns:
        For <= 10,000 rows: JSON ``{"status": "success", "exchange": "NSE",
        "count": N, "instruments": [...]}``.

        For > 10,000 rows: streaming NDJSON (``Content-Type:
        application/x-ndjson``), one instrument per line.

    Raises HTTP 503 when OpenAlgo is unreachable.
    """
    exchange: str = request.args.get("exchange", "NSE").upper()

    try:
        if resolve_openalgo_client is None:
            raise ImportError("OpenAlgo client resolver not available")

        client, close_client = resolve_openalgo_client()
        try:
            raw = client_call_sync(client, client.instruments(exchange=exchange))
        finally:
            if close_client:
                client_close_sync(client)

        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        instruments: list[Any] = data if isinstance(data, list) else []

        if len(instruments) > _STREAM_THRESHOLD:
            logger.info(
                "Streaming %d instruments for %s (threshold=%d)",
                len(instruments),
                exchange,
                _STREAM_THRESHOLD,
            )
            return Response(
                stream_with_context(_ndjson_stream(instruments)),
                status=200,
                mimetype="application/x-ndjson",
                headers={
                    "X-Exchange": exchange,
                    "X-Count": str(len(instruments)),
                },
            )

        return (
            jsonify(
                {
                    "status": "success",
                    "exchange": exchange,
                    "count": len(instruments),
                    "instruments": instruments,
                }
            ),
            200,
        )
    except Exception as exc:
        logger.warning("Instruments fetch failed for %s: %s", exchange, exc)
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Could not fetch instruments from OpenAlgo",
                    "detail": "instrument fetch failed",
                }
            ),
            503,
        )
