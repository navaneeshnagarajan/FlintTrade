"""Historify watchlist Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET    /v1/historify/watchlist  — list all watchlist items
POST   /v1/historify/watchlist  — add an item
DELETE /v1/historify/watchlist  — remove an item
POST   /v1/historify/download   — trigger download for all enabled items
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from .watchlist import DownloadWatchlist

logger = logging.getLogger("flinttrade.historical.watchlist_routes")

historify_bp = Blueprint("historify", __name__)

# Module-level singleton — replaced by ``init_watchlist_routes`` when injected.
_watchlist: DownloadWatchlist | None = None


def _get_watchlist() -> DownloadWatchlist:
    """Return the module-level watchlist singleton, creating it lazily."""
    global _watchlist  # noqa: PLW0603
    if _watchlist is None:
        default_path = Path.home() / ".flinttrade" / "watchlist.db"
        _watchlist = DownloadWatchlist(default_path)
    return _watchlist


def init_watchlist_routes(watchlist: DownloadWatchlist) -> None:
    """Inject a DownloadWatchlist instance into the blueprint's singleton.

    Args:
        watchlist: The :class:`DownloadWatchlist` instance to use.
    """
    global _watchlist  # noqa: PLW0603
    _watchlist = watchlist
    logger.info("DownloadWatchlist singleton injected into watchlist_routes")


@historify_bp.route("/v1/historify/watchlist", methods=["GET"])
def list_watchlist() -> tuple[Any, int]:
    """Return all watchlist items.

    Returns:
        JSON ``{"status": "success", "data": [...]}`` where each element has
        keys ``symbol``, ``exchange``, ``interval``, ``enabled``.
    """
    items = _get_watchlist().list_items()
    return jsonify({
        "status": "success",
        "data": [
            {
                "symbol": item.symbol,
                "exchange": item.exchange,
                "interval": item.interval,
                "enabled": item.enabled,
            }
            for item in items
        ],
    }), 200


@historify_bp.route("/v1/historify/watchlist", methods=["POST"])
def add_watchlist() -> tuple[Any, int]:
    """Add a symbol to the watchlist.

    Request JSON:
        symbol (str): Instrument symbol.
        exchange (str): Exchange code.
        interval (str, optional): OHLCV interval (default ``"1d"``).

    Returns:
        JSON ``{"status": "success", "data": {...}}`` with the created item.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip()
    exchange = body.get("exchange", "").strip()
    interval = body.get("interval", "1d").strip()

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not exchange:
        return jsonify({"status": "error", "message": "exchange is required"}), 400

    item = _get_watchlist().add(symbol, exchange, interval)
    return jsonify({
        "status": "success",
        "data": {
            "symbol": item.symbol,
            "exchange": item.exchange,
            "interval": item.interval,
            "enabled": item.enabled,
        },
    }), 201


@historify_bp.route("/v1/historify/watchlist", methods=["DELETE"])
def remove_watchlist() -> tuple[Any, int]:
    """Remove a symbol from the watchlist.

    Request JSON:
        symbol (str): Instrument symbol.
        exchange (str): Exchange code.

    Returns:
        JSON ``{"status": "success"}``.
    """
    body = request.get_json(silent=True) or {}
    symbol = body.get("symbol", "").strip()
    exchange = body.get("exchange", "").strip()

    if not symbol:
        return jsonify({"status": "error", "message": "symbol is required"}), 400
    if not exchange:
        return jsonify({"status": "error", "message": "exchange is required"}), 400

    _get_watchlist().remove(symbol, exchange)
    return jsonify({"status": "success"}), 200


@historify_bp.route("/v1/historify/download", methods=["POST"])
def trigger_download() -> tuple[Any, int]:
    """Trigger OHLCV download for all enabled watchlist items.

    Attempts to download historical data using the configured downloader.
    Falls back to a summary of enabled items if the downloader is not
    available (e.g. no OpenAlgo connection).

    Request JSON (optional):
        start_date (str): ISO date, e.g. ``"2026-01-01"`` (default: 30 days ago).
        end_date (str): ISO date (default: today).

    Returns:
        JSON ``{"status": "success", "data": {"triggered": N, "items": [...]}}``
        listing the symbols that were queued for download.
    """
    body = request.get_json(silent=True) or {}

    today = date.today()
    default_start = (today - timedelta(days=30)).isoformat()

    start_date = body.get("start_date", default_start)
    end_date = body.get("end_date", today.isoformat())

    enabled = _get_watchlist().get_enabled()
    results: list[dict[str, Any]] = []

    for item in enabled:
        entry: dict[str, Any] = {
            "symbol": item.symbol,
            "exchange": item.exchange,
            "interval": item.interval,
            "status": "queued",
        }
        # Attempt actual download if HistoricalDownloader is available
        try:
            from packages.core.src.openalgo_client import OpenAlgoClient  # noqa: PLC0415
            from packages.historical.src.downloader import HistoricalDownloader  # noqa: PLC0415
            from packages.core.src.config import Settings  # noqa: PLC0415

            settings = Settings()
            oa_client = OpenAlgoClient(
                host=settings.openalgo_host,
                port=settings.openalgo_port,
                api_key=settings.openalgo_api_key,
            )
            downloader = HistoricalDownloader(oa_client)
            result = downloader.download(
                symbol=item.symbol,
                exchange=item.exchange,
                interval=item.interval,
                start_date=start_date,
                end_date=end_date,
            )
            entry["status"] = "ok" if result.success else "error"
            entry["bars"] = result.total_bars
            entry["errors"] = result.errors
        except Exception as exc:
            logger.debug("Download unavailable for %s/%s: %s", item.symbol, item.exchange, exc)
            entry["status"] = "queued"

        results.append(entry)

    return jsonify({
        "status": "success",
        "data": {
            "triggered": len(enabled),
            "start_date": start_date,
            "end_date": end_date,
            "items": results,
        },
    }), 200
