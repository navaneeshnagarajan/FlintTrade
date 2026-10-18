"""Reproducible, source-preserving history publication for DataPipeline.

The caller supplies a versioned calendar's actual session windows. This module
never assumes Indian hours, fills a price, converts currency or adjusts prices.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flinttrade_core.data_contracts import (
    DataIntegrityError,
    digest,
    text,
    timestamp,
    validate_identity,
    validate_ohlcv,
    validate_scope,
    validate_source,
)


def build_history(*, identity: dict[str, Any], scope: dict[str, Any], policy: dict[str, Any],
                  contributors: list[dict[str, Any]]) -> dict[str, Any]:
    """Build immutable inputs and explicit overlap/coverage evidence.

    Priority selects a *whole* compatible bar, not average prices or summed
    overlapping volume. Failed contributors remain recorded and prevent a
    complete result. Publication never invokes a remote provider.
    """
    identity, scope = validate_identity(identity), validate_scope(scope)
    if policy.get("mode") not in ("single", "priority_fill_gaps"):
        raise DataIntegrityError("unsupported history mode")
    if policy.get("duplicates") != "identical_only" or policy.get("conflicts") not in ("reject", "prefer_priority"):
        raise DataIntegrityError("explicit duplicate and conflict policies required")
    text(policy.get("revision"), "policy revision")
    priority = policy.get("priority")
    if not isinstance(priority, list) or not priority or len(set(priority)) != len(priority):
        raise DataIntegrityError("explicit unique source priority required")
    if policy["mode"] == "single" and len(priority) != 1:
        raise DataIntegrityError("single history requires one source")
    expected: set[str] = set()
    sessions = policy.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise DataIntegrityError("versioned calendar sessions required")
    for session in sessions:
        start, end = timestamp(session["start"]), timestamp(session["end"])
        if end <= start or (end - start).total_seconds() % identity["interval_seconds"]:
            raise DataIntegrityError("session alignment")
        cursor = start
        while cursor < end:
            key = cursor.isoformat()
            if key in expected:
                raise DataIntegrityError("overlapping sessions")
            expected.add(key)
            if len(expected) > 1_000_000:
                raise DataIntegrityError("history window exceeds publication bound")
            cursor += timedelta(seconds=identity["interval_seconds"])
    partitions: dict[str, Any] = {}
    duplicates: dict[str, int] = {}
    for contribution in contributors:
        source = validate_source(contribution["source"])
        source_id = source["connection_id"]
        if source_id in partitions:
            raise DataIntegrityError("duplicate contributor")
        if validate_identity(contribution["identity"]) != identity:
            raise DataIntegrityError("incompatible instrument, venue, units, calendar or adjustment")
        retrieved = timestamp(contribution["retrieved_at"])
        text(contribution.get("revision"), "source revision")
        status = contribution.get("status")
        if status not in ("available", "partial", "unavailable"):
            raise DataIntegrityError("source status required")
        bars = {}
        duplicate_count = 0
        for raw in contribution["bars"]:
            bar = validate_ohlcv(raw)
            ts = bar["timestamp"]
            if ts not in expected:
                raise DataIntegrityError("bar outside calendar/session alignment")
            if timestamp(ts) > retrieved or (bar["published_at"] and timestamp(bar["published_at"]) > retrieved):
                raise DataIntegrityError("retrieval precedes observation or publication")
            if ts in bars:
                if bars[ts] != bar:
                    raise DataIntegrityError("conflicting duplicate within source revision")
                duplicate_count += 1
            bars[ts] = bar
        if status == "unavailable" and bars:
            raise DataIntegrityError("unavailable contributor contains observations")
        partitions[source_id] = {"source": source, "identity": identity, "revision": contribution["revision"],
                                 "status": status, "retrieved_at": retrieved.isoformat(),
                                 "bars": [bars[key] for key in sorted(bars)]}
        duplicates[source_id] = duplicate_count
    if set(partitions) != set(priority):
        raise DataIntegrityError("every planned source must report its outcome")
    chosen: dict[str, Any] = {}
    conflicts = []
    for source_id in priority:
        part = partitions[source_id]
        for bar in part["bars"]:
            ts = bar["timestamp"]
            if ts in chosen:
                fields = ("open", "high", "low", "close", "volume", "oi")
                if any(chosen[ts][key] != bar[key] for key in fields):
                    conflicts.append({"timestamp": ts, "selected_source": chosen[ts]["source_id"],
                                      "other_source": source_id, "selected_hash": digest(chosen[ts]),
                                      "other_hash": digest(bar)})
                    if policy["conflicts"] == "reject":
                        raise DataIntegrityError("conflicting historical observations")
            else:
                chosen[ts] = {**bar, "source_id": source_id, "source_revision": part["revision"],
                              "retrieved_at": part["retrieved_at"]}
    missing = sorted(expected - chosen.keys())
    status = "available" if not missing and all(p["status"] == "available" for p in partitions.values()) else "partial"
    if not chosen:
        status = "unavailable"
    document = {
        "schema_version": 1, "identity": identity, "scope": scope, "policy": policy,
        "contributors": [partitions[key] for key in priority],
        "bars": [chosen[key] for key in sorted(chosen)], "status": status,
        "coverage": {"expected": len(expected), "observed": len(chosen), "missing": missing},
        "duplicates": duplicates, "conflicts": conflicts,
        "rights": "not_attested", "execution_authority": False,
    }
    return {**document, "snapshot_id": digest(document)}
