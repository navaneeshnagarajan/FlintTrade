"""Workspace backup and restore.

Creates bounded tar.gz archives of registered historical bhavcopy CSVs.
Workspace, credentials, installation security and live runtime state are
excluded. Authority-bearing archives and all active-workspace restores are
unavailable until a coordinated restore transaction exists.

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

import gzip
import io
import json
import logging
import os
import stat
import tarfile
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .backup_sensitivity import (
    COORDINATED_RESTORE_UNAVAILABLE,
    UnclassifiedArchivePath,
    WorkspaceBackupSensitivity,
)
from .secure_file import durable_replace, harden

logger = logging.getLogger("flinttrade.core.backup")


_MANIFEST_FILENAME = "manifest.json"
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 50_000


@contextmanager
def open_backup_archive(path: Path) -> Iterator[tarfile.TarFile]:
    """Read a gzip/tar through a bounded spool before interpreting any headers."""
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as spool:
        total = 0
        try:
            with gzip.open(path, "rb") as compressed:
                while chunk := compressed.read(min(1024 * 1024, MAX_ARCHIVE_UNCOMPRESSED_BYTES - total + 1)):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise BackupError("Archive exceeds the decompressed size limit")
                    spool.write(chunk)
            spool.seek(0)
            with tarfile.open(fileobj=spool, mode="r:") as archive:
                seen: set[str] = set()
                for count, member in enumerate(archive, start=1):
                    if count > MAX_ARCHIVE_MEMBERS or member.size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                        raise BackupError("Archive exceeds the member limit")
                    if member.name in seen:
                        raise BackupError("Archive contains duplicate members")
                    seen.add(member.name)
                    if member.sparse is not None or any(key.startswith("GNU.sparse") for key in member.pax_headers):
                        raise BackupError("Archive contains unsupported sparse members")
                yield archive
        except (tarfile.TarError, EOFError, gzip.BadGzipFile) as exc:
            raise BackupError("Archive is corrupt or invalid") from exc


def _is_reparse_point(path_stat: os.stat_result) -> bool:
    mask = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(mask and getattr(path_stat, "st_file_attributes", 0) & mask)


def _assert_restore_path_components_safe(target_dir: Path, relative: PurePosixPath) -> None:
    """Reject an existing link/reparse/non-directory pivot before extraction."""
    current = target_dir
    for component in relative.parts[:-1]:
        current /= component
        try:
            path_stat = current.lstat()
        except FileNotFoundError:
            break
        if (
            not stat.S_ISDIR(path_stat.st_mode)
            or stat.S_ISLNK(path_stat.st_mode)
            or _is_reparse_point(path_stat)
        ):
            raise BackupError("Restore archive targets an unsafe existing path")


def _validated_restore_members(
    members: list[tarfile.TarInfo],
    *,
    target_dir: Path,
    workspace_basename: str,
    disjoint: Any,
) -> list[tarfile.TarInfo]:
    """Admit only ordinary files/directories under one exact workspace tree."""
    admitted: list[tarfile.TarInfo] = []
    for member in members:
        if "\\" in member.name or "\x00" in member.name:
            raise BackupError("Restore archive contains an unsafe member path")
        relative = PurePosixPath(member.name)
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in member.name.split("/")):
            raise BackupError("Restore archive contains an unsafe member path")
        if relative.parts == (_MANIFEST_FILENAME,):
            if not member.isfile():
                raise BackupError("Restore manifest is not an ordinary file")
        else:
            if relative.parts[0] != workspace_basename:
                raise BackupError("Restore archive member is outside the workspace tree")
            if not (member.isfile() or member.isdir()):
                raise BackupError("Restore archive contains a link or special member")
        destination = target_dir.joinpath(*relative.parts)
        disjoint(destination, label="restore member")
        _assert_restore_path_components_safe(target_dir, relative)
        try:
            existing = destination.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(existing.st_mode) or _is_reparse_point(existing):
                raise BackupError("Restore archive targets an unsafe existing path")
            if member.isfile():
                if not stat.S_ISREG(existing.st_mode):
                    raise BackupError("Restore archive targets a non-regular file")
                if existing.st_nlink != 1:
                    raise BackupError("Restore archive targets an unsafe existing path")
            if member.isdir() and not stat.S_ISDIR(existing.st_mode):
                raise BackupError("Restore archive targets a non-directory")
        admitted.append(member)
    return admitted


class BackupError(Exception):
    """Raised when a backup or restore operation fails.

    Args:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class CoordinatedRestoreUnavailable(BackupError):
    """Authority snapshots/restores require the future coordinated transaction."""

    code = COORDINATED_RESTORE_UNAVAILABLE
    status_code = 503

    def __init__(self) -> None:
        super().__init__(self.code)


class WorkspaceBackup:
    """Create and restore workspace backups as compressed tar.gz archives.

    Args:
        workspace_dir: Root of the FlintTrade workspace.  Defaults to the
            platform workspace directory resolved by
            :func:`flinttrade_core.workspace.workspace_dir` (``~/.flinttrade``
            on Linux, ``~/Library/Application Support/flinttrade`` on macOS,
            ``%APPDATA%/flinttrade`` on Windows).

    Example::

        bk = WorkspaceBackup()
        path = bk.create_backup(Path("/tmp/backup.tar.gz"))
        info = bk.restore_backup(path, target_dir=Path("/tmp/restore"))
    """

    def __init__(
        self,
        workspace_dir: Path | None = None,
    ) -> None:
        if workspace_dir is None:
            from flinttrade_core.workspace import workspace_dir as _resolve  # noqa: PLC0415

            workspace_dir = _resolve()
        self._workspace_dir = workspace_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(
        self,
        output_path: Path,
        include_ticks: bool = False,
        include_credentials: bool = False,
    ) -> Path:
        """Create a tar.gz backup of the workspace directory.

        Includes only the composition-registered bhavcopy CSV family. All
        authority and secret namespaces are pruned before traversal; unknown
        paths fail closed. Live database and tick stores remain unavailable.

        A ``manifest.json`` is embedded at the archive root containing
        backup metadata (timestamp, version, file count, total size).

        Args:
            output_path: Destination file path for the ``.tar.gz`` archive.
                Parent directories are created if they do not exist.
            include_ticks: When ``True``, include tick data directories
                (may be very large).  Defaults to ``False``.
            include_credentials: Reserved compatibility option. True raises
                coordinated_restore_unavailable before collection.

        Returns:
            The resolved path to the created archive.

        Raises:
            BackupError: If the workspace directory does not exist or the
                archive cannot be written.
        """
        if include_credentials:
            raise CoordinatedRestoreUnavailable
        if not self._workspace_dir.exists():
            raise BackupError(
                f"Workspace directory does not exist: {self._workspace_dir}"
            )

        try:
            from flinttrade_core.installation_state import (  # noqa: PLC0415
                InstallationStateError,
                assert_installation_state_disjoint,
            )

            assert_installation_state_disjoint(self._workspace_dir, label="backup source workspace")
            output_path = output_path.expanduser().resolve()
            assert_installation_state_disjoint(output_path, label="backup archive")
        except InstallationStateError as exc:
            raise BackupError(str(exc)) from exc
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self._workspace_dir.resolve() in output_path.parents:
            raise CoordinatedRestoreUnavailable

        files_to_backup = self._collect_files(
            include_ticks=include_ticks,
            include_credentials=include_credentials,
        )

        manifest = self._build_manifest(
            files_to_backup,
            include_ticks=include_ticks,
            include_credentials=include_credentials,
        )

        descriptor, temporary = tempfile.mkstemp(prefix=".ordinary-backup-", suffix=".tar.gz", dir=output_path.parent)
        os.close(descriptor)
        staged = Path(temporary)
        try:
            harden(staged)
            with tarfile.open(staged, "w:gz") as tar:
                payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
                header = tarfile.TarInfo(_MANIFEST_FILENAME)
                header.size = len(payload)
                header.mode = 0o600
                tar.addfile(header, io.BytesIO(payload))
                for file_path in files_to_backup:
                    fd = os.open(file_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as source:
                        source_stat = os.fstat(source.fileno())
                        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                            raise BackupError("Backup source is not an ordinary file")
                        header = tarfile.TarInfo(file_path.relative_to(self._workspace_dir.parent).as_posix())
                        header.mode = 0o600
                        header.size = source_stat.st_size
                        tar.addfile(header, source)
            # Reopen the complete candidate using the same bounded reader as restore.
            with open_backup_archive(staged) as archive:
                _validated_restore_members(
                    archive.getmembers(), target_dir=self._workspace_dir.parent,
                    workspace_basename=self._workspace_dir.name, disjoint=assert_installation_state_disjoint,
                )
            durable_replace(staged, output_path)
        except Exception as exc:
            raise BackupError("Failed to create ordinary backup archive") from exc
        finally:
            staged.unlink(missing_ok=True)

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
        """Extract an ordinary archive into a proven disjoint non-authority tree.

        Args:
            backup_path: Path to a ``.tar.gz`` file created by
                :meth:`create_backup`.
            target_dir: Directory to restore into.  Defaults to the
                parent of the resolved workspace directory; the workspace
                is restored under ``target_dir/<workspace-dir-name>/``
                (``flinttrade`` on macOS/Windows, ``.flinttrade`` on Linux).
            force: Permit replacement of admitted non-authority files only.
                This never permits authority or active-workspace restoration.

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
        destination_workspace = target_dir / self._workspace_dir.name
        from .workspace import workspace_dir  # noqa: PLC0415

        for active_workspace in (self._workspace_dir.expanduser().resolve(), workspace_dir()):
            if (
                destination_workspace == active_workspace
                or destination_workspace in active_workspace.parents
                or active_workspace in destination_workspace.parents
            ):
                raise CoordinatedRestoreUnavailable

        try:
            from flinttrade_core.installation_state import (  # noqa: PLC0415
                InstallationStateError,
                assert_installation_state_disjoint,
            )

            # The default restore container is the workspace's parent (and on
            # macOS also the installation-state root's parent), so validate the
            # actual extracted workspace tree rather than rejecting that safe
            # sibling container wholesale.
            assert_installation_state_disjoint(
                target_dir / self._workspace_dir.name,
                label="restore tree",
            )
        except InstallationStateError as exc:
            raise BackupError(str(exc)) from exc

        try:
            with open_backup_archive(backup_path) as tar:
                members = tar.getmembers()
                try:
                    restorable_members = _validated_restore_members(
                        members,
                        target_dir=target_dir,
                        workspace_basename=self._workspace_dir.name,
                        disjoint=assert_installation_state_disjoint,
                    )
                except InstallationStateError as exc:
                    raise BackupError(str(exc)) from exc

                registry = WorkspaceBackupSensitivity(include_ticks=True)
                for member in restorable_members:
                    if member.name == _MANIFEST_FILENAME:
                        continue
                    relative = PurePosixPath(member.name)
                    if len(relative.parts) == 1 and member.isdir():
                        continue
                    try:
                        classification = registry.classify(PurePosixPath(*relative.parts[1:]), directory=member.isdir())
                    except UnclassifiedArchivePath as exc:
                        raise CoordinatedRestoreUnavailable from exc
                    if classification == "excluded":
                        raise CoordinatedRestoreUnavailable

                if not force:
                    for member in restorable_members:
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
                tar.extractall(
                    path=target_dir,
                    members=restorable_members,
                    filter="data",
                )  # noqa: S202

        except tarfile.TarError as exc:
            raise BackupError(f"Archive is corrupt or invalid: {exc}") from exc

        # Count results.
        files_restored = sum(
            1 for m in restorable_members if m.isfile() and m.name != _MANIFEST_FILENAME
        )
        dbs_restored = sum(
            1 for m in restorable_members if m.isfile() and m.name.endswith(".duckdb")
        )
        total_size_bytes = sum(m.size for m in restorable_members if m.isfile())
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
                with open_backup_archive(archive_path) as tar:
                    try:
                        member = tar.getmember(_MANIFEST_FILENAME)
                        f = tar.extractfile(member)
                        if f is not None:
                            manifest = json.load(f)
                            info.update(manifest)
                    except KeyError:
                        pass  # No manifest — older backup format.
            except (tarfile.TarError, BackupError):
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
            ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            out = backup_dir / f"flint_backup_{ts}.tar.gz"
            try:
                self.create_backup(out)
            except BackupError as exc:
                logger.error("Scheduled backup failed: %s", exc)
                return

            # Prune old backups.
            cutoff = datetime.now(UTC).timestamp() - retention_days * 86400
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

    def _collect_files(
        self,
        include_ticks: bool,
        include_credentials: bool = False,
    ) -> list[Path]:
        """Gather files to include in the backup.

        Args:
            include_ticks: Whether to include tick-data directories.
            include_credentials: Whether to include credential database files.

        Returns:
            Sorted list of absolute :class:`~pathlib.Path` objects.
        """
        if include_credentials:
            raise CoordinatedRestoreUnavailable
        registry = WorkspaceBackupSensitivity(include_ticks=include_ticks)
        collected: list[Path] = []
        pending = [self._workspace_dir]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    item = Path(entry.path)
                    relative = PurePosixPath(item.relative_to(self._workspace_dir).as_posix())
                    is_directory = entry.is_dir(follow_symlinks=False)
                    try:
                        classification = registry.classify(relative, directory=is_directory)
                    except UnclassifiedArchivePath as exc:
                        raise CoordinatedRestoreUnavailable from exc
                    if classification == "excluded":
                        continue
                    item_stat = entry.stat(follow_symlinks=False)
                    if entry.is_symlink() or _is_reparse_point(item_stat):
                        raise BackupError("Backup source contains an unsafe path")
                    if is_directory:
                        pending.append(item)
                    elif stat.S_ISREG(item_stat.st_mode) and item_stat.st_nlink == 1:
                        collected.append(item)
                    else:
                        raise BackupError("Backup source contains a non-regular file")
        return sorted(collected)

    def _build_manifest(
        self,
        files: list[Path],
        include_ticks: bool,
        include_credentials: bool,
    ) -> dict[str, Any]:
        """Build a manifest dict describing the backup.

        Args:
            files: List of files that will be archived.
            include_ticks: Whether tick data was included.
            include_credentials: Whether credential stores were included.

        Returns:
            Manifest dict with metadata fields.
        """
        total_bytes = sum(f.stat().st_size for f in files)
        return {
            "created_at": datetime.now(UTC).isoformat(),
            "file_count": len(files),
            "workspace_size_mb": round(total_bytes / (1024 * 1024), 3),
            "include_ticks": include_ticks,
            "include_credentials": include_credentials,
            "version": "1",
        }
