#!/usr/bin/env python3
"""Report webhook secrets older than the rotation window."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from flinttrade_core.db import open_sqlite


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--max-age-days", type=int, default=90)
    args = parser.parse_args()
    cutoff = time.time() - args.max_age_days * 86400
    conn = open_sqlite(args.db, durability="normal")
    try:
        rows = conn.execute(
            "SELECT webhook_id FROM webhooks WHERE last_rotated_at < ?",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    for (webhook_id,) in rows:
        print(webhook_id)
    return 1 if rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
