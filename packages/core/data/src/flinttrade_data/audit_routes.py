"""Flask blueprint for local audit-trail endpoints.

Two distinct logs are served here:

* The operator's own **action log** (:class:`~flinttrade_data.activity_log.ActivityLog`,
  read from ``current_app.config["ACTIVITY_LOG"]``) — login/logout, admin actions, with
  ``{log_id, action, user, ip, details}`` rows. Served by ``/log``, ``/export``, ``/stats``.
* The **gated-execution audit** (the hash-chain
  :class:`~flinttrade_data.audit_logger.AuditLogger`, read from
  ``current_app.config["AUDIT"]``) — order placements and per-layer safety verdicts, with
  ``{event_type, strategy, symbol, exchange, action, layer, verdict, reason}`` rows. Served
  by ``/events``; this is the source the Automate → Execution Logs viewer reads.

External URLs (frontend / Vite proxy calls these):
    GET /ft-api/v1/audit/log             — Paginated, filterable operator action log.
    GET /ft-api/v1/audit/export          — CSV export of the operator action log.
    GET /ft-api/v1/audit/stats           — Action-type counts for the admin dashboard.
    GET /ft-api/v1/audit/events          — Gated-execution audit for a single day (newest-first).
    GET /ft-api/v1/audit/events/export   — CSV/PDF export of the gated-execution audit over a date range.
    GET /ft-api/v1/audit/events/summary  — Summary statistics for the gated-execution audit over a date range.
    GET /ft-api/v1/audit/verify          — Verify the gated-execution audit hash chain.

The ``/log``, ``/export``, ``/stats`` endpoints serve the operator **action log**;
``/events``, ``/events/export``, ``/events/summary``, ``/verify`` serve the
**gated-execution audit** (via :class:`~flinttrade_data.audit_export.AuditExporter`
for the range export/summary). All are scope-guarded (``admin.audit.read``).

The WSGI prefix stripper in app.py translates /ft-api/v1/* → /v1/* before
Flask dispatch, so the blueprint is registered at /v1/audit (not /ft-api/v1/audit).

Both config instances are populated at startup by
:func:`~flinttrade_core.app.create_flask_app`.

Response conventions:
- All success responses: ``{"status": "success", "data": {...}}``
- All error responses:   ``{"status": "error", "message": "..."}``
- HTTP 503 when the requested log has not been initialised.
"""

from __future__ import annotations

import csv
import io
import logging
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from flinttrade_core.auth_scopes import require_scope

_IST = ZoneInfo("Asia/Kolkata")

# Upper bound on a single gated-audit report span. Generous (two years) — well
# beyond any realistic single export — so it never blocks a legitimate request,
# but bounds the eager per-day expansion so a fat-fingered ``to=9999-...`` cannot
# spin the worker on a multi-million-day loop.
_MAX_REPORT_DAYS = 731

logger = logging.getLogger("flinttrade.data.audit_routes")

audit_bp = Blueprint("audit", __name__, url_prefix="/v1/audit")

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_log() -> Any:
    """Return the ActivityLog instance from the Flask app config.

    Returns:
        ActivityLog instance, or ``None`` if not configured.
    """
    return current_app.config.get("ACTIVITY_LOG")


def _get_audit() -> Any:
    """Return the hash-chain AuditLogger instance from the Flask app config.

    Returns:
        AuditLogger instance, or ``None`` if not configured.
    """
    return current_app.config.get("AUDIT")


def _coerce_num(value: Any) -> float:
    """Coerce a stored audit field to a float, falling back to ``0.0``.

    Order events persist ``quantity``/``price`` as strings; the viewer's
    contract types them as numbers, so coerce defensively.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_report_range() -> tuple[tuple[date, date] | None, tuple[Response, int] | None]:
    """Parse the ``from``/``to`` day range for a gated-audit report.

    Both are required ``YYYY-MM-DD`` dates and ``from`` must be on or before
    ``to`` (the exporter reads whole days inclusively).

    Returns:
        ``((from_date, to_date), None)`` on success, or ``(None, (response, status))``
        with a 400 JSON error describing the problem.
    """
    from_raw = request.args.get("from") or ""
    to_raw = request.args.get("to") or ""
    if not from_raw or not to_raw:
        return None, (
            jsonify({"status": "error", "message": "'from' and 'to' dates (YYYY-MM-DD) are required"}),
            400,
        )
    try:
        from_date = date.fromisoformat(from_raw)
        to_date = date.fromisoformat(to_raw)
    except ValueError:
        return None, (
            jsonify({"status": "error", "message": "Dates must be in YYYY-MM-DD format"}),
            400,
        )
    if from_date > to_date:
        return None, (
            jsonify({"status": "error", "message": "'from' must be on or before 'to'"}),
            400,
        )
    if (to_date - from_date).days + 1 > _MAX_REPORT_DAYS:
        return None, (
            jsonify({"status": "error", "message": f"date range must not exceed {_MAX_REPORT_DAYS} days"}),
            400,
        )
    return (from_date, to_date), None


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/log
# ---------------------------------------------------------------------------


@audit_bp.route("/log", methods=["GET"])
@require_scope("admin.audit.read")
def audit_log() -> tuple[Response, int]:
    """Return a paginated, filterable audit log.

    Reads all entries from the :class:`ActivityLog` and applies
    optional server-side filters before returning.

    Query parameters:
        action  (str):  Dot-namespaced action filter (e.g. ``order.place``).
        user    (str):  Username filter.
        since   (str):  ISO-8601 lower-bound timestamp (inclusive).
        until   (str):  ISO-8601 upper-bound timestamp (inclusive).
        page    (int):  1-based page number (default 1).
        per_page (int): Entries per page, clamped to 1–500 (default 50).

    Returns:
        JSON with paginated entries and pagination metadata::

            {
                "status": "success",
                "data": {
                    "entries": [ { log_id, timestamp, action, user, ip, details } ],
                    "total": 120,
                    "page": 1,
                    "per_page": 50,
                    "pages": 3
                }
            }
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    action: str | None = request.args.get("action") or None
    user: str | None = request.args.get("user") or None
    since: str | None = request.args.get("since") or None
    until: str | None = request.args.get("until") or None

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "page must be an integer"}), 400

    try:
        per_page = max(1, min(500, int(request.args.get("per_page", 50))))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "per_page must be an integer"}), 400

    # Fetch a large batch to support pagination (max 5000 rows per page)
    # For very large deployments this should be pushed down to SQL OFFSET/LIMIT.
    entries = log.query(action=action, user=user, since=since, limit=5000)

    # Apply until filter (activity_log.query only supports since, not until)
    if until:
        until_dt = datetime.fromisoformat(until) if isinstance(until, str) else until
        # Strip timezone for comparison — TIMESTAMP column stores naive datetimes
        until_naive = until_dt.replace(tzinfo=None) if until_dt.tzinfo else until_dt
        entries = [e for e in entries if (e.timestamp.replace(tzinfo=None) if e.timestamp.tzinfo else e.timestamp) <= until_naive]

    total = len(entries)
    import math  # noqa: PLC0415

    pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    page_entries = entries[start : start + per_page]

    payload: list[dict[str, Any]] = [
        {
            "log_id": e.log_id,
            "timestamp": e.timestamp,
            "action": e.action,
            "user": e.user,
            "ip": e.ip,
            "details": e.details,
        }
        for e in page_entries
    ]

    return jsonify({
        "status": "success",
        "data": {
            "entries": payload,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        },
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/export
# ---------------------------------------------------------------------------


@audit_bp.route("/export", methods=["GET"])
@require_scope("admin.audit.read")
def audit_export() -> tuple[Response, int]:
    """Export the audit log as a CSV file.

    Streams the full (or date-bounded) audit log as a UTF-8 CSV attachment.
    CSV export of the operator's audit log (export as much history as is
    retained on disk).

    Query parameters:
        since   (str): ISO-8601 lower-bound timestamp (inclusive).
        until   (str): ISO-8601 upper-bound timestamp (inclusive).
        action  (str): Optional action filter.
        user    (str): Optional user filter.

    Returns:
        ``text/csv`` attachment with headers::

            log_id,timestamp,action,user,ip,details
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    action: str | None = request.args.get("action") or None
    user: str | None = request.args.get("user") or None
    since: str | None = request.args.get("since") or None
    until: str | None = request.args.get("until") or None

    # Pull all matching rows (retention is operator-controlled)
    entries = log.query(action=action, user=user, since=since, limit=100_000)

    if until:
        until_dt = datetime.fromisoformat(until) if isinstance(until, str) else until
        # Strip timezone for comparison — TIMESTAMP column stores naive datetimes
        until_naive = until_dt.replace(tzinfo=None) if until_dt.tzinfo else until_dt
        entries = [e for e in entries if (e.timestamp.replace(tzinfo=None) if e.timestamp.tzinfo else e.timestamp) <= until_naive]

    # Build CSV in memory — acceptable for audit exports (regulatory, not streaming)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["log_id", "timestamp", "action", "user", "ip", "details"])
    for e in entries:
        import json as _json  # noqa: PLC0415

        writer.writerow([
            e.log_id,
            e.timestamp,
            e.action,
            e.user,
            e.ip or "",
            _json.dumps(e.details, ensure_ascii=False),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    response = make_response(csv_bytes)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=flinttrade_audit.csv"
    response.headers["Content-Length"] = str(len(csv_bytes))
    return response, 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/stats
# ---------------------------------------------------------------------------


@audit_bp.route("/stats", methods=["GET"])
@require_scope("admin.audit.read")
def audit_stats() -> tuple[Response, int]:
    """Return action-type counts for the admin dashboard.

    Fetches the last N days of activity and groups entries by action type.
    Useful for the admin panel sparklines and anomaly detection.

    Query parameters:
        since   (str): ISO-8601 lower-bound (default: no lower bound).
        user    (str): Optional user filter.

    Returns:
        JSON with per-action counts and the total::

            {
                "status": "success",
                "data": {
                    "total": 148,
                    "by_action": {
                        "order.place": 42,
                        "order.cancel": 10,
                        "auth.login": 7,
                        ...
                    }
                }
            }
    """
    log = _get_log()
    if log is None:
        return jsonify({"status": "error", "message": "Activity log not initialised"}), 503

    since: str | None = request.args.get("since") or None
    user: str | None = request.args.get("user") or None

    entries = log.query(user=user, since=since, limit=100_000)

    by_action: dict[str, int] = {}
    for e in entries:
        by_action[e.action] = by_action.get(e.action, 0) + 1

    # Sort by count descending for readability
    sorted_counts = dict(
        sorted(by_action.items(), key=lambda item: item[1], reverse=True)
    )

    return jsonify({
        "status": "success",
        "data": {
            "total": len(entries),
            "by_action": sorted_counts,
        },
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events
# ---------------------------------------------------------------------------


@audit_bp.route("/events", methods=["GET"])
@require_scope("admin.audit.read")
def audit_events() -> tuple[Response, int]:
    """Return the gated-execution audit trail for a single day, newest-first.

    Serves the hash-chain :class:`~flinttrade_data.audit_logger.AuditLogger`
    (order placements, per-layer safety verdicts, kill-switch events) — distinct
    from the operator action log at :func:`audit_log`. This is the source the
    Automate → Execution Logs viewer reads, so the rows carry the gated-execution
    shape (``event_type``/``strategy``/``layer``/``verdict``) rather than the
    action-log shape (``user``/``ip``/``details``).

    Query parameters:
        date    (str): Day to read (YYYY-MM-DD). Defaults to today (IST).
        limit   (int): Page size, clamped to 1–500 (default 50).
        offset  (int): 0-based offset into the newest-first list (default 0).

    Returns:
        JSON with the requested page and the day's total::

            {
                "status": "success",
                "data": {
                    "logs": [ { timestamp, event_type, strategy, symbol,
                                exchange, action, quantity, price,
                                layer, verdict, reason } ],
                    "total": 128
                }
            }
    """
    audit = _get_audit()
    if audit is None:
        return jsonify({"status": "error", "message": "Audit log not initialised"}), 503

    day = request.args.get("date") or datetime.now(_IST).strftime("%Y-%m-%d")

    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "offset must be an integer"}), 400

    try:
        events = audit.read_day(day)
    except Exception:  # noqa: BLE001 — a corrupt/unreadable day file is empty, not a 500
        logger.exception("Failed to read audit day %s", day)
        events = []

    # Newest-first: the viewer's "Load More" pages backwards from the latest event.
    events = list(reversed(events))
    total = len(events)
    page = events[offset : offset + limit]

    logs: list[dict[str, Any]] = [
        {
            "timestamp": e.get("ts", ""),
            "event_type": e.get("event_type", ""),
            "strategy": e.get("strategy", ""),
            "symbol": e.get("symbol", ""),
            "exchange": e.get("exchange", ""),
            "action": e.get("action", ""),
            "quantity": _coerce_num(e.get("quantity")),
            "price": _coerce_num(e.get("price")),
            "layer": e.get("layer", ""),
            "verdict": e.get("verdict", ""),
            "reason": e.get("reason", ""),
        }
        for e in page
    ]

    return jsonify({
        "status": "success",
        "data": {"logs": logs, "total": total},
    }), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/verify
# ---------------------------------------------------------------------------


@audit_bp.route("/verify", methods=["GET"])
@require_scope("admin.audit.read")
def audit_verify() -> tuple[Response, int]:
    """Verify the gated-execution audit hash chain and report any tampering.

    Recomputes the SHA-256 chain across every audit file (see
    :meth:`~flinttrade_data.audit_logger.AuditLogger.verify_chain`). ``ok`` is
    true only when every present record links to its predecessor and matches its
    own hash; a ``break`` pinpoints the first interior edit, deletion, insertion,
    or reorder. ``anchored_at_genesis`` reports whether the chain is provably
    complete from its first record (prefix/suffix removal is indistinguishable
    from retention using the log alone).

    Returns:
        ``{"status": "success", "data": {"ok": bool, "checked": int,
        "anchored_at_genesis": bool, "break": {...} | None}}``.
    """
    audit = _get_audit()
    if audit is None:
        return jsonify({"status": "error", "message": "Audit log not initialised"}), 503

    try:
        result = audit.verify_chain()
    except Exception:  # noqa: BLE001 — verification must never 500 the dashboard
        logger.exception("Audit chain verification failed to run")
        return jsonify({"status": "error", "message": "Audit chain verification failed to run"}), 500

    return jsonify({"status": "success", "data": result}), 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events/export
# ---------------------------------------------------------------------------


@audit_bp.route("/events/export", methods=["GET"])
@require_scope("admin.audit.read")
def audit_events_export() -> tuple[Response, int]:
    """Export the gated-execution audit over a date range as CSV or PDF.

    Serves the hash-chain :class:`~flinttrade_data.audit_logger.AuditLogger`
    (order placements + per-layer safety verdicts) via
    :class:`~flinttrade_data.audit_export.AuditExporter`, distinct from the
    operator action log at :func:`audit_export`. PDF needs the optional
    ``reportlab`` dependency; without it the PDF branch returns 500.

    Query parameters:
        format  (str): ``"csv"`` (default) or ``"pdf"``.
        from    (str): First day (inclusive), ``YYYY-MM-DD``.
        to      (str): Last day (inclusive), ``YYYY-MM-DD``.

    Returns:
        A ``text/csv`` or ``application/pdf`` attachment, or a JSON error
        (400 bad dates, 503 audit not initialised, 500 export failure).
    """
    audit = _get_audit()
    if audit is None:
        return jsonify({"status": "error", "message": "Audit log not initialised"}), 503

    rng, err = _parse_report_range()
    if rng is None:
        return err  # type: ignore[return-value] — err is set whenever rng is None
    from_date, to_date = rng

    fmt = (request.args.get("format") or "csv").strip().lower()
    if fmt not in ("csv", "pdf"):
        return jsonify({"status": "error", "message": "format must be 'csv' or 'pdf'"}), 400

    from flinttrade_data.audit_export import AuditExporter, AuditExportError  # noqa: PLC0415

    exporter = AuditExporter(audit)
    suffix = ".pdf" if fmt == "pdf" else ".csv"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            if fmt == "pdf":
                exporter.to_pdf(from_date, to_date, tmp_path)
            else:
                exporter.to_csv(from_date, to_date, tmp_path)
            payload = tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)
    except AuditExportError as exc:
        logger.warning("Gated audit %s export failed: %s", fmt, exc.message)
        return jsonify({"status": "error", "message": "Audit export failed"}), 500
    except Exception:  # noqa: BLE001 — a corrupt/tampered day file must fail loud, not 500 uncaught
        # The gated audit is tamper-evident: a torn/corrupt day makes read_day
        # raise (JSONDecodeError/OSError), which is NOT an AuditExportError. The
        # /events viewer degrades such a day to empty, but an export must not
        # silently emit an incomplete report — fail with a controlled, logged
        # error and let the operator run /verify to locate the break.
        logger.exception("Gated audit %s export failed to read the audit log", fmt)
        return jsonify({"status": "error", "message": "Audit export failed"}), 500

    range_str = f"{from_date.isoformat()}_{to_date.isoformat()}"
    content_type = "application/pdf" if fmt == "pdf" else "text/csv; charset=utf-8"
    response = make_response(payload)
    response.headers["Content-Type"] = content_type
    response.headers["Content-Disposition"] = (
        f"attachment; filename=flinttrade_gated_audit_{range_str}.{fmt}"
    )
    response.headers["Content-Length"] = str(len(payload))
    return response, 200


# ---------------------------------------------------------------------------
# GET /ft-api/v1/audit/events/summary
# ---------------------------------------------------------------------------


@audit_bp.route("/events/summary", methods=["GET"])
@require_scope("admin.audit.read")
def audit_events_summary() -> tuple[Response, int]:
    """Return summary statistics for the gated-execution audit over a date range.

    Args (query):
        from    (str): First day (inclusive), ``YYYY-MM-DD``.
        to      (str): Last day (inclusive), ``YYYY-MM-DD``.

    Returns:
        ``{"status": "success", "data": {total_events, events_by_type,
        orders_placed, orders_rejected, safety_triggers}}``; 400 on bad dates,
        503 when the audit log is not initialised.
    """
    audit = _get_audit()
    if audit is None:
        return jsonify({"status": "error", "message": "Audit log not initialised"}), 503

    rng, err = _parse_report_range()
    if rng is None:
        return err  # type: ignore[return-value] — err is set whenever rng is None
    from_date, to_date = rng

    from flinttrade_data.audit_export import AuditExporter  # noqa: PLC0415

    try:
        stats = AuditExporter(audit).summary_stats(from_date, to_date)
    except Exception:  # noqa: BLE001 — a corrupt/tampered day file must fail loud, not 500 uncaught
        logger.exception("Gated audit summary failed to read the audit log")
        return jsonify({"status": "error", "message": "Audit summary failed"}), 500
    return jsonify({"status": "success", "data": stats}), 200
