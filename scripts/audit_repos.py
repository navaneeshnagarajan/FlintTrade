"""Audit reference repo absorption status.

Reads .local/reference/absorption-status.json and outputs a formatted
table showing repo name, status, target package, last examined date,
and notes.

Usage:
    python scripts/audit_repos.py
    python scripts/audit_repos.py --status unexamined
    python scripts/audit_repos.py --package gateway
    python scripts/audit_repos.py --format markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Repo root is one level above scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = REPO_ROOT / ".local" / "reference" / "absorption-status.json"

# Column widths for terminal output
COL_NAME = 35
COL_STATUS = 12
COL_PACKAGE = 18
COL_EXAMINED = 12
COL_NOTES = 50


def load_status(path: Path | None = None) -> dict[str, Any]:
    """Load absorption-status.json from the given path.

    Args:
        path: Path to the JSON file. Defaults to the standard location.

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        FileNotFoundError: If the status file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    target = path or STATUS_FILE
    if not target.exists():
        raise FileNotFoundError(f"Status file not found: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def filter_repos(
    repos: dict[str, dict[str, Any]],
    *,
    status: str | None = None,
    package: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Filter repos by status and/or target package.

    Args:
        repos: Dict of repo name -> repo metadata.
        status: If provided, only include repos with this status.
        package: If provided, only include repos targeting this package.

    Returns:
        Filtered dict of repo name -> repo metadata.
    """
    filtered: dict[str, dict[str, Any]] = {}
    for name, info in repos.items():
        if status and info.get("status") != status:
            continue
        if package and info.get("target_package") != package:
            continue
        filtered[name] = info
    return filtered


def format_table(repos: dict[str, dict[str, Any]]) -> str:
    """Format repos as a plain-text table.

    Args:
        repos: Dict of repo name -> repo metadata.

    Returns:
        Formatted table string.
    """
    header = (
        f"{'Repo':<{COL_NAME}} "
        f"{'Status':<{COL_STATUS}} "
        f"{'Package':<{COL_PACKAGE}} "
        f"{'Examined':<{COL_EXAMINED}} "
        f"{'Notes':<{COL_NOTES}}"
    )
    separator = "-" * len(header)

    lines = [header, separator]
    for name, info in sorted(repos.items()):
        examined = info.get("last_examined") or "never"
        notes = info.get("notes", "")
        # Truncate notes if too long
        if len(notes) > COL_NOTES:
            notes = notes[: COL_NOTES - 3] + "..."
        lines.append(
            f"{name:<{COL_NAME}} "
            f"{info.get('status', 'unknown'):<{COL_STATUS}} "
            f"{info.get('target_package', '-'):<{COL_PACKAGE}} "
            f"{examined:<{COL_EXAMINED}} "
            f"{notes:<{COL_NOTES}}"
        )
    return "\n".join(lines)


def format_markdown(repos: dict[str, dict[str, Any]]) -> str:
    """Format repos as a Markdown table.

    Args:
        repos: Dict of repo name -> repo metadata.

    Returns:
        Formatted Markdown table string.
    """
    lines = [
        "# Absorption Status Report",
        "",
        f"**Total repos:** {len(repos)}",
        "",
        "| Repo | Status | Package | Examined | Notes |",
        "|------|--------|---------|----------|-------|",
    ]
    for name, info in sorted(repos.items()):
        examined = info.get("last_examined") or "never"
        notes = info.get("notes", "")
        status_val = info.get("status", "unknown")
        package = info.get("target_package", "-")
        lines.append(f"| {name} | {status_val} | {package} | {examined} | {notes} |")
    return "\n".join(lines)


def format_summary(repos: dict[str, dict[str, Any]], total_declared: int | None = None) -> str:
    """Generate a summary of repo statuses.

    Args:
        repos: Dict of repo name -> repo metadata.
        total_declared: Total number of repos declared in the JSON metadata.

    Returns:
        Formatted summary string.
    """
    by_status: dict[str, int] = {}
    for info in repos.values():
        s = info.get("status", "unknown")
        by_status[s] = by_status.get(s, 0) + 1

    lines = [
        "",
        "=== Summary ===",
        f"Tracked repos: {len(repos)}",
    ]
    if total_declared:
        lines.append(f"Declared total: {total_declared}")

    for s in ["integrated", "verified", "examined", "unexamined", "deferred"]:
        count = by_status.get(s, 0)
        if count > 0:
            lines.append(f"  {s}: {count}")

    # Show unknown statuses if any
    known = {"integrated", "verified", "examined", "unexamined", "deferred"}
    for s, count in sorted(by_status.items()):
        if s not in known:
            lines.append(f"  {s}: {count}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the audit script.

    Args:
        argv: Command line arguments. Defaults to sys.argv[1:].

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = argparse.ArgumentParser(
        description="Audit reference repo absorption status.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--status",
        choices=["unexamined", "examined", "integrated", "verified", "deferred"],
        help="Filter by absorption status",
    )
    parser.add_argument(
        "--package",
        help="Filter by target package (e.g., gateway, ai, terminal)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "markdown"],
        default="table",
        dest="output_format",
        help="Output format (default: table)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to absorption-status.json (default: auto-detect)",
    )

    args = parser.parse_args(argv)

    try:
        data = load_status(args.file)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON — {exc}", file=sys.stderr)
        return 1

    repos = data.get("repos", {})
    total_declared = data.get("total_repos")

    filtered = filter_repos(repos, status=args.status, package=args.package)

    if args.output_format == "markdown":
        print(format_markdown(filtered))
    else:
        print(format_table(filtered))

    print(format_summary(filtered, total_declared))

    return 0


if __name__ == "__main__":
    sys.exit(main())
