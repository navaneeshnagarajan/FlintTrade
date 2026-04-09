"""Trade Journal Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
POST   /ft-api/v1/journal/           — create a journal entry
GET    /ft-api/v1/journal/           — list entries (with optional query filters)
GET    /ft-api/v1/journal/<id>       — get single entry
PATCH  /ft-api/v1/journal/<id>       — partial update
DELETE /ft-api/v1/journal/<id>       — delete entry
GET    /ft-api/v1/journal/stats      — aggregated statistics
GET    /ft-api/v1/journal/export     — export as CSV download
POST   /ft-api/v1/journal/import     — import from OpenAlgo tradebook JSON
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .trade_journal import JournalEntry, JournalFilters, TradeJournal

logger = logging.getLogger("flinttrade.data.journal_routes")

journal_bp = Blueprint("journal", __name__, url_prefix="/ft-api/v1/journal")

# Module-level singleton — replaced by ``init_journal_routes`` when injected.
_journal: TradeJournal | None = None


def init_journal_routes(journal: TradeJournal) -> None:
    """Inject a TradeJournal instance into the blueprint's module singleton.

    Call this from ``create_flask_app()`` after creating the journal.

    Args:
        journal: The :class:`~trade_journal.TradeJournal` instance to use for
            all incoming requests.
    """
    global _journal  # noqa: PLW0603
    _journal = journal
    logger.info("TradeJournal singleton injected into journal_routes")


def _get_journal() -> TradeJournal:
    """Return the current journal singleton.

    Returns:
        The active :class:`~trade_journal.TradeJournal` instance.

    Raises:
        RuntimeError: If ``init_journal_routes`` has not been called yet.
    """
    if _journal is None:
        raise RuntimeError(
            "TradeJournal not initialised. Call init_journal_routes() first."
        )
    return _journal


def _ok(data: Any, status: int = 200) -> tuple[Any, int]:
    """Return a success JSON response.

    Args:
        data: Serialisable response payload.
        status: HTTP status code.

    Returns:
        Tuple of (Flask Response, status code).
    """
    return jsonify({"status": "success", "data": data}), status


def _err(message: str, status: int = 400) -> tuple[Any, int]:
    """Return an error JSON response.

    Args:
        message: Human-readable error description.
        status: HTTP status code.

    Returns:
        Tuple of (Flask Response, status code).
    """
    return jsonify({"status": "error", "message": message}), status


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@journal_bp.route("/", methods=["POST"])
def create_entry() -> tuple[Any, int]:
    """Create a new trade journal entry.

    Request body (JSON):
        All fields of :class:`~trade_journal.JournalEntry`.
        Required: ``symbol``, ``exchange``, ``side``, ``quantity``,
        ``entry_price``.

    Returns:
        ``{"status": "success", "data": {"id": "<uuid>"}}`` on success.
        ``{"status": "error", "message": "..."}`` on validation failure.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return _err("Request body must be JSON", 400)

    try:
        entry = JournalEntry.model_validate(payload)
    except Exception as exc:
        return _err(f"Validation error: {exc}", 422)

    try:
        entry_id = _get_journal().add_entry(entry)
    except Exception as exc:
        logger.exception("Failed to add journal entry")
        return _err(f"Database error: {exc}", 500)

    return _ok({"id": entry_id}, 201)


@journal_bp.route("/", methods=["GET"])
def list_entries() -> tuple[Any, int]:
    """List journal entries with optional filters.

    Query parameters:
        start_date (str): ISO date ``YYYY-MM-DD``.
        end_date (str): ISO date ``YYYY-MM-DD``.
        symbol (str): Exact symbol filter.
        strategy (str): Exact strategy filter.
        side (str): ``BUY`` or ``SELL``.
        tags (str): Comma-separated tag list — all must be present.
        limit (int): Max results (default 500).
        offset (int): Pagination offset (default 0).

    Returns:
        ``{"status": "success", "data": [<entries>]}``
    """
    tags_raw = request.args.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    try:
        limit = int(request.args.get("limit", 500))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return _err("limit and offset must be integers", 400)

    filters = JournalFilters(
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
        symbol=request.args.get("symbol"),
        strategy=request.args.get("strategy"),
        side=request.args.get("side"),
        tags=tags,
        limit=limit,
        offset=offset,
    )

    try:
        entries = _get_journal().list_entries(filters)
    except Exception as exc:
        logger.exception("Failed to list journal entries")
        return _err(f"Database error: {exc}", 500)

    return _ok([e.model_dump(mode="json") for e in entries])


@journal_bp.route("/stats", methods=["GET"])
def get_stats() -> tuple[Any, int]:
    """Return aggregated statistics for a date range.

    Query parameters:
        start_date (str): ISO date ``YYYY-MM-DD`` (optional).
        end_date (str): ISO date ``YYYY-MM-DD`` (optional).

    Returns:
        ``{"status": "success", "data": <JournalStats>}``
    """
    try:
        stats = _get_journal().get_stats(
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
    except Exception as exc:
        logger.exception("Failed to compute journal stats")
        return _err(f"Database error: {exc}", 500)

    return _ok(stats.model_dump(mode="json"))


@journal_bp.route("/export", methods=["GET"])
def export_csv() -> Response | tuple[Any, int]:
    """Export journal entries as a CSV file download.

    Query parameters:
        start_date (str): ISO date ``YYYY-MM-DD`` (optional).
        end_date (str): ISO date ``YYYY-MM-DD`` (optional).

    Returns:
        ``text/csv`` attachment response.
    """
    try:
        csv_data = _get_journal().export_csv(
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
    except Exception as exc:
        logger.exception("Failed to export journal CSV")
        return _err(f"Export error: {exc}", 500)

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=trade_journal.csv"},
    )


@journal_bp.route("/import", methods=["POST"])
def import_tradebook() -> tuple[Any, int]:
    """Import trades from an OpenAlgo tradebook JSON payload.

    Request body (JSON):
        ``{"trades": [<tradebook rows>]}``

    Returns:
        ``{"status": "success", "data": {"created": <count>, "ids": [...]}}``
    """
    payload = request.get_json(silent=True)
    if not payload or "trades" not in payload:
        return _err("Request body must be JSON with a 'trades' key", 400)

    trades: list[dict] = payload["trades"]
    if not isinstance(trades, list):
        return _err("'trades' must be a list", 400)

    try:
        created_ids = _get_journal().import_from_tradebook(trades)
    except Exception as exc:
        logger.exception("Failed to import tradebook")
        return _err(f"Import error: {exc}", 500)

    return _ok({"created": len(created_ids), "ids": created_ids}, 201)


@journal_bp.route("/<string:entry_id>", methods=["GET"])
def get_entry(entry_id: str) -> tuple[Any, int]:
    """Fetch a single journal entry by its UUID.

    Args:
        entry_id: UUID of the entry (path parameter).

    Returns:
        ``{"status": "success", "data": <entry>}`` or 404.
    """
    try:
        entry = _get_journal().get_entry(entry_id)
    except Exception as exc:
        logger.exception("Failed to get journal entry %s", entry_id)
        return _err(f"Database error: {exc}", 500)

    if entry is None:
        return _err(f"Entry '{entry_id}' not found", 404)

    return _ok(entry.model_dump(mode="json"))


@journal_bp.route("/<string:entry_id>", methods=["PATCH"])
def update_entry(entry_id: str) -> tuple[Any, int]:
    """Partially update an existing journal entry.

    Args:
        entry_id: UUID of the entry (path parameter).

    Request body (JSON):
        Any subset of :class:`~trade_journal.JournalEntry` fields.

    Returns:
        ``{"status": "success", "data": <updated entry>}`` or 404.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return _err("Request body must be JSON", 400)

    try:
        updated = _get_journal().update_entry(entry_id, payload)
    except Exception as exc:
        logger.exception("Failed to update journal entry %s", entry_id)
        return _err(f"Database error: {exc}", 500)

    if updated is None:
        return _err(f"Entry '{entry_id}' not found", 404)

    return _ok(updated.model_dump(mode="json"))


@journal_bp.route("/<string:entry_id>", methods=["DELETE"])
def delete_entry(entry_id: str) -> tuple[Any, int]:
    """Delete a journal entry by its UUID.

    Args:
        entry_id: UUID of the entry (path parameter).

    Returns:
        ``{"status": "success", "data": {"deleted": true}}`` or 404.
    """
    try:
        deleted = _get_journal().delete_entry(entry_id)
    except Exception as exc:
        logger.exception("Failed to delete journal entry %s", entry_id)
        return _err(f"Database error: {exc}", 500)

    if not deleted:
        return _err(f"Entry '{entry_id}' not found", 404)

    return _ok({"deleted": True})
