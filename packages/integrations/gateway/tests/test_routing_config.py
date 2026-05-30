"""T2 (gap G1): RoutingConfig parse + validation from workspace.json.brokers.

Encodes the ratified broker-adapter-contract §13 shape: ExecutionRouting
(default + by_segment), DataRouting (ticks/historical/option_chains/quote/
global_indices), FailoverConfig, CostAwareConfig, account_acls, and the
segment-aware ``resolve(task, payload)`` resolver. Every selector is the
canonical composite ``'adapter_id:account_id'`` (identity X7) and MUST appear
in ``registered``; malformed configs raise ``RoutingConfigError`` at parse time.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_gateway.routing_config import (
    RoutingConfig,
    RoutingConfigError,
    RoutingHint,
)


def _valid_brokers() -> dict:
    return {
        "registered": ["openalgo:default", "dhan:personal", "upstox:personal"],
        "account_acls": {
            "dhan": {"personal": ["nava@flinttrade.local"]},
            "upstox": {"personal": ["nava@flinttrade.local"]},
            "openalgo": {"default": ["nava@flinttrade.local"]},
        },
        "execution": {
            "default": "openalgo:default",
            "F&O": "dhan:personal",
            "iceberg": "dhan:personal",
        },
        "data": {
            "ticks": "dhan:personal",
            "historical": "upstox:personal",
            "option_chains": "dhan:personal",
            "quote": "dhan:personal",
            "global_indices": "upstox:personal",
        },
        "failover": {
            "enabled": True,
            "order": ["dhan:personal", "upstox:personal", "openalgo:default"],
        },
        "cost_aware": {"enabled": False, "tasks": []},
    }


# --- parsing -------------------------------------------------------------


def test_from_workspace_parses_canonical_shape() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    assert cfg.execution.default == "openalgo:default"
    assert cfg.execution.by_segment["F&O"] == "dhan:personal"
    assert cfg.data.ticks == "dhan:personal"
    assert cfg.data.quote == "dhan:personal"
    assert cfg.data.global_indices == "upstox:personal"
    assert cfg.failover.enabled is True
    assert cfg.failover.order == ("dhan:personal", "upstox:personal", "openalgo:default")
    assert cfg.account_acls["dhan"]["personal"] == ["nava@flinttrade.local"]


def test_quote_falls_back_to_option_chains_when_absent() -> None:
    brokers = _valid_brokers()
    del brokers["data"]["quote"]
    cfg = RoutingConfig.from_workspace(brokers)
    assert cfg.data.quote == cfg.data.option_chains == "dhan:personal"


# --- resolution ----------------------------------------------------------


def test_resolve_execution_default() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    assert cfg.resolve("execution", None) == "openalgo:default"


def test_resolve_execution_segment_override_for_fno() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    order = SimpleNamespace(exchange="NFO")
    assert cfg.resolve("execution", order) == "dhan:personal"


def test_resolve_execution_no_override_for_equity() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    order = SimpleNamespace(exchange="NSE")
    assert cfg.resolve("execution", order) == "openalgo:default"


def test_resolve_data_tasks() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    assert cfg.resolve("data.ticks") == "dhan:personal"
    assert cfg.resolve("data.historical") == "upstox:personal"
    assert cfg.resolve("data.quote") == "dhan:personal"


def test_resolve_global_indices_falls_back_to_execution_default() -> None:
    brokers = _valid_brokers()
    brokers["data"]["global_indices"] = ""
    cfg = RoutingConfig.from_workspace(brokers)
    assert cfg.resolve("data.global_indices") == "openalgo:default"


def test_resolve_unknown_task_returns_none() -> None:
    cfg = RoutingConfig.from_workspace(_valid_brokers())
    assert cfg.resolve("data.bogus") is None


# --- validation ----------------------------------------------------------


def test_non_colon_selector_raises() -> None:
    brokers = _valid_brokers()
    brokers["execution"]["default"] = "dhan"  # no colon
    with pytest.raises(RoutingConfigError, match="invalid routing selector"):
        RoutingConfig.from_workspace(brokers)


def test_selector_not_in_registered_raises() -> None:
    brokers = _valid_brokers()
    brokers["execution"]["default"] = "kotakneo:x"  # parses, but not registered
    with pytest.raises(RoutingConfigError, match="not in brokers.registered"):
        RoutingConfig.from_workspace(brokers)


def test_missing_required_data_key_raises() -> None:
    brokers = _valid_brokers()
    del brokers["data"]["ticks"]
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(brokers)


def test_missing_execution_default_raises() -> None:
    brokers = _valid_brokers()
    del brokers["execution"]["default"]
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(brokers)


def test_cost_aware_tasks_not_subset_raises() -> None:
    brokers = _valid_brokers()
    brokers["cost_aware"] = {"enabled": True, "tasks": ["execution", "totally.bogus"]}
    with pytest.raises(RoutingConfigError, match="cost_aware"):
        RoutingConfig.from_workspace(brokers)


def test_unauthorised_account_warns_not_raises() -> None:
    # account_acls coverage is a WARNING per §13.3, not a hard error: operators
    # stage accounts before authorising actors.
    brokers = _valid_brokers()
    brokers["account_acls"] = {}  # nothing authorised yet
    cfg = RoutingConfig.from_workspace(brokers)  # must NOT raise
    assert cfg.execution.default == "openalgo:default"


# --- defaults round-trip + RoutingHint -----------------------------------


def test_default_workspace_config_round_trips() -> None:
    brokers = default_workspace_config()["brokers"]
    cfg = RoutingConfig.from_workspace(brokers)
    assert cfg.execution.default == "openalgo:default"
    assert cfg.resolve("data.ticks") == "openalgo:default"


def test_routing_hint_defaults() -> None:
    hint = RoutingHint()
    assert hint.adapter_id == ""
    assert hint.account_id == ""
    assert hint.skip_failover is False
