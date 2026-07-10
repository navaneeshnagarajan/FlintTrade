"""Contract tests for the canonical team preset catalogue."""

from __future__ import annotations

import pytest

from flinttrade_ai._team_presets import (
    TeamPreset,
    TeamPresetAgent,
    get_all_presets,
    get_preset,
    list_presets,
)
from flinttrade_ai.agent_models import AgentRoleType
from flinttrade_ai.swarm_presets import get_all_presets as get_all_swarm_presets
from flinttrade_ai.swarm_presets import get_preset as get_swarm_preset


EXPECTED_CATALOGUE = {
    "derivatives_desk": (
        ("options_analyst", "quick", AgentRoleType.TECHNICAL),
        ("greeks_monitor", "quick", AgentRoleType.RISK_MANAGER),
        ("risk_manager", "deep", AgentRoleType.RISK_MANAGER),
    ),
    "event_driven": (
        ("earnings_analyst", "quick", AgentRoleType.FUNDAMENTAL),
        ("news_scanner", "quick", AgentRoleType.SENTIMENT),
        ("sentiment_scorer", "deep", AgentRoleType.AGGREGATOR),
    ),
    "full_house": (
        ("derivatives_lead", "quick", AgentRoleType.TECHNICAL),
        ("stat_arb_lead", "quick", AgentRoleType.TECHNICAL),
        ("ml_quant_lead", "quick", AgentRoleType.TECHNICAL),
        ("macro_lead", "quick", AgentRoleType.FUNDAMENTAL),
        ("event_lead", "quick", AgentRoleType.SENTIMENT),
        ("sector_rotation_lead", "quick", AgentRoleType.TECHNICAL),
        ("scalp_lead", "quick", AgentRoleType.TECHNICAL),
        ("portfolio_research_lead", "quick", AgentRoleType.FUNDAMENTAL),
        ("risk_committee_lead", "quick", AgentRoleType.RISK_MANAGER),
        ("chief_investment_officer", "deep", AgentRoleType.AGGREGATOR),
    ),
    "investor_team": (
        ("fundamental_analyst", "quick", AgentRoleType.FUNDAMENTAL),
        ("valuation_model", "quick", AgentRoleType.FUNDAMENTAL),
        ("portfolio_optimizer", "deep", AgentRoleType.AGGREGATOR),
    ),
    "macro_research": (
        ("macro_analyst", "quick", AgentRoleType.FUNDAMENTAL),
        ("rates_analyst", "quick", AgentRoleType.FUNDAMENTAL),
        ("fx_analyst", "deep", AgentRoleType.AGGREGATOR),
    ),
    "ml_quant_lab": (
        ("feature_engineer", "quick", AgentRoleType.TECHNICAL),
        ("model_trainer", "quick", AgentRoleType.TECHNICAL),
        ("signal_generator", "deep", AgentRoleType.AGGREGATOR),
    ),
    "risk_committee": (
        ("var_calculator", "quick", AgentRoleType.RISK_MANAGER),
        ("stress_tester", "quick", AgentRoleType.RISK_MANAGER),
        ("order_safety_checker", "deep", AgentRoleType.RISK_MANAGER),
    ),
    "scalp_team": (
        ("tape_reader", "quick", AgentRoleType.TECHNICAL),
        ("level2_analyst", "quick", AgentRoleType.TECHNICAL),
        ("scalp_executor", "deep", AgentRoleType.AGGREGATOR),
    ),
    "sector_rotation": (
        ("sector_ranker", "quick", AgentRoleType.TECHNICAL),
        ("momentum_calculator", "quick", AgentRoleType.TECHNICAL),
        ("sector_rebalancer", "deep", AgentRoleType.AGGREGATOR),
    ),
    "stat_arb_desk": (
        ("pairs_researcher", "quick", AgentRoleType.TECHNICAL),
        ("cointegration_tester", "quick", AgentRoleType.TECHNICAL),
        ("stat_arb_executor", "deep", AgentRoleType.AGGREGATOR),
    ),
}

EXPECTED_DEEP_ROLES = {
    "derivatives_desk": "risk_manager",
    "event_driven": "sentiment_scorer",
    "full_house": "chief_investment_officer",
    "investor_team": "portfolio_optimizer",
    "macro_research": "fx_analyst",
    "ml_quant_lab": "signal_generator",
    "risk_committee": "order_safety_checker",
    "scalp_team": "scalp_executor",
    "sector_rotation": "sector_rebalancer",
    "stat_arb_desk": "stat_arb_executor",
}


def test_catalogue_is_an_exact_port_of_swarm_presets() -> None:
    canonical = [preset.to_dict() for preset in get_all_presets()]
    legacy = [preset.to_dict() for preset in get_all_swarm_presets()]

    assert canonical == legacy


def test_catalogue_has_exact_names_roles_counts_and_tiers() -> None:
    assert list_presets() == sorted(EXPECTED_CATALOGUE)
    assert sum(len(preset.agents) for preset in get_all_presets()) == 37

    for name, expected_agents in EXPECTED_CATALOGUE.items():
        actual = tuple((agent.role, agent.model_tier) for agent in get_preset(name).agents)
        expected = tuple((role, tier) for role, tier, _role_type in expected_agents)
        assert actual == expected


def test_registry_access_matches_swarm_preset_behaviour() -> None:
    presets = get_all_presets()

    assert [preset.name for preset in presets] == list_presets()
    assert all(preset is get_preset(preset.name) for preset in presets)

    with pytest.raises(KeyError) as canonical_error:
        get_preset("missing")
    with pytest.raises(KeyError) as swarm_error:
        get_swarm_preset("missing")

    assert canonical_error.value.args == swarm_error.value.args


def test_dataclasses_serialise_without_losing_defaults() -> None:
    agent = TeamPresetAgent(role="test_agent", system_prompt="Exact prompt")
    preset = TeamPreset(name="test_team", description="Test team", agents=[agent])

    assert agent.to_dict() == {
        "role": "test_agent",
        "system_prompt": "Exact prompt",
        "model_tier": "quick",
    }
    assert preset.to_dict() == {
        "name": "test_team",
        "description": "Test team",
        "agents": [agent.to_dict()],
    }


@pytest.mark.parametrize("name", sorted(EXPECTED_CATALOGUE))
def test_to_agent_roles_preserves_identity_prompt_tier_and_best_fit_type(name: str) -> None:
    preset = get_preset(name)
    converted = preset.to_agent_roles()

    assert len(converted) == len(preset.agents)
    for definition, role, expected in zip(preset.agents, converted, EXPECTED_CATALOGUE[name], strict=True):
        expected_slug, expected_tier, expected_type = expected
        assert role.name == expected_slug.replace("_", " ").title()
        assert role.role_id == expected_slug
        assert role.role_type == expected_type
        assert role.system_prompt == definition.system_prompt
        assert role.model_tier == expected_tier


def test_preset_and_agent_identifiers_are_unique() -> None:
    presets = get_all_presets()
    preset_names = [preset.name for preset in presets]
    all_role_ids = [agent.role for preset in presets for agent in preset.agents]

    assert len(preset_names) == len(set(preset_names))
    assert len(all_role_ids) == len(set(all_role_ids))


def test_each_preset_preserves_its_single_deep_tier() -> None:
    for preset in get_all_presets():
        deep_definitions = [agent.role for agent in preset.agents if agent.model_tier == "deep"]
        deep_roles = [role.role_id for role in preset.to_agent_roles() if role.model_tier == "deep"]

        assert deep_definitions == [EXPECTED_DEEP_ROLES[preset.name]]
        assert deep_roles == deep_definitions
