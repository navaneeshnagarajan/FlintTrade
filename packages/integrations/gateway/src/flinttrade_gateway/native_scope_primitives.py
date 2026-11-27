"""Server-owned synthetic native primitives, never production qualification.

Normal factories install no source. Request DTOs, dates, aliases and booleans
cannot install one. The real verified writer issues invocation correspondence;
independent native resource primitives come from the explicitly inert transport.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .json_evidence import copy_json_evidence

_INVOKING: ContextVar[Any] = ContextVar("native_scope_invocation", default=None)


@contextmanager
def observing_invocation(source: Any) -> Iterator[None]:
    """Retain the existing writer frame across its actual external invocation."""
    token = _INVOKING.set(source)
    try:
        yield
    finally:
        _INVOKING.reset(token)


def _text(value: Any) -> None:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError("native primitive identity unavailable")


def _date(value: Any) -> None:
    _text(value)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("native primitive date unavailable")


def scope_key(resource: dict) -> tuple[str, ...]:
    """Keep native order date separate from every execution date."""
    return tuple(resource[name] for name in (
        "native_account", "native_order_date_basis", "native_order_date", "segment", "family",
        "resource_id", "leg", "order_id",
    ))


def validate_resources(value: Any) -> list[dict]:
    """Detach complete, explicit primitive resource and execution observations."""
    value = copy_json_evidence(value)
    if type(value) is not list or not 1 <= len(value) <= 256:
        raise ValueError("native primitive resources unavailable")
    seen = set()
    for row in value:
        if type(row) is not dict or set(row) != {
            "native_account", "native_order_date_basis", "native_order_date", "segment", "family",
            "resource_id", "leg", "order_id",
            "exchange_order_id", "filled_quantity", "executions",
        }:
            raise ValueError("native resource schema mismatch")
        for name in ("native_account", "segment", "family", "resource_id", "leg", "order_id", "exchange_order_id"):
            _text(row[name])
        _date(row["native_order_date"])
        if row["native_order_date_basis"] != "synthetic-independent-identity-day-v1":
            raise ValueError("independent native identity-day basis required")
        key = scope_key(row)
        if key in seen:
            raise ValueError("duplicate native resource")
        seen.add(key)
        quantity = row["filled_quantity"]
        if quantity is not None:
            if type(quantity) is not str or len(quantity) > 64:
                raise ValueError("invalid native cumulative quantity")
            try:
                number = Decimal(quantity)
            except InvalidOperation:
                raise ValueError("invalid native cumulative quantity") from None
            if not number.is_finite() or not 0 <= number <= 10**18 or number != number.to_integral_value():
                raise ValueError("invalid native cumulative quantity")
        if type(row["executions"]) is not list or len(row["executions"]) > 10000:
            raise ValueError("native executions unavailable")
        identities = set()
        for execution in row["executions"]:
            if type(execution) is not dict or set(execution) != {"fill_id", "execution_date", "fill_leg"}:
                raise ValueError("native execution schema mismatch")
            _text(execution["fill_id"])
            _text(execution["fill_leg"])
            _date(execution["execution_date"])
            identity = tuple(execution[name] for name in ("fill_id", "execution_date", "fill_leg"))
            if identity in identities:
                raise ValueError("duplicate native execution")
            identities.add(identity)
    return value


class SyntheticNativeScopeSource:
    """Trusted server fixture dependency bound to one actual adapter/transport.

    This source is intentionally nominal and labelled synthetic. The receiver
    cannot promote it to documented/production evidence by supplying a label.
    It stores no book: the external fixture supplies independent observations,
    while invocation evidence is persisted by the existing lifecycle owner.
    """

    def __init__(self, *, adapter: Any, transport: object, reader: Any, workspace_path: Path, label: str) -> None:
        _text(label)
        if not callable(reader) or not isinstance(workspace_path, Path):
            raise ValueError("server-owned primitive source required")
        self.adapter, self.transport, self.reader = adapter, transport, reader
        self.workspace_path, self.label = workspace_path.resolve(), label
        self.source_id = uuid4().hex
        self._binding = (adapter, transport, reader, self.workspace_path, self.source_id)

    def _check_binding(self) -> None:
        """Refuse dependency substitution instead of trusting a mutable source label."""
        adapter, transport, reader, workspace, source_id = self._binding
        if (self.adapter is not adapter or self.transport is not transport or self.reader is not reader
                or self.workspace_path != workspace or self.source_id != source_id
                or getattr(adapter, "transport", transport) is not transport):
            raise ValueError("native primitive transport ownership changed")
        if getattr(reader, "__self__", None) is adapter and getattr(adapter, reader.__name__) != reader:
            raise ValueError("native primitive reader changed")

    def observe_transport(self, *, transport: object, native_account: str, order: Any,
                          order_ids: list[str], resources: list[dict]) -> dict:
        """Issue correspondence only inside the actual verified writer call.

        The inert transport supplies independently known native order dates and
        addresses. The issuer adds the actual captured invocation/full intent;
        ACK equality is checked against the real return, not assumed here.
        """
        from .router import _canonical_json
        from .writer_provenance import NativeWriterSource

        source = _INVOKING.get()
        self._check_binding()
        if (type(source) is not NativeWriterSource or source.adapter is not self.adapter
                or transport is not self.transport or source.attempt_id is None
                or native_account != source.session.account_id or source.payload_json != _canonical_json(order)):
            raise ValueError("verified transport correspondence required")
        facts = json.loads(source.facts_json)
        if source.workspace_path != self.workspace_path:
            raise ValueError("synthetic source workspace mismatch")
        resources = validate_resources(resources)
        if (type(order_ids) is not list or not order_ids or len(order_ids) != len(set(order_ids))
                or any(type(item) is not str or not item for item in order_ids)
                or set(order_ids) != {row["order_id"] for row in resources}
                or any(row["native_account"] != native_account for row in resources)):
            raise ValueError("complete transport acknowledgement scope required")
        record = {"provenance": "synthetic", "label": self.label, "source_id": self.source_id,
                  "invocation_id": facts["invocation_id"], "signed_intent_hash": facts["signed_intent_hash"],
                  "order_ids": list(order_ids), "resources": resources}
        if source.native_scope_json is not None:
            raise ValueError("one transport observation per invocation required")
        source.native_scope_json = json.dumps(record, sort_keys=True, separators=(",", ":"))
        return json.loads(source.native_scope_json)

    async def read(self, session: Any) -> list[dict]:
        """Read the bound inert transport's primitive observations, not a DTO grant."""
        self._check_binding()
        records = copy_json_evidence(await self.reader(session))
        self._check_binding()
        if type(records) is not list or len(records) > 256:
            raise ValueError("native primitive response unavailable")
        for record in records:
            if type(record) is not dict or set(record) != {
                "provenance", "label", "source_id", "invocation_id", "signed_intent_hash", "order_ids", "resources",
            }:
                raise ValueError("native primitive envelope invalid")
            if (record["provenance"] != "synthetic" or record["source_id"] != self.source_id
                    or record["label"] != self.label):
                raise ValueError("native primitive source mismatch")
            for field in ("invocation_id", "signed_intent_hash"):
                _text(record[field])
            record["resources"] = validate_resources(record["resources"])
            ids = record["order_ids"]
            if (type(ids) is not list or any(type(item) is not str for item in ids)
                    or len(ids) != len(set(ids)) or set(ids) != {row["order_id"] for row in record["resources"]}
                    or any(row["native_account"] != session.account_id for row in record["resources"])):
                raise ValueError("native primitive account/ACK set mismatch")
        return records
