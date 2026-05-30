"""Workspace backup and restore.

Creates compressed tar.gz archives of the FlintTrade workspace directory
(``~/.flinttrade/``) containing ``workspace.json``, DuckDB databases,
audit logs, and config files.  Tick data (potentially large) is excluded
unless *include_ticks* is set.

Backups store a ``manifest.json`` at the archive root so that restore and
list operations can read metadata without extracting the full archive.

Usage::

    from flinttrade_core.backup import WorkspaceBackup
    from pathlib import Path

    bk = WorkspaceBackup()
    archive = bk.create_backup(Path("/tmp/flint-backup.tar.gz"))
    print(archive)

    result = bk.restore_backup(archive)
    print(result)

CLI::

    python -m scripts.backup create --output ~/flint-backup.tar.gz
    python -m scripts.backup restore --input ~/flint-backup.tar.gz
"""

from __future__ import annotations

import json
import logging
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.core.backup")

# Patterns that are always excluded (even with include_ticks=False).
_ALWAYS_EXCLUDE: frozenset[str] = frozenset(
    {".git", "__pycache__", "*.pyc", "*.pyo"}
)

# Sub-directory name patterns classified as "tick data" (large, optional).
_TICK_DIRS: frozenset[str] = frozenset({"ticks", "tick_data", "questdb_data"})

_MANIFEST_FILENAME = "manifest.json"


class BackupError(Exception):
    """Raised when a backup or restore operation fails.

    Args:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class WorkspaceBackup:
    """Create and restore workspace backups as compressed tar.gz archives.

    Args:
        workspace_dir: Root of the FlintTrade workspace.  Defaults to
            ``~/.flinttrade``.

    Example::

        bk = WorkspaceBackup()
        path = bk.create_backup(Path("/tmp/backup.tar.gz"))
        info = bk.restore_backup(path, target_dir=Path("/tmp/restore"))
    """

    def __init__(
        self,
        workspace_dir: Path = Path.home() / ".flinttrade",
    ) -> None:
        self._workspace_dir = workspace_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(
        self,
        output_path: Path,
        include_ticks: bool = False,
    ) -> Path:
        """Create a tar.gz backup of the workspace directory.

        Includes ``workspace.json``, DuckDB databases (``*.duckdb``),
        audit log files (``*.jsonl``, ``*.jsonl.gz``), and general config
        files.  Tick data directories are excluded unless *include_ticks*
        is ``True``.

        A ``manifest.json`` is embedded at the archive root containing
        backup metadata (timestamp, version, file count, total size).

        Args:
            output_path: Destination file path for the ``.tar.gz`` archive.
                Parent directories are created if they do not exist.
            include_ticks: When ``True``, include tick data directories
                (may be very large).  Defaults to ``False``.

        Returns:
            The resolved path to the created archive.

        Raises:
            BackupError: If the workspace directory does not exist or the
                archive cannot be written.
        """
        if not self._workspace_dir.exists():
            raise BackupError(
                f"Workspace directory does not exist: {self._workspace_dir}"
            )

        output_path = output_path.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        files_to_backup = self._collect_files(include_ticks)

        manifest = self._build_manifest(
            files_to_backup, include_ticks=include_ticks
        )

        # Write manifest to a temporary file so it can be added first.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp_manifest:
            json.dump(manifest, tmp_manifest, indent=2, default=str)
            tmp_manifest_path = Path(tmp_manifest.name)

        try:
            with tarfile.open(output_path, "w:gz") as tar:
                # Embed manifest at archive root.
                tar.add(tmp_manifest_path, arcname=_MANIFEST_FILENAME)
                for file_path in files_to_backup:
                    try:
                        arcname = file_path.relative_to(
                            self._workspace_dir.parent
                        )
                        tar.add(file_path, arcname=str(arcname))
                    except Exception as exc:
                        logger.warning(
                            "Skipping file %s: %s", file_path, exc
                        )
        except Exception as exc:
            raise BackupError(f"Failed to create backup archive: {exc}") from exc
        finally:
            tmp_manifest_path.unlink(missing_ok=True)

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Backup created: %s (%.2f MB, %d files)",
            output_path,
            size_mb,
            len(files_to_backup),
        )
        return output_path

    def restore_backup(
        self,
        backup_path: Path,
        target_dir: Path | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Extract a backup archive to *target_dir*.

        Args:
            backup_path: Path to a ``.tar.gz`` file created by
                :meth:`create_backup`.
            target_dir: Directory to restore into.  Defaults to the parent
                of :attr:`workspace_dir` (i.e. ``~``).  The workspace
                will be restored under ``target_dir/.flinttrade/``.
            force: When ``True``, overwrite existing files without error.
                When ``False`` (default) the restore fails if any target
                file already exists.

        Returns:
            Dict with:

            - ``files_restored`` (int): Number of files extracted.
            - ``dbs_restored`` (int): Number of ``.duckdb`` files restored.
            - ``total_size_mb`` (float): Total uncompressed size in MB.

        Raises:
            BackupError: If the archive does not exist, is corrupt, or
                target files already exist (when *force* is ``False``).
        """
        backup_path = backup_path.expanduser().resolve()
        if not backup_path.exists():
            raise BackupError(f"Backup archive not found: {backup_path}")

        if target_dir is None:
            target_dir = self._workspace_dir.parent
        target_dir = target_dir.expanduser().resolve()

        try:
            with tarfile.open(backup_path, "r:gz") as tar:
                members = tar.getmembers()

                if not force:
                    for member in members:
                        if member.name == _MANIFEST_FILENAME:
                            continue
                        dest = target_dir / member.name
                        if dest.exists() and member.isfile():
                            raise BackupError(
                                f"Restore aborted — target file already exists: "
                                f"{dest}. Use force=True to overwrite."
                            )

                target_dir.mkdir(parents=True, exist_ok=True)
                # filter="data" applies the PEP 706 safe filter that rejects
                # absolute paths, links escaping the destination, and special
                # files. Required ahead of Python 3.14 which emits a
                # DeprecationWarning today and will default to rejecting
                # unfiltered extracts. We're extracting our own backups so
                # the conservative "data" profile is the right fit.
                tar.extractall(path=target_dir, filter="data")  # noqa: S202

        except tarfile.TarError as exc:
            raise BackupError(f"Archive is corrupt or invalid: {exc}") from exc

        # Count results.
        files_restored = sum(
            1 for m in members if m.isfile() and m.name != _MANIFEST_FILENAME
        )
        dbs_restored = sum(
            1 for m in members if m.isfile() and m.name.endswith(".duckdb")
        )
        total_size_bytes = sum(m.size for m in members if m.isfile())
        total_size_mb = round(total_size_bytes / (1024 * 1024), 3)

        logger.info(
            "Backup restored: %d files (%.2f MB) → %s",
            files_restored,
            total_size_mb,
            target_dir,
        )
        return {
            "files_restored": files_restored,
            "dbs_restored": dbs_restored,
            "total_size_mb": total_size_mb,
        }

    def list_backups(self, backup_dir: Path) -> list[dict[str, Any]]:
        """List available backup archives with metadata.

        Reads the embedded ``manifest.json`` from each ``.tar.gz`` in
        *backup_dir* without full extraction.

        Args:
            backup_dir: Directory to search for ``*.tar.gz`` files.

        Returns:
            List of metadata dicts (oldest first), each containing at
            minimum ``path`` and ``size_mb``.  Archives with embedded
            manifests also include ``created_at``, ``file_count``, and
            ``workspace_size_mb``.
        """
        backup_dir = backup_dir.expanduser().resolve()
        if not backup_dir.exists():
            return []

        results: list[dict[str, Any]] = []
        for archive_path in sorted(backup_dir.glob("*.tar.gz")):
            info: dict[str, Any] = {
                "path": str(archive_path),
                "size_mb": round(archive_path.stat().st_size / (1024 * 1024), 3),
                "filename": archive_path.name,
            }
            # Try to read embedded manifest.
            try:
                with tarfile.open(archive_path, "r:gz") as tar:
                    try:
                        member = tar.getmember(_MANIFEST_FILENAME)
                        f = tar.extractfile(member)
                        if f is not None:
                            manifest = json.load(f)
                            info.update(manifest)
                    except KeyError:
                        pass  # No manifest — older backup format.
            except tarfile.TarError:
                info["error"] = "archive_corrupt"
            results.append(info)

        return results

    def backup_schedule(
        self, interval_hours: int, retention_days: int
    ) -> None:
        """Register a recurring backup job via APScheduler.

        Backs up every *interval_hours* hours and deletes archives older
        than *retention_days* days from the same directory as the last
        manual backup (or ``~/flint-backups/`` if none exists).

        Args:
            interval_hours: How often to run the backup (hours).
            retention_days: How many days to retain old backups.

        Raises:
            BackupError: If APScheduler is not installed.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415
        except ImportError as exc:
            raise BackupError(
                "APScheduler is required for scheduled backups. "
                "Install with: pip install apscheduler>=3.10"
            ) from exc

        backup_dir = Path.home() / "flint-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        def _run_backup() -> None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = backup_dir / f"flint_backup_{ts}.tar.gz"
            try:
                self.create_backup(out)
            except BackupError as exc:
                logger.error("Scheduled backup failed: %s", exc)
                return

            # Prune old backups.
            cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
            for old in backup_dir.glob("*.tar.gz"):
                if old.stat().st_mtime < cutoff:
                    old.unlink(missing_ok=True)
                    logger.info("Pruned old backup: %s", old.name)

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            _run_backup,
            trigger="interval",
            hours=interval_hours,
            id="workspace_backup",
            replace_existing=True,
        )
        if not scheduler.running:
            scheduler.start()

        logger.info(
            "Scheduled backup every %d hours, retention %d days",
            interval_hours,
            retention_days,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_files(self, include_ticks: bool) -> list[Path]:
        """Gather files to include in the backup.

        Args:
            include_ticks: Whether to include tick-data directories.

        Returns:
            Sorted list of absolute :class:`~pathlib.Path` objects.
        """
        collected: list[Path] = []
        for item in self._workspace_dir.rglob("*"):
            if not item.is_file():
                continue

            # Skip always-excluded patterns.
            if any(part.startswith(".") and part != ".flinttrade" for part in item.parts):
                continue
            if any(part in _ALWAYS_EXCLUDE for part in item.parts):
                continue
            if item.suffix in (".pyc", ".pyo"):
                continue

            # Optionally skip tick directories.
            if not include_ticks:
                if any(part in _TICK_DIRS for part in item.parts):
                    continue

            collected.append(item)

        return sorted(collected)

    def _build_manifest(
        self, files: list[Path], include_ticks: bool
    ) -> dict[str, Any]:
        """Build a manifest dict describing the backup.

        Args:
            files: List of files that will be archived.
            include_ticks: Whether tick data was included.

        Returns:
            Manifest dict with metadata fields.
        """
        total_bytes = sum(f.stat().st_size for f in files)
        return {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workspace_dir": str(self._workspace_dir),
            "file_count": len(files),
            "workspace_size_mb": round(total_bytes / (1024 * 1024), 3),
            "include_ticks": include_ticks,
            "version": "1",
        }
