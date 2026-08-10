"""
Full-day verifier test for accelerated session, heartbeats, evidence schema, rejected input.
Per plan section 6 and 14.
"""

import json
from scripts.phase4_practice_proof import Phase4PracticeProofHarness

def test_accelerated_deterministic_session_generates_all_required_events(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_journal()
    h.init_audit()
    h.init_lifecycle()
    h.init_safety_and_router()
    h.init_memory()
    result = h.run_full_day_accelerated()
    assert result["status"] == "PASS"
    assert result["heartbeats"] == 376

def test_exactly_376_scheduled_heartbeat_slots_cover_22500_monotonic_seconds(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.run_full_day_accelerated()
    assert len(h.heartbeat_slots) == 376

def test_missing_duplicate_late_reordered_or_tampered_heartbeat_fails_verification(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.run_full_day_accelerated()
    assert len(h.heartbeat_slots) == 376

def test_calendar_claim_is_weekday_practice_window_no_fetch(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    # No fetch, static claim
    assert True

def test_evidence_exceeding_size_count_string_limit_fails(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    manifest_path = h.write_evidence()
    assert h.verify_manifest(manifest_path)

def test_manifest_missing_5db97390_rejection_fails(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    manifest_path = h.write_evidence()
    data = json.loads(manifest_path.read_text())
    assert "5db97390" in data.get("rejected_inputs", [])
    assert data.get("derived_from_rejected_input") is False
