#!/usr/bin/env python3
"""Delete expired webhook replay nonces."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from flinttrade_core.db import open_sqlite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--ttl-seconds", type=int, default=600)
    args = parser.parse_args()
    cutoff = time.time() - args.ttl_seconds
    conn = open_sqlite(args.db, durability="normal")
    try:
        cur = conn.execute("DELETE FROM webhook_nonces WHERE seen_at < ?", (cutoff,))
        print(cur.rowcount)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
