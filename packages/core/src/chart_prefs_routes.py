"""Chart preferences Flask endpoints.

Registered as a Blueprint in ``create_flask_app()``.

Endpoints
---------
GET  /chart-prefs/theme                     — get user's chart theme
POST /chart-prefs/theme                     — set user's chart theme
GET  /chart-prefs/indicators                — list indicator set names
GET  /chart-prefs/indicators/{name}         — load a named indicator set
POST /chart-prefs/indicators/{name}         — save a named indicator set
DELETE /chart-prefs/indicators/{name}       — delete a named indicator set
GET  /chart-prefs/layouts                   — list layout names
GET  /chart-prefs/layouts/{name}            — load a named layout
POST /chart-prefs/layouts/{name}            — save a named layout
DELETE /chart-prefs/layouts/{name}          — delete a named layout

All endpoints require an ``X-User-Id`` header (or ``user_id`` query param)
to identify the user.  In single-user mode the caller can pass ``"default"``.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from .chart_prefs import ChartPreferences

logger = logging.getLogger("flinttrade.core.chart_prefs_routes")

chart_prefs_bp = Blueprint("chart_prefs", __name__)

# Module-level singleton — replaced by init_chart_prefs_routes when injected.
_prefs: ChartPreferences | None = None


def _get_prefs() -> ChartPreferences:
    """Return the singleton, creating it lazily on first access."""
    global _prefs  # noqa: PLW0603
    if _prefs is None:
        _prefs = ChartPreferences()
    return _prefs


def init_chart_prefs_routes(prefs: ChartPreferences) -> None:
    """Inject a ChartPreferences instance into the blueprint.

    Args:
        prefs: The :class:`ChartPreferences` instance to use.
    """
    global _prefs  # noqa: PLW0603
    _prefs = prefs
    logger.info("ChartPreferences singleton injected into chart_prefs_routes")


def _user_id() -> str | None:
    """Extract user ID from header or query parameter."""
    return (
        request.headers.get("X-User-Id")
        or request.args.get("user_id")
        or None
    )


def _require_user_id() -> tuple[str | None, tuple[Any, int] | None]:
    """Return (user_id, None) or (None, error_response)."""
    uid = _user_id()
    if not uid:
        return None, (
            jsonify({"status": "error", "message": "X-User-Id header or user_id param required"}),
            400,
        )
    return uid, None


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


@chart_prefs_bp.route("/chart-prefs/theme", methods=["GET"])
def get_theme() -> tuple[Any, int]:
    """Return the user's chart theme.

    Returns:
        JSON ``{"status": "success", "data": {...}}`` or 404 if not set.
    """
    uid, err = _require_user_id()
    if err:
        return err

    theme = _get_prefs().get_theme(uid)  # type: ignore[arg-type]
    if theme is None:
        return jsonify({"status": "error", "message": "No theme saved for this user"}), 404
    return jsonify({"status": "success", "data": theme}), 200


@chart_prefs_bp.route("/chart-prefs/theme", methods=["POST"])
def set_theme() -> tuple[Any, int]:
    """Save the user's chart theme.

    Request JSON:
        Any key-value pairs that describe the chart theme.

    Returns:
        JSON ``{"status": "success"}``
    """
    uid, err = _require_user_id()
    if err:
        return err

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Request body must be a JSON object"}), 400

    _get_prefs().set_theme(uid, body)  # type: ignore[arg-type]
    return jsonify({"status": "success"}), 200


# ---------------------------------------------------------------------------
# Indicator sets
# ---------------------------------------------------------------------------


@chart_prefs_bp.route("/chart-prefs/indicators", methods=["GET"])
def list_indicator_sets() -> tuple[Any, int]:
    """List saved indicator set names for the user.

    Returns:
        JSON ``{"status": "success", "data": ["name1", "name2", ...]}``
    """
    uid, err = _require_user_id()
    if err:
        return err

    names = _get_prefs().list_indicator_sets(uid)  # type: ignore[arg-type]
    return jsonify({"status": "success", "data": names}), 200


@chart_prefs_bp.route("/chart-prefs/indicators/<name>", methods=["GET"])
def get_indicator_set(name: str) -> tuple[Any, int]:
    """Load a named indicator set.

    Path parameters:
        name (str): Indicator set name.

    Returns:
        JSON ``{"status": "success", "data": [...]}`` or 404 if not found.
    """
    uid, err = _require_user_id()
    if err:
        return err

    indicators = _get_prefs().load_indicator_set(uid, name)  # type: ignore[arg-type]
    if indicators is None:
        return jsonify({"status": "error", "message": f"Indicator set {name!r} not found"}), 404
    return jsonify({"status": "success", "data": indicators}), 200


@chart_prefs_bp.route("/chart-prefs/indicators/<name>", methods=["POST"])
def save_indicator_set(name: str) -> tuple[Any, int]:
    """Save a named indicator set.

    Path parameters:
        name (str): Indicator set name.

    Request JSON:
        List of indicator config objects.

    Returns:
        JSON ``{"status": "success"}``
    """
    uid, err = _require_user_id()
    if err:
        return err

    body = request.get_json(silent=True)
    if not isinstance(body, list):
        return jsonify({"status": "error", "message": "Request body must be a JSON array"}), 400

    _get_prefs().save_indicator_set(uid, name, body)  # type: ignore[arg-type]
    return jsonify({"status": "success"}), 200


@chart_prefs_bp.route("/chart-prefs/indicators/<name>", methods=["DELETE"])
def delete_indicator_set(name: str) -> tuple[Any, int]:
    """Delete a named indicator set.

    Path parameters:
        name (str): Indicator set name.

    Returns:
        JSON ``{"status": "success"}`` or 404 if not found.
    """
    uid, err = _require_user_id()
    if err:
        return err

    deleted = _get_prefs().delete_indicator_set(uid, name)  # type: ignore[arg-type]
    if not deleted:
        return jsonify({"status": "error", "message": f"Indicator set {name!r} not found"}), 404
    return jsonify({"status": "success"}), 200


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


@chart_prefs_bp.route("/chart-prefs/layouts", methods=["GET"])
def list_layouts() -> tuple[Any, int]:
    """List saved layout names for the user.

    Returns:
        JSON ``{"status": "success", "data": ["name1", "name2", ...]}``
    """
    uid, err = _require_user_id()
    if err:
        return err

    names = _get_prefs().list_layouts(uid)  # type: ignore[arg-type]
    return jsonify({"status": "success", "data": names}), 200


@chart_prefs_bp.route("/chart-prefs/layouts/<name>", methods=["GET"])
def get_layout(name: str) -> tuple[Any, int]:
    """Load a named chart layout.

    Path parameters:
        name (str): Layout name.

    Returns:
        JSON ``{"status": "success", "data": {...}}`` or 404 if not found.
    """
    uid, err = _require_user_id()
    if err:
        return err

    layout = _get_prefs().load_layout(uid, name)  # type: ignore[arg-type]
    if layout is None:
        return jsonify({"status": "error", "message": f"Layout {name!r} not found"}), 404
    return jsonify({"status": "success", "data": layout}), 200


@chart_prefs_bp.route("/chart-prefs/layouts/<name>", methods=["POST"])
def save_layout(name: str) -> tuple[Any, int]:
    """Save a named chart layout.

    Path parameters:
        name (str): Layout name.

    Request JSON:
        Serialised layout object.

    Returns:
        JSON ``{"status": "success"}``
    """
    uid, err = _require_user_id()
    if err:
        return err

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"status": "error", "message": "Request body must be a JSON object"}), 400

    _get_prefs().save_layout(uid, name, body)  # type: ignore[arg-type]
    return jsonify({"status": "success"}), 200


@chart_prefs_bp.route("/chart-prefs/layouts/<name>", methods=["DELETE"])
def delete_layout(name: str) -> tuple[Any, int]:
    """Delete a named chart layout.

    Path parameters:
        name (str): Layout name.

    Returns:
        JSON ``{"status": "success"}`` or 404 if not found.
    """
    uid, err = _require_user_id()
    if err:
        return err

    deleted = _get_prefs().delete_layout(uid, name)  # type: ignore[arg-type]
    if not deleted:
        return jsonify({"status": "error", "message": f"Layout {name!r} not found"}), 404
    return jsonify({"status": "success"}), 200
