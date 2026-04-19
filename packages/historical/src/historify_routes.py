"""Historify bulk downloader Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
POST /admin/historify/download      — start bulk download job
GET  /admin/historify/status        — progress / last result
POST /admin/historify/delta-sync    — delta sync (new bars only)
GET  /admin/historify/resume        — pending jobs from interrupted run
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from flask import Blueprint, jsonify, request

from .historify import HistorifyDownloader, HistorifyResult

logger = logging.getLogger("flinttrade.historical.historify_routes")

historify_bulk_bp = Blueprint("historify_bulk", __name__)

# Module-level singleton — replaced by init_historify_routes when injected.
_downloader: HistorifyDownloader | None = None

# Last run result cache (in-memory, no persistence needed)
_last_result: dict[str, Any] | None = None
_progress: dict[str, int] = {"completed": 0, "total": 0}


def _get_downloader() -> HistorifyDownloader:
    """Return the singleton, raising if not initialised."""
    if _downloader is None:
        raise RuntimeError(
            "HistorifyDownloader not initialised. "
            "Call init_historify_routes(downloader) first."
        )
    return _downloader


def init_historify_routes(downloader: HistorifyDownloader) -> None:
    """Inject a HistorifyDownloader instance into the blueprint.

    Args:
        downloader: The :class:`HistorifyDownloader` instance to use.
    """
    global _downloader  # noqa: PLW0603
    _downloader = downloader
    logger.info("HistorifyDownloader singleton injected into historify_routes")


def _result_to_dict(result: HistorifyResult) -> dict[str, Any]:
    return {
        "total": result.total,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
    }


def _run_async(coro: Any) -> Any:
    """Run a coroutine in the current or new event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Inside an async context (e.g. test) — create a new loop in a thread
            import concurrent.futures  # noqa: PLC0415
            import threading  # noqa: PLC0415

            result_holder: list[Any] = []
            exc_holder: list[BaseException] = []

            def _run() -> None:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result_holder.append(new_loop.run_until_complete(coro))
                except Exception as e:
                    exc_holder.append(e)
                finally:
                    new_loop.close()

            t = threading.Thread(target=_run)
            t.start()
            t.join()
            if exc_holder:
                raise exc_holder[0]
            return result_holder[0] if result_holder else None
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@historify_bulk_bp.route("/admin/historify/download", methods=["POST"])
def start_bulk_download() -> tuple[Any, int]:
    """Start a bulk OHLCV download job.

    Request JSON:
        symbols (list): List of ``{"symbol": str, "exchange": str}`` objects.
        intervals (list[str]): OHLCV intervals, e.g. ``["1d", "1h"]``.
        from_date (str, optional): ISO date (default: 365 days ago).
        to_date (str, optional): ISO date (default: today).

    Returns:
        JSON ``{"status": "success", "data": {result fields}}``
    """
    global _last_result, _progress  # noqa: PLW0603

    body = request.get_json(silent=True) or {}
    raw_symbols: list[dict[str, str]] = body.get("symbols", [])
    intervals: list[str] = body.get("intervals", ["1d"])

    today = date.today()
    default_from = (today - timedelta(days=365)).isoformat()
    from_date_str: str = body.get("from_date", default_from)
    to_date_str: str = body.get("to_date", today.isoformat())

    if not raw_symbols:
        return jsonify({"status": "error", "message": "symbols list is required"}), 400

    try:
        from_date = date.fromisoformat(from_date_str)
        to_date = date.fromisoformat(to_date_str)
    except ValueError as exc:
        return jsonify({"status": "error", "message": f"Invalid date: {exc}"}), 400

    symbols = [(s["symbol"], s.get("exchange", "NSE")) for s in raw_symbols if s.get("symbol")]
    if not symbols:
        return jsonify({"status": "error", "message": "No valid symbols provided"}), 400

    _progress["completed"] = 0
    _progress["total"] = len(symbols) * len(intervals)

    def _on_progress(completed: int, total: int) -> None:
        _progress["completed"] = completed
        _progress["total"] = total

    try:
        dl = _get_downloader()
        result = _run_async(
            dl.download_symbols(
                symbols=symbols,
                intervals=intervals,
                from_date=from_date,
                to_date=to_date,
                progress_callback=_on_progress,
            )
        )
        _last_result = _result_to_dict(result)
        return jsonify({"status": "success", "data": _last_result}), 200
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    except Exception as exc:
        logger.exception("Historify bulk download failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@historify_bulk_bp.route("/admin/historify/status", methods=["GET"])
def get_download_status() -> tuple[Any, int]:
    """Return progress of the current or last bulk download job.

    Returns:
        JSON ``{"status": "success", "data": {"completed": N, "total": N,
        "last_result": {...}}}``
    """
    return jsonify({
        "status": "success",
        "data": {
            "completed": _progress.get("completed", 0),
            "total": _progress.get("total", 0),
            "last_result": _last_result,
        },
    }), 200


@historify_bulk_bp.route("/admin/historify/delta-sync", methods=["POST"])
def run_delta_sync() -> tuple[Any, int]:
    """Sync only new bars for a list of symbols since last stored bar.

    Request JSON:
        symbols (list): List of ``{"symbol": str, "exchange": str}`` objects.
        interval (str, optional): OHLCV interval (default ``"1d"``).

    Returns:
        JSON ``{"status": "success", "data": {"inserted": N}}``
    """
    body = request.get_json(silent=True) or {}
    raw_symbols: list[dict[str, str]] = body.get("symbols", [])
    interval: str = body.get("interval", "1d")

    if not raw_symbols:
        return jsonify({"status": "error", "message": "symbols list is required"}), 400

    symbols = [(s["symbol"], s.get("exchange", "NSE")) for s in raw_symbols if s.get("symbol")]
    if not symbols:
        return jsonify({"status": "error", "message": "No valid symbols provided"}), 400

    try:
        dl = _get_downloader()
        inserted = _run_async(dl.delta_sync(symbols, interval))
        return jsonify({"status": "success", "data": {"inserted": inserted}}), 200
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    except Exception as exc:
        logger.exception("Historify delta sync failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500


@historify_bulk_bp.route("/admin/historify/resume", methods=["GET"])
def get_resume_queue() -> tuple[Any, int]:
    """Return pending downloads from an interrupted job.

    Returns:
        JSON ``{"status": "success", "data": {"pending": [...], "count": N}}``
    """
    try:
        dl = _get_downloader()
        pending = dl.resume_queue()
        return jsonify({
            "status": "success",
            "data": {"pending": pending, "count": len(pending)},
        }), 200
    except RuntimeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 503
    except Exception as exc:
        logger.exception("Historify resume_queue failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
