"""Tests for AgentTeam — multi-agent trading team.

All tests mock LLMClient to avoid real LLM calls.
Arrange-Act-Assert structure throughout.
"""

from __future__ import annotations

from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_client(response_text: str = "LLM response") -> MagicMock:
    """Return a mock LLMClient whose chat() returns a successful LLMResponse."""
    from packages.ai.src.llm_client import LLMResponse

    client = MagicMock()
    client.chat.return_value = LLMResponse(content=response_text)
    return client


def _make_team(
    response_text: str = "Analysis report.\nSIGNAL: HOLD\nCONFIDENCE: 0.5\nSUMMARY: Mixed.",
    deep_response_text: str | None = None,
    agents=None,
):
    """Build an AgentTeam with mocked LLM clients."""
    from packages.ai.src.multi_agent import AgentTeam

    quick = _make_llm_client(response_text)
    deep = _make_llm_client(deep_response_text or "DECISION: HOLD\nCONFIDENCE: 0.5\nREASONING: Mixed signals.")
    return AgentTeam(llm_client=quick, deep_llm_client=deep, agents=agents), quick, deep


# ---------------------------------------------------------------------------
# AgentRole dataclass
# ---------------------------------------------------------------------------


class TestAgentRole:
    """Test AgentRole serialisation and construction."""

    def test_to_dict_includes_all_fields(self) -> None:
        from packages.ai.src.agent_models import AgentRole, AgentRoleType

        role = AgentRole(
            name="Test Agent",
            role_type=AgentRoleType.TECHNICAL,
            system_prompt="You are a test agent.",
            enabled=True,
            temperature=0.5,
        )
        d = role.to_dict()
        assert d["name"] == "Test Agent"
        assert d["role_type"] == "technical"
        assert d["system_prompt"] == "You are a test agent."
        assert d["enabled"] is True
        assert d["temperature"] == 0.5

    def test_from_dict_roundtrip(self) -> None:
        from packages.ai.src.agent_models import AgentRole, AgentRoleType

        original = AgentRole(
            name="Sentiment Analyst",
            role_type=AgentRoleType.SENTIMENT,
            system_prompt="Analyse sentiment.",
            enabled=False,
            temperature=0.3,
        )
        restored = AgentRole.from_dict(original.to_dict())
        assert restored.name == original.name
        assert restored.role_type == original.role_type
        assert restored.enabled == original.enabled
        assert restored.temperature == original.temperature


# ---------------------------------------------------------------------------
# AgentAnalysis dataclass
# ---------------------------------------------------------------------------


class TestAgentAnalysis:
    """Test AgentAnalysis defaults and serialisation."""

    def test_defaults(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis

        a = AgentAnalysis(agent_name="Test", role_type="technical")
        assert a.signal == "HOLD"
        assert a.confidence == 0.0
        assert a.error == ""
        assert a.success is False  # no report

    def test_success_property(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis

        a = AgentAnalysis(agent_name="Test", role_type="technical", report="Report text.")
        assert a.success is True

    def test_success_false_on_error(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis

        a = AgentAnalysis(agent_name="Test", role_type="technical", report="Report.", error="timeout")
        assert a.success is False


# ---------------------------------------------------------------------------
# TradeRecommendation
# ---------------------------------------------------------------------------


class TestTradeRecommendation:
    """Test TradeRecommendation construction from TeamAnalysis."""

    def test_from_team_analysis_counts_signals(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis, TeamAnalysis, TradeRecommendation

        ta = TeamAnalysis(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            agent_analyses=[
                AgentAnalysis(agent_name="A", role_type="technical", report="r", signal="BUY", confidence=0.8),
                AgentAnalysis(agent_name="B", role_type="sentiment", report="r", signal="BUY", confidence=0.7),
                AgentAnalysis(agent_name="C", role_type="fundamental", report="r", signal="SELL", confidence=0.6),
            ],
            consensus_signal="BUY",
            consensus_confidence=0.75,
            consensus_reasoning="Majority bullish.",
        )
        rec = TradeRecommendation.from_team_analysis(ta)
        assert rec.action == "BUY"
        assert rec.bullish_count == 2
        assert rec.bearish_count == 1
        assert rec.neutral_count == 0
        assert rec.agent_count == 3


# ---------------------------------------------------------------------------
# AgentTeam — default construction
# ---------------------------------------------------------------------------


class TestAgentTeamInit:
    """Test AgentTeam constructor and default roster."""

    def test_default_agents_count(self) -> None:
        team, _, _ = _make_team()
        assert len(team.agents) == 4

    def test_default_agent_names(self) -> None:
        team, _, _ = _make_team()
        names = {a.name for a in team.agents}
        assert "Technical Analyst" in names
        assert "Fundamental Analyst" in names
        assert "Sentiment Analyst" in names
        assert "Risk Manager" in names

    def test_enabled_agents_excludes_disabled(self) -> None:
        team, _, _ = _make_team()
        team.set_agent_enabled("Risk Manager", False)
        enabled_names = {a.name for a in team.enabled_agents}
        assert "Risk Manager" not in enabled_names
        assert len(team.enabled_agents) == 3


# ---------------------------------------------------------------------------
# AgentTeam — configuration
# ---------------------------------------------------------------------------


class TestAgentTeamConfig:
    """Test add/remove/enable/disable agents."""

    def test_add_agent(self) -> None:
        from packages.ai.src.agent_models import AgentRole, AgentRoleType

        team, _, _ = _make_team()
        new_agent = AgentRole(
            name="Custom Agent",
            role_type=AgentRoleType.AGGREGATOR,
            system_prompt="Custom.",
        )
        team.add_agent(new_agent)
        assert len(team.agents) == 5

    def test_remove_agent(self) -> None:
        team, _, _ = _make_team()
        removed = team.remove_agent("Technical Analyst")
        assert removed is True
        assert len(team.agents) == 3

    def test_remove_nonexistent_returns_false(self) -> None:
        team, _, _ = _make_team()
        removed = team.remove_agent("Nonexistent")
        assert removed is False

    def test_get_config_serialisable(self) -> None:
        team, _, _ = _make_team()
        config = team.get_config()
        assert "agents" in config
        assert len(config["agents"]) == 4
        assert all(isinstance(a, dict) for a in config["agents"])

    def test_update_config_replaces_roster(self) -> None:
        team, _, _ = _make_team()
        team.update_config({
            "agents": [
                {"name": "Only Agent", "role_type": "technical", "system_prompt": "Test."},
            ],
        })
        assert len(team.agents) == 1
        assert team.agents[0].name == "Only Agent"


# ---------------------------------------------------------------------------
# AgentTeam.analyze — full pipeline
# ---------------------------------------------------------------------------


class TestAgentTeamAnalyze:
    """Test the full team analysis pipeline."""

    def test_analyze_returns_team_analysis(self) -> None:
        from packages.ai.src.agent_models import TeamAnalysis

        team, _, _ = _make_team()
        result = team.analyse("NIFTY", "NSE_INDEX")
        assert isinstance(result, TeamAnalysis)
        assert result.symbol == "NIFTY"
        assert result.exchange == "NSE_INDEX"

    def test_analyze_produces_agent_analyses(self) -> None:
        team, _, _ = _make_team()
        result = team.analyse("RELIANCE", "NSE")
        # 4 default agents should each produce an analysis
        assert len(result.agent_analyses) == 4

    def test_analyze_consensus_set(self) -> None:
        agg_response = "DECISION: BUY\nCONFIDENCE: 0.85\nREASONING: Strong technical and sentiment alignment."
        team, _, _ = _make_team(deep_response_text=agg_response)
        result = team.analyse("NIFTY", "NSE_INDEX")
        assert result.consensus_signal == "BUY"
        assert result.consensus_confidence == 0.85
        assert "Strong technical" in result.consensus_reasoning

    def test_analyze_with_no_enabled_agents(self) -> None:
        team, _, _ = _make_team()
        for agent in team.agents:
            agent.enabled = False
        result = team.analyse("NIFTY", "NSE_INDEX")
        assert result.consensus_signal == "HOLD"
        assert "No enabled agents" in result.errors[0]

    def test_analyze_agent_error_captured(self) -> None:
        from packages.ai.src.llm_client import LLMResponse

        quick = MagicMock()
        # First agent fails, rest succeed, aggregator succeeds
        quick.chat.side_effect = [
            RuntimeError("LLM timeout"),
            LLMResponse(content="Report.\nSIGNAL: BUY\nCONFIDENCE: 0.7\nSUMMARY: Up."),
            LLMResponse(content="Report.\nSIGNAL: BUY\nCONFIDENCE: 0.8\nSUMMARY: Up."),
            LLMResponse(content="Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.5\nSUMMARY: Ok."),
        ]
        deep = _make_llm_client("DECISION: BUY\nCONFIDENCE: 0.7\nREASONING: Most agents bullish.")

        from packages.ai.src.multi_agent import AgentTeam
        team = AgentTeam(llm_client=quick, deep_llm_client=deep)
        result = team.analyse("NIFTY", "NSE_INDEX")

        # One error from the failed agent
        assert len(result.errors) >= 1
        assert "Technical Analyst" in result.errors[0]
        # Pipeline still produced a consensus
        assert result.consensus_signal in ("BUY", "SELL", "HOLD")

    def test_get_recommendation_from_analysis(self) -> None:
        agg_response = "DECISION: SELL\nCONFIDENCE: 0.6\nREASONING: Bearish across the board."
        team, _, _ = _make_team(deep_response_text=agg_response)
        result = team.analyse("BANKNIFTY", "NSE_INDEX")
        rec = team.get_recommendation(result)
        assert rec.action == "SELL"
        assert rec.confidence == 0.6
        assert rec.symbol == "BANKNIFTY"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


class TestParsingHelpers:
    """Test the response parsing methods."""

    def test_parse_agent_response_structured(self) -> None:
        from packages.ai.src.multi_agent import AgentTeam

        response = "NIFTY is in an uptrend.\nSIGNAL: BUY\nCONFIDENCE: 0.85\nSUMMARY: Bullish."
        signal, confidence, report = AgentTeam._parse_agent_response(response)
        assert signal == "BUY"
        assert confidence == 0.85
        assert "uptrend" in report

    def test_parse_agent_response_malformed(self) -> None:
        from packages.ai.src.multi_agent import AgentTeam

        response = "I cannot analyse this symbol."
        signal, confidence, report = AgentTeam._parse_agent_response(response)
        assert signal == "HOLD"
        assert confidence == 0.0
        assert report == response

    def test_parse_aggregator_response_structured(self) -> None:
        from packages.ai.src.multi_agent import AgentTeam

        response = "DECISION: SELL\nCONFIDENCE: 0.72\nREASONING: Bearish breakdown confirmed."
        decision, confidence, reasoning = AgentTeam._parse_aggregator_response(response)
        assert decision == "SELL"
        assert confidence == 0.72
        assert "Bearish breakdown" in reasoning

    def test_parse_aggregator_confidence_clamped(self) -> None:
        from packages.ai.src.multi_agent import AgentTeam

        response = "DECISION: BUY\nCONFIDENCE: 1.5\nREASONING: Very confident."
        _, confidence, _ = AgentTeam._parse_aggregator_response(response)
        assert confidence == 1.0


# ---------------------------------------------------------------------------
# Majority vote fallback
# ---------------------------------------------------------------------------


class TestMajorityVoteFallback:
    """Test the fallback mechanism when aggregator LLM fails."""

    def test_majority_vote_picks_winner(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis, TeamAnalysis
        from packages.ai.src.multi_agent import AgentTeam

        result = TeamAnalysis(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            agent_analyses=[
                AgentAnalysis(agent_name="A", role_type="technical", report="r", signal="BUY", confidence=0.8),
                AgentAnalysis(agent_name="B", role_type="sentiment", report="r", signal="BUY", confidence=0.7),
                AgentAnalysis(agent_name="C", role_type="risk_manager", report="r", signal="SELL", confidence=0.6),
            ],
        )
        team, _, _ = _make_team()
        team._majority_vote_fallback(result)
        assert result.consensus_signal == "BUY"
        assert result.consensus_confidence > 0.5
        assert "2 BUY" in result.consensus_reasoning

    def test_majority_vote_no_successful_analyses(self) -> None:
        from packages.ai.src.agent_models import AgentAnalysis, TeamAnalysis
        from packages.ai.src.multi_agent import AgentTeam

        result = TeamAnalysis(
            symbol="NIFTY",
            exchange="NSE_INDEX",
            agent_analyses=[
                AgentAnalysis(agent_name="A", role_type="technical", error="failed"),
            ],
        )
        team, _, _ = _make_team()
        team._majority_vote_fallback(result)
        assert result.consensus_signal == "HOLD"
        assert result.consensus_confidence == 0.0


# ---------------------------------------------------------------------------
# AutonomousResearchLoop (absorbed from MarketCalls/autoresearch)
# ---------------------------------------------------------------------------


class TestResearchIteration:
    """Test ResearchIteration dataclass."""

    def test_default_values(self) -> None:
        from packages.ai.src.multi_agent import ResearchIteration
        it = ResearchIteration(iteration=0, symbol="NIFTY", exchange="NSE_INDEX")
        assert it.signal == "HOLD"
        assert it.confidence == 0.0
        assert it.status == "pending"

    def test_to_dict(self) -> None:
        from packages.ai.src.multi_agent import ResearchIteration
        it = ResearchIteration(
            iteration=1, symbol="RELIANCE", exchange="NSE",
            signal="BUY", confidence=0.8, status="completed",
        )
        d = it.to_dict()
        assert d["symbol"] == "RELIANCE"
        assert d["signal"] == "BUY"
        assert d["iteration"] == 1


class TestAutonomousResearchLoop:
    """Test the autonomous research loop pattern from autoresearch."""

    def test_basic_loop_runs_all_iterations(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop
        team, _, _ = _make_team(
            response_text="Report.\nSIGNAL: BUY\nCONFIDENCE: 0.7\nSUMMARY: Bullish.",
            deep_response_text="DECISION: BUY\nCONFIDENCE: 0.7\nREASONING: Strong technicals.",
        )
        loop = AutonomousResearchLoop(team, max_iterations=3)
        results = loop.run_sync([("NIFTY", "NSE_INDEX")])
        # 3 iterations x 1 symbol = 3 results
        assert len(results) == 3
        for r in results:
            assert r.status == "completed"
            assert r.symbol == "NIFTY"

    def test_loop_with_multiple_symbols(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop
        team, _, _ = _make_team(
            response_text="Report.\nSIGNAL: HOLD\nCONFIDENCE: 0.5\nSUMMARY: Neutral.",
            deep_response_text="DECISION: HOLD\nCONFIDENCE: 0.5\nREASONING: Mixed signals.",
        )
        loop = AutonomousResearchLoop(team, max_iterations=2)
        results = loop.run_sync([("NIFTY", "NSE_INDEX"), ("RELIANCE", "NSE")])
        # 2 iterations x 2 symbols = 4 results
        assert len(results) == 4
        symbols = {r.symbol for r in results}
        assert symbols == {"NIFTY", "RELIANCE"}

    def test_loop_stop(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop
        team, _, _ = _make_team(
            response_text="Report.\nSIGNAL: SELL\nCONFIDENCE: 0.6\nSUMMARY: Bearish.",
            deep_response_text="DECISION: SELL\nCONFIDENCE: 0.6\nREASONING: Weak.",
        )

        iterations_completed = []

        def on_iter(record):
            iterations_completed.append(record)
            if len(iterations_completed) >= 2:
                loop.stop()

        loop = AutonomousResearchLoop(team, max_iterations=100, on_iteration=on_iter)
        results = loop.run_sync([("NIFTY", "NSE_INDEX")])
        # Should stop after 2 iterations (stop takes effect after current symbol completes)
        assert len(results) <= 3

    def test_signal_summary(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop
        team, _, _ = _make_team(
            response_text="Report.\nSIGNAL: BUY\nCONFIDENCE: 0.8\nSUMMARY: Strong.",
            deep_response_text="DECISION: BUY\nCONFIDENCE: 0.8\nREASONING: Consensus.",
        )
        loop = AutonomousResearchLoop(team, max_iterations=3)
        loop.run_sync([("NIFTY", "NSE_INDEX")])
        summary = loop.get_signal_summary()
        assert "NIFTY" in summary
        assert summary["NIFTY"]["dominant_signal"] == "BUY"
        assert summary["NIFTY"]["iterations"] == 3
        assert summary["NIFTY"]["avg_confidence"] > 0

    def test_loop_handles_failures_gracefully(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop, AgentTeam
        # Create a team with a broken LLM
        client = MagicMock()
        client.chat.side_effect = Exception("LLM unavailable")
        team = AgentTeam(llm_client=client)
        loop = AutonomousResearchLoop(team, max_iterations=2)
        results = loop.run_sync([("NIFTY", "NSE_INDEX")])
        # Should complete without crashing
        assert len(results) == 2
        # Aggregator fails -> majority vote fallback (all agents failed -> HOLD)
        for r in results:
            assert r.status == "completed"

    def test_empty_watchlist(self) -> None:
        from packages.ai.src.multi_agent import AutonomousResearchLoop
        team, _, _ = _make_team()
        loop = AutonomousResearchLoop(team, max_iterations=3)
        results = loop.run_sync([])
        assert len(results) == 0
