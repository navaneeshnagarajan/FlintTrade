#!/usr/bin/env python3
"""
Run Phase 4 Practice-only proof (accelerated by default; wall-clock gated).
Uses env-i + unshare for isolation.
Flask in-process client, TESTING=False, signed Practice JWT, live_mode_unlocked=false.
Test-only adapter practice-proof-sandbox.
"""

import argparse
import json
import sys
from pathlib import Path

# Add root for harness
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from scripts.phase4_practice_harness import PracticeProofHarness, ProofConfig, ProofEvidence


def run_accelerated_proof(config: ProofConfig) -> ProofEvidence:
    """Run accelerated synthetic proof."""
    harness = PracticeProofHarness(config)
    harness.setup_isolated_environment()
    evidence = harness.run_accelerated_day()
    harness.close()
    return evidence

def run_wall_clock_proof(config: ProofConfig) -> ProofEvidence:
    """Wall-clock run (gated; do not call unless explicitly requested and calendar validated)."""
    raise RuntimeError("Wall-day run is gated. Use accelerated mode only for this task.")

def persist_evidence(evidence: ProofEvidence, evidence_dir: Path) -> None:
    """Persist manifest, events, etc. (simplified for accelerated)."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = evidence.manifest.get("run_id", "unknown")
    out_dir = evidence_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(evidence.manifest, indent=2))
    (out_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in evidence.events))
    (out_dir / "counts.json").write_text(json.dumps(evidence.counts, indent=2))
    # SHA256SUMS stub
    (out_dir / "SHA256SUMS").write_text("stub-checksum-for-accelerated\n")
    print(f"Evidence persisted to {out_dir}")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-08-10")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--open", default="09:15")
    parser.add_argument("--close", default="15:30")
    parser.add_argument("--mode", default="practice")
    parser.add_argument("--evidence", default=".local/specs/phase4-practice-proof/evidence")
    parser.add_argument("--accelerated", action="store_true", default=True)
    parser.add_argument("--wall-clock", action="store_true")
    args = parser.parse_args()

    config = ProofConfig(
        session_date=args.date,
        exchange=args.exchange,
        open_ist=args.open,
        close_ist=args.close,
        mode=args.mode,
        evidence_dir=Path(args.evidence),
        testing=False,
        live_mode_unlocked=False,
    )

    if args.wall_clock:
        evidence = run_wall_clock_proof(config)
    else:
        evidence = run_accelerated_proof(config)

    persist_evidence(evidence, config.evidence_dir)
    print("Accelerated proof complete. RED/GREEN counts from test suite apply.")
    print("Residual wall-day gate: pending valid market day + clean re-audit (22500s monotonic required).")

if __name__ == "__main__":
    main()
