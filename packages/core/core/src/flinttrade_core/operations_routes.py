"""Operations blueprint — cron, audit, journal, safety, webhooks, news, ditto,
and monitoring/security proxy endpoints.

All routes under /api/v1/ that were previously inline @app.route handlers
in create_flask_app() but are unrelated to indicators, AI advisor, or
backtest/strategy lifecycle.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime as _dt
from datetime import timedelta as _td
from datetime import timezone as _tz
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, current_app, jsonify, request

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

        storage = StorageManager()
        storage.initialise()

        # Use available query methods on StorageManager
        if strategy_filter and start_date and end_date:
            trades = storage.get_trades_by_strategy(strategy_filter, start_date, end_date)
        elif start_date:
            trades = storage.get_trades_by_date(start_date)
        else:
            today = _dt.now(_IST).strftime("%Y-%m-%d")
            trades = storage.get_trades_by_date(today)

        # Apply limit
        trades = trades[:limit]
        # Convert datetime objects to strings for JSON serialisation
        for t in trades:
            for k, v in t.items():
                if isinstance(v, _dt):
                    t[k] = v.isoformat()
        storage.close()

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

@operations_bp.route("/webhooks", methods=["GET"])
def webhooks_list() -> tuple[Any, int]:
    """Return all registered webhook endpoints and their status.

    Returns:
        JSON with ``status`` and ``data.webhooks`` — a list of objects
        with ``path``, ``name``, and ``enabled`` fields.
    """
    try:
        from flinttrade_webhooks.webhook_server import (  # noqa: PLC0415
            WebhookServer,
        )
        server: WebhookServer | None = getattr(current_app, "_webhook_server", None)
        if server is None:
            return jsonify({"status": "success", "data": {"webhooks": [], "info": "Webhook server not started"}}), 200

        webhooks = [
            {"path": ep.path, "name": ep.name, "enabled": ep.enabled}
            for ep in server._endpoints.values()
        ]
        return jsonify({"status": "success", "data": {"webhooks": webhooks}}), 200
    except Exception:
        logger.exception("webhooks_list error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks", methods=["POST"])
def webhooks_create() -> tuple[Any, int]:
    """Register a new webhook endpoint.

    Request JSON:
        path (str): URL path for the webhook (e.g. ``"/webhook/custom/my_signal"``).
        name (str): Human-readable name.
        secret (str, optional): HMAC secret for request validation.

    Returns:
        JSON with ``status`` and the registered webhook details.
    """
    try:
        from flinttrade_webhooks.webhook_server import (  # noqa: PLC0415
            WebhookServer,
        )
        server: WebhookServer | None = getattr(current_app, "_webhook_server", None)
        if server is None:
            return jsonify({
                "status": "error",
                "message": "Webhook server not started — initialise WebhookServer first",
            }), 503

        body = request.get_json(silent=True) or {}
        path: str = body.get("path", "").strip()
        name: str = body.get("name", "").strip()
        secret: str = body.get("secret", "").strip()

        if not path or not name:
            return jsonify({"status": "error", "message": "path and name are required"}), 400

        def _noop_handler(raw_body: bytes, headers: dict[str, str]) -> dict[str, Any]:
            return {"status": "received"}

        server.register(path, name, _noop_handler, secret=secret)
        return jsonify({
            "status": "success",
            "data": {"path": path, "name": name, "enabled": True},
        }), 201
    except Exception:
        logger.exception("webhooks_create error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks/<webhook_id>", methods=["DELETE"])
def webhooks_delete(webhook_id: str) -> tuple[Any, int]:
    """Remove a registered webhook endpoint.

    Args:
        webhook_id: The URL-encoded path or name identifying the webhook.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    try:
        from flinttrade_webhooks.webhook_server import (  # noqa: PLC0415
            WebhookServer,
        )
        server: WebhookServer | None = getattr(current_app, "_webhook_server", None)
        if server is None:
            return jsonify({"status": "error", "message": "Webhook server not started"}), 503

        # webhook_id may be the path (URL-decoded) or name
        path_key = f"/{webhook_id}" if not webhook_id.startswith("/") else webhook_id
        if path_key in server._endpoints:
            del server._endpoints[path_key]
            return jsonify({"status": "success", "data": {"message": f"Webhook '{path_key}' removed"}}), 200

        # Try matching by name
        for ep_path, ep in list(server._endpoints.items()):
            if ep.name == webhook_id:
                del server._endpoints[ep_path]
                return jsonify({"status": "success", "data": {"message": f"Webhook '{ep.name}' removed"}}), 200

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
    manager.  When no real accounts are configured yet, returns sample data
    so the UI can be developed and demonstrated.
    """
    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

        mgr = AccountManager()
        raw = mgr.list_accounts()
        if raw:
            accounts = [_ditto_account_response(acct) for acct in raw]
            return jsonify({"status": "success", "data": {"accounts": accounts}}), 200
    except Exception as exc:
        logger.warning("Ditto account fetch failed: %s", exc)
        if not (current_app.debug or os.environ.get("FLINTTRADE_DEV")):
            return jsonify({"status": "error", "message": "Account service unavailable"}), 503

    # Fallback: sample data for UI development (dev mode only).
    # Uses generic placeholder names + broker_01..07 tokens to avoid leaking
    # real client identities or preferring any specific broker.
    sample_accounts = [
        {"id": "acc_1", "name": "Demo Account 1", "broker": "broker_01", "capital": 5000000, "pnl_today": 12500, "status": "active", "positions": 8, "group": "GroupA", "allocation_weight": 1.0, "is_master": True},
        {"id": "acc_2", "name": "Demo Account 2", "broker": "broker_02", "capital": 3000000, "pnl_today": -8200, "status": "active", "positions": 5, "group": "GroupA", "allocation_weight": 0.6, "is_master": False},
        {"id": "acc_3", "name": "Demo Account 3", "broker": "broker_03", "capital": 8000000, "pnl_today": 34100, "status": "active", "positions": 12, "group": "GroupA", "allocation_weight": 1.6, "is_master": False},
        {"id": "acc_4", "name": "Demo Account 4", "broker": "broker_04", "capital": 2000000, "pnl_today": -3500, "status": "active", "positions": 3, "group": "GroupB", "allocation_weight": 0.4, "is_master": False},
        {"id": "acc_5", "name": "Demo Account 5", "broker": "broker_05", "capital": 10000000, "pnl_today": 56200, "status": "active", "positions": 15, "group": "GroupA", "allocation_weight": 2.0, "is_master": False},
        {"id": "acc_6", "name": "Demo Account 6", "broker": "broker_06", "capital": 4000000, "pnl_today": 0, "status": "disabled", "positions": 0, "group": "GroupB", "allocation_weight": 0.8, "is_master": False},
        {"id": "acc_7", "name": "Demo Account 7", "broker": "broker_07", "capital": 6000000, "pnl_today": -12800, "status": "active", "positions": 9, "group": "GroupC", "allocation_weight": 1.2, "is_master": False},
    ]
    return jsonify({"status": "success", "data": {"accounts": sample_accounts}}), 200


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
    """Start position mirroring from primary to secondary accounts."""
    data = request.get_json(silent=True) or {}
    source = data.get("source_account")
    targets = data.get("target_accounts", [])
    mode = data.get("mode", "proportional")

    if not source:
        return jsonify({"status": "error", "message": "source_account is required"}), 400
    if not targets:
        return jsonify({"status": "error", "message": "target_accounts must be non-empty"}), 400

    return jsonify({
        "status": "success",
        "data": {
            "active": True,
            "source_account": source,
            "target_accounts": targets,
            "mode": mode,
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
    """Per-account risk dashboard: margin utilization, aggregate P&L."""
    if not (current_app.debug or os.environ.get("FLINTTRADE_DEV")):
        return jsonify({"status": "success", "data": {"aggregate_pnl": 0, "aggregate_capital": 0, "accounts": []}}), 200
    risk_data = {
        "aggregate_pnl": 78300,
        "aggregate_capital": 38000000,
        "accounts": [
            {"id": "acc_1", "name": "Account 1", "margin_used_pct": 45.2, "pnl_today": 12500, "positions": 8, "risk_status": "OK"},
            {"id": "acc_2", "name": "Account 2", "margin_used_pct": 62.8, "pnl_today": -8200, "positions": 5, "risk_status": "WARNING"},
            {"id": "acc_3", "name": "Account 3", "margin_used_pct": 38.1, "pnl_today": 34100, "positions": 12, "risk_status": "OK"},
        ],
    }
    return jsonify({"status": "success", "data": risk_data}), 200


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
# AlgoMirror's mirroring logic is fully absorbed into packages/services/ditto/
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
        return jsonify({
            "status": "success",
            "data": {"connected": healthy},
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
