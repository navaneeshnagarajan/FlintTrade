"""T12 (gap G7) CI validator: every shipped workspace selector resolves.

Locks the selector-bound model: each selector in the default workspace config
parses to a ``(adapter_id, account_id)`` pair whose adapter is a known broker
(identity X7). A typo'd or non-canonical selector slipped into the default
config fails CI here rather than at the operator's first order.
"""

from __future__ import annotations

from flinttrade_core.workspace_migrations import default_workspace_config
from flinttrade_engine.request_context import parse_selector
from flinttrade_gateway.brokers.native_factory import NATIVE_ADAPTER_CLASSES
from flinttrade_gateway.routing_config import RoutingConfig

# The bare adapter_id namespace the registry is expected to know (identity X7).
_KNOWN_ADAPTERS = {"openalgo", *NATIVE_ADAPTER_CLASSES}


def _all_selectors(cfg: RoutingConfig) -> list[str]:
    sels = [
        cfg.execution.default,
        *cfg.execution.by_segment.values(),
        cfg.data.ticks,
        cfg.data.historical,
        cfg.data.option_chains,
        cfg.data.quote,
    ]
    if cfg.data.global_indices:
        sels.append(cfg.data.global_indices)
    sels.extend(cfg.failover.order)
    return sels


def test_default_config_selectors_resolve_to_known_adapters() -> None:
    cfg = RoutingConfig.from_workspace(default_workspace_config()["brokers"])
    for selector in _all_selectors(cfg):
        adapter_id, account_id = parse_selector(selector)
        assert adapter_id in _KNOWN_ADAPTERS, f"{selector!r} -> unknown adapter {adapter_id!r}"
        assert account_id, f"{selector!r} has an empty account_id"
