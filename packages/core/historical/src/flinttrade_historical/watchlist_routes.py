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
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .historify_jobs import STATUS_REFUSED, HistorifyJobManager
from .watchlist import DownloadWatchlist

logger = logging.getLogger("flinttrade.historical.watchlist_routes")


def _legacy_state_dir() -> Path:
    """Pre-workspace_dir() state directory (a fixed ``~/.flinttrade`` on every OS)."""
    return Path.home() / ".flinttrade"


def _migrate_legacy_watchlist_db(legacy: Path, new: Path) -> None:
    """One-shot copy of a pre-``workspace_dir()`` watchlist DB into the workspace.

    The watchlist default moved from ``~/.flinttrade/watchlist.db`` to
    ``workspace_dir()/watchlist.db`` (macOS: ``~/Library/Application
    Support/flinttrade``; Windows: ``%APPDATA%/flinttrade``) without a
    migration, silently presenting an empty watchlist to existing installs on
    those platforms. Copy — never move; the legacy file stays behind as a
    backup — when the new path is absent and the legacy one exists. No-op on
    Linux where the two paths coincide. Best-effort: a failed copy degrades to
    the empty-watchlist behaviour, never an exception. (Sibling migration:
    ``flinttrade_ai.pipeline`` does the same for ``signal_model.joblib``.)
    """
    try:
        if new.exists() or not legacy.exists():
            return
        if legacy.resolve() == new.resolve():
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, new)
        logger.info("Migrated legacy download watchlist from %s to %s", legacy, new)
    except OSError as exc:
        logger.warning("Could not migrate legacy watchlist DB %s -> %s: %s", legacy, new, exc)

historify_bp = Blueprint("historify", __name__)

# Module-level singleton — replaced by ``init_watchlist_routes`` when injected.
_watchlist: DownloadWatchlist | None = None

# Background download-job manager singleton.
_job_manager: HistorifyJobManager | None = None


def _get_job_manager() -> HistorifyJobManager:
    """Return the module-level download job manager, creating it lazily."""
    global _job_manager  # noqa: PLW0603
    if _job_manager is None:
        _job_manager = HistorifyJobManager()
    return _job_manager


def _get_watchlist() -> DownloadWatchlist:
    """Return the module-level watchlist singleton, creating it lazily."""
    global _watchlist  # noqa: PLW0603
    if _watchlist is None:
        from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

        default_path = workspace_dir() / "watchlist.db"
        _migrate_legacy_watchlist_db(_legacy_state_dir() / "watchlist.db", default_path)
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
    """Start a background OHLCV download for all enabled watchlist items.

    Non-blocking: returns a job id immediately. Poll
    ``GET /v1/historify/download/status?job_id=<id>`` for progress, the
    time-remaining (ETA) estimate, and the disk safety state. Bars are persisted
    via the Historify engine (DuckDB) — the previous synchronous route discarded
    them and, because it constructed OpenAlgoClient with the wrong signature,
    never actually downloaded.

    Request JSON (optional):
        start_date (str): ISO date (default: 30 days ago).
        end_date (str): ISO date (default: today).

    Returns:
        202 with the initial job snapshot, or 507 when the disk safety check
        refuses to start, or 400 when there is nothing enabled / dates invalid.
    """
    body = request.get_json(silent=True) or {}

    today = date.today()
    default_start = (today - timedelta(days=30)).isoformat()
    start_date = body.get("start_date", default_start)
    end_date = body.get("end_date", today.isoformat())

    try:
        from_date = date.fromisoformat(start_date)
        to_date = date.fromisoformat(end_date)
    except ValueError:
        return jsonify({"status": "error", "message": "start_date/end_date must be ISO dates"}), 400

    job = start_watchlist_download(from_date, to_date)
    if job is None:
        return jsonify({"status": "error", "message": "No enabled watchlist items to download"}), 400
    status_code = 507 if job.status == STATUS_REFUSED else 202
    return jsonify({"status": "success", "data": job.to_dict()}), status_code


def start_watchlist_download(from_date: date, to_date: date) -> Any | None:
    """Start a background OHLCV download for all enabled watchlist items.

    The shared core behind both ``POST /v1/historify/download`` and the
    scheduled EOD auto-sync job (one download path — no parallel
    implementations). Returns the initial job snapshot, or ``None`` when the
    watchlist has nothing enabled.
    """
    enabled = _get_watchlist().get_enabled()
    if not enabled:
        return None

    symbols = sorted({(item.symbol, item.exchange) for item in enabled})
    intervals = sorted({item.interval for item in enabled})
    total = len(symbols) * len(intervals)

    try:
        app_obj = current_app._get_current_object()
    except RuntimeError:
        app_obj = None

    async def _runner(progress: Any) -> None:
        from flinttrade_core.openalgo_client import resolve_openalgo_client  # noqa: PLC0415

        from .historify import HistorifyDownloader  # noqa: PLC0415
        from .pipeline import DataPipeline  # noqa: PLC0415

        client, close_client = resolve_openalgo_client(app_obj)
        try:
            downloader = HistorifyDownloader(client, DataPipeline())
            await downloader.download_symbols(
                symbols, intervals, from_date, to_date, progress_callback=progress,
            )
        finally:
            if close_client:
                await client.close()

    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    storage_dir = str(workspace_dir())
    return _get_job_manager().start(total=total, runner=_runner, storage_path=storage_dir)


@historify_bp.route("/v1/historify/download/status", methods=["GET"])
def download_status() -> tuple[Any, int]:
    """Return a download job's progress + ETA + safety state (or all jobs).

    Query:
        job_id (str, optional): When given, return that job; 404 if unknown.
        When omitted, return all jobs.
    """
    job_id = request.args.get("job_id", "").strip()
    mgr = _get_job_manager()
    if job_id:
        job = mgr.get(job_id)
        if job is None:
            return jsonify({"status": "error", "message": f"Unknown job {job_id}"}), 404
        return jsonify({"status": "success", "data": job.to_dict()}), 200
    return jsonify({"status": "success", "data": [j.to_dict() for j in mgr.list_jobs()]}), 200
