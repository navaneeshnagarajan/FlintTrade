"""FlintTrade workspace CLI.

Usage:
    python -m flinttrade_core.cli init      # Initialise ~/.flinttrade/
    python -m flinttrade_core.cli status    # Show workspace info
"""

from __future__ import annotations

import argparse
import sys

from .workspace import Workspace


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise the workspace with default config."""
    ws = Workspace()
    if ws.is_initialized:
        print(f"Workspace already initialised: {ws.workspace_dir}")
        return
    ws.initialise()
    print(f"Workspace initialised: {ws.workspace_dir}")
    print(f"  Config:  {ws.config_path}")
    print(f"  Data:    {ws.fast_data_dir}")
    print(f"  Archive: {ws.archive_dir}")
    print(f"  Logs:    {ws.log_dir}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show current workspace info."""
    ws = Workspace()
    print(f"Workspace: {ws.workspace_dir}")
    print(f"Initialised: {ws.is_initialized}")
    if ws.is_initialized:
        print(f"Config:  {ws.config_path}")
        print(f"Data:    {ws.fast_data_dir}")
        print(f"Archive: {ws.archive_dir}")
        print(f"Logs:    {ws.log_dir}")
        modules = ws.get("modules", {})
        enabled = [k for k, v in modules.items() if v]
        disabled = [k for k, v in modules.items() if not v]
        print(f"Enabled:  {', '.join(enabled) if enabled else 'none'}")
        print(f"Disabled: {', '.join(disabled) if disabled else 'none'}")
        print(f"Version: {ws.get('version', 'unknown')}")
    else:
        print("Run: python -m flinttrade_core.cli init")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flinttrade",
        description="FlintTrade workspace management",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialise workspace with defaults")
    sub.add_parser("status", help="Show workspace info")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
