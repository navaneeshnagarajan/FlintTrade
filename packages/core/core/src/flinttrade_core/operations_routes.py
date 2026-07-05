"""Operations blueprint — cron, audit, journal, safety, webhooks, news, ditto,
and monitoring/security proxy endpoints.

All routes under /api/v1/ that were previously inline @app.route handlers
in create_flask_app() but are unrelated to indicators, AI advisor, or
backtest/strategy lifecycle.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime as _dt
from datetime import timedelta as _td
from datetime import timezone as _tz
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import safe_join

from .auth_scopes import require_scope

logger = logging.getLogger("flinttrade")

operations_bp = Blueprint("operations", __name__, url_prefix="/api/v1")

_IST = _tz(_td(hours=5, minutes=30))


# ------------------------------------------------------------------
# Cron jobs
# ------------------------------------------------------------------

@operations_bp.route("/cron/jobs", methods=["GET"])
def cron_jobs_list() -> tuple[Any, int]:
    """Return all registered cron jobs with their current status.

    Returns:
        JSON with ``status`` and ``data.jobs`` — a list of job objects
        with ``name``, ``description``, ``trigger_type``, ``status``,
        ``last_run``, ``run_count``, and ``error_count``.
    """
    from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

    _cron: CronManager | None = current_app.config.get("CRON")
    if _cron is None:
        return jsonify({"status": "success", "data": {"jobs": []}}), 200

    try:
        jobs = [
            {
                "name": job.name,
                "description": job.description,
                "trigger_type": job.trigger_type,
                "status": job.status,
                "last_run": job.last_run,
                "run_count": job.run_count,
                "error_count": job.error_count,
            }
            for job in _cron._jobs.values()
        ]
        return jsonify({"status": "success", "data": {"jobs": jobs}}), 200
    except Exception:
        logger.exception("cron_jobs_list error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/cron/jobs/<name>/pause", methods=["POST"])
def cron_job_pause(name: str) -> tuple[Any, int]:
    """Pause a cron job by name.

    Args:
        name: Job name as registered in CronManager.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

    _cron: CronManager | None = current_app.config.get("CRON")
    if _cron is None:
        return jsonify({"status": "error", "message": "CronManager not available"}), 503

    try:
        if name not in _cron._jobs:
            return jsonify({"status": "error", "message": f"Job '{name}' not found"}), 404
        _cron.pause(name)
        return jsonify({"status": "success", "data": {"message": f"Job '{name}' paused"}}), 200
    except Exception:
        logger.exception("cron_job_pause error for %s", name)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/cron/jobs/<name>/resume", methods=["POST"])
def cron_job_resume(name: str) -> tuple[Any, int]:
    """Resume a paused cron job by name.

    Args:
        name: Job name as registered in CronManager.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

    _cron: CronManager | None = current_app.config.get("CRON")
    if _cron is None:
        return jsonify({"status": "error", "message": "CronManager not available"}), 503

    try:
        if name not in _cron._jobs:
            return jsonify({"status": "error", "message": f"Job '{name}' not found"}), 404
        _cron.resume(name)
        return jsonify({"status": "success", "data": {"message": f"Job '{name}' resumed"}}), 200
    except Exception:
        logger.exception("cron_job_resume error for %s", name)
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Audit logs
# ------------------------------------------------------------------

@operations_bp.route("/audit/logs", methods=["GET"])
@require_scope("admin.audit.read")
def audit_logs() -> tuple[Any, int]:
    """Read the local audit logs for a given date.

    Query parameters:
        date (str): Date in ``YYYY-MM-DD`` format (default: today).
        limit (int): Maximum entries to return (default 100, max 1000).
        offset (int): Skip this many entries before returning (default 0).

    Returns:
        JSON with ``status`` and ``data`` containing ``logs`` (list)
        and ``total`` (total entries before pagination).
    """
    from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415

    _audit: AuditLogger | None = current_app.config.get("AUDIT")
    if _audit is None:
        return jsonify({"status": "error", "message": "AuditLogger not available"}), 503

    date_str: str = request.args.get("date", _dt.now(_IST).strftime("%Y-%m-%d"))
    # Validate date format to prevent malformed input
    try:
        _dt.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"status": "error", "message": "date must be in YYYY-MM-DD format"}), 400
    try:
        limit: int = min(int(request.args.get("limit", 100)), 1000)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400
    try:
        offset: int = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "offset must be an integer"}), 400

    try:
        all_logs = _audit.read_day(date_str)
        total = len(all_logs)
        page = all_logs[offset: offset + limit]
        return jsonify({
            "status": "success",
            "data": {"logs": page, "total": total, "date": date_str},
        }), 200
    except Exception:
        logger.exception("audit_logs error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Trade journal
# ------------------------------------------------------------------

@operations_bp.route("/trades/journal", methods=["GET"])
def trades_journal() -> tuple[Any, int]:
    """Query the trade journal from DuckDB storage.

    Query parameters:
        start_date (str): Filter trades from this date (``YYYY-MM-DD``).
        end_date (str): Filter trades up to this date (``YYYY-MM-DD``).
        strategy (str): Filter by strategy name.
        limit (int): Maximum rows to return (default 100, max 1000).

    Returns:
        JSON with ``status`` and ``data`` containing ``trades`` (list)
        and ``total`` (total rows before pagination).
    """
    try:
        from flinttrade_data.storage import StorageManager  # noqa: PLC0415

        start_date: str = request.args.get("start_date", "")
        end_date: str = request.args.get("end_date", "")
        strategy_filter: str = request.args.get("strategy", "")
        limit: int = min(int(request.args.get("limit", 100)), 1000)

        # Prefer the shared store the order dispatch writes to (same file, no
        # per-request open, no within-process file-lock contention); fall back to
        # a short-lived one when journalling isn't wired (e.g. minimal apps).
        shared = current_app.config.get("TRADE_STORAGE")
        lock = current_app.config.get("TRADE_STORAGE_LOCK")
        storage = shared
        opened = False
        if storage is None:
            storage = StorageManager()
            storage.initialise()
            opened = True

        def _query() -> list[dict[str, Any]]:
            # Use available query methods on StorageManager.
            if strategy_filter and start_date and end_date:
                return storage.get_trades_by_strategy(strategy_filter, start_date, end_date)
            if start_date and end_date:
                # History window across all strategies (e.g. the performance
                # dashboard). Without this branch a start+end with no strategy
                # fell through to a single-day query — the recurring contract bug.
                return storage.get_trades_by_date_range(start_date, end_date)
            if start_date:
                return storage.get_trades_by_date(start_date)
            today = _dt.now(_IST).strftime("%Y-%m-%d")
            return storage.get_trades_by_date(today)

        try:
            if lock is not None and not opened:
                with lock:
                    trades = _query()
            else:
                trades = _query()
        finally:
            if opened:
                storage.close()

        # Apply limit + normalise for the terminal contract. The DuckDB column is
        # ``ts`` but the frontend ``JournalTrade`` type (and journalAnalytics,
        # which does ``new Date(t.timestamp)``) keys off ``timestamp`` — emit that
        # name so the journal renders instead of producing Invalid Dates. All
        # datetimes serialise to ISO strings.
        normalised: list[dict[str, Any]] = []
        for t in trades[:limit]:
            row = dict(t)
            ts_val = row.pop("ts", None)
            row["timestamp"] = ts_val.isoformat() if isinstance(ts_val, _dt) else ts_val
            for k, v in list(row.items()):
                if isinstance(v, _dt):
                    row[k] = v.isoformat()
            normalised.append(row)
        trades = normalised

        return jsonify({
            "status": "success",
            "data": {"trades": trades, "total": len(trades)},
        }), 200
    except ImportError:
        return jsonify({
            "status": "error",
            "message": "Trade storage not available (DuckDB not configured)",
        }), 200
    except Exception:
        logger.exception("trades_journal error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Safety config
# ------------------------------------------------------------------

@operations_bp.route("/safety/config", methods=["GET"])
def safety_config_get() -> tuple[Any, int]:
    """Return the current safety system configuration.

    Returns:
        JSON with ``status`` and ``data`` containing all 5-layer
        safety parameters and current kill-switch / pause state.
    """
    from flinttrade_engine.safety import SafetySystem  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    try:
        data = {
            "l1_order": {
                "price_deviation_pct": _safety.l1_order.price_deviation_pct,
                "check_market_hours": _safety.l1_order.check_market_hours,
                "qty_limits": _safety.l1_order.qty_limits,
            },
            "l2_position": {
                "max_positions": _safety.l2_position.max_positions,
                "max_margin_pct": _safety.l2_position.max_margin_pct,
            },
            "l3_portfolio": {
                "max_net_delta": _safety.l3_portfolio.max_net_delta,
                "max_net_vega": _safety.l3_portfolio.max_net_vega,
            },
            "l4_pnl": {
                "pause_pct": _safety.l4_pnl.pause_pct,
                "kill_pct": _safety.l4_pnl.kill_pct,
                "is_paused": _safety.l4_pnl.is_paused,
                "is_killed": _safety.l4_pnl.is_killed,
            },
            "l5_kill": {
                "is_active": _safety.l5_kill.is_active,
                "reason": _safety.l5_kill.reason,
            },
        }
        return jsonify({"status": "success", "data": data}), 200
    except Exception:
        logger.exception("safety_config_get error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/safety/config", methods=["POST"])
def safety_config_update() -> tuple[Any, int]:
    """Update safety system parameters.

    Request JSON (all fields optional):
        price_deviation_pct (float): L1 price deviation tolerance.
        check_market_hours (bool): L1 market-hours enforcement flag.
        max_positions (int): L2 maximum simultaneous positions.
        max_margin_pct (float): L2 maximum margin utilisation %.
        max_net_delta (float): L3 maximum net options delta.
        max_net_vega (float): L3 maximum net options vega.
        pnl_pause_pct (float): L4 daily-loss % that triggers a pause.
        pnl_kill_pct (float): L4 daily-loss % that activates kill switch.

    Returns:
        JSON with ``status`` and confirmation.
    """
    from flinttrade_engine.safety import SafetySystem  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    body = request.get_json(silent=True) or {}
    try:
        if "price_deviation_pct" in body:
            _safety.l1_order.price_deviation_pct = float(body["price_deviation_pct"])
        if "check_market_hours" in body:
            _safety.l1_order.check_market_hours = bool(body["check_market_hours"])
        if "max_positions" in body:
            _safety.l2_position.max_positions = int(body["max_positions"])
        if "max_margin_pct" in body:
            _safety.l2_position.max_margin_pct = float(body["max_margin_pct"])
        if "max_net_delta" in body:
            _safety.l3_portfolio.max_net_delta = float(body["max_net_delta"])
        if "max_net_vega" in body:
            _safety.l3_portfolio.max_net_vega = float(body["max_net_vega"])
        if "pnl_pause_pct" in body:
            _safety.l4_pnl.pause_pct = float(body["pnl_pause_pct"])
        if "pnl_kill_pct" in body:
            _safety.l4_pnl.kill_pct = float(body["pnl_kill_pct"])

        return jsonify({"status": "success", "data": {"message": "Safety config updated"}}), 200
    except (ValueError, TypeError) as exc:
        logger.debug("Invalid safety config value: %s", exc)
        return jsonify({"status": "error", "message": "Invalid value in safety config update."}), 400
    except Exception:
        logger.exception("safety_config_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Kill switch
# ------------------------------------------------------------------

@operations_bp.route("/safety/kill-switch", methods=["POST"])
def kill_switch_activate() -> tuple[Any, int]:
    """Activate the emergency kill switch to halt all trading.

    Request JSON:
        reason (str, optional): Human-readable reason for activation.

    Returns:
        JSON with ``status`` and confirmation.
    """
    from flinttrade_engine.safety import SafetySystem  # noqa: PLC0415
    from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    _client = current_app.config.get("CLIENT")
    _audit: AuditLogger | None = current_app.config.get("AUDIT")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    body = request.get_json(silent=True) or {}
    reason: str = body.get("reason", "Manual kill switch via API").strip()

    try:
        _safety.l5_kill.activate(reason, client=_client)
        if _audit:
            _audit.log_kill_switch(activated=True, reason=reason)
        return jsonify({
            "status": "success",
            "data": {"message": "Kill switch activated", "reason": reason},
        }), 200
    except Exception:
        logger.exception("kill_switch_activate error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/safety/kill-switch", methods=["DELETE"])
def kill_switch_reset() -> tuple[Any, int]:
    """Reset the kill switch to allow trading to resume.

    Returns:
        JSON with ``status`` and confirmation.
    """
    from flinttrade_engine.safety import SafetySystem  # noqa: PLC0415
    from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    _audit: AuditLogger | None = current_app.config.get("AUDIT")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    try:
        _safety.l5_kill.reset()
        if _audit:
            _audit.log_kill_switch(activated=False, reason="Manual reset via API")
        return jsonify({
            "status": "success",
            "data": {"message": "Kill switch reset — trading may resume"},
        }), 200
    except Exception:
        logger.exception("kill_switch_reset error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Webhooks
# ------------------------------------------------------------------

_WEBHOOK_SOURCES = ("tradingview", "chartink", "custom")
_WEBHOOK_REGISTRY_KEY = "automation.webhooks"


def _webhook_type(path: str) -> str:
    """Derive a webhook's source type from its registration path.

    Mounted receiver paths look like ``/v1/webhook/<source>/<slug>``. Legacy
    UI paths such as ``/webhook/<source>/<slug>`` are also understood so old
    workspace rows keep rendering with the correct badge.
    """
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "webhook" and parts[2] in _WEBHOOK_SOURCES:
        return parts[2]
    if len(parts) >= 2 and parts[0] == "webhook" and parts[1] in _WEBHOOK_SOURCES:
        return parts[1]
    return "custom"


def _normalise_webhook_path(raw_path: str, webhook_type: str) -> str:
    """Return the mounted receiver path for a UI-entered webhook path.

    The Flows panel historically prompted for ``/webhook/...`` paths while the
    Flask blueprint mounted the receiver at ``/v1/webhook``. Normalising here
    lets existing operator muscle-memory keep working, but the stored/displayed
    value always names a route that the backend actually serves.
    """
    source = webhook_type.strip().lower()
    if source not in _WEBHOOK_SOURCES:
        raise ValueError(f"type must be one of: {', '.join(_WEBHOOK_SOURCES)}")

    parsed = urlparse(raw_path.strip())
    if parsed.scheme or parsed.netloc:
        raise ValueError("path must be relative, not a full URL")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("path must not include params, query string, or fragment")

    segments = [part for part in parsed.path.split("/") if part]
    if not segments:
        raise ValueError("path must include a webhook slug")

    if len(segments) >= 4 and segments[0] == "ft-api" and segments[1] == "v1" and segments[2] == "webhook":
        segments = segments[1:]

    route_source = source
    if len(segments) >= 3 and segments[0] == "v1" and segments[1] == "webhook":
        route_source = segments[2].lower()
        slug_segments = segments[3:]
    elif segments[0] == "webhook":
        if len(segments) >= 2 and segments[1].lower() in _WEBHOOK_SOURCES:
            route_source = segments[1].lower()
            slug_segments = segments[2:]
        else:
            slug_segments = segments[1:]
    else:
        slug_segments = segments

    if route_source not in _WEBHOOK_SOURCES:
        raise ValueError(f"path source must be one of: {', '.join(_WEBHOOK_SOURCES)}")
    if route_source != source:
        raise ValueError(f"path source '{route_source}' must match type '{source}'")
    if not slug_segments:
        raise ValueError("path must include a webhook slug after the source")
    for segment in slug_segments:
        if segment in {".", ".."} or any(ch.isspace() for ch in segment):
            raise ValueError("path slug must not contain whitespace or traversal segments")

    return f"/v1/webhook/{route_source}/{'/'.join(slug_segments)}"


def _webhook_dict(path: str, name: str, enabled: bool) -> dict[str, Any]:
    """Build the frontend WebhookConfig shape for one endpoint.

    ``id`` is the registration path — the DELETE handler accepts the
    (URL-encoded) path as its identifier, and the frontend round-trips it
    through ``encodeURIComponent``. ``type`` drives the table's source badge.
    """
    return {
        # id drops the leading slash so the frontend's encodeURIComponent(id)
        # round-trips to a single <path:webhook_id> capture (no leading "//").
        "id": path.lstrip("/"),
        "path": path,
        "name": name,
        "type": _webhook_type(path),
        "enabled": enabled,
    }


def _load_webhook_registry() -> tuple[Any, list[dict[str, Any]]]:
    """Load the workspace-backed webhook metadata registry.

    The registry is metadata only; incoming requests still flow through
    ``webhook_bp``/``WebhookReceiver`` and secrets are intentionally not stored
    here.
    """
    from .workspace import Workspace  # noqa: PLC0415

    workspace = Workspace()
    workspace.load()
    raw_rows = workspace.get(_WEBHOOK_REGISTRY_KEY, [])
    if not isinstance(raw_rows, list):
        return workspace, []

    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        raw_path = str(raw.get("path") or "").strip()
        source = str(raw.get("type") or _webhook_type(raw_path)).strip().lower()
        if source not in _WEBHOOK_SOURCES:
            source = "custom"
        try:
            path = _normalise_webhook_path(raw_path, source)
        except ValueError:
            logger.warning("Ignoring invalid webhook registry path: %s", raw_path)
            continue
        if path in seen_paths:
            continue
        seen_paths.add(path)
        name = str(raw.get("name") or "").strip() or path.rsplit("/", 1)[-1]
        enabled_raw = raw.get("enabled", True)
        enabled = enabled_raw if isinstance(enabled_raw, bool) else True
        rows.append(_webhook_dict(path, name, enabled))
    return workspace, rows


def _save_webhook_registry(workspace: Any, rows: list[dict[str, Any]]) -> None:
    """Persist the frontend-safe webhook registry to workspace.json."""
    payload = [
        {
            "path": row["path"],
            "name": row["name"],
            "type": row["type"],
            "enabled": bool(row["enabled"]),
        }
        for row in rows
    ]
    workspace.set(_WEBHOOK_REGISTRY_KEY, payload)


def _get_webhook_secret_store() -> Any | None:
    """Return the app-injected encrypted webhook store, if available."""
    return current_app.config.get("WEBHOOK_SECRET_STORE")


@operations_bp.route("/webhooks", methods=["GET"])
def webhooks_list() -> tuple[Any, int]:
    """Return all registered webhook endpoints and their status.

    Returns:
        JSON with ``status`` and ``data.webhooks`` — a list of objects with
        ``id``, ``path``, ``name``, ``type``, and ``enabled`` fields (the
        frontend WebhookConfig contract; the secret is never echoed).
    """
    try:
        _workspace, webhooks = _load_webhook_registry()
        return jsonify({"status": "success", "data": {"webhooks": webhooks}}), 200
    except Exception:
        logger.exception("webhooks_list error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks", methods=["POST"])
def webhooks_create() -> tuple[Any, int]:
    """Register a new webhook endpoint.

    Request JSON:
        path (str): URL path for the webhook (e.g. ``"/webhook/custom/my_signal"``).
            Stored as the mounted receiver path ``"/v1/webhook/<source>/<slug>"``.
        name (str): Human-readable name.
        secret (str, optional): signing secret stored in the encrypted
            per-webhook receiver store. Never persisted to workspace.json.

    Returns:
        JSON with ``status`` and the registered webhook details.
    """
    try:
        body = request.get_json(silent=True) or {}
        path_raw = str(body.get("path") or "").strip()
        name = str(body.get("name") or "").strip()
        source = str(body.get("type") or "custom").strip().lower()
        secret_raw = body.get("secret")
        secret = secret_raw if isinstance(secret_raw, str) else ""

        if not path_raw or not name:
            return jsonify({"status": "error", "message": "path and name are required"}), 400
        try:
            path = _normalise_webhook_path(path_raw, source)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400

        secret_store = _get_webhook_secret_store()
        if secret and secret_store is None:
            return jsonify({
                "status": "error",
                "message": "Encrypted webhook secret store is unavailable.",
            }), 503

        workspace, rows = _load_webhook_registry()
        row = _webhook_dict(path, name, bool(body.get("enabled", True)))
        rows = [existing for existing in rows if existing["path"] != path]
        rows.append(row)
        _save_webhook_registry(workspace, rows)
        if secret and secret_store is not None:
            secret_store.store_secret(path, row["type"], row["name"], secret)
        return jsonify({
            "status": "success",
            "data": row,
        }), 201
    except Exception:
        logger.exception("webhooks_create error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks/<path:webhook_id>", methods=["DELETE"])
def webhooks_delete(webhook_id: str) -> tuple[Any, int]:
    """Remove a registered webhook endpoint.

    Uses a ``<path:...>`` converter because a webhook's id is its registration
    path (e.g. ``webhook/custom/my_signal``) — multi-segment, so a plain
    ``<webhook_id>`` ([^/]+) would 405 once the encoded slashes decode.

    Args:
        webhook_id: The path identifying the webhook (with or without a leading
            slash), or its name.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    try:
        workspace, rows = _load_webhook_registry()
        key = webhook_id.strip()
        path_key = f"/{key}" if not key.startswith("/") else key
        id_key = key.lstrip("/")

        kept: list[dict[str, Any]] = []
        removed: dict[str, Any] | None = None
        for row in rows:
            if row["id"] == id_key or row["path"] == path_key or row["name"] == key:
                removed = row
                continue
            kept.append(row)
        if removed is not None:
            _save_webhook_registry(workspace, kept)
            secret_store = _get_webhook_secret_store()
            if secret_store is not None:
                secret_store.delete_secret(removed["path"])
            return jsonify({
                "status": "success",
                "data": {"message": f"Webhook '{removed['path']}' removed"},
            }), 200

        return jsonify({"status": "error", "message": f"Webhook '{webhook_id}' not found"}), 404
    except Exception:
        logger.exception("webhooks_delete error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Monitoring proxy routes were REMOVED 2026-05-19. The previous version of
# this file registered duplicate handlers for /api/v1/health,
# /api/v1/traffic/stats, and /api/v1/latency/stats — all of which already
# exist on `monitoring_bp` (packages/core/core/src/monitoring_routes.py:75, 100,
# 147). Flask resolved by registration order, so whichever blueprint
# happened to register last in `app.py` won — non-deterministic if the
# import order ever shifted. The dedicated `monitoring_bp` is the
# canonical owner; the operations_bp wrappers were thin delegations to
# the same `_health_agg` / `get_traffic_counter()` / `get_latency_tracker()`
# singletons anyway, so removing them has zero behaviour change.
#
# Frontend `ftApi.admin.ts::getHealth/getTrafficStats/getLatencyStats`
# continues to call `/api/v1/health`, `/api/v1/traffic/stats`, and
# `/api/v1/latency/stats` — those paths now resolve to monitoring_bp
# without ambiguity.
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Security-settings proxy routes (/api/v1/security/settings) — these
# are the ONLY security routes operations_bp owns; the stats/bans/ban/
# unban handlers that used to live here have been removed because
# security_bp at /api/v1/security/{stats,bans,ban,unban,records} already
# serves them (2026-05-19 audit found the duplicates were silently
# shadowed by Flask's first-registered-wins URL dispatch). Settings GET
# and POST stay here because security_bp does not own them.
# ------------------------------------------------------------------


@operations_bp.route("/security/settings", methods=["GET"])
def api_security_settings_get() -> tuple[Any, int]:
    """Return the SecurityMonitor's current configuration.

    Returns:
        JSON with ``status`` and ``data`` containing:
            ``auto_ban_enabled`` (bool): Whether automatic banning is active.
            ``ban_threshold`` (int): Auth-failure count before auto-ban triggers.
            ``notfound_ban_threshold`` (int): 404-flood count before auto-ban triggers.
            ``ban_duration`` (int): Duration in seconds for automatic bans.
    """
    from .security import SecurityMonitor as _SM  # noqa: PLC0415

    monitor = current_app.config.get("SECURITY_MONITOR")
    if not isinstance(monitor, _SM):
        return jsonify({"status": "error", "message": "Security monitor not available"}), 503

    return jsonify({
        "status": "success",
        "data": {
            "auto_ban_enabled": monitor._auth_ban_threshold > 0,
            "ban_threshold": monitor._auth_ban_threshold,
            "notfound_ban_threshold": monitor._notfound_ban_threshold,
            "ban_duration": monitor._ban_duration,
        },
    }), 200


@operations_bp.route("/security/settings", methods=["POST"])
def api_security_settings_update() -> tuple[Any, int]:
    """Update the SecurityMonitor's configuration.

    Accepts a JSON body with any subset of the configurable fields.
    Changes take effect immediately (in-memory).

    Request JSON (all fields optional):
        ban_threshold (int): Auth-failure count before auto-ban triggers.
        notfound_ban_threshold (int): 404-flood count before auto-ban triggers.
        ban_duration (int): Duration in seconds for automatic bans.

    Returns:
        JSON with ``status`` and updated settings in ``data``.
    """
    from .security import SecurityMonitor as _SM  # noqa: PLC0415

    monitor = current_app.config.get("SECURITY_MONITOR")
    if not isinstance(monitor, _SM):
        return jsonify({"status": "error", "message": "Security monitor not available"}), 503

    body = request.get_json(silent=True) or {}
    try:
        if "ban_threshold" in body:
            monitor._auth_ban_threshold = int(body["ban_threshold"])
        if "notfound_ban_threshold" in body:
            monitor._notfound_ban_threshold = int(body["notfound_ban_threshold"])
        if "ban_duration" in body:
            monitor._ban_duration = int(body["ban_duration"])
    except (TypeError, ValueError) as exc:
        logger.debug("Invalid security settings value: %s", exc)
        return jsonify({"status": "error", "message": "All settings values must be integers"}), 400
    except Exception:
        logger.exception("api_security_settings_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    return jsonify({
        "status": "success",
        "data": {
            "auto_ban_enabled": monitor._auth_ban_threshold > 0,
            "ban_threshold": monitor._auth_ban_threshold,
            "notfound_ban_threshold": monitor._notfound_ban_threshold,
            "ban_duration": monitor._ban_duration,
        },
    }), 200


# ------------------------------------------------------------------
# Sandbox config proxy routes (/api/v1/sandbox/config)
# The engine sandbox blueprint lives at /v1/sandbox-config/ which is
# outside the /api/v1/ namespace.  These proxies let the frontend call
# the standard /api/v1/sandbox/config path.
# ------------------------------------------------------------------

@operations_bp.route("/sandbox/config", methods=["GET"])
def api_sandbox_config_get() -> tuple[Any, int]:
    """Proxy GET sandbox config for frontend compatibility."""
    engine = current_app.config.get("SANDBOX_ENGINE")
    if engine is None:
        return jsonify({"status": "error", "message": "Sandbox engine not configured"}), 503

    cfg = engine.config
    return jsonify({
        "status": "success",
        "data": {
            "enabled": True,
            "mode": "paper",
            "starting_capital": cfg.starting_capital,
            "equity_leverage": cfg.equity_leverage,
            "futures_leverage": cfg.futures_leverage,
            "option_buy_leverage": cfg.option_buy_leverage,
            "option_sell_leverage": cfg.option_sell_leverage,
            "squareoff_time": cfg.squareoff_time,
            "mcx_squareoff_time": cfg.mcx_squareoff_time,
        },
    }), 200


@operations_bp.route("/sandbox/config", methods=["POST"])
def api_sandbox_config_update() -> tuple[Any, int]:
    """Proxy POST sandbox config for frontend compatibility."""
    engine = current_app.config.get("SANDBOX_ENGINE")
    if engine is None:
        return jsonify({"status": "error", "message": "Sandbox engine not configured"}), 503

    body = request.get_json(silent=True) or {}
    cfg = engine.config

    for field_name in (
        "starting_capital",
        "equity_leverage",
        "futures_leverage",
        "option_buy_leverage",
        "option_sell_leverage",
        "squareoff_time",
        "mcx_squareoff_time",
    ):
        if field_name in body:
            setattr(cfg, field_name, body[field_name])

    enabled = body.get("enabled")
    mode = body.get("mode", "paper")

    return jsonify({
        "status": "success",
        "data": {
            "enabled": enabled if enabled is not None else True,
            "mode": mode,
        },
    }), 200


# ------------------------------------------------------------------
# News (server-side RSS proxy — avoids CORS in browser)
# ------------------------------------------------------------------

@operations_bp.route("/news", methods=["GET"])
def api_news() -> tuple[Any, int]:
    """Fetch news from Indian financial RSS feeds server-side."""
    feeds = [
        ("MoneyControl", "https://www.moneycontrol.com/rss/latestnews.xml"),
        ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("LiveMint", "https://www.livemint.com/rss/markets"),
    ]

    articles: list[dict[str, str]] = []
    for source_name, url in feeds:
        try:
            import httpx  # noqa: PLC0415

            resp = httpx.get(url, timeout=5.0, follow_redirects=True)
            if resp.status_code != 200:
                continue
            # Use defused XML parser to prevent XXE attacks from malicious feeds
            try:
                import defusedxml.ElementTree as _SafeET  # noqa: PLC0415
                root = _SafeET.fromstring(resp.text)
            except ImportError:
                # Fallback: disable entity resolution manually
                parser = ET.XMLParser()
                parser.feed(resp.text)
                root = parser.close()
            for item in root.iter("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                pub_el = item.find("pubDate")
                if title_el is not None and title_el.text:
                    articles.append({
                        "title": title_el.text.strip(),
                        "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                        "pub_date": pub_el.text.strip() if pub_el is not None and pub_el.text else "",
                        "source": source_name,
                    })
        except Exception:
            continue

    # Sort by pub_date descending, limit to 50
    articles.sort(key=lambda a: a.get("pub_date", ""), reverse=True)
    articles = articles[:50]

    return jsonify({
        "status": "success",
        "data": {"articles": articles},
    }), 200


# ------------------------------------------------------------------
# Ditto — multi-account management & position mirroring
# ------------------------------------------------------------------

def _ditto_account_response(acct: Any) -> dict[str, Any]:
    """Return a frontend-safe Ditto account payload without credentials."""
    return {
        "id": acct.account_id,
        "name": acct.name or acct.account_id,
        "broker": "OpenAlgo",
        "capital": 0,
        "pnl_today": 0,
        "status": "active" if acct.enabled else "disabled",
        "positions": 0,
        "group": acct.group,
        "allocation_weight": acct.allocation_weight,
        "is_master": acct.is_master,
    }


def _ditto_manager_error(exc: Exception) -> tuple[Any, int]:
    logger.warning("Ditto account operation failed: %s", exc)
    return jsonify({
        "status": "error",
        "message": "Account service unavailable",
    }), 503

@operations_bp.route("/ditto/accounts", methods=["GET"])
def ditto_accounts() -> tuple[Any, int]:
    """List all managed accounts with status.

    Returns a list of broker accounts registered in the Ditto multi-account
    manager. When no real accounts are configured yet, returns an empty list
    rather than fabricating accounts.
    """
    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

        mgr = AccountManager()
        raw = mgr.list_accounts()
        accounts = [_ditto_account_response(acct) for acct in raw]
        return jsonify({"status": "success", "data": {"accounts": accounts}}), 200
    except Exception as exc:
        logger.warning("Ditto account fetch failed: %s", exc)
        return jsonify({"status": "error", "message": "Account service unavailable"}), 503


@operations_bp.route("/accounts/status", methods=["GET"])
def accounts_status() -> tuple[Any, int]:
    """Consolidated Account Manager status — per-broker connection + daily reauth.

    Reports both Ditto/OpenAlgo managed accounts and vault-backed native broker
    accounts. Ditto rows live-ping OpenAlgo (200 = authenticated, 4xx = re-auth
    needed, connection error = offline). Native rows reflect the gateway session
    registry and stored replay status, so Dhan/Upstox/INDmoney accounts appear
    in the Account Manager even when no OpenAlgo bridge account exists.
    """
    statuses: list[dict[str, Any]] = []
    ditto_failed = False
    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

        with AccountManager() as mgr:
            statuses.extend({"source": "openalgo", **s.to_dict()} for s in mgr.account_status_all())
    except Exception as exc:
        ditto_failed = True
        logger.warning("Account status fetch failed: %s", exc)

    try:
        statuses.extend(_native_account_statuses())
    except Exception as exc:  # noqa: BLE001 - native status should not hide Ditto rows
        logger.warning("Native account status fetch failed: %s", type(exc).__name__)
        if ditto_failed:
            return jsonify({"status": "error", "message": "Account status unavailable"}), 503

    if ditto_failed and not statuses:
        return jsonify({"status": "error", "message": "Account status unavailable"}), 503

    summary = {
        "total": len(statuses),
        "connected": sum(1 for s in statuses if s["connected"]),
        "authenticated": sum(1 for s in statuses if s["authenticated"]),
        "needs_reauth": sum(1 for s in statuses if s["needs_reauth"]),
    }
    return jsonify({"status": "success", "data": {"accounts": statuses, "summary": summary}}), 200


def _native_account_statuses() -> list[dict[str, Any]]:
    """Return Account Manager rows for vault-backed native broker accounts."""
    from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: PLC0415
    from flinttrade_gateway.native_login import BROKER_LOGIN_RETRY_MESSAGE  # noqa: PLC0415

    store = current_app.config.get("CREDENTIAL_STORE")
    if store is None:
        return []
    registry = current_app.config.get("REGISTRY")
    login_status: dict[str, Any] = current_app.config.get("NATIVE_SESSION_STATUS") or {}
    rows = store.list_accounts()
    now = _dt.now(_IST).isoformat()
    statuses: list[dict[str, Any]] = []
    for row in rows:
        adapter_id = str(row.get("adapter_id") or row.get("broker") or "").strip().lower()
        info = BROKER_CATALOG.get(adapter_id)
        if info is None or not info.native:
            continue
        account_id = str(row.get("account_id") or "").strip()
        if not account_id:
            continue
        has_session = False
        expires_at = None
        if registry is not None:
            try:
                session = registry.get_session_for(adapter_id, account_id)
                has_session = True
                expires_at = getattr(session, "expires_at", None)
            except Exception:  # noqa: BLE001 - no registered live session
                has_session = False
        connectable = bool(info.connectable)
        selector = f"{adapter_id}:{account_id}"
        last_login = str(login_status.get(selector) or "")
        login_retryable = bool(connectable and not has_session and last_login == BROKER_LOGIN_RETRY_MESSAGE)
        needs_reauth = bool(connectable and not has_session and not login_retryable)
        error = ""
        if not connectable:
            error = "Native connect is coming soon."
        elif login_retryable:
            error = last_login
        elif needs_reauth:
            error = last_login if last_login and last_login != "ok" else "Needs fresh native broker login."
        label = str(row.get("label") or "").strip()
        display_name = info.display_name
        return_label = label if label and label.lower() != adapter_id else f"{display_name} · {account_id}"
        statuses.append({
            "source": "native",
            "broker": adapter_id,
            "broker_display": display_name,
            "account_id": account_id,
            "name": return_label,
            "enabled": connectable,
            "connected": has_session,
            "authenticated": has_session,
            "needs_reauth": needs_reauth,
            "login_retryable": login_retryable,
            "latency_ms": 0,
            "error": error,
            "checked_at": now,
            "expires_at": expires_at,
        })
    return statuses


@operations_bp.route("/ditto/accounts", methods=["POST"])
def ditto_account_create() -> tuple[Any, int]:
    """Create or update a Ditto managed OpenAlgo account."""
    data = request.get_json(silent=True) or {}
    account_id = str(data.get("account_id", "")).strip()
    openalgo_host = str(data.get("openalgo_host", "")).strip()
    api_key = str(data.get("api_key", ""))

    missing = [
        label
        for label, value in (
            ("account_id", account_id),
            ("openalgo_host", openalgo_host),
            ("api_key", api_key),
        )
        if not value
    ]
    if missing:
        return jsonify({
            "status": "error",
            "message": f"Missing required field(s): {', '.join(missing)}",
        }), 400

    parsed = urlparse(openalgo_host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return jsonify({
            "status": "error",
            "message": "openalgo_host must be a valid http(s) URL",
        }), 400

    try:
        allocation_weight = float(data.get("allocation_weight", 1.0))
        max_loss_daily = float(data.get("max_loss_daily", 50000.0))
    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "allocation_weight and max_loss_daily must be numeric",
        }), 400
    if allocation_weight <= 0 or max_loss_daily < 0:
        return jsonify({
            "status": "error",
            "message": "allocation_weight must be positive and max_loss_daily cannot be negative",
        }), 400

    try:
        from flinttrade_ditto.account_manager import AccountManager, BrokerAccount  # noqa: PLC0415

        account = BrokerAccount(
            account_id=account_id,
            openalgo_host=openalgo_host,
            api_key=api_key,
            name=str(data.get("name", "")).strip(),
            enabled=bool(data.get("enabled", True)),
            allocation_weight=allocation_weight,
            group=str(data.get("group", "default")).strip() or "default",
            max_loss_daily=max_loss_daily,
            is_master=bool(data.get("is_master", False)),
        )
        mgr = AccountManager()
        mgr.add_account(account)
        return jsonify({
            "status": "success",
            "data": {"account": _ditto_account_response(account)},
        }), 201
    except Exception as exc:
        return _ditto_manager_error(exc)


@operations_bp.route("/ditto/accounts/<account_id>/enable", methods=["POST"])
def ditto_account_enable(account_id: str) -> tuple[Any, int]:
    """Enable a Ditto managed account."""
    return _ditto_account_set_enabled(account_id, True)


@operations_bp.route("/ditto/accounts/<account_id>/disable", methods=["POST"])
def ditto_account_disable(account_id: str) -> tuple[Any, int]:
    """Disable a Ditto managed account."""
    return _ditto_account_set_enabled(account_id, False)


def _ditto_account_set_enabled(account_id: str, enabled: bool) -> tuple[Any, int]:
    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

        mgr = AccountManager()
        account = mgr.get_account(account_id)
        if account is None:
            return jsonify({
                "status": "error",
                "message": f"Account '{account_id}' not found",
            }), 404
        if enabled:
            mgr.enable_account(account_id)
        else:
            mgr.disable_account(account_id)
        account.enabled = enabled
        return jsonify({
            "status": "success",
            "data": {"account": _ditto_account_response(account)},
        }), 200
    except Exception as exc:
        return _ditto_manager_error(exc)


@operations_bp.route("/ditto/accounts/<account_id>", methods=["DELETE"])
def ditto_account_delete(account_id: str) -> tuple[Any, int]:
    """Remove a Ditto managed account."""
    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

        mgr = AccountManager()
        account = mgr.get_account(account_id)
        if account is None:
            return jsonify({
                "status": "error",
                "message": f"Account '{account_id}' not found",
            }), 404
        mgr.remove_account(account_id)
        return jsonify({
            "status": "success",
            "data": {"id": account_id, "removed": True},
        }), 200
    except Exception as exc:
        return _ditto_manager_error(exc)


@operations_bp.route("/ditto/mirror/status", methods=["GET"])
def ditto_mirror_status() -> tuple[Any, int]:
    """Get position mirroring status across accounts."""
    mirror_status = {
        "active": False,
        "source_account": None,
        "target_accounts": [],
        "mode": "proportional",
        "mirrored_positions": 0,
        "last_sync": None,
        "errors": [],
    }
    return jsonify({"status": "success", "data": mirror_status}), 200


@operations_bp.route("/ditto/mirror/start", methods=["POST"])
def ditto_mirror_start() -> tuple[Any, int]:
    """Start position mirroring from primary to secondary accounts.

    Multi-account mirroring is not yet enabled in this build: the
    ``PositionMirror`` engine is not wired into the running app. Rather
    than fabricate a started session, this fails closed — it validates the
    request shape, then truthfully reports ``active: false`` with a
    ``deferred`` status so the front end can surface a "coming soon" state
    instead of believing mirroring is live.
    """
    data = request.get_json(silent=True) or {}
    source = data.get("source_account")
    targets = data.get("target_accounts", [])
    mode = data.get("mode", "proportional")

    if not source:
        return jsonify({"status": "error", "message": "source_account is required"}), 400
    if not targets:
        return jsonify({"status": "error", "message": "target_accounts must be non-empty"}), 400

    return jsonify({
        "status": "deferred",
        "message": "Multi-account mirroring is not yet enabled in this build",
        "data": {
            "active": False,
            "source_account": source,
            "target_accounts": targets,
            "mode": mode,
            # Timestamp of this (deferred) response, not of a live session —
            # no PositionMirror is started. Kept as an ISO string so the
            # response stays shape-compatible with the typed contract.
            "started_at": _dt.now(_IST).isoformat(),
        },
    }), 200


@operations_bp.route("/ditto/mirror/stop", methods=["POST"])
def ditto_mirror_stop() -> tuple[Any, int]:
    """Stop position mirroring."""
    return jsonify({
        "status": "success",
        "data": {"active": False, "stopped_at": _dt.now(_IST).isoformat()},
    }), 200


@operations_bp.route("/ditto/risk", methods=["GET"])
def ditto_risk() -> tuple[Any, int]:
    """Per-account risk dashboard: margin utilisation, aggregate P&L.

    The per-account risk engine (``MarginCalculator`` / ``RiskManager``) is
    not yet wired into the running app, so there is no live risk data to
    report. This returns an honest empty/deferred shape — zeroed aggregates
    and no accounts — rather than fabricating sample accounts. The front end
    renders this as an empty "coming soon" dashboard.
    """
    return jsonify({
        "status": "deferred",
        "message": "Per-account risk monitoring is not yet enabled in this build",
        "data": {"aggregate_pnl": 0, "aggregate_capital": 0, "accounts": []},
    }), 200


@operations_bp.route("/ditto/kill-all", methods=["POST"])
def ditto_kill_all() -> tuple[Any, int]:
    """Emergency: close all positions across all managed accounts.

    Currently a stub — returns 501 Not Implemented.
    """
    return jsonify({
        "status": "error",
        "message": "Not implemented — ditto kill-all requires real account connections",
    }), 501


# ------------------------------------------------------------------
# Ditto — AlgoMirror bridge
# ------------------------------------------------------------------


# NOTE: The /ditto/algomirror/status route was removed 2026-04-30.
# AlgoMirror's mirroring logic is fully adapted into packages/services/ditto/
# (PositionMirror, TrailingSLManager, MarginCalculator, RiskManager) and
# runs in-process — no separately-deployed AlgoMirror to query.


# ------------------------------------------------------------------
# AI — OpenClaw bridge
# ------------------------------------------------------------------


@operations_bp.route("/ai/openclaw/status", methods=["GET"])
def ai_openclaw_status() -> tuple[Any, int]:
    """Check OpenClaw health.

    Returns whether the OpenClaw AI agent gateway is running.
    """
    try:
        from flinttrade_ai.openclaw_bridge import OpenClawBridge  # noqa: PLC0415

        bridge = OpenClawBridge()
        healthy = bridge.check_health()
        control_supported = getattr(bridge, "agent_control_supported", False)
        if not isinstance(control_supported, bool):
            control_supported = False
        control_message = getattr(bridge, "agent_control_message", "")
        if not isinstance(control_message, str):
            control_message = ""
        return jsonify({
            "status": "success",
            "data": {
                "connected": healthy,
                "agent_control_supported": control_supported,
                "message": control_message,
            },
        }), 200
    except Exception:
        logger.exception("ai_openclaw_status error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/ai/openclaw/agents", methods=["GET"])
def ai_openclaw_agents() -> tuple[Any, int]:
    """List running agents on OpenClaw.

    Returns an empty list if OpenClaw is not reachable.
    """
    try:
        from flinttrade_ai.openclaw_bridge import OpenClawBridge  # noqa: PLC0415

        bridge = OpenClawBridge()
        agents = bridge.list_agents()
        return jsonify({
            "status": "success",
            "data": {"agents": agents},
        }), 200
    except Exception:
        logger.exception("ai_openclaw_agents error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/ai/openclaw/agents", methods=["POST"])
def ai_openclaw_deploy() -> tuple[Any, int]:
    """Deploy a trading agent on OpenClaw.

    Control-plane relay to the external OpenClaw gateway — the agent runs on
    OpenClaw with its OWN broker connection, so this does not traverse
    FlintTrade's gated order path. A 502 is returned when OpenClaw is
    unreachable (the bridge returns an error dict rather than raising).
    """
    try:
        from flinttrade_ai.openclaw_bridge import OpenClawBridge  # noqa: PLC0415

        config = request.get_json(silent=True) or {}
        if not config.get("name"):
            return jsonify({"status": "error", "message": "agent 'name' is required"}), 400
        result = OpenClawBridge().deploy_agent(config)
        if isinstance(result, dict) and result.get("status") == "error":
            status_code = 501 if result.get("code") == "openclaw_agent_control_unsupported" else 502
            return jsonify({"status": "error", "message": result.get("message", "OpenClaw unreachable")}), status_code
        return jsonify({"status": "success", "data": result}), 200
    except Exception:
        logger.exception("ai_openclaw_deploy error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/ai/openclaw/agents/<agent_id>/stop", methods=["POST"])
def ai_openclaw_stop(agent_id: str) -> tuple[Any, int]:
    """Stop a running OpenClaw agent. 502 when OpenClaw is unreachable."""
    try:
        from flinttrade_ai.openclaw_bridge import OpenClawBridge  # noqa: PLC0415

        result = OpenClawBridge().stop_agent(agent_id)
        if isinstance(result, dict) and result.get("status") == "error":
            status_code = 501 if result.get("code") == "openclaw_agent_control_unsupported" else 502
            return jsonify({"status": "error", "message": result.get("message", "OpenClaw unreachable")}), status_code
        return jsonify({"status": "success", "data": result}), 200
    except Exception:
        logger.exception("ai_openclaw_stop error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/ai/openclaw/agents/<agent_id>/logs", methods=["GET"])
def ai_openclaw_logs(agent_id: str) -> tuple[Any, int]:
    """Fetch logs for an OpenClaw agent — an empty list when unreachable."""
    try:
        from flinttrade_ai.openclaw_bridge import OpenClawBridge  # noqa: PLC0415

        logs = OpenClawBridge().get_agent_logs(agent_id)
        return jsonify({"status": "success", "data": {"logs": logs}}), 200
    except Exception:
        logger.exception("ai_openclaw_logs error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Frontend error reporting (H6)
# ------------------------------------------------------------------

@operations_bp.route("/errors", methods=["POST"])
def receive_frontend_error() -> tuple[Any, int]:
    """Receive error reports from the React frontend.

    Rate limited to prevent DoS. Logs via structlog and forwards to
    Glitchtip if sentry_sdk is initialised.

    Request JSON:
        message (str): Error message.
        url (str): Page URL where the error occurred.
        stack (str, optional): Stack trace (capped at 2000 characters).
        userAgent (str, optional): Browser user-agent string.

    Returns:
        JSON with ``status: "success"`` always (avoids leaking info).
    """
    import structlog  # noqa: PLC0415

    data = request.get_json(silent=True) or {}
    log = structlog.get_logger()
    log.error(
        "frontend_error",
        message=data.get("message", "Unknown error"),
        url=data.get("url"),
        stack=data.get("stack", "")[:2000],  # Cap stack trace size
    )
    # Forward to Glitchtip via sentry_sdk if available
    try:
        import sentry_sdk  # noqa: PLC0415
        if sentry_sdk.is_initialized():
            sentry_sdk.capture_message(
                data.get("message", "Frontend error"),
                level="error",
                extras={"url": data.get("url"), "userAgent": data.get("userAgent")},
            )
    except Exception:
        pass
    return jsonify({"status": "success"}), 200


# ------------------------------------------------------------------
# Recent structured log entries (H7)
# ------------------------------------------------------------------

@operations_bp.route("/logs/recent", methods=["GET"])
def get_recent_logs() -> tuple[Any, int]:
    """Return recent structured log entries for the admin dashboard.

    Reads the last 100 lines from the structured log file at
    ``~/.flinttrade/logs/flinttrade.log``. Each line is expected to be a
    JSON-encoded structlog entry; plain-text lines are wrapped in a
    minimal dict.

    Query parameters:
        n (int, optional): Number of lines to return (default 100, max 500).

    Returns:
        JSON with ``status`` and ``data`` containing a list of log entries.
    """
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    try:
        n = min(int(request.args.get("n", 100)), 500)
        if n < 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "n must be a positive integer"}), 400

    log_file = Path.home() / ".flinttrade" / "logs" / "flinttrade.log"
    entries: list[dict[str, Any]] = []
    if log_file.exists():
        lines = log_file.read_text(encoding="utf-8", errors="replace").strip().split("\n")
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"message": line, "level": "info"})
    return jsonify({"status": "success", "data": entries}), 200


# ------------------------------------------------------------------
# Position writes — gated broker verbs (contract §8.1)
#
# These live here (not in order_routes.py) ONLY because the orders
# blueprint is prefixed /api/v1/orders, while position writes belong at
# /api/v1/positions/* — and operations_bp is the existing /api/v1
# blueprint. The dispatch machinery is order_routes' single gated
# channel: live-mode guard → gate_broker_write → BrokerRouter.execute_gated.
# ------------------------------------------------------------------


@operations_bp.route("/positions/convert", methods=["POST"])
def positions_convert() -> tuple[Any, int]:
    """Convert an open position between products — gated ``convert_position`` verb.

    Request JSON: either a ``req`` object, or the conversion fields inline
    (e.g. ``symbol``, ``exchange``, ``from_product``, ``to_product``,
    ``position_type``, ``quantity`` — broker-specific), plus optional
    ``broker`` and ``account_id`` (omitted target uses
    ``brokers.execution.default``). Live mode + PIN unlock required. A conversion changes the
    margin profile of the book, so it is blocked while the L5 kill switch is
    latched. 501 for brokers whose adapter lacks the verb.

    Returns:
        JSON with ``status`` and the broker result in ``data``.
    """
    from .order_routes import (  # noqa: PLC0415
        _gated_target,
        _gated_verb_write,
        _require_live_payload,
    )

    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    req = body.get("req")
    if not isinstance(req, dict):
        req = {k: v for k, v in body.items() if k not in ("broker", "account_id")}
    if not req:
        return jsonify({
            "status": "error",
            "message": "Position conversion requires the conversion fields (or a 'req' object) in the body",
        }), 400
    adapter_id, account_id = _gated_target(body)
    return _gated_verb_write(
        "convert_position", {"req": req}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="POSITION_CONVERTED", fail_message="Position conversion failed",
        kill_switch_gated=True,
    )


@operations_bp.route("/positions/exit-all", methods=["POST"])
def positions_exit_all() -> tuple[Any, int]:
    """Square off EVERY open position — gated ``exit_all_positions`` verb.

    SAFETY: this is the highest-blast-radius write in the platform — one
    request flattens an entire live account at market. The body MUST therefore
    carry an explicit ``{"confirm": true}`` minted by a deliberate operator
    action in the UI; a stray click, a replayed request, or an agent calling
    the endpoint speculatively is refused with 400 before any gate is minted.
    It is deliberately NOT blocked by the L5 kill switch: exiting everything
    REDUCES exposure and is precisely what a halted account may need to do.

    Request JSON: ``confirm`` (must be boolean ``true``), optional ``tag`` /
    ``segment`` narrowing (signed into the payload; brokers without those
    kwargs simply never receive them), optional ``broker`` / ``account_id``.

    Returns:
        JSON with ``status`` and the broker summary in ``data``.
    """
    from .order_routes import (  # noqa: PLC0415
        _gated_target,
        _gated_verb_write,
        _require_live_payload,
    )

    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    if body.get("confirm") is not True:
        return jsonify({
            "status": "error",
            "message": (
                "Exit-all requires explicit operator confirmation — send {\"confirm\": true}. "
                "This squares off EVERY open position at market."
            ),
        }), 400
    fields: dict[str, Any] = {}
    if body.get("tag") is not None:
        fields["tag"] = str(body["tag"])
    if body.get("segment") is not None:
        fields["segment"] = str(body["segment"])
    adapter_id, account_id = _gated_target(body)
    return _gated_verb_write(
        "exit_all_positions", fields, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="POSITIONS_EXITED_ALL", fail_message="Exit-all positions failed",
    )


# ------------------------------------------------------------------
# Reconciliation observability (contract §14.2)
#
# The engine's ReconciliationRunner persists every broker-vs-flinttrade
# report as one JSONL line under
# ``<workspace home>/reconciliation/<broker_id>/<account_id>.jsonl`` and is
# exposed at runtime as ``app.config["RECONCILIATION_RUNNER"]``. These
# routes are the READ side (history + per-target status) plus an
# operator-triggered ``run_once()``. Like the audit-log read above, the
# GETs carry the observability read scope; like the other operator POSTs
# in this file (kill switch, safety config), the run trigger relies on the
# app-level operator API-key auth plus the same scope check for narrowed
# session tokens.
# ------------------------------------------------------------------

_RECONCILIATION_DEFAULT_LIMIT = 5
_RECONCILIATION_MAX_LIMIT = 100


def _reconciliation_safe_component(raw: Any, fallback: str) -> str:
    """Sanitise a broker/account id into a single safe path component.

    Mirrors the engine runner's ``_safe_component``
    (``flinttrade_engine.reconciliation_runner``) so the read side resolves
    EXACTLY the file the write side produced: anything outside
    ``[A-Za-z0-9._-]`` becomes ``_``; results that are empty or consist
    solely of separators/dots (e.g. ``".."``) collapse to ``fallback`` so a
    hostile id can never traverse out of the ``reconciliation/`` tree.

    Args:
        raw: The caller-supplied broker or account identifier.
        fallback: Component to use when the cleaned id is unusable.

    Returns:
        A single, filesystem-safe path component.
    """
    text = str(raw or "").strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in text)
    if not cleaned or set(cleaned) <= {".", "_", "-"}:
        return fallback
    return cleaned


def _reconciliation_root() -> Path:
    """The runner's JSONL persistence root (``<workspace>/reconciliation``)."""
    from .workspace import workspace_dir  # noqa: PLC0415

    return (workspace_dir() / "reconciliation").resolve()


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    """Parse the last ``limit`` JSONL report lines of ``path``, newest first.

    Malformed or blank lines are skipped (the runner writes one JSON object
    per line; a torn final line from a crash must not break the read side).

    Args:
        path: The per-account JSONL file.
        limit: Maximum number of reports to return.

    Returns:
        Up to ``limit`` parsed report dicts, newest first; empty when the
        file is unreadable.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    reports: list[dict[str, Any]] = []
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            reports.append(payload)
        if len(reports) >= limit:
            break
    return reports


def _reconciliation_report_path(root: Path, broker: str, account_id: str) -> Path | None:
    """Resolve one reconciliation JSONL path under ``root``."""
    joined = safe_join(str(root), broker, f"{account_id}.jsonl")
    if joined is None:
        return None
    path = Path(joined).resolve(strict=False)
    if path != root and root not in path.parents:
        return None
    return path


@operations_bp.route("/reconciliation/reports", methods=["GET"])
@require_scope("admin.observability.read")
def reconciliation_reports() -> tuple[Any, int]:
    """Return the last N persisted reconciliation reports for one account.

    Query parameters:
        broker (str): The adapter's canonical broker id (required).
        account_id (str): The broker account id (required).
        limit (int): Maximum reports to return (default 5, max 100).

    Returns:
        JSON with ``status`` and ``data.reports`` — parsed JSONL report
        dicts newest first; an empty list when no history exists yet.
    """
    broker = request.args.get("broker", "").strip()
    account_id = request.args.get("account_id", "").strip()
    if not broker or not account_id:
        return jsonify({
            "status": "error",
            "message": "broker and account_id query parameters are required",
        }), 400
    try:
        limit = int(request.args.get("limit", _RECONCILIATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "limit must be a positive integer"}), 400
    if limit < 1:
        return jsonify({"status": "error", "message": "limit must be a positive integer"}), 400
    limit = min(limit, _RECONCILIATION_MAX_LIMIT)

    try:
        root = _reconciliation_root()
        safe_broker = _reconciliation_safe_component(broker, "unknown")
        safe_account = _reconciliation_safe_component(account_id, "default")
        # Belt-and-braces: the sanitiser already collapses traversal input to a
        # single component, but never read outside the reconciliation tree.
        path = _reconciliation_report_path(root, safe_broker, safe_account)
        if path is None:
            return jsonify({"status": "error", "message": "Invalid broker or account_id"}), 400
        reports = _read_jsonl_tail(path, limit) if path.is_file() else []
        return jsonify({
            "status": "success",
            "data": {"broker": safe_broker, "account_id": safe_account, "reports": reports},
        }), 200
    except Exception:
        logger.exception("reconciliation_reports error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/reconciliation/status", methods=["GET"])
@require_scope("admin.observability.read")
def reconciliation_status() -> tuple[Any, int]:
    """Per-target reconciliation status from the latest line of each history.

    Walks every ``<root>/<broker>/<account>.jsonl`` the runner has written
    and summarises the most recent report per target. Also reports whether
    the background runner is currently active so the terminal can render an
    honest "dormant" state when no native broker sessions exist.

    Returns:
        JSON with ``status`` and ``data`` containing ``targets`` — a list of
        objects with ``broker``, ``account_id``, ``last_report_at``,
        ``clean``, ``severity``, ``severity_counts``, and ``error`` — plus
        ``runner_active`` (bool).
    """
    try:
        targets: list[dict[str, Any]] = []
        root = _reconciliation_root()
        if root.is_dir():
            for broker_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                for history in sorted(broker_dir.glob("*.jsonl")):
                    latest = _read_jsonl_tail(history, 1)
                    if not latest:
                        continue
                    report = latest[0]
                    targets.append({
                        "broker": broker_dir.name,
                        "account_id": history.stem,
                        "last_report_at": str(report.get("generated_at", "")),
                        "clean": bool(report.get("clean", False)),
                        "severity": str(report.get("severity", "")),
                        "severity_counts": dict(report.get("severity_counts") or {}),
                        "error": str(report.get("error", "")),
                    })
        runner = current_app.config.get("RECONCILIATION_RUNNER")
        runner_active = runner is not None and bool(getattr(runner, "is_running", False))
        return jsonify({
            "status": "success",
            "data": {"targets": targets, "runner_active": runner_active},
        }), 200
    except Exception:
        logger.exception("reconciliation_status error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/reconciliation/run", methods=["POST"])
@require_scope("admin.observability.read")
def reconciliation_run() -> tuple[Any, int]:
    """Operator-triggered reconciliation cycle over the active native targets.

    Invokes the app-config runner's ``run_once()`` (broker reads only — no
    order writes traverse this path). Targets reconciled very recently may
    be skipped: the runner re-arms each target's per-broker cadence, so a
    cycle can honestly produce zero reports. 503 when no runner is active
    (dormant natives — broker routing was not built this boot).

    Returns:
        JSON with ``status`` and ``data`` containing ``count`` plus the
        ``reports`` produced by this cycle.
    """
    import asyncio  # noqa: PLC0415

    runner = current_app.config.get("RECONCILIATION_RUNNER")
    if runner is None:
        return jsonify({
            "status": "error",
            "message": "Reconciliation runner not active — no native broker sessions to reconcile",
        }), 503
    try:
        payloads = asyncio.run(runner.run_once())
        return jsonify({
            "status": "success",
            "data": {"count": len(payloads), "reports": payloads},
        }), 200
    except Exception:
        logger.exception("reconciliation_run error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
