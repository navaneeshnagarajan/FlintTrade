"""
RED/GREEN test for Claim B: gated safety/router path to inert sandbox adapter.
Per plan section 6.
"""

from scripts.phase4_practice_proof import Phase4PracticeProofHarness

def test_l1_l5_all_pass_before_gate_mint_router_inert_adapter(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["status"] == "PASS"
    assert result["l1_l5_pass"] >= 1
    assert result["adapter_calls"] >= 1

def test_each_l1_l2_l3_l4_l5_failure_creates_no_gate_adapter_sandbox_write(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["status"] == "PASS"

def test_consumed_gate_replay_fails(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["status"] == "PASS"

def test_gateway_limiter_delays_sequential_third_dispatch(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["status"] == "PASS"

def test_commit_then_lost_ack_produces_durable_unknown_outcome_reopen_resolution(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["unknown_outcomes"] == 1
    assert result["router_reopens"] == 2
    assert result["status"] == "PASS"

def test_terminal_l5_blocks_fresh_and_preminted_context_no_reset(tmp_path):
    run_root = tmp_path / "run"
    h = Phase4PracticeProofHarness(run_root)
    h.setup_isolated_stores()
    h.init_sandbox()
    h.init_lifecycle()
    h.init_safety_and_router()
    result = h.run_gated_router_claim()
    assert result["l5_active"] is True
    assert result["blocked_fresh"] == 3
    assert result["blocked_preminted"] == 1
    assert result["status"] == "PASS"
