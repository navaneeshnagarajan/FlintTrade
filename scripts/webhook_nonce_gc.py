#!/usr/bin/env python3
"""Delete expired webhook replay nonces (data-layer §7.4; daily cron 03:00 IST).

Retention is the 10-minute replay window PLUS a 60-minute forensic grace so the
audit log keeps evidence of post-window replay attempts. Replay *defence* is the
receiver's job (it queries the nonce table within ``REPLAY_WINDOW_SECONDS``); the
GC only sweeps stale evidence. Defaulting the TTL to the replay window alone
would collapse the 10–70-minute grace bucket and discard that evidence.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flinttrade_core.db import open_sqlite
from flinttrade_webhooks import webhook_replay

REPLAY_WINDOW_SECONDS = webhook_replay.REPLAY_WINDOW_SECONDS
GC_GRACE_SECONDS = webhook_replay.GC_GRACE_SECONDS
GC_RETAIN_SECONDS = webhook_replay.GC_RETAIN_SECONDS
gc_old_nonces = webhook_replay.gc_old_nonces


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--ttl-seconds", type=int, default=GC_RETAIN_SECONDS)
    args = parser.parse_args()
    conn = open_sqlite(args.db, durability="normal")
    try:
        print(gc_old_nonces(conn, args.ttl_seconds))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
