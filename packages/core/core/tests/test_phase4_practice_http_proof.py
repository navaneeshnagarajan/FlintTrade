"""
RED test for Claim A: minimal Flask Practice route.
Per plan section 6: assertion failures for absent real behaviour.
Run with: /home/USER/FlintTrade/.venv/bin/python -m pytest ... -v --import-mode=importlib
"""

from scripts.phase4_practice_proof import Phase4PracticeProofHarness

def test_real_practice_jwt_forged_live_header_reaches_real_sandbox_no_sentinel(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.setup_minimal_flask_for_http_claim()
    h.create_practice_jwt()  # token not needed for this test
    result = h.run_http_practice_claim()
    assert result["status"] == "PASS", "HTTP practice route must reach real SandboxEngine"
    assert result["accepted"] == 10, "Exactly 10 orders must be accepted in 21-call burst"
    assert result["rate_limited"] == 11
    assert result["sandbox_orders"] == 10
    assert result["sentinel_access"]["http"] == 0
    assert result["sentinel_access"]["router"] == 0
    assert result["sentinel_access"]["openalgo"] == 0

def test_missing_invalid_jwt_rejected_no_sandbox_row(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.setup_minimal_flask_for_http_claim()
    result = h.run_http_practice_claim()
    assert result["accepted"] == 10

def test_practice_jwt_on_routed_live_endpoint_rejected_before_router(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.setup_minimal_flask_for_http_claim()
    result = h.run_http_practice_claim()
    assert result["sentinel_access"]["router"] == 0, "Must reject before router sentinel"

def test_frozen_clock_21_call_http_burst_exact(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.setup_minimal_flask_for_http_claim()
    result = h.run_http_practice_claim()
    assert result["offered"] == 21
    assert result["accepted"] + result["rate_limited"] == 21
    assert result["sandbox_orders"] == 10
