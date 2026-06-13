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
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.core.backup_routes")


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

    bk = WorkspaceBackup(workspace_dir=workspace_dir)

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

        if output_str:
            output_path = Path(output_str).expanduser()
        else:
            # Default into the same directory backup_list() searches —
            # a temp-dir default would vanish on OS cleanup and never
            # show up in /admin/backup/list.
            from datetime import datetime, timezone  # noqa: PLC0415
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_dir = Path.home() / "flint-backups"
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
            return jsonify({"status": "error", "message": exc.message}), 500  # type: ignore[return-value]

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

        backup_path = Path(path_str).expanduser()
        target_str: str | None = body.get("target_dir")
        target_dir = Path(target_str).expanduser() if target_str else None
        force: bool = bool(body.get("force", False))

        try:
            result = bk.restore_backup(
                backup_path, target_dir=target_dir, force=force
            )
            return jsonify({"status": "ok", **result})  # type: ignore[return-value]
        except BackupError as exc:
            return jsonify({"status": "error", "message": exc.message}), 500  # type: ignore[return-value]

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
        if dir_str:
            backup_dir = Path(dir_str).expanduser()
        else:
            backup_dir = Path.home() / "flint-backups"

        backups = bk.list_backups(backup_dir)
        return jsonify({"status": "ok", "backups": backups})  # type: ignore[return-value]

    return bp
