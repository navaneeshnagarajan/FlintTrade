"""Flask admin routes for workspace backup and restore.

Routes:

- ``POST /admin/backup/create``  — create a new backup archive
- ``POST /admin/backup/restore`` — restore from an existing archive
- ``GET  /admin/backup/list``    — list available backups

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
        workspace_dir: Override the workspace directory.  Defaults to
            ``~/.flinttrade``.

    Returns:
        Configured Flask :class:`~flask.Blueprint`.
    """
    from flinttrade_core.backup import WorkspaceBackup, BackupError  # noqa: PLC0415

    bp = Blueprint("backup_admin", __name__)

    kwargs = {"workspace_dir": workspace_dir} if workspace_dir else {}
    bk = WorkspaceBackup(**kwargs)  # type: ignore[arg-type]

    @bp.route("/admin/backup/create", methods=["POST"])
    def backup_create() -> Response:
        """Create a new workspace backup.

        Request body (JSON, all optional):
            include_ticks (bool): Include tick data directories.
            output_path (str): Override destination path.

        Returns:
            JSON with ``path``, ``size_mb``, ``files``.
        """
        body = request.get_json(silent=True) or {}
        include_ticks: bool = bool(body.get("include_ticks", False))
        output_str: str | None = body.get("output_path")

        if output_str:
            output_path = Path(output_str).expanduser()
        else:
            import tempfile  # noqa: PLC0415
            from datetime import datetime, timezone  # noqa: PLC0415
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = Path(tempfile.gettempdir()) / f"flint_backup_{ts}.tar.gz"

        try:
            created = bk.create_backup(output_path, include_ticks=include_ticks)
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

    @bp.route("/admin/backup/restore", methods=["POST"])
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

    @bp.route("/admin/backup/list", methods=["GET"])
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
