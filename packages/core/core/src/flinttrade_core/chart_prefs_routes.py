"""Chart preferences API backed by FlintTrade's local preference store.

Endpoint
--------
GET/POST /api/v1/chart

The terminal historically exposed ``getChartPreferences`` and
``updateChartPreferences`` through an OpenAlgo-style ``/chart`` helper. The
data is owned by FlintTrade, so this route bridges those exports to the
existing :class:`flinttrade_core.chart_prefs.ChartPreferences` store.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .chart_prefs import ChartPreferences

logger = logging.getLogger("flinttrade.core.chart_prefs_routes")

chart_prefs_bp = Blueprint("chart_prefs", __name__, url_prefix="/api/v1")

_prefs: ChartPreferences | None = None


def init_chart_prefs_routes(prefs: ChartPreferences) -> None:
    """Inject the preference store used by this blueprint."""
    global _prefs  # noqa: PLW0603
    _prefs = prefs
    logger.info("ChartPreferences injected into chart_prefs_routes")


def _store() -> ChartPreferences:
    global _prefs  # noqa: PLW0603
    if _prefs is None:
        _prefs = ChartPreferences()
    return _prefs


def _user_id() -> str:
    """Resolve the preference namespace from the request."""
    raw = (
        request.headers.get("X-User-Id")
        or request.headers.get("X-User-ID")
        or request.args.get("user_id")
        or "default"
    )
    return str(raw).strip() or "default"


def _load_payload(user_id: str) -> dict[str, Any]:
    prefs = _store()
    indicator_sets = {
        name: prefs.load_indicator_set(user_id, name) or []
        for name in prefs.list_indicator_sets(user_id)
    }
    layouts = {
        name: prefs.load_layout(user_id, name) or {}
        for name in prefs.list_layouts(user_id)
    }
    return {
        "user_id": user_id,
        "theme": prefs.get_theme(user_id) or {},
        "indicator_sets": indicator_sets,
        "layouts": layouts,
        "layout": layouts.get("default", {}),
    }


def _as_dict(value: Any, field: str) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, (
            jsonify({"status": "error", "message": f"{field} must be an object"}),
            400,
        )
    return value, None


def _as_indicator_list(value: Any, field: str) -> tuple[list[dict[str, Any]] | None, tuple[Any, int] | None]:
    if value is None:
        return None, None
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        return None, (
            jsonify({"status": "error", "message": f"{field} must be an array of objects"}),
            400,
        )
    return value, None


@chart_prefs_bp.route("/chart", methods=["GET", "POST"])
def chart_preferences() -> tuple[Any, int]:
    """Read or update chart theme, indicator sets, and layouts."""
    user_id = _user_id()
    prefs = _store()

    if request.method == "GET":
        return jsonify({"status": "success", "data": _load_payload(user_id)}), 200

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "JSON object body required"}), 400

    theme, err = _as_dict(body.get("theme"), "theme")
    if err is not None:
        return err
    if theme is not None:
        prefs.set_theme(user_id, theme)

    indicator_sets, err = _as_dict(body.get("indicator_sets"), "indicator_sets")
    if err is not None:
        return err
    if indicator_sets is not None:
        for name, indicators in indicator_sets.items():
            indicator_list, err = _as_indicator_list(indicators, f"indicator_sets.{name}")
            if err is not None:
                return err
            prefs.save_indicator_set(user_id, str(name), indicator_list or [])

    indicators, err = _as_indicator_list(body.get("indicators"), "indicators")
    if err is not None:
        return err
    if indicators is not None:
        prefs.save_indicator_set(user_id, str(body.get("indicator_set_name") or "default"), indicators)

    layouts, err = _as_dict(body.get("layouts"), "layouts")
    if err is not None:
        return err
    if layouts is not None:
        for name, layout_value in layouts.items():
            layout, err = _as_dict(layout_value, f"layouts.{name}")
            if err is not None:
                return err
            prefs.save_layout(user_id, str(name), layout or {})

    layout, err = _as_dict(body.get("layout"), "layout")
    if err is not None:
        return err
    if layout is not None:
        prefs.save_layout(user_id, str(body.get("layout_name") or "default"), layout)

    handled_keys = {
        "theme",
        "indicator_sets",
        "indicators",
        "indicator_set_name",
        "layouts",
        "layout",
        "layout_name",
    }
    if not any(key in body for key in handled_keys):
        prefs.save_layout(user_id, "default", body)

    return jsonify({"status": "success", "data": _load_payload(user_id)}), 200
