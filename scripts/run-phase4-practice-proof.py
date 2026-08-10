#!/usr/bin/env python3
"""
run-phase4-practice-proof.py
Entry point for the accelerated isolated proof run.
Supports --preflight-only and full run.
Must be executed under env -i + unshare as per plan section 11.
"""

import argparse
import sys
from pathlib import Path

from scripts.phase4_practice_proof import Phase4PracticeProofHarness


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--run-root", required=True, type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    h = Phase4PracticeProofHarness(run_root)

    if args.preflight_only:
        checks = h.preflight()
        print("PREFLIGHT:", checks)
        if not all([
            checks.get("user_ns_changed"),
            checks.get("network_namespace_changed"),
            checks.get("env_allowlist_exact"),
            checks.get("no_credential_keys"),
            checks.get("testing_false"),
        ]):
            print("PREFLIGHT FAILED - aborting")
            sys.exit(1)
        print("PREFLIGHT PASSED")
        sys.exit(0)

    # Full accelerated run (no wall day)
    print("Starting accelerated Phase 4 Practice Proof v2")
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_journal()
    h.init_audit()
    h.init_lifecycle()
    h.init_safety_and_router()
    h.init_memory()
    h.setup_minimal_flask_for_http_claim()

    # Run the full day (accelerated)
    full_result = h.run_full_day_accelerated()
    print("FULL DAY RESULT:", full_result)

    # Write evidence
    manifest = h.write_evidence()
    print("EVIDENCE WRITTEN:", manifest)

    # Verify
    if h.verify_manifest(manifest):
        print("VERIFIER: PASS")
        sys.exit(0)
    else:
        print("VERIFIER: FAIL")
        sys.exit(1)

if __name__ == "__main__":
    main()
