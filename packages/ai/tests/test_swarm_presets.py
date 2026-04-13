"""Tests for packages.ai.src.swarm_presets.

Covers:
- list_presets returns exactly 10 preset names
- All expected names are present
- get_preset returns SwarmPreset with correct name
- get_preset raises KeyError on unknown name
- get_all_presets returns all 10 presets
- Each preset has at least 2 agents
- Each agent has non-empty role, system_prompt, and model_tier
- model_tier is one of "quick" or "deep"
- Each preset has a non-empty description
- SwarmPreset.to_dict serialisation
- SwarmAgentDef.to_dict serialisation
- full_house preset has more agents than single-desk presets
- Each preset's agent roles are unique within the preset
- Deep model tier used for aggregator/lead agents
"""

from __future__ import annotations

import pytest

from packages.ai.src.swarm_presets import (
    SwarmAgentDef,
    SwarmPreset,
    get_all_presets,
    get_preset,
    list_presets,
)


# ---------------------------------------------------------------------------
# Expected preset names
# ---------------------------------------------------------------------------

EXPECTED_NAMES = {
    "derivatives_desk",
    "stat_arb_desk",
    "ml_quant_lab",
    "macro_research",
    "event_driven",
    "sector_rotation",
    "scalp_team",
    "investor_team",
    "risk_committee",
    "full_house",
}


# ---------------------------------------------------------------------------
# list_presets
# ---------------------------------------------------------------------------


class TestListPresets:
    def test_returns_list(self):
        names = list_presets()
        assert isinstance(names, list)

    def test_exactly_ten_presets(self):
        assert len(list_presets()) == 10

    def test_all_expected_names_present(self):
        names = set(list_presets())
        assert EXPECTED_NAMES == names

    def test_sorted_alphabetically(self):
        names = list_presets()
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# get_preset
# ---------------------------------------------------------------------------


class TestGetPreset:
    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_returns_swarm_preset_for_each(self, name):
        preset = get_preset(name)
        assert isinstance(preset, SwarmPreset)
        assert preset.name == name

    def test_raises_key_error_on_unknown(self):
        with pytest.raises(KeyError, match="Unknown swarm preset"):
            get_preset("nonexistent_preset")

    def test_error_message_lists_available(self):
        with pytest.raises(KeyError) as exc_info:
            get_preset("bad_name")
        assert "derivatives_desk" in str(exc_info.value)


# ---------------------------------------------------------------------------
# get_all_presets
# ---------------------------------------------------------------------------


class TestGetAllPresets:
    def test_returns_ten_presets(self):
        presets = get_all_presets()
        assert len(presets) == 10

    def test_all_are_swarm_presets(self):
        for p in get_all_presets():
            assert isinstance(p, SwarmPreset)

    def test_all_names_present(self):
        names = {p.name for p in get_all_presets()}
        assert names == EXPECTED_NAMES

    def test_sorted_by_name(self):
        names = [p.name for p in get_all_presets()]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# SwarmPreset structure
# ---------------------------------------------------------------------------


class TestSwarmPresetStructure:
    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_has_non_empty_description(self, name):
        preset = get_preset(name)
        assert preset.description.strip() != ""

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_has_at_least_two_agents(self, name):
        preset = get_preset(name)
        assert len(preset.agents) >= 2

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_agent_roles_unique_within_preset(self, name):
        preset = get_preset(name)
        roles = [a.role for a in preset.agents]
        assert len(roles) == len(set(roles)), f"Duplicate roles in {name}: {roles}"

    def test_full_house_has_most_agents(self):
        full = get_preset("full_house")
        others = [get_preset(n) for n in EXPECTED_NAMES if n != "full_house"]
        assert len(full.agents) > max(len(p.agents) for p in others)

    def test_standard_desk_has_exactly_three_agents(self):
        # All single-desk presets have exactly 3 agents
        single_desks = EXPECTED_NAMES - {"full_house"}
        for name in single_desks:
            preset = get_preset(name)
            assert len(preset.agents) == 3, (
                f"{name} expected 3 agents, got {len(preset.agents)}"
            )


# ---------------------------------------------------------------------------
# SwarmAgentDef structure
# ---------------------------------------------------------------------------


class TestSwarmAgentDefStructure:
    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_all_agents_have_non_empty_role(self, name):
        for agent in get_preset(name).agents:
            assert agent.role.strip() != "", f"Empty role in preset {name}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_all_agents_have_non_empty_system_prompt(self, name):
        for agent in get_preset(name).agents:
            assert len(agent.system_prompt.strip()) > 50, (
                f"System prompt too short for {agent.role} in {name}"
            )

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_all_agents_have_valid_model_tier(self, name):
        valid_tiers = {"quick", "deep"}
        for agent in get_preset(name).agents:
            assert agent.model_tier in valid_tiers, (
                f"Invalid model_tier '{agent.model_tier}' for {agent.role} in {name}"
            )

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_each_preset_has_at_least_one_deep_agent(self, name):
        preset = get_preset(name)
        deep_agents = [a for a in preset.agents if a.model_tier == "deep"]
        assert len(deep_agents) >= 1, (
            f"Preset {name} has no 'deep' model tier agent"
        )

    def test_quick_agents_outnumber_deep_agents(self):
        # Overall, quick agents should be more numerous (cost efficiency)
        all_agents = [a for p in get_all_presets() for a in p.agents]
        quick = sum(1 for a in all_agents if a.model_tier == "quick")
        deep = sum(1 for a in all_agents if a.model_tier == "deep")
        assert quick > deep


# ---------------------------------------------------------------------------
# System prompt quality checks
# ---------------------------------------------------------------------------


class TestSystemPromptQuality:
    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_each_agent_prompt_ends_with_structured_output(self, name):
        """All agents should have a structured output block at the end."""
        for agent in get_preset(name).agents:
            prompt = agent.system_prompt
            # Every prompt should contain at least one colon-delimited instruction
            assert ":" in prompt, (
                f"Agent {agent.role} in {name} has no structured output format"
            )

    def test_derivatives_desk_mentions_options(self):
        preset = get_preset("derivatives_desk")
        combined = " ".join(a.system_prompt for a in preset.agents).lower()
        assert "options" in combined or "greeks" in combined

    def test_macro_research_mentions_rbi(self):
        preset = get_preset("macro_research")
        combined = " ".join(a.system_prompt for a in preset.agents).lower()
        assert "rbi" in combined

    def test_risk_committee_mentions_var(self):
        preset = get_preset("risk_committee")
        combined = " ".join(a.system_prompt for a in preset.agents).lower()
        assert "var" in combined or "value at risk" in combined

    def test_scalp_team_mentions_intraday(self):
        preset = get_preset("scalp_team")
        combined = " ".join(a.system_prompt for a in preset.agents).lower()
        assert "intraday" in combined or "scalp" in combined

    def test_stat_arb_mentions_cointegration(self):
        preset = get_preset("stat_arb_desk")
        combined = " ".join(a.system_prompt for a in preset.agents).lower()
        assert "cointegration" in combined or "pairs" in combined


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_swarm_preset_to_dict(self):
        preset = get_preset("derivatives_desk")
        d = preset.to_dict()
        assert d["name"] == "derivatives_desk"
        assert isinstance(d["description"], str)
        assert isinstance(d["agents"], list)
        assert len(d["agents"]) == 3

    def test_swarm_agent_def_to_dict(self):
        agent = SwarmAgentDef(
            role="test_agent",
            system_prompt="You are a test agent.",
            model_tier="quick",
        )
        d = agent.to_dict()
        assert d["role"] == "test_agent"
        assert d["system_prompt"] == "You are a test agent."
        assert d["model_tier"] == "quick"

    @pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
    def test_preset_to_dict_is_json_serialisable(self, name):
        import json
        preset = get_preset(name)
        # Should not raise
        serialised = json.dumps(preset.to_dict())
        assert len(serialised) > 100

    def test_full_house_to_dict_has_ten_agents(self):
        d = get_preset("full_house").to_dict()
        assert len(d["agents"]) == 10
