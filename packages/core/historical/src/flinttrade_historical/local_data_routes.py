"""Local data-store Flask endpoints — browse downloaded bars, bhavcopy fetch.

Registered as a Blueprint in ``create_flask_app()``. These are the read/fetch
surfaces over the LOCAL historical store: until now downloaded OHLCV lived in
DuckDB reachable only in-process (the backtest connector), and no full-market
EOD (bhavcopy) download existed at all.

Endpoints
---------
GET  /v1/historify/bars           — query locally-downloaded OHLCV bars.
GET  /v1/historify/bars/summary   — per-interval row/symbol counts of the local store.
POST /v1/historify/bhavcopy/download — fetch NSE bhavcopy archives for a date range.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from .pipeline import INTERVAL_TABLES, DataPipeline

logger = logging.getLogger("flinttrade.historical.local_data_routes")

local_data_bp = Blueprint("local_data", __name__)

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 10_000

# Module-level pipeline singleton (injected in tests via init_local_data_routes).
_pipeline: DataPipeline | None = None

# Bhavcopy destination directory override (tests inject a tmp dir).
_bhavcopy_dir: Path | None = None


def init_local_data_routes(
    pipeline: DataPipeline | None = None,
    bhavcopy_dir: Path | None = None,
) -> None:
    """Inject the pipeline/bhavcopy-dir singletons (tests and app factory)."""
    global _pipeline, _bhavcopy_dir  # noqa: PLW0603
    if pipeline is not None:
        _pipeline = pipeline
    if bhavcopy_dir is not None:
        _bhavcopy_dir = bhavcopy_dir


def _get_pipeline() -> DataPipeline:
    global _pipeline  # noqa: PLW0603
    if _pipeline is None:
        _pipeline = DataPipeline()
        _pipeline.initialise()
    return _pipeline


def _get_bhavcopy_dir() -> Path:
    global _bhavcopy_dir  # noqa: PLW0603
    if _bhavcopy_dir is None:
        from flinttrade_core.workspace import bhavcopy_dir  # noqa: PLC0415

        _bhavcopy_dir = bhavcopy_dir()
    return _bhavcopy_dir


@local_data_bp.route("/v1/historify/bars", methods=["GET"])
def query_local_bars() -> tuple[Any, int]:
    """Query locally-downloaded OHLCV bars.

    Query params:
        symbol (str, required), exchange (str, required),
        interval (str, optional, default ``1d`` — one of 1m/5m/15m/1h/D/1d),
        start (str, optional, YYYY-MM-DD), end (str, optional, YYYY-MM-DD),
        limit (int, optional, default 500, cap 10000 — most recent kept).
    """
    symbol = str(request.args.get("symbol", "")).strip().upper()
    exchange = str(request.args.get("exchange", "")).strip().upper()
    interval = str(request.args.get("interval", "1d")).strip()
    if not symbol or not exchange:
        return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

    table = INTERVAL_TABLES.get(interval)
    if table is None:
        return jsonify({
            "status": "error",
            "message": f"Unknown interval {interval!r}. Known: {sorted(INTERVAL_TABLES)}",
        }), 400

    try:
        limit = int(request.args.get("limit", _DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = _DEFAULT_LIMIT
    limit = max(1, min(_MAX_LIMIT, limit))

    try:
        rows = _get_pipeline().get_bars(
            table,
            symbol,
            exchange,
            start_date=request.args.get("start") or None,
            end_date=request.args.get("end") or None,
        )
    except Exception as exc:
        logger.warning("Local bars query failed for %s:%s: %s", exchange, symbol, exc)
        return jsonify({"status": "error", "message": "Local bars query failed"}), 500

    truncated = len(rows) > limit
    if truncated:
        rows = rows[-limit:]
    for row in rows:
        ts = row.get("timestamp")
        if ts is not None and not isinstance(ts, (str, int, float)):
            row["timestamp"] = str(ts)

    return jsonify({
        "status": "success",
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "count": len(rows),
            "truncated": truncated,
            "bars": rows,
        },
    }), 200


@local_data_bp.route("/v1/historify/bars/summary", methods=["GET"])
def local_bars_summary() -> tuple[Any, int]:
    """Summarise the local OHLCV store (per-interval rows/symbols/span)."""
    try:
        summary = _get_pipeline().summary()
    except Exception as exc:
        logger.warning("Local store summary failed: %s", exc)
        return jsonify({"status": "error", "message": "Local store summary failed"}), 500
    return jsonify({"status": "success", "data": {"tables": summary}}), 200


@local_data_bp.route("/v1/historify/bhavcopy/download", methods=["POST"])
def download_bhavcopy() -> tuple[Any, int]:
    """Download NSE bhavcopy archives for a date range to local storage.

    Request JSON:
        start (str, required): YYYY-MM-DD.
        end (str, required): YYYY-MM-DD (inclusive; max 31 calendar days per call).
        segments (list, optional): subset of ``equity``/``fo``/``index``/``full``
            (default: all four).

    Weekends are skipped; NSE holidays surface as per-day errors rather than
    failing the batch. Re-runs skip files already on disk.
    """
    from .bhavcopy import SEGMENTS, BhavcopyDownloader  # noqa: PLC0415

    body = request.get_json(silent=True) or {}
    try:
        start = date.fromisoformat(str(body.get("start", "")))
        end = date.fromisoformat(str(body.get("end", "")))
    except ValueError:
        return jsonify({"status": "error", "message": "start and end must be YYYY-MM-DD"}), 400

    raw_segments = body.get("segments") or list(SEGMENTS)
    segments = [str(s).strip().lower() for s in raw_segments if str(s).strip().lower() in SEGMENTS]
    if not segments:
        return jsonify({
            "status": "error",
            "message": f"segments must be a subset of {list(SEGMENTS)}",
        }), 400

    downloader = BhavcopyDownloader(_get_bhavcopy_dir())
    try:
        result = downloader.download_range(start, end, segments)
    except ValueError as exc:
        logger.info("Bhavcopy range rejected: %s", exc)
        return jsonify({
            "status": "error",
            "message": "Invalid range: end must not precede start and the span is capped at 31 days per call",
        }), 400
    except Exception as exc:
        logger.warning("Bhavcopy download failed: %s", exc)
        return jsonify({"status": "error", "message": "Bhavcopy download failed"}), 500

    return jsonify({
        "status": "success",
        "data": {
            "dest_dir": str(_get_bhavcopy_dir()),
            **result.to_dict(),
        },
    }), 200
