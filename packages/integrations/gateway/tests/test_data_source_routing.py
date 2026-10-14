"""Market/dataset selection stays separate from execution routing."""
from __future__ import annotations

import pytest

from flinttrade_gateway.routing_config import RoutingConfig, RoutingConfigError

pytestmark = pytest.mark.unit


def config():
    return {
        "registered": ["dhan:execution", "dhan:data"], "execution": {"default": "dhan:execution"},
        "data": {"ticks": "dhan:data", "historical": "dhan:data", "option_chains": "dhan:data"},
        "data_connections": ["us-history", "crypto-history", "fx-history"],
        "data_policies": [
            {"dataset": "history", "market": market, "venue": venue, "sources": [source], "priority": 10,
             "revision": "1", "coverage_start": "2026-01-01", "coverage_end": "2026-12-31",
             "mode": "single", "duplicates": "identical_only", "conflicts": "reject"}
            for market, venue, source in [("US", "XNAS", "us-history"), ("crypto", "test-venue", "crypto-history"),
                                          ("FX-spot", "test-fx", "fx-history")]
        ],
    }


def test_per_market_history_policy_never_retargets_execution():
    parsed = RoutingConfig.from_workspace(config())
    assert callable(getattr(parsed, "resolve_data", None)), "explicit dataset routing missing"
    for market, venue, expected in [("US", "XNAS", "us-history"), ("crypto", "test-venue", "crypto-history"),
                                     ("FX-spot", "test-fx", "fx-history")]:
        policy = parsed.resolve_data("history", market=market, venue=venue, start="2026-01-02", end="2026-01-03")
        assert policy["sources"] == [expected]
        assert parsed.resolve("execution") == "dhan:execution"
    with pytest.raises(RoutingConfigError):
        parsed.resolve_data("history", market="US", venue="XNYS", start="2026-01-02", end="2026-01-03")


def test_data_policy_ambiguity_unknown_sources_and_uncovered_period_refuse():
    raw = config()
    raw["data_policies"].append({**raw["data_policies"][0], "sources": ["fx-history"]})
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(raw)
    raw = config()
    raw["data_policies"][0]["sources"] = ["not-configured"]
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(raw)
    parsed = RoutingConfig.from_workspace(config())
    with pytest.raises(RoutingConfigError):
        parsed.resolve_data("history", market="US", venue="XNAS", start="2025-01-02", end="2026-01-03")
