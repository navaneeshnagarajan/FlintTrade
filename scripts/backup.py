"""CLI for workspace backup and restore.

Usage::

    python -m scripts.backup create --output ~/flint-backup.tar.gz
    python -m scripts.backup create --output ~/flint-backup.tar.gz --include-ticks
    python -m scripts.backup restore --input ~/flint-backup.tar.gz
    python -m scripts.backup restore --input ~/flint-backup.tar.gz --target /tmp/restore --force
    python -m scripts.backup list --dir ~/flint-backups/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _cmd_create(args: argparse.Namespace) -> None:
    """Handle the ``create`` sub-command."""
    from flinttrade_core.backup import WorkspaceBackup, BackupError  # noqa: PLC0415

    bk = WorkspaceBackup()
    output = Path(args.output).expanduser()
    try:
        created = bk.create_backup(output, include_ticks=args.include_ticks)
        size_mb = round(created.stat().st_size / (1024 * 1024), 3)
        print(f"Backup created: {created} ({size_mb} MB)")
    except BackupError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)


def _cmd_restore(args: argparse.Namespace) -> None:
    """Handle the ``restore`` sub-command."""
    from flinttrade_core.backup import WorkspaceBackup, BackupError  # noqa: PLC0415

    bk = WorkspaceBackup()
    input_path = Path(args.input).expanduser()
    target_dir = Path(args.target).expanduser() if args.target else None
    try:
        result = bk.restore_backup(
            input_path, target_dir=target_dir, force=args.force
        )
        print(
            f"Restored: {result['files_restored']} files "
            f"({result['total_size_mb']} MB), "
            f"{result['dbs_restored']} databases"
        )
    except BackupError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        sys.exit(1)


def _cmd_list(args: argparse.Namespace) -> None:
    """Handle the ``list`` sub-command."""
    from flinttrade_core.backup import WorkspaceBackup  # noqa: PLC0415

    bk = WorkspaceBackup()
    backup_dir = (
        Path(args.dir).expanduser()
        if args.dir
        else Path.home() / "flint-backups"
    )
    backups = bk.list_backups(backup_dir)
    if not backups:
        print(f"No backups found in {backup_dir}")
        return

    for b in backups:
        if args.json:
            print(json.dumps(b, default=str))
        else:
            created = b.get("created_at", "unknown")
            size = b.get("size_mb", "?")
            files = b.get("file_count", "?")
            print(f"{b['filename']}  {size} MB  {files} files  created={created}")


def main() -> None:
    """Entry point for the backup CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.backup",
        description="FlintTrade workspace backup and restore",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    create_p = sub.add_parser("create", help="Create a new workspace backup")
    create_p.add_argument(
        "--output",
        required=True,
        help="Destination path for the .tar.gz archive",
    )
    create_p.add_argument(
        "--include-ticks",
        action="store_true",
        default=False,
        help="Include tick data directories (can be very large)",
    )

    # restore
    restore_p = sub.add_parser("restore", help="Restore a workspace backup")
    restore_p.add_argument(
        "--input",
        required=True,
        help="Path to the .tar.gz archive to restore",
    )
    restore_p.add_argument(
        "--target",
        default=None,
        help="Target directory (default: parent of workspace dir)",
    )
    restore_p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing files without error",
    )

    # list
    list_p = sub.add_parser("list", help="List available backup archives")
    list_p.add_argument(
        "--dir",
        default=None,
        help="Directory to search (default: ~/flint-backups/)",
    )
    list_p.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON lines",
    )

    args = parser.parse_args()

    if args.command == "create":
        _cmd_create(args)
    elif args.command == "restore":
        _cmd_restore(args)
    elif args.command == "list":
        _cmd_list(args)


if __name__ == "__main__":
    main()
