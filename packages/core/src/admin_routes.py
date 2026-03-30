"""Admin API endpoints — dev/debug only.

Provides internal visibility into package health, widget registry,
repo absorption status, feature flags, and project introspection.

Blueprint: /ft-api/v1/admin/
Only registered when app.debug is True or FLINTTRADE_DEV env var is set.
"""

from __future__ import annotations

import glob as _glob
import json
import logging
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify

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
        "packages": data,
        "total_packages": len(data),
        "total_tests": total_tests,
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
