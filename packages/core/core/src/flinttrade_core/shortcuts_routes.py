"""Keyboard shortcut persistence — per-user, DuckDB-backed.

Stores customised keyboard shortcut overrides so they sync across devices.

Blueprint prefix: /v1/shortcuts

Endpoints:
    GET  /v1/shortcuts          — fetch overrides for the authenticated user
    POST /v1/shortcuts          — save/update overrides for the authenticated user
    POST /v1/shortcuts/reset    — delete all overrides (restore defaults)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request
from flinttrade_gateway.log_safety import log_ref

logger = logging.getLogger("flinttrade.shortcuts")

shortcuts_bp = Blueprint("shortcuts", __name__, url_prefix="/v1/shortcuts")

# ---------------------------------------------------------------------------
# DuckDB storage
# ---------------------------------------------------------------------------

# Module-level connection — created lazily so tests can override the path.
_conn: Any = None


def _legacy_db_path() -> Path:
    """Return the pre-``workspace_dir()`` shortcut store location.

    Module-level so tests can monkeypatch the probe away from the developer's
    real home directory.

    Returns:
        ``<legacy dot-directory>/shortcuts.duckdb`` — the fixed
        ``~/.flinttrade`` root every pre-workspace install used, on every OS.
    """
    from flinttrade_core.workspace import legacy_dotdir  # noqa: PLC0415

    return legacy_dotdir() / "shortcuts.duckdb"


def _default_db_path() -> Path:
    """Resolve the shortcut store under the active workspace, migrating once.

    Replaces the former import-time ``_DB_PATH`` constant, which froze the
    location before pytest or a Gunicorn preload+fork could set
    ``FLINTTRADE_WORKSPACE_DIR``. When no environment override is in force, a
    pre-workspace ``~/.flinttrade/shortcuts.duckdb`` is copied into the
    workspace once — together with its DuckDB ``.wal`` sidecar — so upgraded
    macOS and Windows installs keep their customised keybindings instead of
    silently reverting to defaults. Copy, never move: the legacy family is
    retained as a backup and an existing workspace copy always wins.

    Returns:
        Absolute path of ``shortcuts.duckdb`` inside the workspace directory.

    Raises:
        flinttrade_core.workspace.WorkspaceStateMigrationError: The copy could
            not be completed; the legacy store is retained.
    """
    from flinttrade_core.workspace import (  # noqa: PLC0415
        copy_legacy_database_once,
        default_workspace_active,
        workspace_dir,
    )

    target = workspace_dir() / "shortcuts.duckdb"
    if default_workspace_active():
        copy_legacy_database_once(
            _legacy_db_path(),
            target,
            sidecar_suffixes=(".wal",),
            lock_name=".shortcuts-migration.lock",
            lock_dir=target.parent,
            label="keyboard shortcuts store",
        )
    return target


def _get_conn(db_path: Path | str | None = None) -> Any:
    """Return (and lazily initialise) the DuckDB connection.

    Args:
        db_path: Override the store location. Used in tests. When ``None`` the
            workspace-scoped default is resolved at call time, which may
            perform the one-shot legacy copy.

    Returns:
        A live DuckDB connection with the ``shortcuts`` table created, or
        ``None`` when DuckDB is not installed.
    """
    global _conn  # noqa: PLW0603
    if _conn is None:
        try:
            import duckdb  # noqa: PLC0415

            path = Path(db_path) if db_path is not None else _default_db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = duckdb.connect(str(path))
            _conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shortcuts (
                    user_id  TEXT    NOT NULL,
                    id       TEXT    NOT NULL,
                    keys     TEXT    NOT NULL,
                    updated  TIMESTAMP DEFAULT current_timestamp,
                    PRIMARY KEY (user_id, id)
                )
                """
            )
        except ImportError:
            logger.warning("duckdb not installed — shortcut persistence disabled")
            return None
    return _conn


def _reset_conn() -> None:
    """Close and reset the module-level connection (used by tests)."""
    global _conn  # noqa: PLW0603
    if _conn is not None:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _load_overrides(user_id: str, conn: Any) -> dict[str, list[str]]:
    """Load all shortcut overrides for a user from DuckDB.

    Args:
        user_id: The authenticated user ID.
        conn: DuckDB connection.

    Returns:
        Dict mapping shortcut ID → key list, e.g. ``{"cancel-orders": ["C"]}``.
    """
    rows = conn.execute(
        "SELECT id, keys FROM shortcuts WHERE user_id = ?",
        [user_id],
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        shortcut_id, keys_json = row
        try:
            result[shortcut_id] = json.loads(keys_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def _save_overrides(
    user_id: str, overrides: dict[str, list[str]], conn: Any
) -> None:
    """Upsert shortcut overrides for a user in DuckDB.

    Existing rows are replaced; overrides not in the payload are untouched.

    Args:
        user_id: The authenticated user ID.
        overrides: Dict mapping shortcut ID → key list.
        conn: DuckDB connection.
    """
    for shortcut_id, keys in overrides.items():
        if not isinstance(keys, list):
            continue
        keys_json = json.dumps(keys)
        conn.execute(
            """
            INSERT INTO shortcuts (user_id, id, keys, updated)
            VALUES (?, ?, ?, current_timestamp)
            ON CONFLICT (user_id, id) DO UPDATE
                SET keys = excluded.keys,
                    updated = excluded.updated
            """,
            [user_id, shortcut_id, keys_json],
        )


def _delete_overrides(user_id: str, conn: Any) -> int:
    """Delete all shortcut overrides for a user.

    Args:
        user_id: The authenticated user ID.
        conn: DuckDB connection.

    Returns:
        Number of rows deleted.
    """
    result = conn.execute(
        "SELECT COUNT(*) FROM shortcuts WHERE user_id = ?", [user_id]
    ).fetchone()
    count = result[0] if result else 0
    conn.execute("DELETE FROM shortcuts WHERE user_id = ?", [user_id])
    return count


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def _get_user_id() -> str:
    """Extract user ID from request context.

    Uses the ``X-User-Id`` header (set by the JWT middleware) or falls back to
    a fixed ``"default"`` user for single-user setups.

    Returns:
        A non-empty string user ID.
    """
    user_id = request.headers.get("X-User-Id", "").strip()
    return user_id or "default"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@shortcuts_bp.route("", methods=["GET"])
def get_shortcuts() -> Any:
    """Return customised shortcut overrides for the authenticated user.

    Response::

        {
            "status": "ok",
            "user_id": "default",
            "overrides": {
                "cancel-orders": ["Ctrl", "C"],
                ...
            }
        }

    Returns:
        JSON response with overrides dict.
    """
    user_id = _get_user_id()
    conn = _get_conn()
    if conn is None:
        return jsonify({"status": "ok", "user_id": user_id, "overrides": {}})

    try:
        overrides = _load_overrides(user_id, conn)
        return jsonify({"status": "ok", "user_id": user_id, "overrides": overrides})
    except Exception as exc:
        logger.error("Failed to load shortcuts: %s", exc)
        return (
            jsonify({"status": "error", "message": "Failed to load shortcuts"}),
            500,
        )


@shortcuts_bp.route("", methods=["POST"])
def save_shortcuts() -> Any:
    """Save or update shortcut overrides for the authenticated user.

    Request body::

        {
            "overrides": {
                "cancel-orders": ["Ctrl", "C"],
                "quick-buy": ["Shift", "B"]
            }
        }

    Response::

        {"status": "ok", "saved": 2}

    Returns:
        JSON response confirming number of overrides saved.

    Raises:
        400: If request body is missing or ``overrides`` key is absent.
        500: On database error.
    """
    user_id = _get_user_id()
    body = request.get_json(silent=True, force=True)
    if not body or not isinstance(body.get("overrides"), dict):
        return (
            jsonify({"status": "error", "message": "Missing 'overrides' dict in request body"}),
            400,
        )

    overrides: dict[str, list[str]] = body["overrides"]
    conn = _get_conn()
    if conn is None:
        return jsonify({"status": "ok", "saved": 0, "note": "persistence disabled"})

    try:
        _save_overrides(user_id, overrides, conn)
        return jsonify({"status": "ok", "saved": len(overrides)})
    except Exception as exc:
        logger.error("Failed to save shortcuts: %s", exc)
        return (
            jsonify({"status": "error", "message": "Failed to save shortcuts"}),
            500,
        )


@shortcuts_bp.route("/reset", methods=["POST"])
def reset_shortcuts() -> Any:
    """Delete all shortcut overrides for the authenticated user.

    Restores the user to default bindings on the next GET request.

    Response::

        {"status": "ok", "deleted": 3}

    Returns:
        JSON response confirming number of overrides deleted.
    """
    user_id = _get_user_id()
    conn = _get_conn()
    if conn is None:
        return jsonify({"status": "ok", "deleted": 0})

    try:
        count = _delete_overrides(user_id, conn)
        logger.info("Reset %d shortcut overrides for user %s", count, log_ref(user_id, kind="user"))
        return jsonify({"status": "ok", "deleted": count})
    except Exception as exc:
        logger.error("Failed to reset shortcuts: %s", exc)
        return (
            jsonify({"status": "error", "message": "Failed to reset shortcuts"}),
            500,
        )
