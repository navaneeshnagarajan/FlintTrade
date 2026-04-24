"""Workspace preset management API — /ft-api/v1/presets/*.

Persists custom Dockview workspace presets to ~/.flinttrade/presets.json so
they are shared across machines when the file is synced (or served from the
same backend).

Built-in presets are read-only and always included in the listing.  Custom
presets are stored in the JSON file and can be created, updated, deleted, or
forked from a built-in.

External URL: /ft-api/v1/presets/* (the WSGI prefix stripper in app.py
translates this to /v1/presets/* before Flask dispatch).
Blueprint prefix: /v1/presets
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("flinttrade.core.preset_routes")

preset_bp = Blueprint("presets", __name__, url_prefix="/v1/presets")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WorkspacePreset(BaseModel):
    """A named Dockview workspace layout, built-in or custom.

    Attributes:
        id: Unique identifier (UUID4 for custom, slug for built-ins).
        name: Human-readable display name.
        description: Short description shown in the preset picker.
        widgets: Ordered list of widget IDs included in this preset.
        layout: Serialised Dockview layout object (arbitrary nested dict).
        is_builtin: True for built-in presets shipped with FlintTrade.
        created_at: ISO 8601 UTC timestamp of creation.
        updated_at: ISO 8601 UTC timestamp of last update.
    """

    id: str
    name: str
    description: str
    widgets: list[str]
    layout: dict[str, Any] = Field(default_factory=dict)
    is_builtin: bool = False
    created_at: datetime
    updated_at: datetime


class PresetCreateRequest(BaseModel):
    """Request body for POST /presets/ and POST /presets/<id>/fork.

    Attributes:
        name: Unique name for the new preset.
        description: Short description.
        widgets: List of widget IDs.
        layout: Serialised Dockview layout.
    """

    name: str
    description: str = ""
    widgets: list[str] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)


class PresetUpdateRequest(BaseModel):
    """Request body for PUT /presets/<id>.

    All fields are optional — only provided fields are updated.

    Attributes:
        name: New display name (optional).
        description: New description (optional).
        widgets: Replacement widget list (optional).
        layout: Replacement layout object (optional).
    """

    name: str | None = None
    description: str | None = None
    widgets: list[str] | None = None
    layout: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Built-in presets (read-only, not persisted to disk)
# ---------------------------------------------------------------------------

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

_BUILTIN_PRESETS: list[WorkspacePreset] = [
    WorkspacePreset(
        id="scalper-zone",
        name="Scalper Zone",
        description="High-frequency intraday scalping layout with chart, depth, and order pad",
        widgets=["chart", "depth", "orderpad", "positions", "scalper", "mtmmonitor"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="options-desk",
        name="Options Desk",
        description="Full options workflow — chain, straddle, greeks, and risk panel",
        widgets=["optionchain", "straddle", "greeks", "ivsmile", "volsurface", "riskpanel"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="market-watch",
        name="Market Watch",
        description="Broad market overview with watchlist, sector map, news, and ticker",
        widgets=["watchlist", "sectormap", "news", "ticker", "oichart"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="analysis",
        name="Analysis",
        description="Deep technical analysis with chart, GEX, OI profile, and order flow",
        widgets=["chart", "gex", "oiprofile", "orderflow", "straddlepnl"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="risk-monitor",
        name="Risk Monitor",
        description="Portfolio-level risk view — MTM, risk panel, positions, and action centre",
        widgets=["mtmmonitor", "riskpanel", "positions", "actioncenter", "dashboard"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="investor-view",
        name="Investor View",
        description="Long-term investor dashboard — holdings, calculator, news, and AI advisor",
        widgets=["holdings", "calculator", "news", "aiadvisor", "watchlist"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
]

# Fast lookup by id
_BUILTIN_BY_ID: dict[str, WorkspacePreset] = {p.id: p for p in _BUILTIN_PRESETS}


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------


def _flinttrade_home() -> Path:
    """Resolve the platform-appropriate FlintTrade workspace directory.

    Respects the ``FLINTTRADE_HOME`` environment variable for test isolation
    and cross-platform CI.

    Returns:
        Resolved absolute path to the ``~/.flinttrade`` (or equivalent) directory.
    """
    env = os.environ.get("FLINTTRADE_HOME")
    if env:
        return Path(env).expanduser().resolve()

    # Use sys.platform rather than platform.system() — the latter performs a
    # WMI query on Python 3.14/Windows which can hang in restricted
    # environments (no WMI service).
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "flinttrade"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "flinttrade"
        return Path.home() / "AppData" / "Roaming" / "flinttrade"
    # Linux and everything else
    return Path.home() / ".flinttrade"


def _presets_path() -> Path:
    """Return the path to presets.json inside the FlintTrade home directory."""
    return _flinttrade_home() / "presets.json"


def _load_custom() -> dict[str, WorkspacePreset]:
    """Load custom presets from presets.json.

    Returns:
        Mapping of preset id → WorkspacePreset for all persisted custom presets.
        Returns an empty dict if the file does not exist or is malformed.
    """
    path = _presets_path()
    if not path.exists():
        return {}
    try:
        raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return {p["id"]: WorkspacePreset(**p) for p in raw}
    except (json.JSONDecodeError, KeyError, ValidationError) as exc:
        logger.warning("presets.json could not be parsed (%s) — treating as empty", exc)
        return {}


def _save_custom(custom: dict[str, WorkspacePreset]) -> None:
    """Persist custom presets to presets.json.

    Args:
        custom: Mapping of preset id → WorkspacePreset to persist.

    Raises:
        OSError: If the file cannot be written (e.g. permissions).
    """
    path = _presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [p.model_dump(mode="json") for p in custom.values()]
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------


def _preset_dict(preset: WorkspacePreset) -> dict[str, Any]:
    """Serialise a WorkspacePreset to a JSON-safe dict.

    Args:
        preset: The preset to serialise.

    Returns:
        Dict with all fields; datetime values as ISO 8601 strings.
    """
    return preset.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@preset_bp.route("/", methods=["GET"])
def list_presets() -> tuple[Response, int]:
    """List all presets — built-in first, then custom sorted by name.

    Returns:
        JSON ``{ status, data: { presets, total, builtin_count, custom_count } }``
    """
    custom = _load_custom()
    all_presets = list(_BUILTIN_PRESETS) + sorted(custom.values(), key=lambda p: p.name)
    return jsonify({
        "status": "success",
        "data": {
            "presets": [_preset_dict(p) for p in all_presets],
            "total": len(all_presets),
            "builtin_count": len(_BUILTIN_PRESETS),
            "custom_count": len(custom),
        },
    }), 200


@preset_bp.route("/", methods=["POST"])
def create_preset() -> tuple[Response, int]:
    """Save a new custom preset.

    Request JSON:
        name (str): Unique display name.
        description (str, optional): Short description.
        widgets (list[str], optional): Ordered list of widget IDs.
        layout (dict, optional): Serialised Dockview layout.

    Returns:
        JSON ``{ status, data: preset }`` with HTTP 201 on success.
        HTTP 400 if validation fails or name already exists.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = PresetCreateRequest(**body)
    except ValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    name_stripped = req.name.strip()
    if not name_stripped:
        return jsonify({"status": "error", "message": "name must not be empty"}), 400

    custom = _load_custom()

    # Check for name collision across built-ins and custom
    all_names = {p.name.lower() for p in _BUILTIN_PRESETS}
    all_names |= {p.name.lower() for p in custom.values()}
    if name_stripped.lower() in all_names:
        return jsonify({"status": "error", "message": f"A preset named '{name_stripped}' already exists"}), 400

    now = datetime.now(tz=timezone.utc)
    preset = WorkspacePreset(
        id=str(uuid.uuid4()),
        name=name_stripped,
        description=req.description,
        widgets=req.widgets,
        layout=req.layout,
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    custom[preset.id] = preset
    _save_custom(custom)
    logger.info("Created preset '%s' (id=%s)", preset.name, preset.id)
    return jsonify({"status": "success", "data": _preset_dict(preset)}), 201


@preset_bp.route("/<preset_id>", methods=["GET"])
def get_preset(preset_id: str) -> tuple[Response, int]:
    """Retrieve a single preset by id.

    Args:
        preset_id: UUID for custom presets; slug for built-ins.

    Returns:
        JSON ``{ status, data: preset }`` or HTTP 404 if not found.
    """
    # Check built-ins first
    builtin = _BUILTIN_BY_ID.get(preset_id)
    if builtin is not None:
        return jsonify({"status": "success", "data": _preset_dict(builtin)}), 200

    custom = _load_custom()
    preset = custom.get(preset_id)
    if preset is None:
        return jsonify({"status": "error", "message": f"Preset '{preset_id}' not found"}), 404
    return jsonify({"status": "success", "data": _preset_dict(preset)}), 200


@preset_bp.route("/<preset_id>", methods=["PUT"])
def update_preset(preset_id: str) -> tuple[Response, int]:
    """Update a custom preset.

    Only custom presets can be updated; built-ins are immutable.

    Args:
        preset_id: UUID of the custom preset to update.

    Request JSON (all fields optional):
        name (str): New display name.
        description (str): New description.
        widgets (list[str]): Replacement widget list.
        layout (dict): Replacement layout object.

    Returns:
        JSON ``{ status, data: updated_preset }`` or appropriate error.
    """
    if preset_id in _BUILTIN_BY_ID:
        return jsonify({"status": "error", "message": "Built-in presets cannot be modified. Fork it first."}), 403

    custom = _load_custom()
    preset = custom.get(preset_id)
    if preset is None:
        return jsonify({"status": "error", "message": f"Preset '{preset_id}' not found"}), 404

    body = request.get_json(silent=True) or {}
    try:
        req = PresetUpdateRequest(**body)
    except ValidationError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    # Apply partial updates
    update_data = req.model_dump(exclude_none=True)
    if not update_data:
        return jsonify({"status": "error", "message": "No fields provided for update"}), 400

    if "name" in update_data:
        new_name = update_data["name"].strip()
        if not new_name:
            return jsonify({"status": "error", "message": "name must not be empty"}), 400
        # Check name collision (excluding the current preset)
        all_names = {p.name.lower() for p in _BUILTIN_PRESETS}
        all_names |= {p.name.lower() for pid, p in custom.items() if pid != preset_id}
        if new_name.lower() in all_names:
            return jsonify({"status": "error", "message": f"A preset named '{new_name}' already exists"}), 400
        update_data["name"] = new_name

    updated = preset.model_copy(update={**update_data, "updated_at": datetime.now(tz=timezone.utc)})
    custom[preset_id] = updated
    _save_custom(custom)
    logger.info("Updated preset '%s' (id=%s)", updated.name, preset_id)
    return jsonify({"status": "success", "data": _preset_dict(updated)}), 200


@preset_bp.route("/<preset_id>", methods=["DELETE"])
def delete_preset(preset_id: str) -> tuple[Response, int]:
    """Delete a custom preset.

    Built-in presets cannot be deleted.

    Args:
        preset_id: UUID of the custom preset to delete.

    Returns:
        JSON ``{ status, data: { message } }`` or HTTP 404/403.
    """
    if preset_id in _BUILTIN_BY_ID:
        return jsonify({"status": "error", "message": "Built-in presets cannot be deleted"}), 403

    custom = _load_custom()
    if preset_id not in custom:
        return jsonify({"status": "error", "message": f"Preset '{preset_id}' not found"}), 404

    name = custom[preset_id].name
    del custom[preset_id]
    _save_custom(custom)
    logger.info("Deleted preset '%s' (id=%s)", name, preset_id)
    return jsonify({"status": "success", "data": {"message": f"Preset '{name}' deleted"}}), 200


@preset_bp.route("/<preset_id>/fork", methods=["POST"])
def fork_preset(preset_id: str) -> tuple[Response, int]:
    """Fork any preset (built-in or custom) as a new custom preset.

    Creates a copy with a new UUID, stripped of the ``is_builtin`` flag.
    The forked preset's name defaults to ``"Copy of <original name>"`` unless
    overridden in the request body.

    Args:
        preset_id: ID of the preset to fork.

    Request JSON (optional):
        name (str): Name for the forked preset (default: "Copy of <original>").
        description (str): Description override.

    Returns:
        JSON ``{ status, data: forked_preset }`` with HTTP 201 on success.
    """
    # Resolve source preset
    source: WorkspacePreset | None = _BUILTIN_BY_ID.get(preset_id)
    if source is None:
        custom = _load_custom()
        source = custom.get(preset_id)
    if source is None:
        return jsonify({"status": "error", "message": f"Preset '{preset_id}' not found"}), 404

    body = request.get_json(silent=True) or {}
    fork_name = str(body.get("name", f"Copy of {source.name}")).strip()
    fork_description = str(body.get("description", source.description))

    if not fork_name:
        fork_name = f"Copy of {source.name}"

    custom = _load_custom()

    all_names = {p.name.lower() for p in _BUILTIN_PRESETS}
    all_names |= {p.name.lower() for p in custom.values()}
    if fork_name.lower() in all_names:
        return jsonify({"status": "error", "message": f"A preset named '{fork_name}' already exists"}), 400

    now = datetime.now(tz=timezone.utc)
    forked = WorkspacePreset(
        id=str(uuid.uuid4()),
        name=fork_name,
        description=fork_description,
        widgets=list(source.widgets),
        layout=dict(source.layout),
        is_builtin=False,
        created_at=now,
        updated_at=now,
    )
    custom[forked.id] = forked
    _save_custom(custom)
    logger.info("Forked preset '%s' → '%s' (id=%s)", source.name, forked.name, forked.id)
    return jsonify({"status": "success", "data": _preset_dict(forked)}), 201
