"""Flask admin routes for workspace backup and restore.

Routes:

- ``POST /v1/admin/backup/create``  — create a new backup archive
- ``POST /v1/admin/backup/restore`` — restore from an existing archive
- ``GET  /v1/admin/backup/list``    — list available backups

The ``/v1/admin`` prefix matches the sibling dev-gated admin blueprints
(``admin_bp``, ``infra_bp``) so callers face one admin namespace.

Usage::

    from flinttrade_core.backup_routes import create_backup_blueprint
    app.register_blueprint(create_backup_blueprint())
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import safe_join

logger = logging.getLogger("flinttrade.core.backup_routes")


def _backup_root() -> Path:
    """Supported archive root for the HTTP admin surface."""
    return (Path.home() / "flint-backups").resolve()


def _resolve_contained_path(root: Path, raw: str | None, default: Path | None = None) -> Path:
    """Resolve an operator-supplied path while keeping it under ``root``."""
    root = root.expanduser().resolve()
    if raw:
        candidate_str = str(raw).strip()
        if os.path.isabs(candidate_str):
            try:
                candidate_str = os.path.relpath(os.path.normpath(candidate_str), str(root))
            except ValueError as exc:
                raise ValueError("path must stay under the FlintTrade backup directory") from exc
        joined = safe_join(str(root), candidate_str)
        if joined is None:
            raise ValueError("path must stay under the FlintTrade backup directory")
        candidate = Path(joined)
    elif default is not None:
        candidate = default
    else:
        candidate = root
    resolved = candidate.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ValueError("path must stay under the FlintTrade backup directory")
    return resolved


def create_backup_blueprint(
    workspace_dir: Path | None = None,
) -> Blueprint:
    """Create the backup admin Blueprint.

    Args:
        workspace_dir: Override the workspace directory.  Defaults to the
            platform workspace directory resolved by
            :func:`flinttrade_core.workspace.workspace_dir`.

    Returns:
        Configured Flask :class:`~flask.Blueprint`.
    """
    from flinttrade_core.backup import WorkspaceBackup, BackupError  # noqa: PLC0415

    bp = Blueprint("backup_admin", __name__, url_prefix="/v1/admin")

    if workspace_dir is None:
        from flinttrade_core.workspace import workspace_dir as _workspace_dir  # noqa: PLC0415

        workspace_path = _workspace_dir()
    else:
        workspace_path = Path(workspace_dir)
    workspace_restore_root = workspace_path.expanduser().resolve().parent
    bk = WorkspaceBackup(workspace_dir=workspace_path)

    @bp.route("/backup/create", methods=["POST"])
    def backup_create() -> Response:
        """Create a new workspace backup.

        Request body (JSON, all optional):
            include_ticks (bool): Include tick data directories.
            include_credentials (bool): Include credential database files.
            output_path (str): Override destination path.

        Returns:
            JSON with ``path``, ``size_mb``, ``files``.
        """
        body = request.get_json(silent=True) or {}
        include_ticks: bool = bool(body.get("include_ticks", False))
        include_credentials: bool = bool(body.get("include_credentials", False))
        output_str: str | None = body.get("output_path")

        backup_dir = _backup_root()
        if output_str:
            try:
                output_path = _resolve_contained_path(backup_dir, output_str)
            except ValueError:
                return jsonify(  # type: ignore[return-value]
                    {"status": "error", "message": "Backup output path is outside the backup directory"}
                ), 400
        else:
            # Default into the same directory backup_list() searches —
            # a temp-dir default would vanish on OS cleanup and never
            # show up in /admin/backup/list.
            from datetime import datetime, timezone  # noqa: PLC0415

            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_dir.mkdir(parents=True, exist_ok=True)
            output_path = backup_dir / f"flint_backup_{ts}.tar.gz"

        try:
            created = bk.create_backup(
                output_path,
                include_ticks=include_ticks,
                include_credentials=include_credentials,
            )
            size_mb = round(created.stat().st_size / (1024 * 1024), 3)
            return jsonify(  # type: ignore[return-value]
                {
                    "status": "ok",
                    "path": str(created),
                    "size_mb": size_mb,
                }
            )
        except BackupError as exc:
            logger.warning("Workspace backup creation failed: %s", exc.message)
            return jsonify({"status": "error", "message": "Backup creation failed"}), 500  # type: ignore[return-value]

    @bp.route("/backup/restore", methods=["POST"])
    def backup_restore() -> Response:
        """Restore a workspace backup.

        Request body (JSON):
            path (str, required): Path to the ``.tar.gz`` archive.
            target_dir (str, optional): Directory to restore into.
            force (bool, optional): Overwrite existing files (default false).

        Returns:
            JSON with ``files_restored``, ``dbs_restored``, ``total_size_mb``.
        """
        body = request.get_json(silent=True) or {}
        path_str: str | None = body.get("path")
        if not path_str:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Missing required field: 'path'"}
            ), 400

        try:
            backup_path = _resolve_contained_path(_backup_root(), path_str)
        except ValueError:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Backup archive path is outside the backup directory"}
            ), 400
        target_str: str | None = body.get("target_dir")
        if target_str:
            try:
                target_dir = _resolve_contained_path(workspace_restore_root, target_str)
            except ValueError:
                return jsonify(  # type: ignore[return-value]
                    {"status": "error", "message": "Restore target is outside the workspace restore root"}
                ), 400
        else:
            target_dir = None
        force: bool = bool(body.get("force", False))

        try:
            result = bk.restore_backup(
                backup_path, target_dir=target_dir, force=force
            )
            return jsonify({"status": "ok", **result})  # type: ignore[return-value]
        except BackupError as exc:
            logger.warning("Workspace backup restore failed: %s", exc.message)
            return jsonify({"status": "error", "message": "Backup restore failed"}), 500  # type: ignore[return-value]

    @bp.route("/backup/list", methods=["GET"])
    def backup_list() -> Response:
        """List available backup archives.

        Query parameters:
            dir (str, optional): Directory to search. Defaults to
                ``~/flint-backups/``.

        Returns:
            JSON with ``backups`` list.
        """
        dir_str: str | None = request.args.get("dir")
        try:
            backup_dir = _resolve_contained_path(_backup_root(), dir_str)
        except ValueError:
            return jsonify(  # type: ignore[return-value]
                {"status": "error", "message": "Backup list path is outside the backup directory"}
            ), 400

        backups = bk.list_backups(backup_dir)
        return jsonify({"status": "ok", "backups": backups})  # type: ignore[return-value]

    return bp
