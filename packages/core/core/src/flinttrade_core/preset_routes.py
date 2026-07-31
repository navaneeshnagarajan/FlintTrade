"""Workspace preset management API — /ft-api/api/v1/presets/*.

Persists custom Dockview workspace presets to ~/.flinttrade/presets.json so
they are shared across machines when the file is synced (or served from the
same backend).

Built-in presets are read-only and always included in the listing.  Custom
presets are stored in the JSON file and can be created, updated, deleted, or
forked from a built-in.

External URL: /ft-api/api/v1/presets/* (the WSGI prefix stripper in app.py
strips the /ft-api segment, leaving /api/v1/presets/* for Flask dispatch).
Blueprint prefix: /api/v1/presets
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("flinttrade.core.preset_routes")

preset_bp = Blueprint("presets", __name__, url_prefix="/api/v1/presets")


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

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_BUILTIN_PRESETS: list[WorkspacePreset] = [
    WorkspacePreset(
        id="scalper-zone",
        name="Scalper Zone",
        description="Chart + Order Pad + DOM / Ladder + Positions + Scalper",
        widgets=["chart", "orderpad", "orderladder", "positions", "scalper"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="options-scalper",
        name="Options Scalper",
        description="Four-chart desk — Index + Futures + CE/PE strike charts + Option Chain",
        widgets=["chart", "optionchain"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="multi-chart",
        name="Multi Chart",
        description="Four independent charts in a 2×2 grid — NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY",
        widgets=["chart"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="options-desk",
        name="Options Desk",
        description="Option Chain + Chart + Greeks + Positions + Straddle",
        widgets=["optionchain", "chart", "greeks", "positions", "straddle"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="market-watch",
        name="Market Watch",
        description="Watchlist + Chart + Ticker + Dashboard",
        widgets=["watchlist", "chart", "ticker", "indexstrip"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="analysis",
        name="Analysis",
        description="Chart + OI Analytics + DOM / Ladder + Positions + News",
        widgets=["chart", "oichart", "orderladder", "positions", "news"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="risk-monitor",
        name="Risk Monitor",
        description="Dashboard + Risk + MTM Monitor + Positions + Orders",
        widgets=["indexstrip", "riskdashboard", "pnlmonitor", "positions", "orders"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="investor-view",
        name="Investor View",
        description="Chart + Watchlist + Holdings + Indices",
        widgets=["chart", "watchlist", "holdings", "indexstrip"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="trading-desk",
        name="Trading Desk",
        description="Indices + Positions + Risk + Orders — the retired Dashboard as a composition",
        widgets=["indexstrip", "positions", "riskdashboard", "orders"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="three-panel",
        name="Three Panel",
        description="CE | Index | PE — three time-synchronised charts on the nearest-expiry ATM strikes",
        widgets=["chart"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="options-analysis",
        name="Options Analysis",
        description="Option Chain + IV Smile & Skew + Greeks Matrix + Straddle & Implied Move + Straddle P&L",
        widgets=["optionchain", "ivsmile", "greeksheatmap", "straddle", "straddlepnl"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="sector-view",
        name="Sector View",
        description="Market Overview + Heat Calendar + Correlation Matrix",
        widgets=["marketoverview", "correlationmatrix"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="order-automation",
        name="Order Automation",
        description="Strategy Monitor + Chart + Strategy Templates + Session Stats",
        widgets=["strategymonitor", "chart", "strategytemplates"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="portfolio-manager",
        name="Portfolio Manager",
        description="Portfolio Allocation + Positions (net and heat-map views) + Risk + Trade Performance",
        widgets=["portfolioallocation", "positions", "riskdashboard"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="market-overview",
        name="Market Overview",
        description="Market Summary + Global Indices + Economic Calendar + Earnings Calendar + Market Clock + News",
        widgets=["marketoverview", "economiccalendar", "earningscalendar", "marketclock", "news"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="quick-scalper",
        name="Quick Scalper",
        description="Quick Trade + Order Ladder + DOM Heatmap + Tape & Microstructure + Tick Speed + Intraday P&L",
        widgets=["quicktrade", "domheatmap", "tickspeed", "orderladder", "timesales", "pnlmonitor"],
        layout={},
        is_builtin=True,
        created_at=_EPOCH,
        updated_at=_EPOCH,
    ),
    WorkspacePreset(
        id="everything",
        name="Everything",
        description="A broad sweep of the widget catalogue in one workspace — Charts, Trading, Options, Analysis, Positions, Utility",
        widgets=["chart", "scalper", "optionchain", "domheatmap", "indexstrip", "watchlist"],
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


def _legacy_presets_path() -> Path:
    """Return the pre-``workspace_dir()`` custom-preset file location.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/presets.json`` — the fixed ``~/.flinttrade``
        root every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / "presets.json"


def _presets_path() -> Path:
    """Resolve ``presets.json`` under the active workspace, migrating once.

    Supersedes this module's former private home resolver:
    :func:`flinttrade_core.workspace.workspace_dir` is the single authority, so
    the preset store now honours ``FLINTTRADE_WORKSPACE_DIR`` as well as
    ``FLINTTRADE_HOME`` and the platform-specific workspace root. When no
    environment override is in force, a pre-workspace
    ``~/.flinttrade/presets.json`` is copied into the workspace once — copy,
    never move, so the legacy file survives as a backup — and an existing
    workspace copy always wins.

    Resolution happens on every call, never at import time, so a mid-run
    change to the environment is honoured.

    Returns:
        Absolute path of ``presets.json`` inside the workspace directory.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The copy could
            not be completed; the legacy file is retained.
    """
    from flinttrade_core.workspace import (  # noqa: PLC0415
        copy_legacy_database_once,
        default_workspace_active,
        workspace_dir,
    )

    target = workspace_dir() / "presets.json"
    if default_workspace_active():
        copy_legacy_database_once(
            _legacy_presets_path(),
            target,
            sidecar_suffixes=(),
            lock_name=".presets-migration.lock",
            lock_dir=target.parent,
            label="workspace presets",
        )
    return target


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
    except ValidationError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

    name_stripped = req.name.strip()
    if not name_stripped:
        return jsonify({"status": "error", "message": "name must not be empty"}), 400

    custom = _load_custom()

    # Check for name collision across built-ins and custom
    all_names = {p.name.lower() for p in _BUILTIN_PRESETS}
    all_names |= {p.name.lower() for p in custom.values()}
    if name_stripped.lower() in all_names:
        return jsonify({"status": "error", "message": f"A preset named '{name_stripped}' already exists"}), 400

    now = datetime.now(tz=UTC)
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
    except ValidationError:
        return jsonify({"status": "error", "message": "Invalid request"}), 400

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

    updated = preset.model_copy(update={**update_data, "updated_at": datetime.now(tz=UTC)})
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

    now = datetime.now(tz=UTC)
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
