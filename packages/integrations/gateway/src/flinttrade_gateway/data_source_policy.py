"""Explicit market/dataset policy, separate from broker execution defaults."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from flinttrade_core.data_contracts import canonical_json, text


def _date(value: Any) -> str:
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError("coverage date must be YYYY-MM-DD")
    return value


def parse_data_policies(raw: Any, connections: set[str]) -> tuple[str, ...]:
    """Freeze declared policy bytes; configured does not mean entitled/ready."""
    if type(raw) is not list:
        raise ValueError("data_policies must be a list")
    policies = []
    for item in raw:
        if type(item) is not dict:
            raise ValueError("data policy must be an object")
        policy = {key: text(item.get(key), key) for key in ("dataset", "market", "venue", "revision")}
        sources = item.get("sources")
        if type(sources) is not list or not sources or any(type(s) is not str for s in sources):
            raise ValueError("data sources must be explicit")
        if len(set(sources)) != len(sources) or not set(sources) <= connections:
            raise ValueError("duplicate or unknown data connection")
        priority = item.get("priority")
        if type(priority) is not int:
            raise ValueError("numeric policy priority required")
        if item.get("mode") not in ("single", "priority_fill_gaps"):
            raise ValueError("explicit merge mode required")
        if item["mode"] == "single" and len(sources) != 1:
            raise ValueError("single mode requires one source")
        if item.get("duplicates") != "identical_only" or item.get("conflicts") not in ("reject", "prefer_priority"):
            raise ValueError("explicit overlap rules required")
        start, end = _date(item.get("coverage_start")), _date(item.get("coverage_end"))
        if start > end:
            raise ValueError("reversed coverage")
        policy.update(sources=sources, priority=priority, coverage_start=start, coverage_end=end,
                      mode=item["mode"], duplicates=item["duplicates"], conflicts=item["conflicts"])
        for other in policies:
            if all(other[k] == policy[k] for k in ("dataset", "market", "venue", "priority")) and (
                start <= other["coverage_end"] and end >= other["coverage_start"]
            ):
                raise ValueError("ambiguous data policies")
        policies.append(policy)
    return tuple(canonical_json(policy) for policy in policies)


def resolve_data_policy(policies: tuple[str, ...], dataset: str, *, market: str, venue: str,
                        start: str, end: str) -> dict[str, Any]:
    """Return the planned contributors; an outage never alters this choice."""
    start, end = _date(start), _date(end)
    if end < start:
        raise ValueError("reversed requested coverage")
    candidates = [json.loads(policy) for policy in policies]
    candidates = [item for item in candidates if item["dataset"] == dataset and item["market"] == market
                  and item["venue"] == venue and item["coverage_start"] <= start and item["coverage_end"] >= end]
    if not candidates:
        raise ValueError("no explicit data policy covers the requested dataset")
    candidates.sort(key=lambda item: item["priority"], reverse=True)
    return candidates[0]
