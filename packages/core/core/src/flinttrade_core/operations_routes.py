"""Operations blueprint — cron, audit, journal, safety, webhooks, news, ditto,
and monitoring/security proxy endpoints.

All routes under /api/v1/ that were previously inline @app.route handlers
in create_flask_app() but are unrelated to indicators, AI advisor, or
backtest/strategy lifecycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import queue
import stat
import threading
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from filelock import FileLock
from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.utils import safe_join

from .auth_scopes import require_scope

logger = logging.getLogger("flinttrade")

operations_bp = Blueprint("operations", __name__, url_prefix="/api/v1")

_IST = _tz(_td(hours=5, minutes=30))
_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS = 5.0
_DITTO_CONTROL_LOCK = threading.RLock()
_WEBHOOK_REGISTRY_LOCK_TIMEOUT_SECONDS = 10.0


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
        page = all_logs[offset : offset + limit]
        return jsonify(
            {
                "status": "success",
                "data": {"logs": page, "total": total, "date": date_str},
            }
        ), 200
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

        return jsonify(
            {
                "status": "success",
                "data": {"trades": trades, "total": len(trades)},
            }
        ), 200
    except ImportError:
        return jsonify(
            {
                "status": "error",
                "message": "Trade storage not available (DuckDB not configured)",
            }
        ), 200
    except Exception:
        logger.exception("trades_journal error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


# ------------------------------------------------------------------
# Safety config
# ------------------------------------------------------------------


def _daily_pnl_selector(values: Mapping[str, Any]) -> tuple[str | None, tuple[Any, int] | None]:
    """Return an exact optional selector from request values."""
    from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415

    adapter_id = str(values.get("broker") or "").strip().lower()
    account_id = str(values.get("account_id") or "").strip()
    if bool(adapter_id) != bool(account_id):
        return None, (
            jsonify({"status": "error", "message": "Both broker and account_id are required"}),
            400,
        )
    if not adapter_id:
        return None, None
    selector = f"{adapter_id}:{account_id}"
    try:
        parse_selector(selector)
    except ValueError:
        return None, (jsonify({"status": "error", "message": "Invalid account selector"}), 400)
    return selector, None


def _authorise_daily_pnl_selector(jwt_payload: Mapping[str, Any], selector: str) -> tuple[Any, int] | None:
    """Require the authenticated operator to own the selected execution account."""
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    router = current_app.config.get("BROKER_ROUTER")
    authorised_selectors = getattr(router, "authorised_selectors", None)
    authorised = set(authorised_selectors(actor_id)) if callable(authorised_selectors) else set()
    if selector not in authorised:
        return jsonify({"status": "error", "message": "Account selector is not authorised"}), 403
    return None


def _authorised_account_selectors(
    jwt_payload: Mapping[str, Any],
) -> tuple[set[str] | None, tuple[Any, int] | None]:
    """Return the current router generation's account ACL for one operator."""
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    router = current_app.config.get("BROKER_ROUTER")
    authorised_selectors = getattr(router, "authorised_selectors", None)
    if not callable(authorised_selectors):
        return None, (
            jsonify({"status": "error", "message": "Broker account authorisation is unavailable"}),
            503,
        )
    return set(authorised_selectors(actor_id)), None


@operations_bp.route("/safety/config", methods=["GET"])
def safety_config_get() -> tuple[Any, int]:
    """Return the current safety system configuration.

    Returns:
        JSON with ``status`` and ``data`` containing all 5-layer
        safety parameters and current kill-switch / pause state.
    """
    from flinttrade_engine.safety import EmergencyDispatchResult, SafetySystem  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    try:
        selected_selector, selector_error = _daily_pnl_selector(request.args)
        if selector_error is not None:
            return selector_error
        selected_l4_state = None
        l4_states = ()
        if selected_selector is not None:
            jwt_payload, auth_error = _authenticated_live_operator()
            if auth_error is not None:
                return auth_error
            assert jwt_payload is not None
            selector_auth_error = _authorise_daily_pnl_selector(jwt_payload, selected_selector)
            if selector_auth_error is not None:
                return selector_auth_error
            selected_l4_state = _safety.l4_pnl.state(selected_selector)
            l4_states = (selected_l4_state,) if selected_l4_state is not None else ()
        last_emergency_result = _safety.l5_kill.last_emergency_result
        if not isinstance(last_emergency_result, EmergencyDispatchResult):
            last_emergency_result = None
        is_l5_active = bool(_safety.l5_kill.is_active)
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
                "selector": selected_selector,
                "opening_risk_capital": (
                    selected_l4_state.opening_risk_capital if selected_l4_state is not None else 0.0
                ),
                "is_paused": (
                    selected_l4_state.paused if selected_selector is not None else _safety.l4_pnl.is_paused
                ),
                "is_killed": (
                    selected_l4_state.killed if selected_selector is not None else _safety.l4_pnl.is_killed
                ),
                "accounts": [
                    {
                        "selector": state.selector,
                        "session_key": state.session_key,
                        "opening_risk_capital": state.opening_risk_capital,
                        "is_paused": state.paused,
                        "is_killed": state.killed,
                    }
                    for state in l4_states
                ],
            },
            "l5_kill": {
                "is_active": is_l5_active,
                "reason": _safety.l5_kill.reason,
                "flatten_complete": (
                    last_emergency_result.complete
                    if is_l5_active and last_emergency_result is not None
                    else not is_l5_active
                ),
                "emergency_result": (last_emergency_result.as_dict() if last_emergency_result is not None else None),
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
        pnl_kill_pct (float): L4 daily-loss % that latches the new-order hard stop.
            Layer 4 does not activate the Layer 5 cancel-and-flatten workflow.

    Returns:
        JSON with ``status`` and confirmation.
    """
    from flinttrade_engine.daily_pnl_state import DailyPnLStateError  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        SafetyConfigApplicationError,
        SafetySystem,
    )

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    raw_body = request.get_json(silent=True)
    if not isinstance(raw_body, dict):
        return jsonify({"status": "error", "message": "Safety config update must be a JSON object"}), 400
    body: dict[str, Any] = raw_body
    jwt_payload, auth_error = _authenticated_live_operator(require_unlock=True)
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None
    try:
        allowed_fields = {
            "price_deviation_pct",
            "check_market_hours",
            "max_positions",
            "max_margin_pct",
            "max_net_delta",
            "max_net_vega",
            "pnl_pause_pct",
            "pnl_kill_pct",
            "opening_risk_capital",
            "broker",
            "account_id",
        }
        global_fields = allowed_fields - {"opening_risk_capital", "broker", "account_id"}
        unknown_fields = sorted(set(body) - allowed_fields)
        if unknown_fields:
            raise ValueError(f"unknown safety config fields: {', '.join(unknown_fields)}")
        if not body:
            raise ValueError("safety config update cannot be empty")
        if "opening_risk_capital" in body and set(body) & global_fields:
            raise ValueError("opening risk capital must be configured separately from global safety limits")

        update_and_persist = getattr(_safety, "update_and_persist_config", None)
        if not callable(update_and_persist):
            return jsonify({"status": "error", "message": "Durable safety configuration is unavailable"}), 503

        def finite_number(name: str, *, minimum: float, maximum: float | None = None) -> float:
            raw_value = body[name]
            if isinstance(raw_value, bool):
                raise ValueError(f"{name} must be numeric")
            value = float(raw_value)
            if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
                raise ValueError(f"{name} is outside its permitted range")
            return value

        updates: dict[str, Any] = {}
        if "price_deviation_pct" in body:
            updates["price_deviation_pct"] = finite_number(
                "price_deviation_pct", minimum=0.0, maximum=100.0
            )
        if "check_market_hours" in body:
            if not isinstance(body["check_market_hours"], bool):
                raise ValueError("check_market_hours must be a boolean")
            updates["check_market_hours"] = body["check_market_hours"]
        if "max_positions" in body:
            raw_max_positions = body["max_positions"]
            if isinstance(raw_max_positions, bool) or not isinstance(raw_max_positions, int):
                raise ValueError("max_positions must be an integer")
            max_positions = raw_max_positions
            if max_positions < 0:
                raise ValueError("max_positions cannot be negative")
            updates["max_positions"] = max_positions
        if "max_margin_pct" in body:
            updates["max_margin_pct"] = finite_number("max_margin_pct", minimum=0.0, maximum=100.0)
        if "max_net_delta" in body:
            updates["max_net_delta"] = finite_number("max_net_delta", minimum=0.0)
        if "max_net_vega" in body:
            updates["max_net_vega"] = finite_number("max_net_vega", minimum=0.0)

        if "pnl_pause_pct" in body:
            updates["pnl_pause_pct"] = finite_number("pnl_pause_pct", minimum=0.0)
        if "pnl_kill_pct" in body:
            updates["pnl_kill_pct"] = finite_number("pnl_kill_pct", minimum=0.0)

        configured_state = None
        capital_selector: str | None = None
        capital: float | None = None
        if "opening_risk_capital" in body:
            capital_selector, selector_error = _daily_pnl_selector(body)
            if selector_error is not None:
                return selector_error
            if capital_selector is None:
                return jsonify(
                    {"status": "error", "message": "Opening risk capital requires an exact account selector"}
                ), 400
            selector_auth_error = _authorise_daily_pnl_selector(jwt_payload, capital_selector)
            if selector_auth_error is not None:
                return selector_auth_error
            if isinstance(body["opening_risk_capital"], bool):
                raise ValueError("opening risk capital must be numeric")
            capital = float(body["opening_risk_capital"])
            if not math.isfinite(capital) or capital <= 0:
                raise ValueError("opening risk capital must be positive and finite")
        elif "broker" in body or "account_id" in body:
            raise ValueError("account selector is only valid with opening risk capital")

        if "opening_risk_capital" in body:
            assert capital_selector is not None and capital is not None
            configured_state = _safety.l4_pnl.configure_opening_capital(capital_selector, capital)

        if set(body) & global_fields:
            from .safety_config import persist_workspace_safety_config  # noqa: PLC0415
            from .workspace import workspace_dir  # noqa: PLC0415

            try:
                update_and_persist(
                    updates,
                    lambda config: persist_workspace_safety_config(workspace_dir(), config),
                )
            except SafetyConfigApplicationError:
                current_app.config["SAFETY_CONFIG_READY"] = False
                from .app import retire_broker_router_generation  # noqa: PLC0415

                retire_broker_router_generation(current_app)
                logger.critical("Persisted safety configuration could not be published; routing retired")
                return jsonify({"status": "error", "message": "Safety configuration requires restart"}), 503
            except Exception as exc:  # noqa: BLE001 - old in-memory config remains authoritative
                logger.error("Safety configuration persistence failed (%s)", type(exc).__name__)
                return jsonify({"status": "error", "message": "Safety configuration could not be persisted"}), 503

        if configured_state is not None:
            audit = current_app.config.get("AUDIT")
            log_event = getattr(audit, "log_event", None)
            if callable(log_event):
                try:
                    log_event(
                        "L4_OPENING_CAPITAL_FROZEN",
                        selector=configured_state.selector,
                        session_key=configured_state.session_key,
                    )
                except Exception:  # noqa: BLE001 - state is already durable
                    logger.exception("Opening-risk-capital audit write failed")

        return jsonify({"status": "success", "data": {"message": "Safety config updated"}}), 200
    except DailyPnLStateError as exc:
        logger.warning("Opening risk capital update refused: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 409
    except (ValueError, TypeError) as exc:
        logger.debug("Invalid safety config value: %s", exc)
        return jsonify({"status": "error", "message": "Invalid value in safety config update."}), 400
    except Exception:
        logger.exception("safety_config_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/safety/l4", methods=["DELETE"])
def daily_pnl_latches_reset() -> tuple[Any, int]:
    """Reset one selector's current-session L4 latches without changing capital."""
    from flinttrade_engine.daily_pnl_state import DailyPnLStateError  # noqa: PLC0415
    from flinttrade_engine.safety import SafetySystem  # noqa: PLC0415

    safety: SafetySystem | None = current_app.config.get("SAFETY")
    if safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    values: dict[str, Any] = dict(request.args)
    raw_body = request.get_json(silent=True)
    if isinstance(raw_body, dict):
        values.update(raw_body)
    selector, selector_error = _daily_pnl_selector(values)
    if selector_error is not None:
        return selector_error
    if selector is None:
        return jsonify({"status": "error", "message": "L4 reset requires an exact account selector"}), 400

    jwt_payload, auth_error = _authenticated_live_operator(require_unlock=True)
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None
    selector_auth_error = _authorise_daily_pnl_selector(jwt_payload, selector)
    if selector_auth_error is not None:
        return selector_auth_error

    try:
        state = safety.l4_pnl.reset(selector)
    except DailyPnLStateError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 409
    except Exception:
        logger.exception("Daily P&L latch reset failed")
        return jsonify({"status": "error", "message": "Daily-loss state is unavailable"}), 503

    audit = current_app.config.get("AUDIT")
    log_event = getattr(audit, "log_event", None)
    if callable(log_event):
        try:
            log_event("L4_LATCHES_RESET", selector=selector, session_key=state.session_key)
        except Exception:  # noqa: BLE001 - reset is already durable
            logger.exception("Daily P&L reset audit write failed")
    return jsonify(
        {
            "status": "success",
            "data": {
                "selector": selector,
                "session_key": state.session_key,
                "opening_risk_capital": state.opening_risk_capital,
                "is_paused": state.paused,
                "is_killed": state.killed,
            },
        }
    ), 200


# ------------------------------------------------------------------
# Kill switch
# ------------------------------------------------------------------


def _authenticated_live_operator(
    *,
    require_unlock: bool = False,
) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Return verified Live JWT claims or a ready Flask error response."""
    from .order_routes import _decode_request_payload  # noqa: PLC0415

    jwt_payload = _decode_request_payload()
    if not jwt_payload:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Authentication required - provide a valid JWT",
                }
            ),
            401,
        )
    if jwt_payload.get("mode") != "live":
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Protected safety actions require an authenticated Live session",
                }
            ),
            403,
        )
    if require_unlock and jwt_payload.get("live_mode_unlocked") is not True:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Live mode must be PIN-unlocked before changing protected safety state",
                }
            ),
            403,
        )
    jti = str(jwt_payload.get("jti") or "").strip()
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    if not jti or not actor_id:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Authenticated emergency principal is missing identity claims",
                }
            ),
            401,
        )
    return jwt_payload, None


def _authenticated_operator_identity() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Return verified session claims for account-scoped observability reads."""
    from .order_routes import _decode_request_payload  # noqa: PLC0415

    jwt_payload = _decode_request_payload()
    if not jwt_payload:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Authentication required - provide a valid session JWT",
                }
            ),
            401,
        )
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    if not actor_id:
        return None, (
            jsonify(
                {
                    "status": "error",
                    "message": "Authenticated observability principal is missing identity claims",
                }
            ),
            401,
        )
    return jwt_payload, None


@operations_bp.route("/safety/kill-switch", methods=["POST"])
def kill_switch_activate() -> tuple[Any, int]:
    """Activate L5 and run its cancel-all/exit-all policy through BrokerRouter.

    Request JSON:
        reason (str, optional): Human-readable reason for activation.

    L5 is process-global and always targets every registered execution account.
    Per-account ``broker`` / ``account_id`` narrowing is refused so a successful
    partial flatten cannot later unblock untouched accounts.

    A valid live-session JWT is required so the emergency writes carry the same
    selector ACL identity as every other broker mutation. A fresh PIN unlock is
    deliberately not required: cancel/exit reduce exposure and must remain
    available after the L5 latch. There is no raw OpenAlgo fallback.

    Returns:
        JSON with the latched state and bounded per-verb emergency outcomes.
    """
    from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext, parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
        SafetySystem,
        bounded_generation_lease,
    )

    from .order_routes import _run_on_client_loop  # noqa: PLC0415

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    _audit: AuditLogger | None = current_app.config.get("AUDIT")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    jwt_payload, auth_error = _authenticated_live_operator()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    raw_body = request.get_json(silent=True)
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
    reason = str(body.get("reason") or "Manual kill switch via API").strip()
    reason = reason[:500] or "Manual kill switch via API"
    explicit_adapter = str(body.get("broker") or "").strip().lower()
    explicit_account = str(body.get("account_id") or "").strip()
    if bool(explicit_adapter) != bool(explicit_account):
        return jsonify(
            {
                "status": "error",
                "message": "Emergency target requires both broker and account_id, or neither",
            }
        ), 400
    if explicit_adapter:
        return jsonify(
            {
                "status": "error",
                "message": "The L5 kill switch is global and cannot be narrowed to one account",
            }
        ), 400

    jti = str(jwt_payload.get("jti") or "").strip()
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    if not jti or not actor_id:
        return jsonify(
            {
                "status": "error",
                "message": "Authenticated emergency principal is missing identity claims",
            }
        ), 401

    app_obj = current_app._get_current_object()
    rebuild_lock = app_obj.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    try:
        # Latch FIRST, lease for the sweep after: L5 must latch even while a
        # router rebuild holds the generation lock (a busy rebuild previously
        # returned 503 with NO latch, leaving normal writes flowing). activate()
        # latches under the KillSwitch condition and the dispatcher then takes
        # the generation lease around target snapshot + broker sweep, so the
        # global lock order (generation lease -> KillSwitch condition -> router
        # generation condition) is preserved and a busy lease degrades to a
        # bounded generation_lease_unavailable outcome with the latch held.
        def _generation_lease() -> Any:
            return bounded_generation_lease(
                rebuild_lock,
                timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
            )

        def _targets_provider() -> tuple[EmergencyBrokerTarget, ...]:
            router = app_obj.config.get("BROKER_ROUTER")
            configured = getattr(router, "configured_selectors", ())
            selectors = tuple(configured) if isinstance(configured, tuple) else ()
            if not selectors:
                raise ValueError("no configured emergency execution selectors")
            targets: list[EmergencyBrokerTarget] = []
            for selector in selectors:
                adapter_id, account_id = parse_selector(selector)
                request_ctx = RequestContext(
                    jti=jti,
                    actor_type="human",
                    actor_id=actor_id,
                    mode="live",
                    selector=selector,
                )
                targets.append(
                    EmergencyBrokerTarget(
                        request_ctx=request_ctx,
                        adapter_id=adapter_id,
                        account_id=account_id,
                    )
                )
            return tuple(targets)

        dispatcher = GatedEmergencyBrokerDispatcher(
            router_provider=lambda: app_obj.config.get("BROKER_ROUTER"),
            targets_provider=_targets_provider,
            run_awaitable=_run_on_client_loop,
            generation_lease_provider=_generation_lease,
            # The shared process-wide wrapper: fallback replay/acknowledgement
            # continuity must span activations during a storage outage.
            intent_journal=(
                app_obj.config.get("EMERGENCY_INTENT_JOURNAL_WRAPPER")
                or app_obj.config.get("EMERGENCY_INTENT_JOURNAL")
            ),
        )
        emergency_result = _safety.l5_kill.activate(
            reason,
            emergency_dispatcher=dispatcher,
            replace_scope=True,
        )
    except Exception:
        logger.exception("kill_switch_activate error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    audit_recorded = _audit is None
    if _audit:
        try:
            _audit.log_kill_switch(activated=True, reason=reason)
        except Exception:
            logger.exception("Kill switch activated but its audit record could not be persisted")
        else:
            audit_recorded = True
    response_status = 200 if emergency_result.complete else 207
    response_kind = "success" if emergency_result.complete else "partial"
    message = (
        "Kill switch activated and emergency broker actions completed"
        if emergency_result.complete
        else "Kill switch activated, but one or more emergency broker actions did not complete"
    )
    return jsonify(
        {
            "status": response_kind,
            "message": message,
            "data": {
                "message": message,
                "reason": reason,
                "is_active": _safety.l5_kill.is_active,
                "audit_recorded": audit_recorded,
                "emergency_actions": emergency_result.as_dict(),
            },
        }
    ), response_status


@operations_bp.route("/safety/kill-switch", methods=["DELETE"])
def kill_switch_reset() -> tuple[Any, int]:
    """Reset the kill switch to allow trading to resume.

    Returns:
        JSON with ``status`` and confirmation.
    """
    from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
    from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        KillSwitchResetAuthorisationError,
        SafetySystem,
        bounded_generation_lease,
    )

    _safety: SafetySystem | None = current_app.config.get("SAFETY")
    _audit: AuditLogger | None = current_app.config.get("AUDIT")
    if _safety is None:
        return jsonify({"status": "error", "message": "SafetySystem not available"}), 503

    jwt_payload, auth_error = _authenticated_live_operator(require_unlock=True)
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    emergency_result = _safety.l5_kill.last_emergency_result
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    rebuild_lock = current_app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())

    def _authorise_final_selectors(selectors: frozenset[str]) -> bool:
        router = current_app.config.get("BROKER_ROUTER")
        authorised_selectors = getattr(router, "authorised_selectors", None)
        authorised = set(authorised_selectors(actor_id)) if callable(authorised_selectors) else set()
        return selectors.issubset(authorised)

    raw_body = request.get_json(silent=True)
    body: dict[str, Any] = raw_body if isinstance(raw_body, dict) else {}
    override_incomplete = (
        body.get("confirm_incomplete") is True and body.get("confirmation") == "RESET WITH OPEN EXPOSURE"
    )
    if (
        _safety.l5_kill.is_active
        and (emergency_result is None or not emergency_result.complete)
        and not override_incomplete
    ):
        return jsonify(
            {
                "status": "error",
                "message": "Emergency broker actions are incomplete; retry flattening before reset",
                "data": {
                    "is_active": True,
                    "emergency_actions": (emergency_result.as_dict() if emergency_result is not None else None),
                },
            }
        ), 409

    try:
        # Drain admitted emergency work before taking the generation lease. An
        # activation increments the L5 dispatch count before it tries to acquire
        # this same lease; taking the lease while waiting would starve that
        # activation and could turn a valid flatten into a timeout. The zero-time
        # reset recheck below closes the race between the drain and the lease.
        _safety.l5_kill.wait_for_idle()
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            _safety.l5_kill.reset(
                require_complete=not override_incomplete,
                timeout=0,
                authorise_selectors=_authorise_final_selectors,
            )
    except GenerationLeaseUnavailableError:
        return jsonify(
            {
                "status": "error",
                "message": "Broker routing generation is busy; kill switch remains active",
            }
        ), 503
    except KillSwitchResetAuthorisationError:
        return jsonify(
            {
                "status": "error",
                "message": "Kill-switch reset is not authorised for every affected account",
            }
        ), 403
    except SafetyBypassError:
        latest_result = _safety.l5_kill.last_emergency_result
        return jsonify(
            {
                "status": "error",
                "message": "Emergency broker actions are incomplete; retry flattening before reset",
                "data": {
                    "is_active": _safety.l5_kill.is_active,
                    "emergency_actions": (latest_result.as_dict() if latest_result is not None else None),
                },
            }
        ), 409
    except Exception:
        logger.exception("kill_switch_reset error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    audit_recorded = _audit is None
    if _audit:
        try:
            _audit.log_kill_switch(activated=False, reason="Manual reset via API")
        except Exception:
            logger.exception("Kill switch reset but its audit record could not be persisted")
        else:
            audit_recorded = True
    message = "Kill switch reset — trading may resume"
    return jsonify(
        {
            "status": "success",
            "message": message,
            "data": {"message": message, "audit_recorded": audit_recorded},
        }
    ), 200


# ------------------------------------------------------------------
# Webhooks
# ------------------------------------------------------------------

_WEBHOOK_SOURCES = ("custom",)
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


def _webhook_registry_lock() -> FileLock:
    """Serialise registry and encrypted-secret changes across processes."""
    from .workspace import workspace_dir  # noqa: PLC0415

    return FileLock(
        workspace_dir() / ".webhook-registry.lock",
        timeout=_WEBHOOK_REGISTRY_LOCK_TIMEOUT_SECONDS,
        mode=0o600,
        thread_local=False,
    )


def webhook_endpoint_enabled(path: str) -> bool | None:
    """Return whether a mounted webhook path is enabled in the workspace registry.

    Returns ``None`` when the path is not registry-managed. The mounted named
    receiver treats that as unregistered and rejects it before secret lookup.
    """
    raw_path = str(path or "").strip()
    if not raw_path:
        return None
    try:
        mounted_path = _normalise_webhook_path(raw_path, _webhook_type(raw_path))
    except ValueError:
        return None
    with _webhook_registry_lock():
        _workspace, rows = _load_webhook_registry()
        for row in rows:
            if row["path"] == mounted_path:
                if not row["enabled"]:
                    return False
                secret_store = _get_webhook_secret_store()
                return bool(secret_store is not None and secret_store.has_secret(mounted_path))
    return None


def _get_webhook_secret_store() -> Any | None:
    """Return the app-injected encrypted webhook store, if available."""
    return current_app.config.get("WEBHOOK_SECRET_STORE")


def _webhook_with_secret_state(row: dict[str, Any]) -> dict[str, Any]:
    """Return one frontend-safe row with fail-closed secret readiness."""
    secret_store = _get_webhook_secret_store()
    configured = bool(secret_store is not None and secret_store.has_secret(row["path"]))
    return {
        **row,
        "enabled": bool(row["enabled"] and configured),
        "secret_configured": configured,
    }


@operations_bp.route("/webhooks", methods=["GET"])
def webhooks_list() -> tuple[Any, int]:
    """Return all registered webhook endpoints and their status.

    Returns:
        JSON with ``status`` and ``data.webhooks`` — a list of objects with
        ``id``, ``path``, ``name``, ``type``, and ``enabled`` fields (the
        frontend WebhookConfig contract; the secret is never echoed).
    """
    try:
        with _webhook_registry_lock():
            _workspace, webhooks = _load_webhook_registry()
            public_rows = [_webhook_with_secret_state(row) for row in webhooks]
        return jsonify({"status": "success", "data": {"webhooks": public_rows}}), 200
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
        secret (str): required signing secret stored in the encrypted
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
        if not secret.strip():
            return jsonify({"status": "error", "message": "signing secret is required"}), 400
        try:
            path = _normalise_webhook_path(path_raw, source)
        except ValueError as exc:
            logger.info("Webhook path rejected: %s", exc)
            return jsonify({"status": "error", "message": "Invalid webhook path"}), 400

        secret_store = _get_webhook_secret_store()
        if secret_store is None:
            return jsonify(
                {
                    "status": "error",
                    "message": "Encrypted webhook secret store is unavailable.",
                }
            ), 503

        enabled_raw = body.get("enabled", True)
        if not isinstance(enabled_raw, bool):
            return jsonify({"status": "error", "message": "enabled must be a boolean"}), 400

        with _webhook_registry_lock():
            workspace, rows = _load_webhook_registry()
            row = _webhook_dict(path, name, enabled_raw)
            previous_row = next((existing for existing in rows if existing["path"] == path), None)
            rows = [existing for existing in rows if existing["path"] != path]
            rows.append(row)
            try:
                previous_secret = secret_store.get_secret(path)
            except Exception:
                logger.exception("Webhook signing secret could not be read before update")
                return jsonify({"status": "error", "message": "Encrypted webhook secret store is unavailable."}), 503
            try:
                secret_store.store_secret(path, row["type"], row["name"], secret)
            except Exception:
                logger.exception("Webhook signing secret could not be persisted")
                return jsonify({"status": "error", "message": "Encrypted webhook secret store is unavailable."}), 503
            try:
                _save_webhook_registry(workspace, rows)
            except Exception:
                logger.exception("Webhook registry save failed after secret persistence; rolling back secret")
                try:
                    if previous_secret is None:
                        secret_store.delete_secret(path)
                    else:
                        rollback_row = previous_row or row
                        secret_store.store_secret(
                            path,
                            rollback_row["type"],
                            rollback_row["name"],
                            previous_secret,
                        )
                except Exception:
                    logger.critical("Webhook create rollback failed for %s", path, exc_info=True)
                raise
        return jsonify(
            {
                "status": "success",
                "data": {**row, "secret_configured": True},
            }
        ), 201
    except Exception:
        logger.exception("webhooks_create error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks/<path:webhook_id>", methods=["PATCH"])
def webhooks_update(webhook_id: str) -> tuple[Any, int]:
    """Update the enabled state of a registered webhook endpoint."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Request body must be a JSON object"}), 400
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return jsonify({"status": "error", "message": "enabled must be a boolean"}), 400

    try:
        with _webhook_registry_lock():
            workspace, rows = _load_webhook_registry()
            key = webhook_id.strip()
            path_key = f"/{key}" if not key.startswith("/") else key
            id_key = key.lstrip("/")
            updated: dict[str, Any] | None = None
            for row in rows:
                if row["id"] == id_key or row["path"] == path_key:
                    if enabled:
                        secret_store = _get_webhook_secret_store()
                        if secret_store is None or not secret_store.has_secret(row["path"]):
                            return jsonify({
                                "status": "error",
                                "message": "Webhook signing secret is not configured; recreate the endpoint first.",
                            }), 409
                    row["enabled"] = enabled
                    updated = row
                    break
            if updated is None:
                return jsonify({"status": "error", "message": f"Webhook '{webhook_id}' not found"}), 404
            _save_webhook_registry(workspace, rows)
            return jsonify({"status": "success", "data": _webhook_with_secret_state(updated)}), 200
    except Exception:
        logger.exception("webhooks_update error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/webhooks/<path:webhook_id>", methods=["DELETE"])
def webhooks_delete(webhook_id: str) -> tuple[Any, int]:
    """Remove a registered webhook endpoint.

    Uses a ``<path:...>`` converter because a webhook's id is its registration
    path (e.g. ``webhook/custom/my_signal``) — multi-segment, so a plain
    ``<webhook_id>`` ([^/]+) would 405 once the encoded slashes decode.

    Args:
        webhook_id: The path-backed id identifying exactly one webhook (with or
            without a leading slash). Display names are intentionally not ids.

    Returns:
        JSON with ``status`` and confirmation message.
    """
    try:
        with _webhook_registry_lock():
            workspace, rows = _load_webhook_registry()
            key = webhook_id.strip()
            path_key = f"/{key}" if not key.startswith("/") else key
            id_key = key.lstrip("/")

            removed = next(
                (row for row in rows if row["id"] == id_key or row["path"] == path_key),
                None,
            )
            kept = [row for row in rows if row is not removed]
            if removed is not None:
                secret_store = _get_webhook_secret_store()
                if secret_store is None:
                    return jsonify(
                        {"status": "error", "message": "Encrypted webhook secret store is unavailable."}
                    ), 503
                previous_secret = secret_store.get_secret(removed["path"])
                try:
                    secret_store.delete_secret(removed["path"])
                except Exception:
                    logger.exception("Webhook signing secret could not be removed")
                    return jsonify({"status": "error", "message": "Encrypted webhook secret store is unavailable."}), 503
                try:
                    _save_webhook_registry(workspace, kept)
                except Exception:
                    logger.exception("Webhook registry delete failed; restoring signing secret")
                    if previous_secret is not None:
                        try:
                            secret_store.store_secret(
                                removed["path"], removed["type"], removed["name"], previous_secret
                            )
                        except Exception:
                            logger.critical("Webhook delete rollback failed for %s", removed["path"], exc_info=True)
                    raise
                return jsonify(
                    {
                        "status": "success",
                        "data": {"message": f"Webhook '{removed['path']}' removed"},
                    }
                ), 200

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

    return jsonify(
        {
            "status": "success",
            "data": {
                "auto_ban_enabled": monitor._auth_ban_threshold > 0,
                "ban_threshold": monitor._auth_ban_threshold,
                "notfound_ban_threshold": monitor._notfound_ban_threshold,
                "ban_duration": monitor._ban_duration,
            },
        }
    ), 200


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

    return jsonify(
        {
            "status": "success",
            "data": {
                "auto_ban_enabled": monitor._auth_ban_threshold > 0,
                "ban_threshold": monitor._auth_ban_threshold,
                "notfound_ban_threshold": monitor._notfound_ban_threshold,
                "ban_duration": monitor._ban_duration,
            },
        }
    ), 200


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
                    articles.append(
                        {
                            "title": title_el.text.strip(),
                            "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                            "pub_date": pub_el.text.strip() if pub_el is not None and pub_el.text else "",
                            "source": source_name,
                        }
                    )
        except Exception:
            continue

    # Sort by pub_date descending, limit to 50
    articles.sort(key=lambda a: a.get("pub_date", ""), reverse=True)
    articles = articles[:50]

    return jsonify(
        {
            "status": "success",
            "data": {"articles": articles},
        }
    ), 200


# ------------------------------------------------------------------
# Ditto — multi-account management & position mirroring
# ------------------------------------------------------------------


def _ditto_account_response(acct: Any) -> dict[str, Any]:
    """Return a frontend-safe Ditto account payload without credentials."""
    return {
        "id": acct.account_id,
        "name": acct.name or acct.account_id,
        "broker": "OpenAlgo",
        "capital": None,
        "pnl_today": None,
        "status": "active" if acct.enabled else "disabled",
        "positions": None,
        "group": acct.group,
        "allocation_weight": acct.allocation_weight,
        "max_loss_daily": acct.max_loss_daily,
        "is_master": acct.is_master,
    }


def _ditto_manager_error(exc: Exception) -> tuple[Any, int]:
    logger.warning("Ditto account operation failed (%s)", type(exc).__name__)
    return jsonify(
        {
            "status": "error",
            "message": "Account service unavailable",
        }
    ), 503


def _ditto_manager() -> Any | None:
    """Build a Ditto AccountManager bound to the canonical credential vault.

    Returns ``None`` when the Ditto vault is not configured (the caller then
    returns 503) — Ditto account api_keys are stored in the vault, so the
    manager cannot operate without it.
    """
    store = current_app.config.get("DITTO_CREDENTIAL_STORE")
    if store is None:
        return None
    from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415

    return AccountManager(credential_store=store)


def _ditto_runtime() -> Any | None:
    """Return the process-owned Ditto runtime, if startup configured one."""
    return current_app.config.get("DITTO_RUNTIME")


def _ditto_runtime_unavailable(exc: Exception | None = None) -> tuple[Any, int]:
    """Return a bounded Ditto failure without exposing broker responses."""
    if exc is not None:
        logger.warning("Ditto runtime operation failed (%s)", type(exc).__name__)
    return jsonify(
        {
            "status": "error",
            "message": (
                "Ditto runtime operation unavailable"
                if exc is not None
                else "Ditto runtime unavailable"
            ),
        }
    ), 503


def _validated_ditto_runtime_status(runtime: Any) -> dict[str, Any]:
    """Return the lifecycle fields required to prove account mutation safety."""
    raw_status = runtime.status()
    if not isinstance(raw_status, Mapping):
        raise RuntimeError("Ditto runtime returned invalid status")

    active = raw_status.get("active")
    lifecycle = raw_status.get("lifecycle")
    source = raw_status.get("source_account")
    targets = raw_status.get("target_accounts")
    if not isinstance(active, bool) or not isinstance(lifecycle, str):
        raise RuntimeError("Ditto runtime returned invalid lifecycle state")
    if source is not None and not isinstance(source, str):
        raise RuntimeError("Ditto runtime returned invalid source state")
    if not isinstance(targets, list) or any(not isinstance(target, str) for target in targets):
        raise RuntimeError("Ditto runtime returned invalid target state")
    return {
        "active": active,
        "lifecycle": lifecycle,
        "source_account": source,
        "target_accounts": list(targets),
    }


def _quiesce_ditto_account_generation(account_id: str) -> tuple[Any, int] | None:
    """Drain a generation containing ``account_id`` before its store row changes.

    The caller must retain ``_DITTO_CONTROL_LOCK`` through the subsequent store
    mutation so a new route-owned generation cannot claim the account in between.
    """
    runtime = _ditto_runtime()
    if runtime is None:
        return None
    try:
        status = _validated_ditto_runtime_status(runtime)
        participates = account_id == status["source_account"] or account_id in status["target_accounts"]
        retained_cleanup = status["lifecycle"] == "retained-shutdown"
        if not participates and not retained_cleanup:
            return None

        # One-shot risk/emergency owners are built over a snapshot of the whole
        # managed-account set. Their account ids are deliberately not exposed in
        # status, so any retained owner is a global mutation barrier until its
        # revoked router generation has drained and its clients have closed.
        runtime.stop(timeout=5.0)
        stopped = _validated_ditto_runtime_status(runtime)
        fully_stopped = (
            stopped["active"] is False
            and stopped["source_account"] is None
            and not stopped["target_accounts"]
            and stopped["lifecycle"] in {"idle", "reconciliation-needed"}
        )
        if not fully_stopped:
            raise RuntimeError("Ditto runtime drain was not proven")
    except Exception as exc:  # noqa: BLE001 - runtime and broker details stay bounded
        return _ditto_runtime_unavailable(exc)
    return None


@operations_bp.route("/ditto/accounts", methods=["GET"])
def ditto_accounts() -> tuple[Any, int]:
    """List all managed accounts with status.

    Returns a list of broker accounts registered in the Ditto multi-account
    manager. When no real accounts are configured yet, returns an empty list
    rather than fabricating accounts.
    """
    try:
        mgr = _ditto_manager()
        if mgr is None:
            return jsonify({"status": "error", "message": "Account service unavailable"}), 503
        raw = mgr.list_accounts()
        accounts = [_ditto_account_response(acct) for acct in raw]
        return jsonify({"status": "success", "data": {"accounts": accounts}}), 200
    except Exception as exc:
        logger.warning("Ditto account fetch failed (%s)", type(exc).__name__)
        return jsonify({"status": "error", "message": "Account service unavailable"}), 503


@operations_bp.route("/accounts/status", methods=["GET"])
def accounts_status() -> tuple[Any, int]:
    """Consolidated Account Manager status — per-broker connection + daily reauth.

    Reports both Ditto/OpenAlgo managed accounts and vault-backed native broker
    accounts. Ditto rows live-ping OpenAlgo (200 = authenticated, 4xx = re-auth
    needed, connection error = offline). Native rows reflect the gateway session
    registry and stored replay status, so enabled native accounts appear
    in the Account Manager even when no OpenAlgo bridge account exists.
    """
    statuses: list[dict[str, Any]] = []
    ditto_failed = False
    try:
        mgr = _ditto_manager()
        if mgr is not None:
            with mgr:
                statuses.extend({"source": "openalgo", **s.to_dict()} for s in mgr.account_status_all())
    except Exception as exc:
        ditto_failed = True
        logger.warning("Account status fetch failed (%s)", type(exc).__name__)

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
        statuses.append(
            {
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
            }
        )
    return statuses


@operations_bp.route("/ditto/accounts", methods=["POST"])
def ditto_account_create() -> tuple[Any, int]:
    """Create or update a Ditto managed OpenAlgo account.

    Broker-management write (G9): requires the operator's session JWT — this
    route stores an OpenAlgo api_key into the Ditto vault.
    """
    _jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
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
        return jsonify(
            {
                "status": "error",
                "message": f"Missing required field(s): {', '.join(missing)}",
            }
        ), 400

    parsed = urlparse(openalgo_host)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return jsonify(
            {
                "status": "error",
                "message": "openalgo_host must be a valid http(s) URL",
            }
        ), 400

    try:
        allocation_weight = float(data.get("allocation_weight", 1.0))
        max_loss_daily = float(data.get("max_loss_daily", 50000.0))
    except (TypeError, ValueError):
        return jsonify(
            {
                "status": "error",
                "message": "allocation_weight and max_loss_daily must be numeric",
            }
        ), 400
    if (
        not math.isfinite(allocation_weight)
        or not math.isfinite(max_loss_daily)
        or allocation_weight <= 0
        or max_loss_daily < 0
    ):
        return jsonify(
            {
                "status": "error",
                "message": "allocation_weight must be positive and max_loss_daily cannot be negative",
            }
        ), 400

    try:
        from flinttrade_ditto.account_manager import BrokerAccount  # noqa: PLC0415

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
        with _DITTO_CONTROL_LOCK:
            mgr = _ditto_manager()
            if mgr is None:
                return jsonify({"status": "error", "message": "Account service unavailable"}), 503
            runtime_error = _quiesce_ditto_account_generation(account_id)
            if runtime_error is not None:
                return runtime_error
            mgr.add_account(account)
        return jsonify(
            {
                "status": "success",
                "data": {"account": _ditto_account_response(account)},
            }
        ), 201
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
    _jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    try:
        with _DITTO_CONTROL_LOCK:
            mgr = _ditto_manager()
            if mgr is None:
                return jsonify({"status": "error", "message": "Account service unavailable"}), 503
            account = mgr.get_account(account_id)
            if account is None:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"Account '{account_id}' not found",
                    }
                ), 404
            if not enabled:
                runtime_error = _quiesce_ditto_account_generation(account_id)
                if runtime_error is not None:
                    return runtime_error
            if enabled:
                mgr.enable_account(account_id)
            else:
                mgr.disable_account(account_id)
            account.enabled = enabled
        return jsonify(
            {
                "status": "success",
                "data": {"account": _ditto_account_response(account)},
            }
        ), 200
    except Exception as exc:
        return _ditto_manager_error(exc)


@operations_bp.route("/ditto/accounts/<account_id>", methods=["DELETE"])
def ditto_account_delete(account_id: str) -> tuple[Any, int]:
    """Remove a Ditto managed account (G9: requires the operator's session JWT)."""
    _jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    try:
        with _DITTO_CONTROL_LOCK:
            mgr = _ditto_manager()
            if mgr is None:
                return jsonify({"status": "error", "message": "Account service unavailable"}), 503
            account = mgr.get_account(account_id)
            if account is None:
                return jsonify(
                    {
                        "status": "error",
                        "message": f"Account '{account_id}' not found",
                    }
                ), 404
            runtime_error = _quiesce_ditto_account_generation(account_id)
            if runtime_error is not None:
                return runtime_error
            mgr.remove_account(account_id)
        return jsonify(
            {
                "status": "success",
                "data": {"id": account_id, "removed": True},
            }
        ), 200
    except Exception as exc:
        return _ditto_manager_error(exc)


@operations_bp.route("/ditto/mirror/status", methods=["GET"])
def ditto_mirror_status() -> tuple[Any, int]:
    """Get position mirroring status across accounts."""
    runtime = _ditto_runtime()
    if runtime is None:
        return _ditto_runtime_unavailable()
    try:
        status = runtime.status()
    except Exception as exc:  # noqa: BLE001 - broker/runtime detail must stay bounded
        return _ditto_runtime_unavailable(exc)
    return jsonify({"status": "success", "data": status}), 200


@operations_bp.route("/ditto/mirror/start", methods=["POST"])
def ditto_mirror_start() -> tuple[Any, int]:
    """Start a gated live mirror session for an authenticated operator."""
    raw_data = request.get_json(silent=True)
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    source = str(data.get("source_account") or "").strip()
    raw_targets = data.get("target_accounts", [])
    mode = str(data.get("mode") or "proportional").strip()

    if not source:
        return jsonify({"status": "error", "message": "source_account is required"}), 400
    if not isinstance(raw_targets, list):
        return jsonify({"status": "error", "message": "target_accounts must be a list"}), 400
    targets = [str(account_id).strip() for account_id in raw_targets]
    if not targets or any(not account_id for account_id in targets):
        return jsonify({"status": "error", "message": "target_accounts must be non-empty"}), 400

    jwt_payload, auth_error = _authenticated_live_operator(require_unlock=True)
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    runtime = _ditto_runtime()
    if runtime is None:
        return _ditto_runtime_unavailable()
    try:
        with _DITTO_CONTROL_LOCK:
            status = runtime.start(
                source_account=source,
                target_accounts=targets,
                mode=mode,
                actor_id=str(jwt_payload["sub"]),
                jti=str(jwt_payload["jti"]),
            )
    except Exception as exc:  # noqa: BLE001 - broker/runtime detail must stay bounded
        return _ditto_runtime_unavailable(exc)
    return jsonify(
        {
            "status": "success",
            "data": {**status, "started_at": _dt.now(_IST).isoformat()},
        }
    ), 200


@operations_bp.route("/ditto/mirror/stop", methods=["POST"])
def ditto_mirror_stop() -> tuple[Any, int]:
    """Stop position mirroring (G9: requires the operator's session JWT).

    A valid session in any mode suffices — stopping the mirror reduces
    activity, so it must not demand a live unlock the way start does.
    """
    _jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    runtime = _ditto_runtime()
    if runtime is None:
        return _ditto_runtime_unavailable()
    try:
        with _DITTO_CONTROL_LOCK:
            status = runtime.stop(timeout=5.0)
    except Exception as exc:  # noqa: BLE001 - broker/runtime detail must stay bounded
        return _ditto_runtime_unavailable(exc)
    return jsonify(
        {
            "status": "success",
            "data": {**status, "stopped_at": _dt.now(_IST).isoformat()},
        }
    ), 200


@operations_bp.route("/ditto/risk", methods=["GET"])
def ditto_risk() -> tuple[Any, int]:
    """Return one complete real-state risk snapshot across managed accounts."""
    runtime = _ditto_runtime()
    if runtime is None:
        return _ditto_runtime_unavailable()
    try:
        snapshot = runtime.risk_snapshot()
    except Exception as exc:  # noqa: BLE001 - broker/runtime detail must stay bounded
        return _ditto_runtime_unavailable(exc)
    return jsonify({"status": "success", "data": snapshot}), 200


@operations_bp.route("/ditto/kill-all", methods=["POST"])
def ditto_kill_all() -> tuple[Any, int]:
    """Cancel and flatten all managed accounts through gated emergency writes."""
    jwt_payload, auth_error = _authenticated_live_operator()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    raw_data = request.get_json(silent=True)
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    reason = str(data.get("reason") or "Operator requested Ditto kill-all").strip()
    reason = reason[:500] or "Operator requested Ditto kill-all"
    runtime = _ditto_runtime()
    if runtime is None:
        return _ditto_runtime_unavailable()
    try:
        with _DITTO_CONTROL_LOCK:
            result = runtime.kill_all(
                actor_id=str(jwt_payload["sub"]),
                jti=str(jwt_payload["jti"]),
                reason=reason,
            )
    except Exception as exc:  # noqa: BLE001 - broker/runtime detail must stay bounded
        return _ditto_runtime_unavailable(exc)
    complete = bool(result.get("complete"))
    return jsonify(
        {
            "status": "success" if complete else "partial",
            "data": result,
        }
    ), 200 if complete else 207


# ------------------------------------------------------------------
# Ditto — AlgoMirror bridge
# ------------------------------------------------------------------


# NOTE: The /ditto/algomirror/status route was removed 2026-04-30.
# AlgoMirror's mirroring logic is fully adapted into packages/services/ditto/
# (PositionMirror, TrailingSLManager, MarginCalculator, RiskManager) and
# runs in-process — no separately-deployed AlgoMirror to query.


# ------------------------------------------------------------------
# AI — agent backends (replaces the removed OpenClaw external-gateway bridge)
#
# merge-not-delete: OpenClaw's honest health-probe + error-dict scaffolding is
# preserved here. ``/ai/agents/backends`` is the health/status probe — a live
# ``detect_backend`` status per backend rather than a single gateway ping — and
# ``/ai/agents/run`` returns honest error dicts (unknown id / LLM-only /
# not-installed / unavailable) instead of ever fabricating a stream.
# ------------------------------------------------------------------


def _sse_frame(payload: dict[str, Any]) -> str:
    """Serialise one payload dict as a single Server-Sent Events ``data:`` frame."""
    return f"data: {json.dumps(payload)}\n\n"


# Upper bound (seconds) we wait, on a client disconnect, for the agent turn to
# interrupt and its backend subprocess to be torn down. Bounded so a stuck close
# never wedges the WSGI worker; the driver thread is a daemon regardless.
_AGENT_TEARDOWN_TIMEOUT = 15.0


def _stream_agent_turn(
    backend_id: str,
    prompt: str,
    session_kwargs: dict[str, Any],
) -> Iterator[str]:
    """Yield SSE frames for one agent turn, bridging the async session to WSGI.

    The :class:`~flinttrade_ai.agent_backends.AgentSession` API is asyncio-native
    while Flask is WSGI (synchronous). The turn is driven on a private event loop
    in a background thread; each streamed ``AgentEvent`` is funnelled through a
    thread-safe queue and yielded here as an SSE frame as it arrives. A terminal
    ``done`` frame is always emitted — even when the backend fails to start — so
    the client always sees a clean end-of-stream.

    Client-disconnect honesty: when the operator hits Stop (or the socket drops),
    the WSGI server closes this generator, raising ``GeneratorExit`` at the paused
    ``yield``. The ``finally`` below then cancels the in-flight turn on the loop
    thread and joins it, so the session's ``run_turn`` unwinds (best-effort
    interrupting the backend) and ``AgentSession.close()`` runs — the backend
    subprocess is genuinely stopped rather than left running on the operator's
    machine after Stop is pressed.

    Args:
        backend_id: The catalogue backend id to run (a CLI/ACP agent runtime).
        prompt: The operator instruction forwarded to the agent.
        session_kwargs: Extra keyword args for the concrete session (e.g. ``cwd``).

    Yields:
        ``text/event-stream`` frames, one JSON :class:`AgentEvent` per frame.
    """
    from flinttrade_ai.agent_backends import (  # noqa: PLC0415
        AgentBackendUnavailable,
        AgentEvent,
        AgentEventKind,
        get_session,
    )

    events: queue.Queue[Any] = queue.Queue()
    sentinel = object()
    # Cross-thread handles so a client disconnect (below) can reach into the loop
    # thread and cancel the running turn.
    loop_box: dict[str, asyncio.AbstractEventLoop] = {}
    task_box: dict[str, asyncio.Task[None]] = {}
    disconnected = threading.Event()

    async def _drive() -> None:
        session: Any = None
        saw_done = False

        async def _on_event(event: AgentEvent) -> None:
            nonlocal saw_done
            if event.kind == AgentEventKind.DONE:
                saw_done = True
            events.put(event)

        try:
            session = get_session(backend_id, **session_kwargs)
            await session.ensure_started()
            await session.run_turn(prompt, _on_event)
        except asyncio.CancelledError:
            # Client disconnected: unwind so the ``finally`` closes the session
            # (terminating the backend subprocess). Never emit — nobody is reading.
            raise
        except AgentBackendUnavailable as exc:
            events.put(AgentEvent(AgentEventKind.ERROR, text=exc.reason, data={"backend": backend_id}))
        except (ValueError, NotImplementedError) as exc:
            # LLM ids never reach here (pre-checked in the route); this covers a
            # runtime whose streaming session is not implemented yet (Phase B2).
            events.put(AgentEvent(AgentEventKind.ERROR, text=str(exc), data={"backend": backend_id}))
        except Exception:
            logger.exception("agent run failed for backend %s", backend_id)
            events.put(AgentEvent(AgentEventKind.ERROR, text="Agent run failed", data={"backend": backend_id}))
        finally:
            if session is not None:
                # Runs on both the happy path and the cancelled path (one
                # CancelledError is delivered, so this await completes), so the
                # runtime is always torn down. ``suppress(Exception)`` never
                # swallows the propagating ``CancelledError`` (a BaseException).
                with contextlib.suppress(Exception):
                    await session.close()
            if not saw_done and not disconnected.is_set():
                events.put(
                    AgentEvent(
                        AgentEventKind.DONE,
                        text="",
                        data={"backend": backend_id, "interrupted": True},
                    )
                )

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        loop_box["loop"] = loop
        asyncio.set_event_loop(loop)
        try:
            task = loop.create_task(_drive())
            task_box["task"] = task
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass  # disconnect-triggered cancellation; teardown ran in _drive
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            with contextlib.suppress(Exception):
                loop.close()
            events.put(sentinel)

    worker = threading.Thread(target=_runner, name=f"agent-run-{backend_id}", daemon=True)
    worker.start()

    try:
        while True:
            item = events.get()
            if item is sentinel:
                break
            yield _sse_frame(item.to_dict())
    finally:
        # Normal completion and client disconnect (``GeneratorExit``) both land
        # here. On disconnect the turn is still live: flag it, cancel the driving
        # task on the loop thread, then wait (bounded) for the teardown so the
        # backend is genuinely stopped before this request returns.
        disconnected.set()
        loop = loop_box.get("loop")
        task = task_box.get("task")
        if loop is not None and task is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(task.cancel)
        worker.join(timeout=_AGENT_TEARDOWN_TIMEOUT)


@operations_bp.route("/ai/agents/backends", methods=["GET"])
def ai_agents_backends() -> tuple[Any, int]:
    """List every supported agent backend with a live detection status.

    Returns:
        JSON with ``status`` and ``data.backends`` — one object per backend
        carrying its ``id``, ``display_name``, ``kind``, ``auth_mode``,
        ``description``, ``requires_binary`` (from ``profile.to_dict()``), and a
        live ``status`` (``ready`` / ``installed`` / ``not_installed`` /
        ``needs_config``). LLM backends are detected by their configured
        provider + key; CLI/ACP agents by their binary on ``PATH``.
    """
    try:
        from flinttrade_ai.agent_backends import (  # noqa: PLC0415
            detect_backend,
            list_backends,
        )
    except Exception:
        logger.exception("agent_backends import failed")
        return jsonify({"status": "error", "message": "Agent backends unavailable"}), 503

    backends: list[dict[str, Any]] = []
    for profile in list_backends():
        try:
            status = str(detect_backend(profile.id))
        except Exception:
            logger.warning("detect_backend failed for %s", profile.id)
            # Honest fallback: we could not confirm it is usable.
            status = "needs_config" if profile.is_llm else "not_installed"
        backends.append({**profile.to_dict(), "status": status})
    return jsonify({"status": "success", "data": {"backends": backends}}), 200


@operations_bp.route("/ai/agents/run", methods=["POST"])
def ai_agents_run() -> Response | tuple[Any, int]:
    """Run one turn on an agent backend, streaming events as Server-Sent Events.

    Request JSON:
        backend_id (str): A catalogue backend id (see ``/ai/agents/backends``).
        prompt (str): The operator instruction for the agent.
        cwd (str, optional): Working directory for a CLI/ACP agent runtime.

    Behaviour by backend kind (honest — never a fabricated stream):
        * LLM backends (``claude-code``, ``claude-code-oauth``, ``cerebras``)
          are chat/completion providers driven through the AI advisor path — a
          clear ``400`` is returned pointing at ``/api/v1/advisor``.
        * A CLI/ACP agent that is not installed returns a ``503`` with its
          detection status.
        * An installed agent returns ``text/event-stream``: one JSON
          :class:`AgentEvent` per ``data:`` frame, always ending with a
          ``done`` event.

    Returns:
        A streaming ``text/event-stream`` :class:`Response` on success, or a
        ``(json, status)`` tuple for the honest error cases above.
    """
    body = request.get_json(silent=True) or {}
    backend_id = str(body.get("backend_id") or "").strip()
    prompt = str(body.get("prompt") or "").strip()

    if not backend_id:
        return jsonify({"status": "error", "message": "backend_id is required"}), 400
    if not prompt:
        return jsonify({"status": "error", "message": "prompt is required"}), 400

    try:
        from flinttrade_ai.agent_backends import (  # noqa: PLC0415
            BackendStatus,
            detect_backend,
            get_backend,
        )
    except Exception:
        logger.exception("agent_backends import failed")
        return jsonify({"status": "error", "message": "Agent backends unavailable"}), 503

    try:
        profile = get_backend(backend_id)
    except KeyError:
        return jsonify({"status": "error", "message": f"Unknown agent backend '{backend_id}'"}), 404

    if profile.is_llm:
        # Honest: LLM backends are chat/completion providers, not agent runtimes.
        return jsonify(
            {
                "status": "error",
                "code": "llm_backend_not_agent_run",
                "message": (
                    f"'{profile.display_name}' is an LLM backend — chat with it via the "
                    "AI advisor (/api/v1/advisor), not the agent-run stream."
                ),
                "data": {"backend": backend_id, "kind": str(profile.kind)},
            }
        ), 400

    try:
        status = detect_backend(backend_id)
    except Exception:
        status = BackendStatus.NOT_INSTALLED
    if status == BackendStatus.NOT_INSTALLED:
        return jsonify(
            {
                "status": "error",
                "code": "backend_not_installed",
                "message": f"{profile.display_name} is not installed on this host.",
                "data": {"backend": backend_id, "status": str(status)},
            }
        ), 503

    session_kwargs: dict[str, Any] = {}
    cwd_raw = body.get("cwd")
    if isinstance(cwd_raw, str) and cwd_raw.strip():
        session_kwargs["cwd"] = cwd_raw.strip()

    return Response(
        _stream_agent_turn(backend_id, prompt, session_kwargs),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    Reads the last 100 lines from ``flinttrade.log`` inside the workspace log
    directory (``Workspace().log_dir`` — ``~/.flinttrade/logs`` on Linux,
    ``~/Library/Application Support/flinttrade/logs`` on macOS,
    ``%APPDATA%/flinttrade/logs`` on Windows, and whatever
    ``FLINTTRADE_WORKSPACE_DIR``/``FLINTTRADE_HOME`` select). Each line is
    expected to be a JSON-encoded structlog entry; plain-text lines are wrapped
    in a minimal dict.

    The previous hardcoded ``~/.flinttrade/logs`` was wrong on macOS and
    Windows. The file is written by the rotating handler that
    ``flinttrade_core.app._attach_log_file_handler`` installs during app
    startup, so entries appear as soon as the backend emits its first log
    record.

    Query parameters:
        n (int, optional): Number of lines to return (default 100, max 500).

    Returns:
        JSON with ``status`` and ``data`` containing a list of log entries.
    """
    import json  # noqa: PLC0415

    from .workspace import Workspace  # noqa: PLC0415

    try:
        n = min(int(request.args.get("n", 100)), 500)
        if n < 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "n must be a positive integer"}), 400

    log_file = Workspace().log_dir / "flinttrade.log"
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
        _admit_position_conversion,
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
        return jsonify(
            {
                "status": "error",
                "message": "Position conversion requires the conversion fields (or a 'req' object) in the body",
            }
        ), 400
    adapter_id, account_id = _gated_target(body)
    admission_block = _admit_position_conversion(
        req,
        adapter_id,
        account_id=account_id,
    )
    if admission_block is not None:
        return admission_block
    return _gated_verb_write(
        "convert_position",
        {"req": req},
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
        audit_event="POSITION_CONVERTED",
        fail_message="Position conversion failed",
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
    Once L5 is active, the operator retries its selector-bound emergency action
    instead of calling this ordinary route; that prevents overlapping square-off
    requests from reversing exposure.

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
        return jsonify(
            {
                "status": "error",
                "message": (
                    'Exit-all requires explicit operator confirmation — send {"confirm": true}. '
                    "This squares off EVERY open position at market."
                ),
            }
        ), 400
    fields: dict[str, Any] = {}
    if body.get("tag") is not None:
        fields["tag"] = str(body["tag"])
    if body.get("segment") is not None:
        fields["segment"] = str(body["segment"])
    adapter_id, account_id = _gated_target(body)
    return _gated_verb_write(
        "exit_all_positions",
        fields,
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
        audit_event="POSITIONS_EXITED_ALL",
        fail_message="Exit-all positions failed",
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
_RECONCILIATION_TAIL_MAX_BYTES = 16 * 1024 * 1024


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
    if not text:
        return fallback
    if not cleaned or set(cleaned) <= {".", "_", "-"}:
        cleaned = fallback
    if cleaned != text:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        return f"{cleaned}--{digest}"
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
    descriptor = -1
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        current = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_ISLNK(current.st_mode)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            return []
        start = max(0, opened.st_size - _RECONCILIATION_TAIL_MAX_BYTES)
        starts_on_boundary = start == 0
        if start > 0:
            os.lseek(descriptor, start - 1, os.SEEK_SET)
            starts_on_boundary = os.read(descriptor, 1) == b"\n"
        os.lseek(descriptor, start, os.SEEK_SET)
        remaining = opened.st_size - start
        chunks: list[bytes] = []
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        lines = b"".join(chunks).splitlines()
        if start > 0 and not starts_on_boundary and lines:
            lines = lines[1:]
    except OSError:
        return []
    finally:
        if descriptor != -1:
            os.close(descriptor)
    reports: list[dict[str, Any]] = []
    for line in reversed(lines):
        encoded = line.strip()
        if not encoded:
            continue
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            reports.append(payload)
        if len(reports) >= limit:
            break
    return reports


def _normalise_reconciliation_report(payload: Any) -> dict[str, Any] | None:
    """Return one validated report shape or ``None`` for untrusted evidence."""
    if not isinstance(payload, Mapping):
        return None
    adapter_id = str(payload.get("adapter_id") or "").strip().lower()
    account_id = str(payload.get("account_id") or "").strip()
    generated_at = str(payload.get("generated_at") or "").strip()
    if not adapter_id or not account_id or not generated_at:
        return None

    def rows(field: str) -> list[dict[str, Any]] | None:
        value = payload.get(field)
        if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
            return None
        return [dict(row) for row in value]

    orders_diff = rows("orders_diff")
    positions_diff = rows("positions_diff")
    holdings_diff = rows("holdings_diff")
    if orders_diff is None or positions_diff is None or holdings_diff is None:
        return None

    raw_counts = payload.get("severity_counts")
    if not isinstance(raw_counts, Mapping):
        return None

    counts: dict[str, int] = {}
    for name in ("info", "warning", "critical"):
        value = raw_counts.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts[name] = value

    clean = payload.get("clean")
    error = payload.get("error")
    severity = payload.get("severity")
    if not isinstance(clean, bool) or not isinstance(error, str) or not isinstance(severity, str):
        return None
    if severity not in {"", "info", "warning", "critical"}:
        return None
    if clean and (
        orders_diff
        or positions_diff
        or holdings_diff
        or error
        or severity
        or counts["info"]
        or counts["warning"]
        or counts["critical"]
    ):
        return None

    return {
        "adapter_id": adapter_id,
        "account_id": account_id,
        "generated_at": generated_at,
        "orders_diff": orders_diff,
        "positions_diff": positions_diff,
        "holdings_diff": holdings_diff,
        "error": error,
        "clean": clean,
        "severity": severity,
        "severity_counts": counts,
    }


def _operator_resolution_payload(resolution: Mapping[str, Any]) -> dict[str, Any]:
    """Return the non-secret immutable decision fields safe for HTTP errors."""
    fields = {
        "resolution_id",
        "outcome",
        "broker_order_ids",
        "broker_order_item_indexes",
        "not_applied_item_indexes",
        "note",
        "evidence_digest",
        "status",
        "prepared_at",
        "snapshot_generation",
        "snapshot_observed_at",
    }
    return {key: resolution.get(key) for key in fields}


def _operator_resolution_error_data(
    attempt_id: str,
    resolution: Mapping[str, Any],
) -> dict[str, Any]:
    """Return both legacy summary fields and the full safe pending decision."""
    return {
        "attempt_id": attempt_id,
        "resolution_id": resolution.get("resolution_id"),
        "status": resolution.get("status"),
        "resolution": _operator_resolution_payload(resolution),
    }


def _reconciliation_report_path(root: Path, broker: str, account_id: str) -> Path | None:
    """Resolve one reconciliation JSONL path under ``root``."""
    joined = safe_join(str(root), broker, f"{account_id}.jsonl")
    if joined is None:
        return None
    path = Path(joined).resolve(strict=False)
    if path != root and root not in path.parents:
        return None
    return path


@operations_bp.route("/reconciliation/outcomes", methods=["GET"])
@require_scope("admin.observability.read")
def reconciliation_outcomes() -> tuple[Any, int]:
    """Return unresolved broker outcomes for the operator's authorised accounts."""
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None
    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    ledger = current_app.config.get("ORDER_LIFECYCLE_LEDGER")
    list_outcomes = getattr(ledger, "list_unresolved_outcomes", None)
    if not callable(list_outcomes):
        return jsonify(
            {"status": "error", "message": "Order lifecycle recovery is unavailable"}
        ), 503
    rebuild_lock = current_app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    try:
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            router = current_app.config.get("BROKER_ROUTER")
            authorised_selectors = getattr(router, "authorised_selectors", None)
            if not callable(authorised_selectors):
                return jsonify(
                    {"status": "error", "message": "Broker account authorisation is unavailable"}
                ), 503
            authorised = set(authorised_selectors(actor_id))
            outcomes = [
                outcome
                for outcome in list_outcomes()
                if f"{outcome.get('adapter_id')}:{outcome.get('account_id')}" in authorised
            ]
    except GenerationLeaseUnavailableError:
        return jsonify(
            {"status": "error", "message": "Broker routing generation is busy; retry"}
        ), 503
    except Exception:
        logger.exception("Could not read unresolved broker outcomes")
        return jsonify(
            {"status": "error", "message": "Unresolved broker outcomes are unavailable"}
        ), 503
    return jsonify(
        {"status": "success", "data": {"count": len(outcomes), "outcomes": outcomes}}
    ), 200


@operations_bp.route("/reconciliation/outcomes/<attempt_id>/resolve", methods=["POST"])
@require_scope("admin.observability.run")
def reconciliation_outcome_resolve(attempt_id: str) -> tuple[Any, int]:
    """Commit one broker-verified unknown outcome after durable audit."""
    from flinttrade_engine.local_state_provider import LifecycleStateError  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    jwt_payload, auth_error = _authenticated_live_operator(require_unlock=True)
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    raw_body = request.get_json(silent=True)
    if not isinstance(raw_body, dict):
        return jsonify({"status": "error", "message": "Resolution must be a JSON object"}), 400
    body: dict[str, Any] = raw_body
    allowed = {
        "broker",
        "account_id",
        "business_date",
        "outcome",
        "broker_order_ids",
        "broker_order_item_indexes",
        "not_applied_item_indexes",
        "confirmation",
        "note",
    }
    unknown = sorted(set(body) - allowed)
    if unknown:
        return jsonify(
            {"status": "error", "message": f"Unknown resolution fields: {', '.join(unknown)}"}
        ), 400

    attempt_key = str(attempt_id).strip()
    broker = str(body.get("broker") or "").strip().lower()
    account_id = str(body.get("account_id") or "").strip()
    business_date = str(body.get("business_date") or "").strip()
    outcome = str(body.get("outcome") or "").strip().lower()
    confirmation = str(body.get("confirmation") or "").strip()
    note = str(body.get("note") or "").strip()
    broker_order_ids = body.get("broker_order_ids", [])
    broker_order_item_indexes = body.get("broker_order_item_indexes", [])
    not_applied_item_indexes = body.get("not_applied_item_indexes", [])
    if not attempt_key or not broker or not account_id or not business_date:
        return jsonify(
            {
                "status": "error",
                "message": "attempt, broker, account_id, and business_date are required",
            }
        ), 400
    try:
        _dt.strptime(business_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"status": "error", "message": "business_date must be YYYY-MM-DD"}), 400
    if outcome not in {"confirmed_applied", "confirmed_not_applied", "confirmed_partial"}:
        return jsonify(
            {
                "status": "error",
                "message": (
                    "outcome must be confirmed_applied, confirmed_not_applied, "
                    "or confirmed_partial"
                ),
            }
        ), 400
    if not isinstance(broker_order_ids, list):
        return jsonify({"status": "error", "message": "broker_order_ids must be a list"}), 400
    if not isinstance(broker_order_item_indexes, list):
        return jsonify(
            {"status": "error", "message": "broker_order_item_indexes must be a list"}
        ), 400
    if not isinstance(not_applied_item_indexes, list):
        return jsonify(
            {"status": "error", "message": "not_applied_item_indexes must be a list"}
        ), 400
    confirmation_decision = {
        "confirmed_applied": "APPLIED",
        "confirmed_not_applied": "NOT_APPLIED",
        "confirmed_partial": "PARTIAL",
    }[outcome]
    selector = f"{broker}:{account_id}"
    expected_confirmation = f"CONFIRM {confirmation_decision} {selector}:{attempt_key}"
    if confirmation != expected_confirmation:
        return jsonify(
            {
                "status": "error",
                "message": "Type the exact decision and account confirmation before resolving",
            }
        ), 400

    actor_id = str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "").strip()
    ledger = current_app.config.get("ORDER_LIFECYCLE_LEDGER")
    audit = current_app.config.get("AUDIT")
    if ledger is None:
        return jsonify(
            {"status": "error", "message": "Order lifecycle recovery is unavailable"}
        ), 503
    log_event = getattr(audit, "log_event", None)
    if not callable(log_event):
        return jsonify(
            {"status": "error", "message": "Durable audit logging is unavailable"}
        ), 503
    outcome_resolution_lease = getattr(ledger, "outcome_resolution_lease", None)
    list_outcomes = getattr(ledger, "list_unresolved_outcomes", None)
    if not callable(outcome_resolution_lease) or not callable(list_outcomes):
        return jsonify(
            {"status": "error", "message": "Atomic outcome recovery is unavailable"}
        ), 503

    rebuild_lock = current_app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    router_fault_cleared = False
    resolution: Mapping[str, Any] | None = None
    try:
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            current_router = current_app.config.get("BROKER_ROUTER")
            if current_router is None:
                raise RuntimeError("current broker router is unavailable")
            current_selector_error = _authorise_daily_pnl_selector(jwt_payload, selector)
            if current_selector_error is not None:
                return current_selector_error
            current_outcome = next(
                (
                    row
                    for row in list_outcomes()
                    if str(row.get("attempt_id") or "") == attempt_key
                ),
                None,
            )
            current_resolution = (
                current_outcome.get("resolution")
                if isinstance(current_outcome, Mapping)
                and isinstance(current_outcome.get("resolution"), Mapping)
                else None
            )
            if isinstance(current_resolution, Mapping):
                resolution = current_resolution
            required_snapshot_generation: int | None = None
            resolution_status = str(
                current_resolution.get("status") if isinstance(current_resolution, Mapping) else ""
            )
            if resolution_status not in {"PENDING_ROUTER_CLEAR", "COMMITTED"}:
                runner = current_app.config.get("RECONCILIATION_RUNNER")
                trigger = getattr(runner, "trigger", None)
                if not callable(trigger):
                    return jsonify(
                        {
                            "status": "error",
                            "message": (
                                "Outcome remains blocked because fresh broker reconciliation "
                                "is unavailable"
                            ),
                        }
                    ), 503
                refresh_payloads = trigger(selectors={selector}, force=True)
                generations: list[int] = []
                for payload in refresh_payloads:
                    if not isinstance(payload, Mapping):
                        continue
                    payload_selector = (
                        f"{str(payload.get('adapter_id') or '').lower()}:"
                        f"{str(payload.get('account_id') or '')}"
                    )
                    try:
                        generation = int(payload.get("snapshot_generation"))
                    except (TypeError, ValueError):
                        continue
                    if payload_selector == selector and generation > 0:
                        generations.append(generation)
                previous_generation = (
                    int(current_resolution.get("snapshot_generation") or 0)
                    if isinstance(current_resolution, Mapping)
                    else 0
                )
                if not generations or max(generations) <= previous_generation:
                    error_payload: dict[str, Any] = {
                        "status": "error",
                        "message": (
                            "Outcome remains blocked because a newer broker snapshot "
                            "could not be adopted"
                        ),
                    }
                    if isinstance(current_resolution, Mapping):
                        error_payload["data"] = _operator_resolution_error_data(
                            attempt_key,
                            current_resolution,
                        )
                    return jsonify(
                        error_payload
                    ), 503
                required_snapshot_generation = max(generations)

            with outcome_resolution_lease():
                current_router = current_app.config.get("BROKER_ROUTER")
                if current_router is None:
                    raise RuntimeError("current broker router is unavailable")
                current_selector_error = _authorise_daily_pnl_selector(jwt_payload, selector)
                if current_selector_error is not None:
                    return current_selector_error
                resolution = ledger.prepare_outcome_resolution(
                    attempt_id=attempt_key,
                    adapter_id=broker,
                    account_id=account_id,
                    business_date=business_date,
                    outcome=outcome,
                    broker_order_ids=broker_order_ids,
                    broker_order_item_indexes=broker_order_item_indexes,
                    not_applied_item_indexes=not_applied_item_indexes,
                    actor_type="human",
                    actor_id=actor_id,
                    note=note,
                    required_snapshot_generation=required_snapshot_generation,
                )
                audit_reference = str(resolution.get("audit_reference") or "")
                if resolution["status"] == "PENDING_AUDIT":
                    try:
                        audit_reference = str(log_event(
                            "ORDER_OUTCOME_RESOLUTION_AUTHORISED",
                            resolution_id=resolution["resolution_id"],
                            attempt_id=attempt_key,
                            selector=selector,
                            business_date=business_date,
                            outcome=outcome,
                            operation_count=1,
                            broker_order_id_count=len(broker_order_ids),
                            actor_id=actor_id,
                            evidence_digest=resolution["evidence_digest"],
                        ) or "")
                        if not audit_reference:
                            raise RuntimeError("audit logger returned no durable receipt")
                    except Exception:  # noqa: BLE001 - audit failure keeps the ledger blocked
                        logger.exception("Outcome resolution audit write failed")
                        return jsonify(
                            {
                                "status": "error",
                                "message": (
                                    "Outcome remains blocked because durable audit recording failed"
                                ),
                                "data": _operator_resolution_error_data(
                                    attempt_key,
                                    resolution,
                                ),
                            }
                        ), 503
                current_router = current_app.config.get("BROKER_ROUTER")
                if current_router is None:
                    raise RuntimeError("current broker router is unavailable")
                current_selector_error = _authorise_daily_pnl_selector(jwt_payload, selector)
                if current_selector_error is not None:
                    return current_selector_error
                resolution = ledger.finalize_outcome_resolution(
                    resolution["resolution_id"],
                    audit_reference=audit_reference,
                )
                clear_fault = getattr(current_router, "clear_lifecycle_fault", None)
                verify_clear = getattr(current_router, "verify_lifecycle_fault_clear", None)
                if not callable(clear_fault) or not callable(verify_clear):
                    raise RuntimeError("current broker router cannot clear lifecycle faults")
                try:
                    router_clear_receipt = clear_fault(
                        attempt_key,
                        resolution_id=str(resolution["resolution_id"]),
                        selector=selector,
                    )
                except Exception:  # noqa: BLE001 - durable pending state must remain retryable
                    logger.exception("Outcome decision recorded but router fault clear failed")
                    return jsonify(
                        {
                            "status": "error",
                            "message": (
                                "Decision recorded; outcome remains blocked pending exact router clear"
                            ),
                            "data": _operator_resolution_error_data(
                                attempt_key,
                                resolution,
                            ),
                        }
                    ), 503
                if router_clear_receipt is None:
                    return jsonify(
                        {
                            "status": "error",
                            "message": (
                                "Decision recorded; outcome remains blocked pending exact router clear"
                            ),
                            "data": _operator_resolution_error_data(
                                attempt_key,
                                resolution,
                            ),
                        }
                    ), 503
                try:
                    resolution = ledger.complete_outcome_resolution(
                        resolution["resolution_id"],
                        router_clear_receipt=router_clear_receipt,
                        router_clear_verifier=verify_clear,
                    )
                    router_fault_cleared = True
                except Exception:  # noqa: BLE001 - keep the durable pending state visible
                    logger.exception("Router fault cleared but durable completion failed")
                    return jsonify(
                        {
                            "status": "error",
                            "message": (
                                "Router fault cleared; durable outcome completion remains pending"
                            ),
                            "data": _operator_resolution_error_data(
                                attempt_key,
                                resolution,
                            ),
                        }
                    ), 503

                try:
                    ledger.assert_write_ready()
                except LifecycleStateError:
                    writes_unblocked = False
                except Exception:
                    logger.exception("Could not verify lifecycle write readiness after resolution")
                    writes_unblocked = False
                else:
                    writes_unblocked = True

                remaining_outcomes: int | None = None
                try:
                    authorised_selectors = getattr(current_router, "authorised_selectors", None)
                    if callable(authorised_selectors):
                        authorised = set(authorised_selectors(actor_id))
                        remaining_outcomes = sum(
                            1
                            for unresolved in list_outcomes()
                            if (
                                f"{unresolved.get('adapter_id')}:{unresolved.get('account_id')}"
                                in authorised
                            )
                        )
                except Exception:
                    logger.exception(
                        "Could not count authorised unresolved outcomes after resolution"
                    )
    except GenerationLeaseUnavailableError:
        return jsonify(
            {"status": "error", "message": "Broker routing generation is busy; retry resolution"}
        ), 503
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    except LifecycleStateError as exc:
        data = None
        if isinstance(resolution, Mapping):
            data = _operator_resolution_error_data(attempt_key, resolution)
        return jsonify(
            {
                "status": "error",
                "message": str(exc),
                **({"data": data} if data is not None else {}),
            }
        ), 409
    except Exception:
        logger.exception("Outcome resolution finalisation failed")
        data = None
        if isinstance(resolution, Mapping):
            data = _operator_resolution_error_data(attempt_key, resolution)
        return jsonify(
            {
                "status": "error",
                "message": "Outcome resolution remains blocked until finalisation succeeds",
                **({"data": data} if data is not None else {}),
            }
        ), 503

    assert resolution is not None

    return jsonify(
        {
            "status": "success",
            "data": {
                "resolution_id": resolution["resolution_id"],
                "attempt_id": attempt_key,
                "outcome": resolution["outcome"],
                "status": resolution["status"],
                "evidence_digest": resolution["evidence_digest"],
                "router_fault_cleared": router_fault_cleared,
                "writes_unblocked": writes_unblocked,
                "remaining_outcomes": remaining_outcomes,
            },
        }
    ), 200


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
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None

    broker = request.args.get("broker", "").strip().lower()
    account_id = request.args.get("account_id", "").strip()
    if not broker or not account_id:
        return jsonify(
            {
                "status": "error",
                "message": "broker and account_id query parameters are required",
            }
        ), 400
    try:
        limit = int(request.args.get("limit", _RECONCILIATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "limit must be a positive integer"}), 400
    if limit < 1:
        return jsonify({"status": "error", "message": "limit must be a positive integer"}), 400
    limit = min(limit, _RECONCILIATION_MAX_LIMIT)

    rebuild_lock = current_app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    try:
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            selector_error = _authorise_daily_pnl_selector(
                jwt_payload,
                f"{broker}:{account_id}",
            )
            if selector_error is not None:
                return selector_error
            root = _reconciliation_root()
            safe_broker = _reconciliation_safe_component(broker, "unknown")
            safe_account = _reconciliation_safe_component(account_id, "default")
            # The sanitiser collapses traversal input to one component; the
            # resolved-path guard still prevents reads outside this tree.
            path = _reconciliation_report_path(root, safe_broker, safe_account)
            if path is None:
                return jsonify({"status": "error", "message": "Invalid broker or account_id"}), 400
            reports: list[dict[str, Any]] = []
            if path.is_file():
                for raw_report in _read_jsonl_tail(path, _RECONCILIATION_MAX_LIMIT):
                    report = _normalise_reconciliation_report(raw_report)
                    if (
                        report is None
                        or report["adapter_id"] != broker
                        or report["account_id"] != account_id
                    ):
                        continue
                    reports.append(report)
                    if len(reports) >= limit:
                        break
            return jsonify(
                {
                    "status": "success",
                    "data": {"broker": broker, "account_id": account_id, "reports": reports},
                }
            ), 200
    except GenerationLeaseUnavailableError:
        return jsonify(
            {"status": "error", "message": "Broker routing generation is busy; retry"}
        ), 503
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
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None
    rebuild_lock = current_app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    try:
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            authorised, authorised_error = _authorised_account_selectors(jwt_payload)
            if authorised_error is not None:
                return authorised_error
            assert authorised is not None
            targets: list[dict[str, Any]] = []
            root = _reconciliation_root()
            if root.is_dir():
                for broker_dir in sorted(p for p in root.iterdir() if p.is_dir()):
                    for history in sorted(broker_dir.glob("*.jsonl")):
                        latest = next(
                            (
                                report
                                for raw_report in _read_jsonl_tail(
                                    history,
                                    _RECONCILIATION_MAX_LIMIT,
                                )
                                if (report := _normalise_reconciliation_report(raw_report))
                                is not None
                            ),
                            None,
                        )
                        if latest is None:
                            continue
                        report = latest
                        broker = str(report["adapter_id"])
                        account_id = str(report["account_id"])
                        if f"{broker}:{account_id}" not in authorised:
                            continue
                        targets.append(
                            {
                                "broker": broker,
                                "account_id": account_id,
                                "last_report_at": str(report.get("generated_at", "")),
                                "clean": bool(report.get("clean", False)),
                                "severity": str(report.get("severity", "")),
                                "severity_counts": dict(report.get("severity_counts") or {}),
                                "error": str(report.get("error", "")),
                            }
                        )
            runner = current_app.config.get("RECONCILIATION_RUNNER")
            runner_active = runner is not None and bool(getattr(runner, "is_running", False))
            return jsonify(
                {
                    "status": "success",
                    "data": {"targets": targets, "runner_active": runner_active},
                }
            ), 200
    except GenerationLeaseUnavailableError:
        return jsonify(
            {"status": "error", "message": "Broker routing generation is busy; retry"}
        ), 503
    except Exception:
        logger.exception("reconciliation_status error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@operations_bp.route("/reconciliation/run", methods=["POST"])
@require_scope("admin.observability.run")
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
    from flinttrade_engine.safety import (  # noqa: PLC0415
        GenerationLeaseUnavailableError,
        bounded_generation_lease,
    )

    jwt_payload, auth_error = _authenticated_operator_identity()
    if auth_error is not None:
        return auth_error
    assert jwt_payload is not None
    runner = current_app.config.get("RECONCILIATION_RUNNER")
    if runner is None:
        return jsonify(
            {
                "status": "error",
                "message": "Reconciliation runner not active — no native broker sessions to reconcile",
            }
        ), 503
    try:
        rebuild_lock = current_app.config.setdefault(
            "BROKER_ROUTER_REBUILD_LOCK",
            threading.RLock(),
        )
        with bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_ROUTER_GENERATION_LEASE_TIMEOUT_SECONDS,
        ):
            authorised, authorised_error = _authorised_account_selectors(jwt_payload)
            if authorised_error is not None:
                return authorised_error
            assert authorised is not None
            payloads = runner.trigger(selectors=authorised, force=False)
            payloads = [
                payload
                for payload in payloads
                if (
                    f"{str(payload.get('adapter_id') or '').lower()}:"
                    f"{str(payload.get('account_id') or '')}"
                ) in authorised
            ]
        return jsonify(
            {
                "status": "success",
                "data": {"count": len(payloads), "reports": payloads},
            }
        ), 200
    except Exception as exc:
        from flinttrade_engine.reconciliation_runner import (  # noqa: PLC0415
            ReconciliationRunBusyError,
        )

        if isinstance(exc, ReconciliationRunBusyError):
            return jsonify(
                {
                    "status": "error",
                    "message": "A reconciliation cycle is already active",
                }
            ), 409
        if isinstance(exc, GenerationLeaseUnavailableError):
            return jsonify(
                {"status": "error", "message": "Broker routing generation is busy; retry"}
            ), 503
        logger.exception("reconciliation_run error")
        return jsonify({"status": "error", "message": "Internal server error"}), 500
