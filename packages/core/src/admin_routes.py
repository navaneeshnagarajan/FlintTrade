"""Admin API endpoints — dev/debug only.

Provides internal visibility into package health, widget registry,
repo absorption status, and feature flags.

Blueprint: /ft-api/v1/admin/
Only registered when app.debug is True or FLINTTRADE_DEV env var is set.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify

logger = logging.getLogger("flinttrade.admin")

admin_bp = Blueprint("admin", __name__, url_prefix="/ft-api/v1/admin")

# Repo root — 3 levels up from packages/core/src/
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
    {"name": "AI Advisor Chat", "status": "preview", "route": "/ai"},
    {"name": "Backtest Lab", "status": "preview", "route": "/lab"},
    {"name": "Flow Builder", "status": "preview", "route": "/automate"},
    {"name": "Strategy Builder", "status": "preview", "route": "/automate"},
    {"name": "Investor Dashboard", "status": "preview", "route": "/invest"},
    {"name": "Learn Center", "status": "preview", "route": "/learn"},
    {"name": "Voice Trading", "status": "locked", "route": "/trade"},
    {"name": "Telegram Kill Switch", "status": "locked", "route": "/automate"},
    {"name": "Multi-account Mirroring", "status": "locked", "route": "/settings"},
    {"name": "AI Swarm Intelligence", "status": "locked", "route": "/ai"},
    {"name": "Rust Tick Engine", "status": "locked", "route": "/trade"},
]


@admin_bp.route("/health", methods=["GET"])
def admin_health() -> tuple[Response, int]:
    """Aggregate package health status.

    Returns a summary of all packages with their test status.
    In future this will run tests in a background thread and cache results.
    """
    packages = [
        {"name": "core", "type": "python", "status": "active", "tests": 180},
        {"name": "engine", "type": "python", "status": "active", "tests": 145},
        {"name": "data", "type": "python", "status": "active", "tests": 85},
        {"name": "historical", "type": "python", "status": "active", "tests": 92},
        {"name": "screener", "type": "python", "status": "active", "tests": 110},
        {"name": "backtest-engine", "type": "python", "status": "active", "tests": 98},
        {"name": "ai", "type": "python", "status": "active", "tests": 72},
        {"name": "integration", "type": "python", "status": "active", "tests": 55},
        {"name": "automation", "type": "python", "status": "active", "tests": 48},
        {"name": "ditto", "type": "python", "status": "active", "tests": 42},
        {"name": "indicators", "type": "python", "status": "active", "tests": 58},
        {"name": "gateway", "type": "python", "status": "active", "tests": 0},
        {"name": "terminal", "type": "react", "status": "active", "tests": 36},
        {"name": "tick-engine", "type": "rust", "status": "planned", "tests": 0},
    ]
    total_tests = sum(p["tests"] for p in packages)
    return jsonify({
        "packages": packages,
        "total_packages": len(packages),
        "total_tests": total_tests,
    }), 200


@admin_bp.route("/widgets", methods=["GET"])
def admin_widgets() -> tuple[Response, int]:
    """Return the widget registry."""
    by_category: dict[str, int] = {}
    for w in _WIDGET_REGISTRY:
        cat = w["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    return jsonify({
        "widgets": _WIDGET_REGISTRY,
        "total": len(_WIDGET_REGISTRY),
        "by_category": by_category,
    }), 200


@admin_bp.route("/repos", methods=["GET"])
def admin_repos() -> tuple[Response, int]:
    """Read absorption-status.json and return as JSON."""
    if not _STATUS_FILE.exists():
        return jsonify({
            "error": "absorption-status.json not found",
            "path": str(_STATUS_FILE),
        }), 404

    try:
        data: dict[str, Any] = json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        return jsonify(data), 200
    except json.JSONDecodeError as exc:
        return jsonify({
            "error": f"Invalid JSON: {exc}",
        }), 500


@admin_bp.route("/features", methods=["GET"])
def admin_features() -> tuple[Response, int]:
    """Return feature flag status."""
    by_status: dict[str, int] = {}
    for f in _FEATURE_FLAGS:
        s = f["status"]
        by_status[s] = by_status.get(s, 0) + 1

    return jsonify({
        "features": _FEATURE_FLAGS,
        "total": len(_FEATURE_FLAGS),
        "by_status": by_status,
    }), 200
