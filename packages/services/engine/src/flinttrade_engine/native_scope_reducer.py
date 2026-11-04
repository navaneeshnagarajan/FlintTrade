"""Exact native resource correspondence over the existing sealed ledger facts.

This reducer owns no storage or authority. Only captures and writer manifests
already verified by OrderLifecycleLedger are operands. Synthetic scope remains
synthetic; ordinary timestamps never establish an order identity day.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from flinttrade_gateway.native_scope_primitives import scope_key, validate_resources


class NativeScopeIndex:
    """Reconstruct causally witnessed resources and monotonic cumulative facts."""

    def __init__(self, writer_rows: list[dict], captures: list[tuple[Any, dict]], adapter_id: str) -> None:
        self.resources: dict[tuple[str, ...], dict] = {}
        self.conflicts: set[str] = set()
        self._executions: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
        self._origins: dict[tuple[str, str], tuple[str, dict, dict]] = {}
        prepared = {row["attempt_id"]: row["facts"] for row in writer_rows if row["kind"] == "prepared"}
        for row in writer_rows:
            observation = row.get("native_scope_observation")
            if row["kind"] != "acknowledged" or observation is None:
                continue
            facts = prepared.get(row["attempt_id"])
            if (facts is None or row.get("native_scope_ack_matches") is not True
                    or row["invocation_id"] != facts["invocation_id"]
                    or observation["invocation_id"] != facts["invocation_id"]
                    or observation["signed_intent_hash"] != facts["signed_intent_hash"]
                    or set(observation["order_ids"]) != set(row["order_ids"])):
                self.conflicts.add("native_scope_ack_correspondence_conflict")
                continue
            identity = (observation["source_id"], observation["invocation_id"])
            origin = (row["attempt_id"], facts, observation)
            if identity in self._origins and self._origins[identity] != origin:
                self.conflicts.add("native_scope_invocation_conflict")
                continue
            self._origins[identity] = origin
            self._observe(origin, observation, adapter_id)
        for _, capture in captures:
            encoded = capture.get("native_scope_json")
            if capture.get("schema") != "flinttrade.canonical-observations.v1" or encoded is None:
                continue
            envelope = json.loads(encoded)
            if envelope["availability"] != "available":
                continue
            for observation in envelope["records"]:
                origin = self._origins.get((observation["source_id"], observation["invocation_id"]))
                if (origin is None or observation["source_id"] != envelope["source_id"]
                        or origin[1]["provider_account_id"] != capture["provider_account_id"]):
                    continue
                self._observe(origin, observation, adapter_id)

    def _observe(self, origin: tuple[str, dict, dict], observation: dict, adapter_id: str) -> None:
        attempt, facts, initial = origin
        initial_rows = {scope_key(row): row for row in validate_resources(initial["resources"])}
        rows = validate_resources(observation["resources"])
        if (observation["provenance"] != "synthetic" or observation["label"] != initial["label"]
                or observation["signed_intent_hash"] != initial["signed_intent_hash"]
                or observation["order_ids"] != initial["order_ids"]
                or {scope_key(row) for row in rows} != set(initial_rows)):
            self.conflicts.add("native_scope_immutable_correspondence_conflict")
            return
        for row in rows:
            key = (adapter_id, *scope_key(row))
            before = initial_rows[scope_key(row)]
            if (row["native_account"] != facts["provider_account_id"]
                    or row["order_id"] not in initial["order_ids"]
                    or row["exchange_order_id"] != before["exchange_order_id"]
                    or facts.get("native_segment") not in (None, row["segment"])
                    or facts.get("resource_family") != row["family"]):
                self.conflicts.add("native_scope_resource_conflict")
                continue
            existing = self.resources.get(key)
            quantity = Decimal(row["filled_quantity"]) if row["filled_quantity"] is not None else None
            if existing is not None and existing["attempt"] != attempt:
                existing["ambiguous"] = True
                self.conflicts.add("native_scope_multiple_attempts")
                if quantity is not None:
                    high = existing["high_water"]
                    existing["high_water"] = max(high, quantity) if high is not None else quantity
                continue
            if existing is None:
                existing = {"attempt": attempt, "facts": facts, "resource": before,
                            "high_water": quantity, "ambiguous": False}
                self.resources[key] = existing
            elif quantity is not None:
                high = existing["high_water"]
                if high is not None and quantity < high:
                    self.conflicts.add("native_scope_cumulative_regression")
                existing["high_water"] = max(high, quantity) if high is not None else quantity
            for execution in row["executions"]:
                address = (row["native_account"], row["segment"], row["order_id"], row["exchange_order_id"],
                           execution["fill_id"], execution["execution_date"], execution["fill_leg"])
                self._executions.setdefault(address, set()).add(key)

    def allocation(self, native_account: str, trade: Any) -> tuple[str | None, tuple[str, ...] | None]:
        """Join an independently witnessed execution, never a scalar order ID."""
        address = (native_account, trade.broker_exchange_segment, trade.orderid, trade.exchange_order_id,
                   trade.fill_id, trade.trade_date, trade.fill_leg)
        keys = self._executions.get(address, set())
        if len(keys) != 1:
            if keys:
                self.conflicts.add("native_scope_ambiguous_execution")
            return None, None
        key = next(iter(keys))
        row = self.resources[key]
        intent = row["facts"]["intent"]
        if row["ambiguous"] or any(intent.get(field) != getattr(trade, field)
                                   for field in ("symbol", "exchange", "product", "action")):
            self.conflicts.add("native_scope_execution_intent_conflict")
            return None, None
        return row["attempt"], key
