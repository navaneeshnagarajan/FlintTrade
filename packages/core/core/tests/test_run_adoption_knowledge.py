"""Practice consumes the shared knowledge owner with backend-issued scope."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_practice_agent_runtime import desk as desk, _start, _supervisor, _wait_for

pytestmark = pytest.mark.integration


def test_practice_knowledge_scope_is_backend_owned_not_ui_selection(desk, tmp_path, monkeypatch):
    from flinttrade_core.knowledge_integration import install_knowledge_runtime
    from flinttrade_core.run_adoption import install_run_services
    from flinttrade_core import agent_routes
    (tmp_path / "knowledge-workspace").mkdir(mode=0o700)
    install_knowledge_runtime(desk.app, tmp_path / "knowledge-workspace")
    assert desk.app.config["KNOWLEDGE_RUNTIME"] is not None
    owner = install_run_services(desk.app, tmp_path / "knowledge-workspace")
    monkeypatch.setattr(agent_routes, "_build_learning_memory", lambda: pytest.fail("legacy/unscoped memory path used"))
    result = _start(desk, cycle_interval_sec=3600)
    assert result.status_code == 202, result.json
    supervisor = _supervisor(desk)
    _wait_for(lambda: supervisor.run.trader is not None or supervisor.run.cleanup_complete)
    assert supervisor.run.trader is not None, supervisor.run.error
    scope = desk.app.config["KNOWLEDGE_SCOPE_RESOLVER"](desk.owner)
    assert scope.run_id == supervisor.run.run_id
    assert scope.account_id == "paper:sandbox" and scope.environment == "paper"
    assert supervisor.run.trader.memory.scope == scope
    assert supervisor.run.trader.skill_registry.knowledge_scope == scope
    desk.app.config["ACTIVE_ACCOUNT"] = "unrelated-live-account"
    desk.app.config["MODE"] = "live"
    assert desk.app.config["KNOWLEDGE_SCOPE_RESOLVER"](desk.owner) == scope
    assert desk.app.config["KNOWLEDGE_SCOPE_RESOLVER"]("different-operator") is None
    assert supervisor.run.trader.automatic_learning, "local evidence needs no remote inference consent"
    assert supervisor.run.trader.learning_client.policy.control("binding") == (0, None)
    from flinttrade_core.practice_agent_runtime import shutdown_practice_agent
    shutdown_practice_agent(desk.app, timeout=5)
    owner.close()
    desk.app.config["KNOWLEDGE_RUNTIME"].close()
