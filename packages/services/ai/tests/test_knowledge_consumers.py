"""Public knowledge consumers, with synthetic inputs and no model server."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from flinttrade_ai.autonomous_agent import AutonomousTrader, MarketData
from flinttrade_ai.skill_system import SkillRegistry


@pytest.mark.integration
def test_selected_full_body_and_reference_reach_real_trader(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "references/check.md").write_text("Verify the exact account before using evidence.")
    (tmp_path / "risk_management.md").write_text(
        "---\nname: risk_management\ncategory: safety\ndescription: Risk procedure\n"
        "references: [references/check.md]\n---\n# Risk procedure\nKeep protective exits independent.\n"
    )
    sent = []
    llm = SimpleNamespace(chat=lambda messages: sent.append(messages) or SimpleNamespace(content="HOLD"))
    trader = AutonomousTrader(llm, None, skill_registry=SkillRegistry(tmp_path))
    assert asyncio.run(trader.decide(MarketData(symbol="FIXTURE", ltp=100))) == "HOLD"
    prompt = sent[0][-1].content
    assert "Keep protective exits independent." in prompt
    assert "Verify the exact account before using evidence." in prompt
    receipt = trader.context_receipts[-1]
    assert receipt["skills"][0]["name"] == "risk_management"
    assert receipt["skills"][0]["files"]["references/check.md"]
    assert receipt["context_hash"]


@pytest.mark.unit
def test_body_budget_is_fail_closed_not_silent_truncation(tmp_path):
    (tmp_path / "large.md").write_text("---\nname: large\n---\n" + "procedure " * 100)
    registry = SkillRegistry(tmp_path)
    with pytest.raises(ValueError, match="budget"):
        registry.context(["large"], max_bytes=50)


@pytest.mark.integration
def test_inference_enablement_cannot_send_reflection_and_raw_memory_cannot_influence():
    from flinttrade_ai.trade_reflection import ReflectionConfig, TradeReflector
    sent = []
    llm = SimpleNamespace(chat=lambda messages: sent.append(messages) or SimpleNamespace(content="HOLD"))
    reflector = TradeReflector(ReflectionConfig(min_trades_for_reflection=1), llm_client=llm)
    result = asyncio.run(reflector.reflect_batch([{"symbol": "FIXTURE", "pnl_pct": 1}]))
    assert result is not None  # useful deterministic local analysis, no training/egress required
    assert sent == []
    trader = AutonomousTrader(llm, None, memory=SimpleNamespace(summarise_context=lambda *a, **kw: "RAW LESSON"))
    asyncio.run(trader.decide(MarketData(symbol="FIXTURE", ltp=100)))
    assert "RAW LESSON" not in sent[0][-1].content
