"""T12 (gap G7) CI validator: RoutingConfig.from_workspace enforces the §13 schema.

A dedicated, named gate (run by CI alongside the supply-chain checks) that the
routing schema still rejects malformed configs and accepts the canonical shape —
so a future refactor cannot silently loosen validation.
"""

from __future__ import annotations

import pytest

from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_gateway.routing_config import RoutingConfig, RoutingConfigError


def _brokers() -> dict:
    return default_workspace_config()["brokers"]


def test_accepts_canonical_default() -> None:
    RoutingConfig.from_workspace(_brokers())  # must not raise


def test_rejects_non_colon_selector() -> None:
    bad = {**_brokers(), "execution": {"default": "openalgo"}}  # no colon
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(bad)


def test_rejects_missing_required_data_key() -> None:
    brokers = _brokers()
    data = {k: v for k, v in brokers["data"].items() if k != "historical"}
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace({**brokers, "data": data})


def test_rejects_unknown_cost_aware_task() -> None:
    bad = {**_brokers(), "cost_aware": {"enabled": True, "tasks": ["totally.bogus"]}}
    with pytest.raises(RoutingConfigError):
        RoutingConfig.from_workspace(bad)
