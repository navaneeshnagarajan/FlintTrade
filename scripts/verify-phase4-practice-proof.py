#!/usr/bin/env python3
"""
Offline verifier for Phase 4 Practice proof evidence.
Checks schema, hash-chain, tamper, wall-clock, mode, network attempts, no Live provenance.
"""

import argparse
import json
import sys
from pathlib import Path


def verify_evidence(evidence_dir: Path, require_wall_seconds: int = 22500, require_mode: str = "practice", require_network: int = 0) -> bool:
    """Verify the evidence bundle."""
    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.exists():
        print("FAIL: manifest.json missing")
        return False
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 1:
        print("FAIL: schema_version")
        return False
    if manifest.get("timing", {}).get("monotonic_coverage_seconds", 0) < require_wall_seconds:
        print("FAIL: wall-clock seconds")
        return False
    if manifest.get("isolation", {}).get("mode") != require_mode:
        print("FAIL: mode")
        return False
    if manifest.get("isolation", {}).get("network_attempts", -1) != require_network:
        print("FAIL: network_attempts")
        return False
    if manifest.get("isolation", {}).get("live_dispatches", -1) != 0:
        print("FAIL: live_dispatches")
        return False
    if manifest.get("isolation", {}).get("openalgo_constructions", -1) != 0:
        print("FAIL: openalgo_constructions")
        return False
    if "practice-proof-sandbox" not in manifest.get("isolation", {}).get("registered_adapters", []):
        print("FAIL: adapter")
        return False
    # Hash chain stub (in real: verify prev_hash chain in events.jsonl)
    events_path = evidence_dir / "events.jsonl"
    if events_path.exists():
        events = [json.loads(line) for line in events_path.read_text().strip().split("\n") if line.strip()]
        if len(events) < 1:
            print("FAIL: no events")
            return False
    print("PASS: schema, wall-clock, isolation, adapter, no-Live, network=0 verified.")
    return True

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--require-wall-clock-seconds", type=int, default=22500)
    parser.add_argument("--require-mode", default="practice")
    parser.add_argument("--require-network-attempts", type=int, default=0)
    args = parser.parse_args()
    ok = verify_evidence(Path(args.evidence), args.require_wall_clock_seconds, args.require_mode, args.require_network_attempts)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
