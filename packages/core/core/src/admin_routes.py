"""Admin API endpoints — dev/debug only.

Provides internal visibility into package health, widget registry,
repo absorption status, feature flags, and project introspection.

Blueprint: /v1/admin/
Only registered when app.debug is True or FLINTTRADE_DEV env var is set.
"""

from __future__ import annotations

import glob as _glob
import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

logger = logging.getLogger("flinttrade.admin")

admin_bp = Blueprint("admin", __name__, url_prefix="/v1/admin")

# Repo root — 3 levels up from packages/core/core/src/
_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATUS_FILE = _REPO_ROOT / ".local" / "reference" / "absorption-status.json"


# ---------------------------------------------------------------------------
# Widget registry — mirrors widgetFactory.tsx
# ---------------------------------------------------------------------------

_WIDGET_REGISTRY: list[dict[str, str]] = [
    # Trading
    {"id": "dashboard", "name": "Dashboard", "category": "Trading", "status": "live"},
    {"id": "scalper", "name": "Scalper", "category": "Trading", "status": "live"},
    {"id": "positions", "name": "Positions", "category": "Trading", "status": "live"},
    {"id": "orders", "name": "Orders", "category": "Trading", "status": "live"},
    {"id": "holdings", "name": "Holdings", "category": "Trading", "status": "live"},
    {"id": "tradebook", "name": "Trade Book", "category": "Trading", "status": "live"},
    {"id": "orderpad", "name": "Order Pad", "category": "Trading", "status": "live"},
    {"id": "mtmmonitor", "name": "MTM Monitor", "category": "Trading", "status": "live"},
    {"id": "riskpanel", "name": "Risk Panel", "category": "Trading", "status": "live"},
    {"id": "actioncenter", "name": "Action Center", "category": "Trading", "status": "live"},
    # Analysis
    {"id": "chart", "name": "Chart", "category": "Analysis", "status": "live"},
    {"id": "optionchain", "name": "Option Chain", "category": "Analysis", "status": "live"},
    {"id": "oichart", "name": "OI Chart", "category": "Analysis", "status": "live"},
    {"id": "straddle", "name": "Straddle", "category": "Analysis", "status": "live"},
    {"id": "depth", "name": "Depth", "category": "Analysis", "status": "live"},
    {"id": "greeks", "name": "Greeks", "category": "Analysis", "status": "live"},
    {"id": "sectormap", "name": "Sector Map", "category": "Analysis", "status": "live"},
    {"id": "gex", "name": "GEX Dashboard", "category": "Analysis", "status": "live"},
    {"id": "volsurface", "name": "Vol Surface", "category": "Analysis", "status": "live"},
    {"id": "ivsmile", "name": "IV Smile", "category": "Analysis", "status": "live"},
    {"id": "straddlepnl", "name": "Straddle P&L", "category": "Analysis", "status": "live"},
    {"id": "oiprofile", "name": "OI Profile", "category": "Analysis", "status": "live"},
    {"id": "orderflow", "name": "Order Flow", "category": "Analysis", "status": "live"},
    # Utility
    {"id": "watchlist", "name": "Watchlist", "category": "Utility", "status": "live"},
    {"id": "calculator", "name": "Calculator", "category": "Utility", "status": "live"},
    {"id": "news", "name": "News Feed", "category": "Utility", "status": "live"},
    {"id": "ticker", "name": "Ticker", "category": "Utility", "status": "live"},
    {"id": "aiadvisor", "name": "AI Advisor", "category": "Utility", "status": "live"},
]

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

_FEATURE_FLAGS: list[dict[str, str]] = [
    {"name": "Dockview Workspace", "status": "live", "route": "/trade"},
    {"name": "Multi-broker Gateway", "status": "live", "route": "/settings"},
    {"name": "Option Chain (real-time)", "status": "live", "route": "/trade"},
    {"name": "GEX Dashboard", "status": "live", "route": "/trade"},
    {"name": "IV Smile / Vol Surface", "status": "live", "route": "/trade"},
    {"name": "Security Monitoring", "status": "live", "route": "/settings"},
    {"name": "P&L Tracker", "status": "live", "route": "/trade"},
    {"name": "AI Advisor Chat", "status": "live", "route": "/ai"},
    {"name": "Backtest Lab", "status": "live", "route": "/lab"},
    {"name": "Flow Builder", "status": "live", "route": "/automate"},
    {"name": "Strategy Builder", "status": "live", "route": "/automate"},
    {"name": "Investor Dashboard", "status": "live", "route": "/invest"},
    {"name": "Learn Center", "status": "live", "route": "/learn"},
    {"name": "Voice Trading", "status": "locked", "route": "/trade"},
    {"name": "Telegram Kill Switch", "status": "locked", "route": "/automate"},
    {"name": "Multi-account Mirroring", "status": "locked", "route": "/settings"},
    {"name": "AI Swarm Intelligence", "status": "locked", "route": "/ai"},
    {"name": "Rust Tick Engine", "status": "locked", "route": "/trade"},
]


@admin_bp.route("/health", methods=["GET"])
def admin_health() -> tuple[Response, int]:
    """Aggregate package health status (delegates to introspect)."""
    data = _introspect_packages()
    total_tests = sum(p["testCount"] for p in data)
    return jsonify({
        "status": "success",
        "data": {
            "packages": data,
            "total_packages": len(data),
            "total_tests": total_tests,
        },
    }), 200


def _introspect_packages() -> list[dict[str, object]]:
    """Scan the packages/ directory and count real test functions."""
    root = str(_REPO_ROOT)
    packages: list[dict[str, object]] = []

    pkg_dirs = sorted(_glob.glob(os.path.join(root, "packages", "*")))
    for pkg_dir in pkg_dirs:
        if not os.path.isdir(pkg_dir):
            continue
        name = os.path.basename(pkg_dir)

        if name == "terminal":
            pkg_type = "react"
            test_files = _glob.glob(os.path.join(pkg_dir, "src", "**", "*.test.ts"), recursive=True)
            test_files += _glob.glob(os.path.join(pkg_dir, "src", "**", "*.test.tsx"), recursive=True)
        elif name == "tick-engine":
            pkg_type = "rust"
            test_files = _glob.glob(os.path.join(pkg_dir, "tests", "*.py"))
        else:
            pkg_type = "python"
            test_files = _glob.glob(os.path.join(pkg_dir, "tests", "*.py"))

        test_count = 0
        for tf in test_files:
            try:
                with open(tf, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        stripped = line.strip()
                        if (
                            stripped.startswith("def test_")
                            or stripped.startswith("it(")
                            or stripped.startswith("test(")
                        ):
                            test_count += 1
            except OSError:
                pass

        packages.append({
            "name": name,
            "type": pkg_type,
            "status": "active",
            "testCount": test_count,
            "testFiles": len(test_files),
        })

    return packages


@admin_bp.route("/introspect", methods=["GET"])
def admin_introspect() -> tuple[Response, int]:
    """Return real-time project introspection data for /admin dashboard.

    Scans the filesystem for actual test counts per package and
    enumerates all Flask routes registered on the running application.
    """
    packages = _introspect_packages()

    # Enumerate Flask routes from the running app
    endpoints: list[dict[str, str]] = []
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        methods = [m for m in rule.methods if m not in ("HEAD", "OPTIONS")]
        for method in methods:
            endpoints.append({
                "method": method,
                "path": rule.rule,
                "status": "wired",
            })

    endpoints.sort(key=lambda e: e["path"])

    return jsonify({
        "status": "success",
        "data": {
            "packages": packages,
            "endpoints": endpoints,
            "endpoint_count": len(endpoints),
            "package_count": len(packages),
        },
    }), 200


@admin_bp.route("/widgets", methods=["GET"])
def admin_widgets() -> tuple[Response, int]:
    """Return the widget registry."""
    by_category: dict[str, int] = {}
    for w in _WIDGET_REGISTRY:
        cat = w["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    return jsonify({
        "status": "success",
        "data": {
            "widgets": _WIDGET_REGISTRY,
            "total": len(_WIDGET_REGISTRY),
            "by_category": by_category,
        },
    }), 200


@admin_bp.route("/repos", methods=["GET"])
def admin_repos() -> tuple[Response, int]:
    """Read absorption-status.json and return as JSON."""
    if not _STATUS_FILE.exists():
        return jsonify({
            "status": "error",
            "message": "absorption-status.json not found",
        }), 404

    try:
        data: dict[str, Any] = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        return jsonify({"status": "success", "data": data}), 200
    except json.JSONDecodeError as exc:
        return jsonify({
            "status": "error",
            "message": f"Invalid JSON: {exc}",
        }), 500


@admin_bp.route("/system", methods=["GET"])
def admin_system() -> tuple[Response, int]:
    """Return current host resource metrics for the /admin dashboard.

    Delegates to :func:`~flinttrade_core.system_metrics.get_system_metrics`.
    When psutil is not installed the response is still HTTP 200 with all
    metric fields set to zero and ``psutil_available: false``.
    """
    from .system_metrics import get_system_metrics  # noqa: PLC0415

    metrics = get_system_metrics()
    return jsonify({
        "status": "success",
        "data": metrics.to_dict(),
    }), 200


@admin_bp.route("/errors", methods=["GET"])
def admin_errors() -> tuple[Response, int]:
    """Return recent error log entries for the /admin dashboard.

    Reads the ``ERROR_LOG`` instance from ``current_app.config``.
    Supports ``limit`` (default 100, max 500) and ``offset`` (default 0)
    query parameters for pagination.

    Returns:
        JSON response with ``status``, ``data.errors``, and ``data.total``.
    """
    error_log = current_app.config.get("ERROR_LOG")
    if error_log is None:
        return jsonify({"status": "error", "message": "Error log not initialised"}), 503

    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("offset", 0))
    except ValueError:
        return jsonify({"status": "error", "message": "limit and offset must be integers"}), 400

    errors = error_log.recent(limit=limit, offset=offset)
    total = error_log.count()
    return jsonify({
        "status": "success",
        "data": {
            "errors": errors,
            "total": total,
            "limit": limit,
            "offset": offset,
        },
    }), 200


@admin_bp.route("/errors/count", methods=["GET"])
def admin_errors_count() -> tuple[Response, int]:
    """Return the total number of persisted error entries.

    Returns:
        JSON response with ``status`` and ``data.count``.
    """
    error_log = current_app.config.get("ERROR_LOG")
    if error_log is None:
        return jsonify({"status": "error", "message": "Error log not initialised"}), 503

    count = error_log.count()
    return jsonify({"status": "success", "data": {"count": count}}), 200


@admin_bp.route("/features", methods=["GET"])
def admin_features() -> tuple[Response, int]:
    """Return feature flag status."""
    by_status: dict[str, int] = {}
    for f in _FEATURE_FLAGS:
        s = f["status"]
        by_status[s] = by_status.get(s, 0) + 1

    return jsonify({
        "status": "success",
        "data": {
            "features": _FEATURE_FLAGS,
            "total": len(_FEATURE_FLAGS),
            "by_status": by_status,
        },
    }), 200


# ---------------------------------------------------------------------------
# Security dashboard routes
# ---------------------------------------------------------------------------


def _get_login_activity():  # type: ignore[return]
    """Return the LoginActivity instance from app config."""
    from flinttrade_data.activity_log import LoginActivity  # noqa: PLC0415

    la = current_app.config.get("LOGIN_ACTIVITY")
    if la is None:
        # Lazy-initialise a persistent instance on first use.
        from pathlib import Path  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "activity.db"
        la = LoginActivity(str(db_path))
        current_app.config["LOGIN_ACTIVITY"] = la
    return la


def _get_session_tracker():  # type: ignore[return]
    """Return the SessionTracker instance from app config."""
    from flinttrade_data.activity_log import SessionTracker  # noqa: PLC0415

    st = current_app.config.get("SESSION_TRACKER")
    if st is None:
        from pathlib import Path  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "activity.db"
        st = SessionTracker(str(db_path))
        current_app.config["SESSION_TRACKER"] = st
    return st


def _get_security_tracker():  # type: ignore[return]
    """Return the SecurityTracker instance from app config."""
    from flinttrade_data.security_tracker import SecurityTracker  # noqa: PLC0415

    skt = current_app.config.get("SECURITY_TRACKER")
    if skt is None:
        from pathlib import Path  # noqa: PLC0415

        db_path = Path.home() / ".flinttrade" / "security.db"
        skt = SecurityTracker(str(db_path))
        current_app.config["SECURITY_TRACKER"] = skt
    return skt


@admin_bp.route("/security/logins", methods=["GET"])
def recent_logins() -> tuple[Response, int]:
    """Return recent login events.

    Query params:
        user_id (str, optional): Filter to a specific user.
        limit (int, optional): Max rows, default 100.

    Returns:
        JSON with ``status`` and ``data.logins`` list.
    """
    user_id: str | None = request.args.get("user_id") or None
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    la = _get_login_activity()
    logins = la.recent_logins(user_id=user_id, limit=limit)
    return jsonify({
        "status": "success",
        "data": {"logins": logins, "count": len(logins)},
    }), 200


@admin_bp.route("/security/sessions", methods=["GET"])
def active_sessions() -> tuple[Response, int]:
    """Return currently active sessions.

    Query params:
        user_id (str, optional): Filter to a specific user.

    Returns:
        JSON with ``status`` and ``data.sessions`` list.
    """
    user_id: str | None = request.args.get("user_id") or None
    st = _get_session_tracker()
    sessions = st.active_sessions(user_id=user_id)
    return jsonify({
        "status": "success",
        "data": {"sessions": sessions, "count": len(sessions)},
    }), 200


@admin_bp.route("/security/suspicious", methods=["GET"])
def suspicious_activity() -> tuple[Response, int]:
    """Return IPs with suspicious activity (failed logins + 404 floods).

    Query params:
        window_hours (int, optional): Lookback window for login failures,
            default 24.
        threshold (int, optional): Min failed request count for IP bans
            analysis, default 10.

    Returns:
        JSON with ``status`` and ``data`` containing ``suspicious_logins``
        and ``suspicious_ips``.
    """
    try:
        window_hours = int(request.args.get("window_hours", 24))
        threshold = int(request.args.get("threshold", 10))
    except ValueError:
        return jsonify({"status": "error", "message": "window_hours and threshold must be integers"}), 400

    la = _get_login_activity()
    skt = _get_security_tracker()
    return jsonify({
        "status": "success",
        "data": {
            "suspicious_logins": la.suspicious_logins(window_hours=window_hours),
            "suspicious_ips": skt.suspicious_ips(threshold=threshold),
        },
    }), 200


@admin_bp.route("/security/bans", methods=["GET"])
def banned_ips() -> tuple[Response, int]:
    """Return recent IP ban records.

    Query params:
        limit (int, optional): Max rows, default 50.

    Returns:
        JSON with ``status`` and ``data.bans`` list.
    """
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400

    skt = _get_security_tracker()
    bans = skt.recent_bans(limit=limit)
    return jsonify({
        "status": "success",
        "data": {"bans": bans, "count": len(bans)},
    }), 200


@admin_bp.route("/security/bans", methods=["POST"])
def ban_ip_route() -> tuple[Response, int]:
    """Manually ban an IP address (persisted in DuckDB).

    Request JSON:
        ip (str): IP address to ban.
        reason (str): Human-readable justification.
        duration_hours (int, optional): How long to ban; 0 = permanent.
            Defaults to 24.

    Returns:
        JSON with ``status`` and ``data.ban_id`` on success.
    """
    body = request.get_json(silent=True) or {}
    ip: str = (body.get("ip") or "").strip()
    reason: str = (body.get("reason") or "").strip()

    if not ip:
        return jsonify({"status": "error", "message": "ip is required"}), 400
    if not reason:
        return jsonify({"status": "error", "message": "reason is required"}), 400

    try:
        duration_hours = int(body.get("duration_hours", 24))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "duration_hours must be an integer"}), 400

    skt = _get_security_tracker()
    ban_id = skt.ban_ip(ip, reason, duration_hours=duration_hours)

    # Also apply the in-memory ban so requests are blocked immediately.
    try:
        mon = current_app.config.get("SECURITY_MONITOR")
        if mon is not None:
            duration_seconds = duration_hours * 3600 if duration_hours > 0 else None
            mon.ban_ip(ip, reason, duration_seconds)
    except Exception:
        pass  # Best-effort — persistent ban is already recorded

    return jsonify({
        "status": "success",
        "data": {"ban_id": ban_id, "ip": ip, "reason": reason, "duration_hours": duration_hours},
    }), 200


@admin_bp.route("/security/bans/<path:ip>", methods=["DELETE"])
def unban_ip_route(ip: str) -> tuple[Response, int]:
    """Lift persistent and in-memory bans on an IP address.

    Args:
        ip: IP address to unban (URL path segment).

    Returns:
        JSON with ``status`` and ``data.lifted`` (bool).
    """
    ip = ip.strip()
    if not ip:
        return jsonify({"status": "error", "message": "ip is required"}), 400

    skt = _get_security_tracker()
    lifted = skt.unban_ip(ip)

    # Also lift the in-memory ban.
    try:
        mon = current_app.config.get("SECURITY_MONITOR")
        if mon is not None:
            mon.unban_ip(ip)
    except Exception:
        pass

    return jsonify({
        "status": "success",
        "data": {"ip": ip, "lifted": lifted},
    }), 200
