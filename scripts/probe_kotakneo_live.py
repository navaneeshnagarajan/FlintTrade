#!/usr/bin/env python3
"""Compatibility wrapper for the Kotak Neo read-only live probe."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
root_path = str(ROOT)
if root_path not in sys.path:
    sys.path.insert(0, root_path)

from scripts.probe_native_broker_live import run_probe  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only Kotak Neo native adapter probe with redacted output.",
    )
    parser.add_argument(
        "--environment",
        default="prod",
        choices=("prod", "uat"),
        help="Kotak Neo SDK environment to use.",
    )
    parser.add_argument(
        "--reads",
        nargs="+",
        default=["default"],
        help=(
            "Read-only calls: default, all, or any of funds limits positions holdings orders trades "
            "scrip_master search_scrip quotes quote_details market_depth."
        ),
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Call the broker logout endpoint after probing; this may revoke access tokens.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(run_probe("kotakneo", "totp_mpin", args.reads, args.environment, logout=args.logout))
    except KeyboardInterrupt:
        print("probe: cancelled")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
