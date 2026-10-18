"""Versioned procedures and recall through the public portable knowledge interface."""
from datetime import UTC, datetime, timedelta

import pytest

from flinttrade_ai.memory_ledger import MemoryLedger
from flinttrade_core.service_providers import (
    EvidenceUseScope, LicenceFact, PermissionState, RightsBasis, RightsGrant, UsageRights, intersect_rights,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def rights():
    return intersect_rights(RightsGrant(
        "fixture", RightsBasis.LICENCE,
        UsageRights(output_use=PermissionState.ALLOWED, retention=PermissionState.ALLOWED,
                    max_evidence_use_scope=EvidenceUseScope.LIVE_DECISION),
        (LicenceFact("fixture", "document", "fixture", "https://example.invalid", "1", "a" * 64,
                     NOW.isoformat(), RightsBasis.LICENCE),),
    ))


@pytest.mark.integration
def test_stock_three_way_candidate_validation_default_and_run_pin_survive_restart(tmp_path):
    from flinttrade_ai.knowledge_store import KnowledgeStore
    with MemoryLedger(tmp_path / "ledger") as ledger:
        store = KnowledgeStore(ledger, clock=lambda: NOW)
        base = store.stock("risk", "1", {"risk.md": "one\ntwo\nthree\n", "references/r.md": "reference"}, rights())
        local = store.adapt(base, {"risk.md": "ONE\ntwo\nthree\n", "references/r.md": "reference"},
                            proposer="author", rights=rights())
        store.validate(local, validator="independent", evidence_ref="fixture:validation")
        store.promote(local, expected=base)
        assert store.pin("run-a", "risk") == local
        new = store.stock("risk", "2", {"risk.md": "one\ntwo\nTHREE\n", "references/r.md": "reference-2"}, rights())
        merged = store.rebase(local, new)
        assert store.version(merged)["files"]["risk.md"] == "ONE\ntwo\nTHREE\n"
        assert store.version(merged)["old_base"] == base
        assert store.version(merged)["new_base"] == new
        assert store.version(merged)["local"] == local
        with pytest.raises(ValueError, match="validated"):
            store.promote(merged, expected=local)
        with pytest.raises(ValueError, match="independent"):
            store.validate(merged, validator="author", evidence_ref="self-report")
        store.validate(merged, validator="independent", evidence_ref="fixture:validation-2")
        store.promote(merged, expected=local)
        assert store.resolve("risk", run_id="run-a") == local
        assert store.resolve("risk") == merged
        assert store.version(base)["files"]["references/r.md"] == "reference"
    with MemoryLedger(tmp_path / "ledger") as ledger:
        store = KnowledgeStore(ledger, clock=lambda: NOW)
        assert store.resolve("risk", run_id="run-a") == local
        assert store.resolve("risk") == merged
        assert store.version(new)["package_hash"] != store.version(base)["package_hash"]


@pytest.mark.integration
def test_scoped_validated_lexical_recall_excludes_raw_and_future_lessons(tmp_path):
    from flinttrade_ai.knowledge_store import KnowledgeMemory, KnowledgeScope
    scope = KnowledgeScope("sandbox:fixture", "paper", "run-a")
    with MemoryLedger(tmp_path / "ledger") as ledger:
        memory = KnowledgeMemory(ledger, scope, rights=rights(), clock=lambda: NOW)
        candidate = memory.propose("trading lessons: retain protection", symbol="FIXTURE", source_ref="fixture:trade")
        assert memory.context("FIXTURE", "trading lessons")[0] == ""
        memory.validate(candidate, validator="independent", evidence_ref="fixture:checked")
        text, receipt = memory.context("FIXTURE", "trading lessons")
        assert "retain protection" in text and receipt.event_ids
        other = KnowledgeMemory(ledger, KnowledgeScope("sandbox:other", "paper", "run-a"), rights=rights())
        assert other.context("FIXTURE", "trading lessons")[0] == ""
        early = KnowledgeMemory(ledger, scope, rights=rights(), clock=lambda: NOW - timedelta(seconds=1))
        assert early.context("FIXTURE", "trading lessons")[0] == ""


@pytest.mark.integration
def test_no_training_runtime_supplies_real_procedures_and_validated_scoped_memory(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from flinttrade_ai.autonomous_agent import AutonomousTrader, MarketData
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    from flinttrade_ai.knowledge_store import KnowledgeScope

    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    scope = KnowledgeScope("sandbox:fixture", "paper", "run-a")
    memory = runtime.memory(scope, rights=rights())
    candidate = memory.propose("trading lessons: do not reuse another account's history", symbol="FIXTURE",
                               source_ref="fixture:closed-trade")
    memory.validate(candidate, validator="independent", evidence_ref="fixture:criterion-passed")
    sent = []
    trader = AutonomousTrader(SimpleNamespace(chat=lambda messages: sent.append(messages) or SimpleNamespace(content="HOLD")),
                              None, memory=memory, skill_registry=runtime.skills(scope))
    asyncio.run(trader.decide(MarketData(symbol="FIXTURE", ltp=100)))
    assert "do not reuse another account's history" in sent[0][-1].content
    assert "## Procedure: risk_management" in sent[0][-1].content
    receipt = next(item for item in trader.context_receipts if "skills" in item)
    persisted = runtime.ledger.get_event(receipt["receipt_id"])
    assert persisted.payload["context_hash"] == receipt["context_hash"]
    assert receipt["skills"][0]["version_id"] == runtime.store.resolve("risk_management", run_id="run-a", scope=scope)
    runtime.close()


@pytest.mark.integration
def test_conflicted_updates_and_stale_promotions_leave_incumbent_intact(tmp_path):
    from flinttrade_ai.knowledge_store import KnowledgeStore
    with MemoryLedger(tmp_path / "ledger") as ledger:
        store = KnowledgeStore(ledger, clock=lambda: NOW)
        base = store.stock("risk", "1", {"risk.md": "old"}, rights())
        local = store.adapt(base, {"risk.md": "local"}, proposer="author", rights=rights())
        store.validate(local, validator="other", evidence_ref="fixture:checked")
        store.promote(local, expected=base)
        new = store.stock("risk", "2", {"risk.md": "upstream"}, rights())
        conflict = store.rebase(local, new)
        assert store.version(conflict)["conflicts"] == ["risk.md"]
        with pytest.raises(ValueError, match="quarantined"):
            store.validate(conflict, validator="other", evidence_ref="fixture:checked")
        with pytest.raises(ValueError, match="changed"):
            store.promote(new, expected=base)
        with pytest.raises(ValueError, match="immutable"):
            store.stock("risk", "1", {"risk.md": "replacement"}, rights())
        assert store.resolve("risk") == local
        store.retire(local, reason="fixture:failed-prospective-check")
        with pytest.raises(ValueError, match="retired"):
            store.resolve("risk")
        store.promote(base, expected=local)  # explicit eligible rollback, not ledger rewind
        assert store.resolve("risk") == base
        assert store.version(local)["files"]["risk.md"] == "local"


@pytest.mark.integration
@pytest.mark.parametrize("provider", ["custom", "anthropic"])
def test_selected_procedure_reaches_nontrading_http_consumer_with_durable_receipt(tmp_path, provider):
    import json
    import httpx
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    from flinttrade_ai.llm_client import LLMClient, LLMConfig, LLMMessage

    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "text", "text": "fixture answer"}],
                                       "choices": [{"message": {"content": "fixture answer"}}]})
    with LLMClient(LLMConfig(provider=provider, host="https://example.invalid" if provider == "custom" else "", model="fixture"),
                   knowledge_registry=runtime.registry, http_transport=httpx.MockTransport(transport)) as client:
        result = client.chat([LLMMessage("system", "Explain safely."), LLMMessage("user", "How do I backtest?")],
                             selected_skills=("backtest_guide",))
    actual = sent[0]["messages"][0]["content"] if provider == "custom" else sent[0]["system"]
    assert "Explain safely." in actual
    assert "BacktestSimulator" in actual
    assert "def evaluate_candidate" in actual
    receipt = result.context_receipts[0]
    assert runtime.ledger.get_event(receipt["receipt_id"]).payload["context_hash"] == receipt["context_hash"]
    version = runtime.store.version(receipt["skills"][0]["version_id"])
    assert receipt["skills"][0]["package_hash"] == version["package_hash"]
    runtime.close()
