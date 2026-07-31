"""Operator-controlled, privacy-preserving support diagnostics."""

from __future__ import annotations

import logging
import platform
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from flask import Blueprint, Response, current_app, has_app_context, jsonify
from werkzeug.exceptions import HTTPException

from .auth_scopes import require_scope
from .version import APP_VERSION_TAG

logger = logging.getLogger("flinttrade.support")

support_bp = Blueprint("support", __name__, url_prefix="/v1/support")

_MAX_ERROR_ROWS = 100
_MAX_ERROR_GROUPS = 50
_SAFE_METHOD = re.compile(r"^[A-Z]{1,12}$")
_SAFE_ERROR_CLASS = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$")
_FRONTEND_ROUTES = frozenset(
    {
        "admin",
        "ai",
        "automate",
        "ditto",
        "explore",
        "home",
        "invest",
        "lab",
        "learn",
        "settings",
        "setup",
        "setup-account",
        "terminal",
        "trade",
        "welcome",
    }
)


def _safe_frontend_route(path: str) -> str:
    """Collapse a client URL to a known top-level screen without path identifiers."""
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return "/"
    if segments[:2] == ["admin", "observability"]:
        return "/admin/observability"
    return f"/{segments[0]}" if segments[0] in _FRONTEND_ROUTES else "/frontend"


def _safe_route(value: Any, *, method: str) -> str:
    """Return a route template without authorities, queries or concrete identifiers."""
    raw = str(value or "").strip()
    if not raw:
        return "unknown"
    try:
        parsed = urlsplit(raw)
        candidate = parsed.path or "unknown"
    except ValueError:
        candidate = raw.split("?", 1)[0].split("#", 1)[0]
    cleaned = "".join(character for character in candidate if character.isprintable())[:240]
    if not cleaned:
        return "unknown"
    if method == "CLIENT":
        return _safe_frontend_route(cleaned)
    if not has_app_context():
        return "/unmatched"
    try:
        adapter = current_app.url_map.bind("localhost")
        rule, _arguments = adapter.match(cleaned, method=method, return_rule=True)
        return str(rule)
    except (HTTPException, RuntimeError, ValueError):
        return "/unmatched"


def _safe_method(value: Any) -> str:
    method = str(value or "UNKNOWN").strip().upper()
    return method if _SAFE_METHOD.fullmatch(method) else "UNKNOWN"


def _safe_status(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 0 <= status <= 599 else None


def _safe_error_class(value: Any) -> str:
    error_class = str(value or "UnknownError").strip()
    return error_class if _SAFE_ERROR_CLASS.fullmatch(error_class) else "UnknownError"


def _safe_timestamp(value: Any) -> str:
    """Parse and re-emit a timestamp so arbitrary log text cannot enter the export."""
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat()


def _aggregate_errors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int | None, str], dict[str, Any]] = {}
    for row in rows[:_MAX_ERROR_ROWS]:
        method = _safe_method(row.get("method"))
        key = (
            _safe_route(row.get("route"), method=method),
            method,
            _safe_status(row.get("status_code")),
            _safe_error_class(row.get("error_class")),
        )
        timestamp = _safe_timestamp(row.get("timestamp"))
        group = groups.get(key)
        if group is None:
            group = {
                "route": key[0],
                "method": key[1],
                "status_code": key[2],
                "error_class": key[3],
                "occurrences": 0,
                "first_seen": timestamp,
                "last_seen": timestamp,
            }
            groups[key] = group
        group["occurrences"] += 1
        if timestamp:
            first_seen = str(group["first_seen"] or "")
            last_seen = str(group["last_seen"] or "")
            group["first_seen"] = min(first_seen, timestamp) if first_seen else timestamp
            group["last_seen"] = max(last_seen, timestamp) if last_seen else timestamp

    ordered = sorted(
        groups.values(),
        key=lambda group: (str(group["last_seen"]), int(group["occurrences"])),
        reverse=True,
    )
    return ordered[:_MAX_ERROR_GROUPS]


def _error_summary() -> dict[str, Any]:
    error_log = current_app.config.get("ERROR_LOG")
    if error_log is None:
        return {"available": False, "total": 0, "sampled": 0, "groups": []}
    try:
        rows = list(error_log.recent_metadata(limit=_MAX_ERROR_ROWS))[:_MAX_ERROR_ROWS]
        return {
            "available": True,
            "total": int(error_log.count()),
            "sampled": len(rows),
            "groups": _aggregate_errors(rows),
        }
    except Exception as exc:  # noqa: BLE001 - support diagnostics must degrade, not fail startup
        logger.warning("Support error summary unavailable (%s)", type(exc).__name__)
        return {"available": False, "total": 0, "sampled": 0, "groups": []}


@support_bp.route("/diagnostics", methods=["GET"])
@require_scope("admin.errors.read")
def support_diagnostics() -> Response:
    """Return bounded diagnostics that are safe to review or attach publicly."""
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "app": {"name": "FlintTrade", "version": APP_VERSION_TAG},
        "runtime": {
            "os": platform.system() or "unknown",
            "os_release": platform.release() or "unknown",
            "architecture": platform.machine() or "unknown",
            "python": platform.python_version(),
        },
        "errors": _error_summary(),
    }
    response = jsonify({"status": "success", "data": payload})
    response.headers["Cache-Control"] = "no-store"
    return response


__all__ = ["support_bp", "support_diagnostics"]
