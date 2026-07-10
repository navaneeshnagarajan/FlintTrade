"""Integration tests for canonical AgentTeam execution modes."""

from __future__ import annotations

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from flinttrade_ai._team_dag import TeamEvent, TeamTask
from flinttrade_ai._team_presets import get_preset
from flinttrade_ai.agent_models import AgentRole, AgentRoleType, TeamAnalysis, TeamMode
from flinttrade_ai.llm_client import LLMResponse
from flinttrade_ai.multi_agent import AgentTeam


def _llm(*responses: str) -> MagicMock:
    client = MagicMock()
    values = responses or ("Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.5\nSUMMARY: Mixed.",)
    client.chat.side_effect = [LLMResponse(content=value) for value in values]
    return client


def test_team_exposes_all_modes_and_exact_preset_catalogue() -> None:
    team = AgentTeam(_llm())

    assert team.available_modes() == ["flat", "dag", "sequential", "debate"]
    assert [preset["name"] for preset in team.available_presets()] == [
        "derivatives_desk",
        "event_driven",
        "full_house",
        "investor_team",
        "macro_research",
        "ml_quant_lab",
        "risk_committee",
        "scalp_team",
        "sector_rotation",
        "stat_arb_desk",
    ]
    assert len(team.available_presets()[2]["agents"]) == 10


def test_package_root_exports_canonical_team_types() -> None:
    from flinttrade_ai import (
        AnalysisState,
        AnalystChain,
        DebateResult,
        DebateRound,
        RiskDebate,
        TeamMode as ExportedTeamMode,
        TeamPreset,
        TeamPresetAgent,
        TeamTask as ExportedTeamTask,
    )
    from flinttrade_ai import _team_modes, _team_presets

    assert AnalysisState is _team_modes.AnalysisState
    assert AnalystChain is _team_modes.AnalystChain
    assert DebateResult is _team_modes.DebateResult
    assert DebateRound is _team_modes.DebateRound
    assert RiskDebate is _team_modes.RiskDebate
    assert TeamPreset is _team_presets.TeamPreset
    assert TeamPresetAgent is _team_presets.TeamPresetAgent
    assert ExportedTeamTask is TeamTask
    assert ExportedTeamMode is TeamMode


def test_preset_dag_uses_tiers_dependencies_events_and_canonical_result() -> None:
    quick = _llm(
        "Options report.\nSIGNAL: BUY\nCONFIDENCE: 0.7\nSUMMARY: Bullish.",
        "Greeks report.\nSIGNAL: HOLD\nCONFIDENCE: 0.6\nSUMMARY: Balanced.",
    )
    deep = _llm(
        "Integrated risk report.",
        "DECISION: BUY\nCONFIDENCE: 0.65\nREASONING: Options upside survives risk review.",
    )
    team = AgentTeam(quick, deep_llm_client=deep)
    events: list[TeamEvent] = []

    result = asyncio.run(
        team.analyse_async(
            "NIFTY",
            "NSE_INDEX",
            market_data={"vix": 13.5},
            mode=TeamMode.DAG,
            preset="derivatives_desk",
            on_event=events.append,
        )
    )

    assert result.mode is TeamMode.DAG
    assert result.preset == "derivatives_desk"
    assert [analysis.task_id for analysis in result.agent_analyses] == [
        "options_analyst",
        "greeks_monitor",
        "risk_manager",
    ]
    assert [analysis.model_tier for analysis in result.agent_analyses] == ["quick", "quick", "deep"]
    assert result.agent_analyses[-1].report == "Integrated risk report."
    assert result.consensus_signal == "BUY"
    assert quick.chat.call_count == 2
    assert deep.chat.call_count == 2
    risk_prompt = deep.chat.call_args_list[0].args[0][-1].content
    assert "Options report" in risk_prompt
    assert "Greeks report" in risk_prompt
    assert [event.event_type for event in events].count("started") >= 4
    assert any(event.task_id == "risk_manager" and event.event_type == "completed" for event in events)
    assert events[-1].task_id == "aggregator"
    assert events[-1].event_type == "completed"


def test_active_preset_executes_exact_explicit_preset_dag() -> None:
    active_quick = _llm("options", "greeks")
    active_deep = _llm("risk", "DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: Controlled.")
    active_team = AgentTeam(active_quick, deep_llm_client=active_deep)
    active_team.update_config({"preset": "derivatives_desk"})

    explicit_quick = _llm("options", "greeks")
    explicit_deep = _llm("risk", "DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: Controlled.")
    explicit_team = AgentTeam(explicit_quick, deep_llm_client=explicit_deep)

    active = active_team.analyse("NIFTY", "NSE_INDEX")
    explicit = explicit_team.analyse("NIFTY", "NSE_INDEX", preset="derivatives_desk")

    assert active.preset == explicit.preset == "derivatives_desk"
    assert [item.task_id for item in active.agent_analyses] == [item.task_id for item in explicit.agent_analyses]
    assert active_deep.chat.call_count == explicit_deep.chat.call_count == 2


def test_preset_role_contract_appends_canonical_signal_for_majority_fallback() -> None:
    quick = MagicMock()

    def quick_response(messages, **_kwargs):
        if "senior options analyst" in messages[0].content:
            return LLMResponse(
                content=(
                    "Options view.\nMAX_PAIN: 25000\nSIGNAL: SELL\n"
                    "CONFIDENCE: 0.8\nSUMMARY: Bearish skew."
                )
            )
        return LLMResponse(
            content="Greeks view.\nRISK_LEVEL: HIGH\nSIGNAL: SELL\nCONFIDENCE: 0.7"
        )

    quick.chat.side_effect = quick_response
    deep = MagicMock()
    deep.chat.side_effect = [
        LLMResponse(
            content=(
                "Risk synthesis.\nRISK_REVIEW: ELEVATED\n"
                "SIGNAL: SELL\nCONFIDENCE: 0.9"
            )
        ),
        LLMResponse(error="aggregator unavailable"),
    ]
    team = AgentTeam(quick, deep_llm_client=deep)

    result = team.analyse("NIFTY", "NSE_INDEX", mode="flat", preset="derivatives_desk")

    original_system = get_preset("derivatives_desk").agents[0].system_prompt
    sent_system = next(
        call.args[0][0].content
        for call in quick.chat.call_args_list
        if call.args[0][0].content.startswith(original_system)
    )
    risk_system = deep.chat.call_args_list[0].args[0][0].content
    assert sent_system == original_system
    assert "SIGNAL: [BUY/SELL/HOLD]" in risk_system
    assert "CONFIDENCE: [0.0-1.0]" in risk_system
    assert "MAX_PAIN: 25000" in result.agent_analyses[0].report
    assert "SIGNAL: SELL" in result.agent_analyses[0].report
    assert "CONFIDENCE: 0.8" in result.agent_analyses[0].report
    assert "SUMMARY: Bearish skew." in result.agent_analyses[0].report
    assert "RISK_LEVEL: HIGH" in result.agent_analyses[1].report
    assert [analysis.signal for analysis in result.agent_analyses] == ["SELL", "SELL", "SELL"]
    assert result.consensus_signal == "SELL"
    assert "3 SELL" in result.consensus_reasoning


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_dependencies"),
    [
        (TeamMode.FLAT, []),
        (TeamMode.DAG, ["options_analyst", "greeks_monitor"]),
    ],
)
async def test_only_mode_controls_preset_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    mode: TeamMode,
    expected_dependencies: list[str],
) -> None:
    captured: list[TeamTask] = []

    async def execute(_runner, tasks, **_kwargs):
        captured.extend(tasks)
        return {
            task.id: "Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.4"
            for task in tasks
        }

    monkeypatch.setattr("flinttrade_ai.multi_agent.TeamDagRunner.execute", execute)
    deep = _llm("DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: Mixed.")

    await AgentTeam(_llm(), deep_llm_client=deep).analyse_async(
        "NIFTY",
        "NSE_INDEX",
        mode=mode,
        preset="derivatives_desk",
    )

    risk_task = next(task for task in captured if task.id == "risk_manager")
    assert risk_task.depends_on == expected_dependencies


@pytest.mark.parametrize("mode", [TeamMode.SEQUENTIAL, TeamMode.DEBATE])
@pytest.mark.parametrize("entrypoint", ["sync", "async"])
def test_fixed_modes_reject_explicit_preset(mode: TeamMode, entrypoint: str) -> None:
    team = AgentTeam(_llm())

    with pytest.raises(ValueError, match="preset is not supported for sequential or debate modes"):
        if entrypoint == "sync":
            team.analyse("NIFTY", "NSE_INDEX", mode=mode, preset="derivatives_desk")
        else:
            asyncio.run(
                team.analyse_async(
                    "NIFTY",
                    "NSE_INDEX",
                    mode=mode,
                    preset="derivatives_desk",
                )
            )

    team._quick.chat.assert_not_called()


@pytest.mark.asyncio
async def test_active_preset_can_be_explicitly_bypassed_for_custom_roster() -> None:
    role = AgentRole("Custom", AgentRoleType.TECHNICAL, "custom", role_id="custom")
    team = AgentTeam(
        _llm("Report.\nSIGNAL: BUY\nCONFIDENCE: 0.6"),
        deep_llm_client=_llm("DECISION: BUY\nCONFIDENCE: 0.6\nREASONING: Custom."),
        agents=[role],
    )
    team.update_config({"preset": "derivatives_desk"})
    assert [agent.role_id for agent in team.agents] == [
        "options_analyst",
        "greeks_monitor",
        "risk_manager",
    ]

    result = await team.analyse_async(
        "NIFTY",
        "NSE_INDEX",
        mode="flat",
        preset=None,
        use_active_preset=False,
    )

    assert result.preset == ""
    assert [analysis.task_id for analysis in result.agent_analyses] == ["custom"]


def test_sync_flat_execution_limits_dispatch_through_bounded_async_runner() -> None:
    team = AgentTeam(_llm())
    bounded_result = TeamAnalysis(symbol="NIFTY", exchange="NSE_INDEX")
    team.analyse_async = AsyncMock(return_value=bounded_result)

    result = team.analyse(
        "NIFTY",
        "NSE_INDEX",
        max_concurrent=1,
        task_timeout_seconds=3,
    )

    assert result is bounded_result
    team.analyse_async.assert_awaited_once_with(
        "NIFTY",
        "NSE_INDEX",
        market_data=None,
        mode=TeamMode.FLAT,
        preset=None,
        use_active_preset=False,
        debate_rounds=2,
        max_concurrent=1,
        task_timeout_seconds=3,
    )


@pytest.mark.parametrize("mode", [TeamMode.SEQUENTIAL, TeamMode.DEBATE])
def test_fixed_modes_do_not_inherit_active_preset(mode: TeamMode) -> None:
    quick = _llm(
        "market",
        "sentiment",
        "BULL: upside\nBEAR: downside",
        "aggressive",
        "conservative",
        "neutral",
    )
    deep = _llm(
        "DECISION: HOLD\nCONFIDENCE: 0.4\nREASONING: Mixed.",
        "VERDICT: HOLD\nCONFIDENCE: 0.4\nREASONING: Mixed.",
    )
    team = AgentTeam(quick, deep_llm_client=deep)
    team._active_preset = "derivatives_desk"

    result = team.analyse(
        "NIFTY",
        "NSE_INDEX",
        mode=mode,
        debate_rounds=1,
    )

    assert result.preset == ""
    assert {analysis.task_id for analysis in result.agent_analyses} <= {
        "market",
        "sentiment",
        "fundamentals",
        "aggressive",
        "conservative",
        "neutral",
    }


@pytest.mark.asyncio
async def test_flat_mode_starts_deep_and_quick_roles_without_dependencies() -> None:
    release_quick = threading.Event()
    quick_started = threading.Event()
    deep_started = threading.Event()

    def quick_chat(_messages: object, **_kwargs: object) -> LLMResponse:
        quick_started.set()
        release_quick.wait(timeout=3)
        return LLMResponse(content="quick")

    def deep_chat(_messages: object, **_kwargs: object) -> LLMResponse:
        deep_started.set()
        return LLMResponse(content="deep")

    quick = MagicMock()
    quick.chat.side_effect = quick_chat
    deep = MagicMock()
    deep.chat.side_effect = deep_chat
    roles = [
        AgentRole("Quick", AgentRoleType.TECHNICAL, "quick", role_id="quick"),
        AgentRole("Deep", AgentRoleType.RISK_MANAGER, "deep", role_id="deep", model_tier="deep"),
    ]
    team = AgentTeam(quick, deep_llm_client=deep, agents=roles)

    execution = asyncio.create_task(
        team.analyse_async("NIFTY", "NSE_INDEX", mode="flat", max_concurrent=2)
    )
    assert await asyncio.to_thread(quick_started.wait, 1)
    deep_was_concurrent = await asyncio.to_thread(deep_started.wait, 0.3)
    release_quick.set()
    await execution

    assert deep_was_concurrent


@pytest.mark.asyncio
async def test_timed_out_aggregator_cannot_mutate_returned_consensus_later() -> None:
    release_aggregator = threading.Event()
    aggregator_finished = threading.Event()
    quick = _llm("Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.3\nSUMMARY: Mixed.")
    deep = MagicMock()

    def delayed_aggregate(_messages: object, **_kwargs: object) -> LLMResponse:
        release_aggregator.wait(timeout=4)
        aggregator_finished.set()
        return LLMResponse(content="DECISION: BUY\nCONFIDENCE: 0.99\nREASONING: Late mutation.")

    deep.chat.side_effect = delayed_aggregate
    team = AgentTeam(quick, deep_llm_client=deep, agents=[AgentRole("Only", AgentRoleType.TECHNICAL, "only")])

    result = await team.analyse_async(
        "NIFTY",
        "NSE_INDEX",
        mode="flat",
        task_timeout_seconds=1,
    )
    snapshot = (result.consensus_signal, result.consensus_confidence, result.consensus_reasoning, list(result.errors))
    release_aggregator.set()
    assert await asyncio.to_thread(aggregator_finished.wait, 1)
    await asyncio.sleep(0.05)

    assert (result.consensus_signal, result.consensus_confidence, result.consensus_reasoning, result.errors) == snapshot


def test_public_run_tasks_uses_real_chat_contract() -> None:
    quick = _llm("macro result", "risk result")
    team = AgentTeam(quick)
    tasks = [
        TeamTask(id="macro", agent_role="macro", prompt="macro"),
        TeamTask(id="risk", agent_role="risk", prompt="use {macro}", depends_on=["macro"]),
    ]

    results = asyncio.run(team.run_tasks(tasks))

    assert results == {"macro": "macro result", "risk": "risk result"}
    assert quick.chat.call_args_list[1].args[0][-1].content == "use macro result"


def test_sequential_mode_maps_memory_chain_state_to_team_analysis() -> None:
    quick = _llm(
        "market report",
        "sentiment report",
        "BULL: earnings growth\nBEAR: rich valuation",
    )
    deep = _llm("DECISION: SELL\nCONFIDENCE: 0.7\nREASONING: Valuation dominates.")
    team = AgentTeam(quick, deep_llm_client=deep)

    result = team.analyse("TCS", "NSE", mode="sequential")

    assert result.mode is TeamMode.SEQUENTIAL
    assert [analysis.task_id for analysis in result.agent_analyses] == [
        "market",
        "sentiment",
        "fundamentals",
    ]
    assert result.consensus_signal == "SELL"
    assert result.consensus_confidence == pytest.approx(0.7)
    assert result.details["bull_thesis"] == "earnings growth"
    assert result.details["bear_thesis"] == "rich valuation"


def test_debate_mode_maps_rounds_transcript_and_verdict_to_team_analysis() -> None:
    quick = _llm("aggressive", "conservative", "neutral")
    deep = _llm("VERDICT: HOLD\nCONFIDENCE: 0.55\nREASONING: Risks balance upside.")
    team = AgentTeam(quick, deep_llm_client=deep)

    result = team.analyse(
        "BANKNIFTY",
        "NSE_INDEX",
        market_data={"trade_proposal": "BUY BANKNIFTY", "vix": 15},
        mode="debate",
        debate_rounds=1,
    )

    assert result.mode is TeamMode.DEBATE
    assert [analysis.task_id for analysis in result.agent_analyses] == [
        "aggressive",
        "conservative",
        "neutral",
    ]
    assert result.consensus_signal == "HOLD"
    assert result.consensus_confidence == pytest.approx(0.55)
    assert result.details["trade_proposal"] == "BUY BANKNIFTY"
    assert len(result.details["rounds"]) == 1
    assert "Aggressive" in result.details["full_transcript"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [TeamMode.SEQUENTIAL, TeamMode.DEBATE])
async def test_modes_apply_per_call_timeout_and_emit_persona_lifecycle(mode: TeamMode) -> None:
    release = threading.Event()
    events: list[TeamEvent] = []
    calls = 0
    lock = threading.Lock()

    def blocking_chat(_messages: object, **_kwargs: object) -> LLMResponse:
        nonlocal calls
        with lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            release.wait(timeout=4)
        return LLMResponse(content="VERDICT: HOLD\nCONFIDENCE: 0.2\nREASONING: Mixed.")

    quick = MagicMock()
    quick.chat.side_effect = blocking_chat
    team = AgentTeam(quick)
    started = time.monotonic()

    result = await team.analyse_async(
        "NIFTY",
        "NSE_INDEX",
        mode=mode,
        debate_rounds=1,
        task_timeout_seconds=1,
        on_event=events.append,
    )
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 2.5
    assert result.agent_analyses[0].error == "Agent analysis timed out"
    assert any(event.event_type == "started" and event.agent_role != "judge" for event in events)
    assert any(event.event_type == "timeout" and event.data == {"timeout_seconds": 1} for event in events)


def test_unsuccessful_mode_responses_map_to_failed_public_analyses() -> None:
    secret = "provider token=mode-secret"
    quick = MagicMock()
    quick.chat.side_effect = [
        LLMResponse(error=secret),
        LLMResponse(content="sentiment"),
        LLMResponse(content="BULL: upside\nBEAR: downside"),
    ]
    deep = MagicMock()
    deep.chat.return_value = LLMResponse(error=secret)

    sequential = AgentTeam(quick, deep_llm_client=deep).analyse("TCS", "NSE", mode="sequential")

    assert sequential.agent_analyses[0].error == "Agent analysis failed"
    assert sequential.consensus_signal == "HOLD"
    assert secret not in repr(sequential)


@pytest.mark.parametrize(
    ("kwargs", "error_type", "message"),
    [
        ({"mode": "unknown"}, ValueError, "mode"),
        ({"mode": "dag", "preset": "missing"}, KeyError, "Unknown swarm preset"),
        ({"mode": "debate", "debate_rounds": 0}, ValueError, "debate_rounds"),
    ],
)
def test_mode_input_validation_is_fail_fast(
    kwargs: dict[str, object],
    error_type: type[Exception],
    message: str,
) -> None:
    team = AgentTeam(_llm())

    with pytest.raises(error_type, match=message):
        team.analyse("NIFTY", "NSE_INDEX", **kwargs)
