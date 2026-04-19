"""Master contract status Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET  /admin/contracts/status                    — all broker/exchange sync records
POST /admin/contracts/sync/{broker}/{exchange}  — record a sync (or trigger one)
GET  /admin/contracts/stale                     — contracts older than max_age_hours
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .master_contract_status import MasterContractStatus

logger = logging.getLogger("flinttrade.historical.contract_status_routes")

contract_status_bp = Blueprint("contract_status", __name__)

# Module-level singleton — replaced by init_contract_status_routes when injected.
_status: MasterContractStatus | None = None


def _get_status() -> MasterContractStatus:
    """Return the singleton, creating it lazily on first access."""
    global _status  # noqa: PLW0603
    if _status is None:
        _status = MasterContractStatus()
    return _status


def init_contract_status_routes(status: MasterContractStatus) -> None:
    """Inject a MasterContractStatus instance into the blueprint.

    Args:
        status: The :class:`MasterContractStatus` instance to use.
    """
    global _status  # noqa: PLW0603
    _status = status
    logger.info("MasterContractStatus singleton injected into contract_status_routes")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@contract_status_bp.route("/admin/contracts/status", methods=["GET"])
def get_all_statuses() -> tuple[Any, int]:
    """Return all recorded master contract sync statuses.

    Returns:
        JSON ``{"status": "success", "data": [...]}`` where each element has
        keys ``broker``, ``exchange``, ``last_sync_utc``, ``symbol_count``,
        ``checksum``.
    """
    rows = _get_status().all_statuses()
    return jsonify({"status": "success", "data": rows}), 200


@contract_status_bp.route("/admin/contracts/sync/<broker>/<exchange>", methods=["POST"])
def record_sync(broker: str, exchange: str) -> tuple[Any, int]:
    """Record a manual master contract sync for a broker/exchange pair.

    Path parameters:
        broker (str): Broker identifier, e.g. ``zerodha``.
        exchange (str): Exchange code, e.g. ``NSE``.

    Request JSON (optional):
        symbol_count (int): Number of symbols downloaded (default 0).
        checksum (str): Hash of the contract file (default ``""``).

    Returns:
        JSON ``{"status": "success", "data": {...}}`` with the updated record.
    """
    body = request.get_json(silent=True) or {}
    symbol_count: int = int(body.get("symbol_count", 0))
    checksum: str = str(body.get("checksum", ""))

    svc = _get_status()
    svc.record_sync(broker, exchange, symbol_count, checksum)

    last = svc.last_sync(broker, exchange)
    return jsonify({
        "status": "success",
        "data": {
            "broker": broker.lower(),
            "exchange": exchange.upper(),
            "last_sync_utc": last.isoformat() if last else None,
            "symbol_count": symbol_count,
            "checksum": checksum,
        },
    }), 200


@contract_status_bp.route("/admin/contracts/stale", methods=["GET"])
def get_stale_contracts() -> tuple[Any, int]:
    """Return contracts that need re-syncing.

    Query parameters:
        max_age_hours (int, optional): Staleness threshold in hours (default 24).

    Returns:
        JSON ``{"status": "success", "data": [...]}`` listing stale contracts.
    """
    try:
        max_age_hours = int(request.args.get("max_age_hours", 24))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "max_age_hours must be an integer"}), 400

    if max_age_hours < 1:
        return jsonify({"status": "error", "message": "max_age_hours must be >= 1"}), 400

    stale = _get_status().stale_contracts(max_age_hours=max_age_hours)
    return jsonify({"status": "success", "data": stale}), 200
