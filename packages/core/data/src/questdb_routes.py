"""Flask endpoints for QuestDB tick storage and aggregation.

Registered as a Blueprint by ``create_flask_app()``.

Endpoints
---------
GET  /api/v1/data/questdb/health            — check if QuestDB is running
POST /api/v1/data/questdb/ticks             — bulk insert ticks via ILP
POST /api/v1/data/questdb/query             — execute arbitrary SQL
POST /api/v1/data/questdb/ohlcv             — aggregate OHLCV bars
GET  /api/v1/data/questdb/tick/latest/<sym> — get latest tick for a symbol
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .questdb_bridge import QuestDBBridge, QuestDBBridgeError

logger = logging.getLogger("flinttrade.data.questdb_routes")

questdb_bp = Blueprint("questdb", __name__, url_prefix="/api/v1/data/questdb")

# Module-level singleton — replaced via ``init_questdb_routes`` for DI.
_bridge: QuestDBBridge | None = None


def _get_bridge() -> QuestDBBridge:
    """Return the module-level QuestDBBridge singleton, creating it lazily."""
    global _bridge  # noqa: PLW0603
    if _bridge is None:
        _bridge = QuestDBBridge()
    return _bridge


def init_questdb_routes(bridge: QuestDBBridge) -> None:
    """Inject a QuestDBBridge instance into the blueprint's singleton.

    Args:
        bridge: The :class:`QuestDBBridge` instance to use for all requests.
    """
    global _bridge  # noqa: PLW0603
    _bridge = bridge
    logger.info("QuestDBBridge singleton injected into questdb_routes")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@questdb_bp.route("/health", methods=["GET"])
def health() -> tuple[Response, int]:
    """Check if QuestDB is running and reachable via HTTP.

    Returns:
        JSON ``{"status": "success", "data": {"running": true}}`` when QuestDB
        is up, or ``{"status": "error", ...}`` when it is unreachable.
    """
    bridge = _get_bridge()
    running = bridge.check_health()

    if running:
        return jsonify({"status": "success", "data": {"running": True}}), 200

    return jsonify({
        "status": "error",
        "message": "QuestDB is not reachable. Ensure it is running on the configured host.",
        "data": {"running": False},
    }), 503


# ---------------------------------------------------------------------------
# Tick ingestion
# ---------------------------------------------------------------------------


@questdb_bp.route("/ticks", methods=["POST"])
def insert_ticks() -> tuple[Response, int]:
    """Bulk insert ticks into QuestDB via ILP over TCP.

    Request JSON:
        ticks (list[dict], required): List of tick objects. Each tick must
            have ``symbol``, ``exchange``, and ``ltp``. Optional fields:
            ``open``, ``high``, ``low``, ``close``, ``volume``, ``bid``,
            ``ask``, ``oi``, ``timestamp_ns``.

    Returns:
        JSON ``{"status": "success", "data": {"inserted": N}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}
    ticks: list[dict[str, Any]] = body.get("ticks", [])

    if not isinstance(ticks, list):
        return jsonify({"status": "error", "message": "ticks must be a list"}), 400

    if not ticks:
        return jsonify({"status": "error", "message": "ticks list is empty"}), 400

    try:
        count = bridge.insert_ticks(ticks)
    except QuestDBBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502

    return jsonify({"status": "success", "data": {"inserted": count}}), 200


# ---------------------------------------------------------------------------
# SQL query
# ---------------------------------------------------------------------------


@questdb_bp.route("/query", methods=["POST"])
def run_query() -> tuple[Response, int]:
    """Execute a SQL query against QuestDB.

    Request JSON:
        sql (str, required): SQL query to execute.

    Returns:
        JSON ``{"status": "success", "data": {"rows": [...], "count": N}}``.

    Warning:
        This endpoint is for internal tooling and monitoring only. Do not
        expose it to untrusted clients — it executes raw SQL.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}
    sql: str = body.get("sql", "").strip()

    if not sql:
        return jsonify({"status": "error", "message": "sql is required"}), 400

    try:
        rows = bridge.query(sql)
    except QuestDBBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({
        "status": "success",
        "data": {"rows": rows, "count": len(rows)},
    }), 200


# ---------------------------------------------------------------------------
# OHLCV aggregation
# ---------------------------------------------------------------------------


@questdb_bp.route("/ohlcv", methods=["POST"])
def aggregate_ohlcv() -> tuple[Response, int]:
    """Aggregate tick data into OHLCV bars using QuestDB SAMPLE BY.

    Request JSON:
        symbol   (str, required): Instrument symbol, e.g. ``"NIFTY"``.
        interval (str, required): Bar interval, e.g. ``"1m"``, ``"5m"``, ``"1h"``.
        start    (str, required): ISO 8601 start timestamp.
        end      (str, required): ISO 8601 end timestamp.

    Returns:
        JSON ``{"status": "success", "data": {"bars": [...], "count": N}}``.
    """
    bridge = _get_bridge()
    body: dict[str, Any] = request.get_json(silent=True) or {}

    symbol: str = body.get("symbol", "").strip()
    interval: str = body.get("interval", "").strip()
    start: str = body.get("start", "").strip()
    end: str = body.get("end", "").strip()

    missing = [f for f, v in [("symbol", symbol), ("interval", interval), ("start", start), ("end", end)] if not v]
    if missing:
        return jsonify({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing)}",
        }), 400

    try:
        bars = bridge.aggregate_ohlcv(symbol, interval, start, end)
    except QuestDBBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({
        "status": "success",
        "data": {"bars": bars, "count": len(bars)},
    }), 200


# ---------------------------------------------------------------------------
# Latest tick
# ---------------------------------------------------------------------------


@questdb_bp.route("/tick/latest/<symbol>", methods=["GET"])
def get_latest_tick(symbol: str) -> tuple[Response, int]:
    """Get the most recent tick for a symbol from QuestDB.

    Path parameters:
        symbol: Instrument symbol, e.g. ``NIFTY`` or ``RELIANCE``.

    Returns:
        JSON ``{"status": "success", "data": {...tick fields...}}`` or
        ``{"status": "error", "message": "No data for symbol"}`` when
        the symbol has no ticks stored.
    """
    bridge = _get_bridge()
    try:
        tick = bridge.get_latest_tick(symbol)
    except QuestDBBridgeError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    if tick is None:
        return jsonify({
            "status": "error",
            "message": f"No tick data found for symbol '{symbol}'",
        }), 404

    return jsonify({"status": "success", "data": tick}), 200
