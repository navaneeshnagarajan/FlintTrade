"""Trade Journal Flask endpoints (SQLite + FTS5 TradeJournal).

Registered as a Blueprint in ``create_flask_app()``. Distinct from the
execution-record ``/trades/journal`` route (which reads the raw ``trades``
table): these endpoints serve the annotated journal — notes, emotions, setup /
execution quality, tags, screenshots — with full-text search.

Endpoints (all under ``/api/v1/journal``)
-----------------------------------------
GET    /entries            — list, filterable (start_date/end_date/symbol/
                             strategy/side/tags/limit/offset)
POST   /entries            — create an entry from a JSON body
GET    /entries/<id>       — fetch one entry
PATCH  /entries/<id>       — partial update (pnl recomputes when price/qty change)
DELETE /entries/<id>       — delete one entry
GET    /search?q=          — FTS5 search over symbol/notes/tags/strategy
GET    /stats              — aggregate win rate / P&L / breakdowns
GET    /export             — CSV export (text/csv attachment)
POST   /import             — bulk import from OpenAlgo tradebook rows

Response conventions match the rest of the API: ``{"status": "success",
"data": ...}`` / ``{"status": "error", "message": "..."}``; HTTP 503 when the
journal store has not been initialised.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from flinttrade_journal.trade_journal import JournalEntry, JournalFilters, TradeJournal

logger = logging.getLogger("flinttrade.journal.routes")

journal_bp = Blueprint("journal", __name__, url_prefix="/api/v1/journal")

# Module-level singleton — injected by ``init_journal_routes`` at app startup.
_journal: TradeJournal | None = None

# Keys a client must never set directly on create/update — they are managed by
# the model / store (identity + audit timestamps).
_IMMUTABLE_KEYS = frozenset({"id", "created_at", "updated_at"})


def init_journal_routes(journal: TradeJournal) -> None:
    """Inject the :class:`TradeJournal` instance the blueprint should use."""
    global _journal  # noqa: PLW0603
    _journal = journal
    logger.info("TradeJournal singleton injected into journal_routes")


def _get_journal() -> TradeJournal | None:
    return _journal


def _ok(data: Any, code: int = 200) -> tuple[Response, int]:
    return jsonify({"status": "success", "data": data}), code


def _err(message: str, code: int) -> tuple[Response, int]:
    return jsonify({"status": "error", "message": message}), code


def _int_arg(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    return max(lo, min(hi, int(raw)))


@journal_bp.route("/entries", methods=["GET"])
def list_entries() -> tuple[Response, int]:
    """List journal entries, newest first, with optional filters."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    try:
        limit = _int_arg("limit", 100, lo=1, hi=1000)
        offset = _int_arg("offset", 0, lo=0, hi=1_000_000)
    except (ValueError, TypeError):
        return _err("limit and offset must be integers", 400)

    tags_raw = request.args.get("tags", "")
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    filters = JournalFilters(
        start_date=request.args.get("start_date") or None,
        end_date=request.args.get("end_date") or None,
        symbol=request.args.get("symbol") or None,
        strategy=request.args.get("strategy") or None,
        side=request.args.get("side") or None,
        tags=tags,
        limit=limit,
        offset=offset,
    )
    entries = journal.list_entries(filters)
    return _ok({"entries": [e.model_dump(mode="json") for e in entries], "total": len(entries)})


@journal_bp.route("/entries", methods=["POST"])
def create_entry() -> tuple[Response, int]:
    """Create a journal entry from a JSON body."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _err("Request body must be a JSON object", 400)
    payload = {k: v for k, v in body.items() if k not in _IMMUTABLE_KEYS}
    try:
        entry = JournalEntry.model_validate(payload)
    except ValidationError as exc:
        return _err(f"Invalid journal entry: {exc.errors()[0]['msg']}", 400)
    journal.add_entry(entry)
    return _ok(entry.model_dump(mode="json"), 201)


@journal_bp.route("/entries/<entry_id>", methods=["GET"])
def get_entry(entry_id: str) -> tuple[Response, int]:
    """Fetch a single journal entry by id."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    entry = journal.get_entry(entry_id)
    if entry is None:
        return _err("Entry not found", 404)
    return _ok(entry.model_dump(mode="json"))


@journal_bp.route("/entries/<entry_id>", methods=["PATCH"])
def update_entry(entry_id: str) -> tuple[Response, int]:
    """Partially update a journal entry."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _err("Request body must be a JSON object", 400)
    updates = {k: v for k, v in body.items() if k not in _IMMUTABLE_KEYS}
    try:
        updated = journal.update_entry(entry_id, updates)
    except ValidationError as exc:
        return _err(f"Invalid update: {exc.errors()[0]['msg']}", 400)
    if updated is None:
        return _err("Entry not found", 404)
    return _ok(updated.model_dump(mode="json"))


@journal_bp.route("/entries/<entry_id>", methods=["DELETE"])
def delete_entry(entry_id: str) -> tuple[Response, int]:
    """Delete a journal entry by id."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    if not journal.delete_entry(entry_id):
        return _err("Entry not found", 404)
    return _ok({"deleted": entry_id})


@journal_bp.route("/search", methods=["GET"])
def search() -> tuple[Response, int]:
    """Full-text search over symbol / notes / tags / strategy."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    query = request.args.get("q", "")
    try:
        limit = _int_arg("limit", 100, lo=1, hi=1000)
        offset = _int_arg("offset", 0, lo=0, hi=1_000_000)
    except (ValueError, TypeError):
        return _err("limit and offset must be integers", 400)
    hits = journal.search(query, limit=limit, offset=offset)
    return _ok({"entries": [e.model_dump(mode="json") for e in hits], "total": len(hits)})


@journal_bp.route("/stats", methods=["GET"])
def stats() -> tuple[Response, int]:
    """Aggregate journal statistics over an optional date range."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    result = journal.get_stats(
        start_date=request.args.get("start_date") or None,
        end_date=request.args.get("end_date") or None,
    )
    return _ok(result.model_dump(mode="json"))


@journal_bp.route("/export", methods=["GET"])
def export_csv() -> tuple[Response, int]:
    """Export journal entries as a CSV attachment."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    csv_text = journal.export_csv(
        start_date=request.args.get("start_date") or None,
        end_date=request.args.get("end_date") or None,
    )
    resp = Response(csv_text, mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=trade-journal.csv"
    return resp, 200


@journal_bp.route("/import", methods=["POST"])
def import_tradebook() -> tuple[Response, int]:
    """Bulk-create entries from OpenAlgo tradebook rows (skips duplicates)."""
    journal = _get_journal()
    if journal is None:
        return _err("Journal not initialised", 503)
    body = request.get_json(silent=True)
    trades = body.get("trades") if isinstance(body, dict) else body
    if not isinstance(trades, list):
        return _err("Request body must be a list of trades or {\"trades\": [...]}", 400)
    created = journal.import_from_tradebook(trades)
    return _ok({"created": created, "count": len(created)}, 201)
