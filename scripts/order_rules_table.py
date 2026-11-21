"""Print the order rules as a markdown table, or check a docs page against it.

Usage:
    python scripts/order_rules_table.py
    python scripts/order_rules_table.py --check docs/BROKER_AND_EXCHANGE_RULES.md

The table lists each rule's id, scope, effective-from date and on-screen
message, generated from flinttrade_core/data/order_rules.json. ``--check``
exits 1 when the page does not contain the current table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from flinttrade_core.order_rules import rules_markdown

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", type=Path, help="docs page that must contain the generated table")
    args = parser.parse_args(argv)
    table = rules_markdown()
    if args.check is None:
        sys.stdout.write(table)
        return 0
    if not args.check.exists():
        print(f"{args.check} does not exist", file=sys.stderr)
        return 1
    if table not in args.check.read_text(encoding="utf-8"):
        print(f"{args.check} is out of date; regenerate it with scripts/order_rules_table.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
