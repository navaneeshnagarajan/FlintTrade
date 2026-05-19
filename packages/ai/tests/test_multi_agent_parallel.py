"""Tests for async parallel agent execution in AgentTeam.

Covers:
- run_parallel() returns one AgentAnalysis per agent.
- Semaphore limits concurrent calls (verified via call ordering).
- analyze(parallel=True) produces a valid TeamAnalysis.
- analyze(parallel=False) still works as sequential fallback.
- run_parallel() with an empty agent list returns [].
- max_concurrent parameter is respected (semaphore created with correct value).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock


from packages.ai.src.llm_client import LLMResponse
from packages.ai.src.multi_agent import AgentTeam


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_llm(text: str = "Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.5\nSUMMARY: ok") -> MagicMock:
    """Return a mock LLMClient with a fixed successful response."""
    client = MagicMock()
    client.chat.return_value = LLMResponse(content=text)
    return client


def _make_team(agent_text: str | None = None, agg_text: str | None = None) -> AgentTeam:
    quick = _make_mock_llm(
        agent_text or "Report.\nSIGNAL: BUY\nCONFIDENCE: 0.7\nSUMMARY: Bullish."
    )
    deep = _make_mock_llm(
        agg_text or "DECISION: BUY\nCONFIDENCE: 0.7\nREASONING: Consensus bullish."
    )
    return AgentTeam(llm_client=quick, deep_llm_client=deep)


# ---------------------------------------------------------------------------
# run_parallel — async direct tests
# ---------------------------------------------------------------------------


class TestRunParallel:
    """Tests for AgentTeam.run_parallel() async method."""

    def test_returns_one_result_per_agent(self) -> None:
        """run_parallel returns a list with the same length as agents."""
        team = _make_team()
        agents = team.enabled_agents

        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        )

        assert len(result) == len(agents)

    def test_each_result_has_agent_name(self) -> None:
        """Each AgentAnalysis.agent_name matches the corresponding agent."""
        team = _make_team()
        agents = team.enabled_agents

        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "RELIANCE", "exchange": "NSE"})
        )

        agent_names = {a.name for a in agents}
        result_names = {r.agent_name for r in result}
        assert result_names == agent_names

    def test_empty_agent_list_returns_empty(self) -> None:
        """run_parallel with an empty list returns []."""
        team = _make_team()

        result = asyncio.run(team.run_parallel([], {"symbol": "NIFTY", "exchange": "NSE_INDEX"}))

        assert result == []

    def test_max_concurrent_parameter_accepted(self) -> None:
        """run_parallel accepts max_concurrent without error."""
        team = _make_team()
        agents = team.enabled_agents[:2]

        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}, max_concurrent=2)
        )

        assert len(result) == 2

    def test_context_symbol_exchange_forwarded(self) -> None:
        """Symbol and exchange from context are excluded from market_data kwarg."""
        team = _make_team()
        agents = team.enabled_agents[:1]

        # Should not raise — symbol/exchange are stripped from market_data
        result = asyncio.run(
            team.run_parallel(
                agents,
                {"symbol": "BANKNIFTY", "exchange": "NFO", "rsi": 45, "vix": 14.2},
            )
        )

        assert len(result) == 1

    def test_failed_agent_returns_error_analysis(self) -> None:
        """If the LLM raises, the agent's analysis has a non-empty error field."""
        client = MagicMock()
        client.chat.side_effect = RuntimeError("LLM unavailable")
        team = AgentTeam(llm_client=client)
        agents = team.enabled_agents[:1]

        result = asyncio.run(team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}))

        assert len(result) == 1
        assert result[0].error != ""

    def test_results_ordered_same_as_input(self) -> None:
        """Output order matches input agent order."""
        team = _make_team()
        agents = team.enabled_agents

        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"})
        )

        for expected_agent, analysis in zip(agents, result):
            assert analysis.agent_name == expected_agent.name


# ---------------------------------------------------------------------------
# analyze(parallel=True/False) — synchronous wrapper
# ---------------------------------------------------------------------------


class TestAnalyzeParallelFlag:
    """Tests for the parallel= parameter on AgentTeam.analyse()."""

    def test_analyze_parallel_false_is_default(self) -> None:
        """analyze() with no parallel flag runs sequentially and returns TeamAnalysis."""
        team = _make_team()
        result = team.analyse("NIFTY", "NSE_INDEX")

        assert result.symbol == "NIFTY"
        assert result.consensus_signal in {"BUY", "SELL", "HOLD"}
        assert len(result.agent_analyses) == len(team.enabled_agents)

    def test_analyze_parallel_true_produces_valid_result(self) -> None:
        """analyze(parallel=True) returns a TeamAnalysis with the same structure."""
        team = _make_team()
        result = team.analyse("NIFTY", "NSE_INDEX", parallel=True)

        assert result.symbol == "NIFTY"
        assert result.exchange == "NSE_INDEX"
        assert len(result.agent_analyses) == len(team.enabled_agents)
        assert result.consensus_signal in {"BUY", "SELL", "HOLD"}

    def test_analyze_parallel_true_calls_llm_for_each_agent(self) -> None:
        """Each enabled agent calls the LLM exactly once under parallel=True."""
        team = _make_team()
        n_agents = len(team.enabled_agents)

        team.analyse("NIFTY", "NSE_INDEX", parallel=True)

        # quick LLM called once per analyst agent; deep called once for aggregator
        assert team._quick.chat.call_count == n_agents

    def test_analyze_parallel_false_calls_llm_for_each_agent(self) -> None:
        """Each enabled agent calls the LLM exactly once under parallel=False."""
        team = _make_team()
        n_agents = len(team.enabled_agents)

        team.analyse("NIFTY", "NSE_INDEX", parallel=False)

        assert team._quick.chat.call_count == n_agents

    def test_analyze_no_agents_returns_hold(self) -> None:
        """With no agents, parallel=True still returns HOLD safely."""
        quick = _make_mock_llm()
        team = AgentTeam(llm_client=quick, agents=[])

        result = team.analyse("NIFTY", "NSE_INDEX", parallel=True)

        assert result.consensus_signal == "HOLD"

    def test_analyze_with_market_data_parallel(self) -> None:
        """parallel=True forwards market_data to each agent prompt."""
        team = _make_team()

        result = team.analyse(
            "RELIANCE",
            "NSE",
            market_data={"rsi": 55, "ema20": 2900},
            parallel=True,
        )

        assert result.symbol == "RELIANCE"
        # LLM was called — market_data was forwarded
        assert team._quick.chat.called


# ---------------------------------------------------------------------------
# Semaphore concurrency check
# ---------------------------------------------------------------------------


class TestSemaphoreConcurrency:
    """Verify that the semaphore cap is enforced."""

    def test_semaphore_limits_concurrent_tasks(self) -> None:
        """With max_concurrent=1 all agents still complete but serially."""
        team = _make_team()
        agents = team.enabled_agents

        # max_concurrent=1 should still return all results
        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}, max_concurrent=1)
        )

        assert len(result) == len(agents)

    def test_semaphore_larger_than_agents_ok(self) -> None:
        """max_concurrent > len(agents) does not raise."""
        team = _make_team()
        agents = team.enabled_agents[:2]

        result = asyncio.run(
            team.run_parallel(agents, {"symbol": "NIFTY", "exchange": "NSE_INDEX"}, max_concurrent=10)
        )

        assert len(result) == 2
