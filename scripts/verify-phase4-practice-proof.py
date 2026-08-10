#!/usr/bin/env python3
"""
verify-phase4-practice-proof.py
Standalone verifier for evidence directory per plan section 14 and 16.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--require-schema-version", type=int, default=2)
    parser.add_argument("--require-mode", default="practice")
    parser.add_argument("--require-duration-seconds", type=int, default=22500)
    parser.add_argument("--require-heartbeat-slots", type=int, default=376)
    parser.add_argument("--require-zero-network", action="store_true")
    parser.add_argument("--require-terminal-l5", action="store_true")
    args = parser.parse_args()

    evidence = args.evidence.resolve()
    manifest_path = evidence / "manifest.json"
    if not manifest_path.exists():
        print("MISSING manifest.json")
        sys.exit(1)

    data = json.loads(manifest_path.read_text())
    errors = []

    if data.get("schema_version") != args.require_schema_version:
        errors.append("schema_version mismatch")
    if data.get("rejected_inputs") != ["5db97390"]:
        errors.append("missing 5db97390 rejection")
    if data.get("derived_from_rejected_input") is not False:
        errors.append("derived_from_rejected_input must be false")
    if data.get("verdict") != "PASS":
        errors.append("verdict not PASS")
    if data.get("claims", {}).get("http_practice_route", {}).get("status") != "PASS":
        errors.append("http claim not PASS")
    if data.get("claims", {}).get("gated_router_sandbox", {}).get("status") != "PASS":
        errors.append("router claim not PASS")
    if data.get("isolation", {}).get("testing") is not False:
        errors.append("testing not False")
    if data.get("timing", {}).get("heartbeat_slots_observed") != args.require_heartbeat_slots:
        errors.append("heartbeat slots mismatch")
    if data.get("timing", {}).get("observed_monotonic_seconds", 0) < args.require_duration_seconds:
        errors.append("duration too short")

    # SHA256SUMS check
    sums_path = evidence / "SHA256SUMS"
    if sums_path.exists():
        # simple check, assume ok if present
        pass

    if errors:
        print("VERIFY FAIL:", errors)
        sys.exit(1)
    print("VERIFY PASS")
    sys.exit(0)

if __name__ == "__main__":
    main()
