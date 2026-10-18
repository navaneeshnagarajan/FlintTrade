"""Actual run learning: portable evidence first, no inference-consent escalation."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_practice_agent_runtime import (
    _run_finished, _start, _supervisor, _wait_for, desk as desk,
)

pytestmark = pytest.mark.integration


def test_closed_trade_records_and_local_candidates_reopen_without_remote_consent(desk, tmp_path):
    from flinttrade_ai.memory_ledger import MemoryDomain, MemoryLedger
    from flinttrade_core.knowledge_integration import install_knowledge_runtime
    from flinttrade_core.run_adoption import install_run_services

    workspace = tmp_path / "canonical"
    workspace.mkdir(mode=0o700)
    install_knowledge_runtime(desk.app, workspace)
    services = install_run_services(desk.app, workspace)
    desk.signal = "BUY"
    assert _start(desk, cycle_interval_sec=3600).status_code == 202
    run = _supervisor(desk).run
    _wait_for(lambda: run.snapshot.get("cycle_count") == 1)
    assert run.trader.automatic_learning, "local portable evidence is not remote consent"
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    assert run.trader.join_background_learning(0)
    assert len(desk.sandbox.get_trades()) == 2
    runtime = desk.app.config["KNOWLEDGE_RUNTIME"]
    events = runtime.ledger.history(MemoryDomain.EPISODIC)
    records = [e for e in events if e.payload.get("kind") == "closed-trade"]
    lessons = [e for e in events if e.payload.get("kind") == "memory-candidate"]
    assert len(records) == 1 and lessons
    record = records[0]
    assert record.payload["account_id"] == "paper:sandbox"
    assert record.payload["environment"] == "paper" and record.payload["run_id"] == run.run_id
    assert dict(record.payload["values"]) == run.trader.state.closed_trades[0]
    assert record.source_refs == ("autonomous-trader.closed-trades:v1",)
    assert all(record.event_id in e.parent_ids for e in lessons)
    assert all(e.payload["generation"] == "local-rule-candidate" for e in lessons)
    assert run.trader._memory_context("RELIANCE") == "", "candidate is not independent validation"
    ids = [e.event_id for e in lessons]
    services.close()
    runtime.close()
    reopened = MemoryLedger(workspace / "knowledge")
    try:
        assert [reopened.get_event(identity).event_id for identity in ids] == ids
        assert reopened.get_event(record.event_id).digest == record.digest
    finally:
        reopened.close()


def test_model_owner_refuses_close_until_the_actual_learning_thread_has_joined(desk, tmp_path):
    import threading
    from flinttrade_core.knowledge_integration import install_knowledge_runtime
    from flinttrade_core.run_adoption import install_run_services
    workspace = tmp_path / "owned-learning"
    workspace.mkdir(mode=0o700)
    install_knowledge_runtime(desk.app, workspace)
    services = install_run_services(desk.app, workspace)
    assert _start(desk, cycle_interval_sec=3600).status_code == 202
    run = _supervisor(desk).run
    _wait_for(lambda: run.snapshot.get("cycle_count") == 1)
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    entered, release = threading.Event(), threading.Event()
    def learner():
        entered.set()
        release.wait(5)
    worker = threading.Thread(target=learner)
    run.trader._learning_thread = worker
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(RuntimeError, match="learning"):
            services.close()
        assert not services.closed
        assert desk.app.config["KNOWLEDGE_RUNTIME"].registry.context(["risk_management"])[0]
    finally:
        release.set()
        assert run.trader.join_background_learning(5)
        services.close()
        desk.app.config["KNOWLEDGE_RUNTIME"].close()
