"""Flask blueprint for ML model auto-retraining endpoints.

Mounts under ``/ft-api/v1/retrain/`` and exposes:

    GET  /ft-api/v1/retrain/status          — current retrainer state + last result
    POST /ft-api/v1/retrain/trigger         — manually trigger retrain for a symbol
    GET  /ft-api/v1/retrain/history         — paginated list of past retrain results

The ``AutoRetrainer`` singleton is stored on ``current_app`` (keyed as
``_auto_retrainer``) so it survives across requests.  The retraining loop
runs in a background asyncio task.  Because FlintTrade's backend is a sync
Flask app (not Quart), background retraining is driven by a dedicated
``threading.Thread`` running its own event loop — the HTTP handlers submit
one-shot coroutines to that loop via ``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from packages.ai.src.auto_retrain import AutoRetrainer, RetrainConfig

logger = logging.getLogger("flinttrade.ai.retrain_routes")

retrain_bp = Blueprint("retrain", __name__, url_prefix="/ft-api/v1/retrain")


# ---------------------------------------------------------------------------
# Background loop management
# ---------------------------------------------------------------------------


def _get_retrainer() -> AutoRetrainer | None:
    """Return the application-scoped ``AutoRetrainer`` singleton, or None.

    The retrainer is only created when the application first calls
    ``init_auto_retrainer()``.  If not initialised, endpoints return a
    503 response explaining the setup requirement.

    Returns:
        The singleton ``AutoRetrainer`` or ``None``.
    """
    return getattr(current_app, "_auto_retrainer", None)


def _get_bg_loop() -> asyncio.AbstractEventLoop | None:
    """Return the background event loop running the retrain loop, or None.

    Returns:
        The background ``asyncio.AbstractEventLoop`` or ``None``.
    """
    return getattr(current_app, "_retrain_loop", None)


def init_auto_retrainer(
    app: Any,
    config: RetrainConfig | None = None,
    data_fetcher: Any = None,
) -> AutoRetrainer:
    """Initialise the ``AutoRetrainer`` singleton and attach it to ``app``.

    Starts a background daemon thread that runs the retraining loop in its
    own asyncio event loop.  Safe to call multiple times — subsequent calls
    return the existing instance without restarting the loop.

    Args:
        app: The Flask application instance.
        config: Optional ``RetrainConfig``.  Defaults to ``RetrainConfig()``.
        data_fetcher: Async callable ``(symbol, lookback_days) -> DataFrame``.
            When ``None``, a no-op stub is used so the server starts without
            a data provider configured.

    Returns:
        The ``AutoRetrainer`` singleton attached to ``app``.
    """
    if hasattr(app, "_auto_retrainer") and app._auto_retrainer is not None:
        return app._auto_retrainer  # type: ignore[return-value]

    resolved_config = config or RetrainConfig()

    if data_fetcher is None:
        import pandas as pd  # noqa: PLC0415

        async def _noop_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
            """Stub data fetcher — replace with real implementation."""
            logger.warning(
                "[AutoRetrainer] No data_fetcher configured for %s. "
                "Pass a real fetcher to init_auto_retrainer().",
                symbol,
            )
            return pd.DataFrame()

        data_fetcher = _noop_fetcher

    retrainer = AutoRetrainer(resolved_config, data_fetcher=data_fetcher)

    # Start a background thread with a dedicated event loop.
    bg_loop = asyncio.new_event_loop()

    def _thread_main() -> None:
        asyncio.set_event_loop(bg_loop)
        bg_loop.run_until_complete(retrainer.start_loop())

    bg_thread = threading.Thread(
        target=_thread_main,
        name="flinttrade-retrain-loop",
        daemon=True,
    )
    bg_thread.start()

    app._auto_retrainer = retrainer  # type: ignore[attr-defined]
    app._retrain_loop = bg_loop  # type: ignore[attr-defined]
    app._retrain_thread = bg_thread  # type: ignore[attr-defined]

    logger.info(
        "[AutoRetrainer] Initialised — symbols=%s interval=%dh",
        resolved_config.symbols,
        resolved_config.retrain_interval_hours,
    )
    return retrainer


# ---------------------------------------------------------------------------
# GET /ft-api/v1/retrain/status
# ---------------------------------------------------------------------------


@retrain_bp.route("/status", methods=["GET"])
def retrain_status() -> tuple[Any, int]:
    """Return current retrainer state, last result, and next scheduled time.

    Returns:
        ``{ "status": "success", "data": { ... } }`` with:
            - ``running``: whether the loop is active.
            - ``symbols``: configured instrument list.
            - ``interval_hours``: retrain interval.
            - ``last_result``: most recent ``RetrainResult`` dict, or ``null``.
            - ``total_cycles``: total retrain cycles completed.
    """
    retrainer = _get_retrainer()
    if retrainer is None:
        return jsonify({
            "status": "error",
            "message": "AutoRetrainer not initialised. Call init_auto_retrainer() at app startup.",
        }), 503

    history = retrainer.get_history()
    last_result = history[0].to_dict() if history else None

    return jsonify({
        "status": "success",
        "data": {
            "running": retrainer._running,
            "symbols": retrainer._config.symbols,
            "interval_hours": retrainer._config.retrain_interval_hours,
            "min_accuracy": retrainer._config.min_accuracy,
            "last_result": last_result,
            "total_cycles": len(history),
        },
    }), 200


# ---------------------------------------------------------------------------
# POST /ft-api/v1/retrain/trigger
# ---------------------------------------------------------------------------


@retrain_bp.route("/trigger", methods=["POST"])
def retrain_trigger() -> tuple[Any, int]:
    """Manually trigger an immediate retrain for one symbol.

    Request JSON:
        symbol (str): Instrument ticker to retrain (required).

    Returns:
        ``{ "status": "success", "data": <RetrainResult dict> }`` on success.
        The call blocks until the retrain cycle completes (or fails).

    Example::

        POST /ft-api/v1/retrain/trigger
        { "symbol": "NIFTY" }
    """
    retrainer = _get_retrainer()
    if retrainer is None:
        return jsonify({
            "status": "error",
            "message": "AutoRetrainer not initialised.",
        }), 503

    body = request.get_json(silent=True) or {}
    symbol: str = str(body.get("symbol", "")).strip().upper()

    if not symbol:
        return jsonify({
            "status": "error",
            "message": "symbol is required.",
        }), 400

    bg_loop = _get_bg_loop()

    if bg_loop is not None and bg_loop.is_running():
        # Submit to the background loop and wait for the result.
        future = asyncio.run_coroutine_threadsafe(
            retrainer.run_once(symbol), bg_loop
        )
        try:
            result = future.result(timeout=300)  # 5-minute timeout
        except TimeoutError:
            return jsonify({
                "status": "error",
                "message": "Retrain timed out after 300s.",
            }), 504
        except Exception as exc:  # noqa: BLE001
            logger.exception("[retrain_trigger] Unexpected error for %s", symbol)
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 500
    else:
        # No background loop — run synchronously in a new event loop.
        try:
            result = asyncio.run(retrainer.run_once(symbol))
        except Exception as exc:  # noqa: BLE001
            logger.exception("[retrain_trigger] Sync error for %s", symbol)
            return jsonify({
                "status": "error",
                "message": str(exc),
            }), 500

    return jsonify({
        "status": "success",
        "data": result.to_dict(),
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/retrain/history
# ---------------------------------------------------------------------------


@retrain_bp.route("/history", methods=["GET"])
def retrain_history() -> tuple[Any, int]:
    """Return paginated retrain history, newest first.

    Query params:
        limit (int, optional): Max entries to return (default 50, max 500).
        symbol (str, optional): Filter to a specific instrument.

    Returns:
        ``{ "status": "success", "data": { "results": [...], "total": N } }``
    """
    retrainer = _get_retrainer()
    if retrainer is None:
        return jsonify({
            "status": "error",
            "message": "AutoRetrainer not initialised.",
        }), 503

    # Parse query params.
    try:
        limit = min(max(int(request.args.get("limit", "50")), 1), 500)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    symbol_filter: str = request.args.get("symbol", "").strip().upper()

    history = retrainer.get_history()

    if symbol_filter:
        history = [r for r in history if r.symbol == symbol_filter]

    total = len(history)
    page = history[:limit]

    return jsonify({
        "status": "success",
        "data": {
            "results": [r.to_dict() for r in page],
            "total": total,
            "limit": limit,
        },
    }), 200
