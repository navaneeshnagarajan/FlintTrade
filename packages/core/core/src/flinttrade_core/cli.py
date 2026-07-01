"""FlintTrade workspace CLI.

Usage:
    python -m flinttrade_core.cli init      # Initialise ~/.flinttrade/
    python -m flinttrade_core.cli status    # Show workspace info
"""

from __future__ import annotations

import argparse
import secrets
import sys

from .secure_file import harden
from .workspace import Workspace


def _provision_master_password(ws: Workspace) -> bool:
    """Ensure the credential-vault master password exists for source/dev runs.

    The backend deliberately refuses to auto-generate this secret. Installers,
    the Tauri shell, and this explicit CLI command are allowed provisioning
    points because they write the supported hardened at-rest file before the
    backend starts.
    """
    password_file = ws.workspace_dir / "master_password"
    if password_file.exists() and password_file.read_text(encoding="utf-8").strip():
        harden(password_file)
        return False

    password_file.parent.mkdir(parents=True, exist_ok=True)
    password_file.write_text(secrets.token_hex(32), encoding="utf-8")
    harden(password_file)
    return True


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise the workspace with default config."""
    ws = Workspace()
    created_workspace = not ws.is_initialized
    if created_workspace:
        ws.initialise()
        print(f"Workspace initialised: {ws.workspace_dir}")
        print(f"  Config:  {ws.config_path}")
        print(f"  Data:    {ws.fast_data_dir}")
        print(f"  Archive: {ws.archive_dir}")
        print(f"  Logs:    {ws.log_dir}")
    else:
        print(f"Workspace already initialised: {ws.workspace_dir}")

    if args.provision_master_password:
        created_secret = _provision_master_password(ws)
        action = "generated" if created_secret else "already present"
        print(f"  Master password: {action} at {ws.workspace_dir / 'master_password'}")


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

    init_parser = sub.add_parser("init", help="Initialise workspace with defaults")
    init_parser.add_argument(
        "--provision-master-password",
        action="store_true",
        help="Create the hardened master_password file when it is missing or empty.",
    )
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
