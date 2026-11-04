"""Durable selector-scoped order intent and broker-observation ledger.

The ledger records a normal broker write before invocation, separates dispatch
state from broker order state, and keeps FlintTrade-origin intent independent
from broker observations. Reconciliation may advance a matching local order's
status and fills, but an empty broker snapshot never erases unresolved local
intent and a broker-only row never becomes FlintTrade-origin truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable
from zoneinfo import ZoneInfo

from flinttrade_core.db import open_sqlite
from flinttrade_core.secure_file import harden

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.broker_read_port import (
        BrokerReadPort,
        CanonicalObservationSnapshot,
        LedgerRequest,
        LotSizeRequest,
        MarginRequest,
        TradeHistoryRequest,
    )
    from flinttrade_gateway.broker_read_service import BrokerReadOwner
    from flinttrade_gateway.reconciliation import LocalStateSnapshot

_SCHEMA_VERSION = 8
_BUSINESS_TZ = ZoneInfo("Asia/Kolkata")

DISPATCH_PREPARED = "PREPARED"
DISPATCH_INVOKED = "INVOKED"
DISPATCH_ACKNOWLEDGED = "ACKNOWLEDGED"
DISPATCH_FAILED_BEFORE_INVOKE = "FAILED_BEFORE_INVOKE"
DISPATCH_OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
DISPATCH_CONFIRMED_APPLIED = "CONFIRMED_APPLIED"
DISPATCH_CONFIRMED_NOT_APPLIED = "CONFIRMED_NOT_APPLIED"
DISPATCH_CONFIRMED_PARTIAL = "CONFIRMED_PARTIAL"

_DISPATCH_STATES = {
    DISPATCH_PREPARED,
    DISPATCH_INVOKED,
    DISPATCH_ACKNOWLEDGED,
    DISPATCH_FAILED_BEFORE_INVOKE,
    DISPATCH_OUTCOME_UNKNOWN,
    DISPATCH_CONFIRMED_APPLIED,
    DISPATCH_CONFIRMED_NOT_APPLIED,
    DISPATCH_CONFIRMED_PARTIAL,
}
_RESOLUTION_OUTCOMES = {
    "confirmed_applied",
    "confirmed_not_applied",
    "confirmed_partial",
}
_REGULAR_PLACEMENT_OPERATIONS = {
    "place_order",
    "place_multi_order",
    "place_reducing_order",
}
_TERMINAL_STATUSES = {"COMPLETE", "CANCELLED", "REJECTED", "EXPIRED", "CLOSED"}
_MODIFY_RECOVERY_FIELDS = {
    "symbol",
    "exchange",
    "product",
    "action",
    "quantity",
    "price",
    "trigger_price",
    "price_type",
    "variety",
    "validity",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dispatch_attempts (
    attempt_id          TEXT PRIMARY KEY,
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    business_date       TEXT NOT NULL,
    operation           TEXT NOT NULL,
    dispatch_state      TEXT NOT NULL,
    history_complete    INTEGER NOT NULL DEFAULT 1,
    request_jti_hash    TEXT NOT NULL DEFAULT '',
    actor_type          TEXT NOT NULL DEFAULT '',
    actor_id            TEXT NOT NULL DEFAULT '',
    intent_source       TEXT NOT NULL DEFAULT '',
    payload_fingerprint TEXT NOT NULL,
    symbol              TEXT NOT NULL DEFAULT '',
    exchange            TEXT NOT NULL DEFAULT '',
    product             TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL DEFAULT '',
    quantity            REAL NOT NULL DEFAULT 0,
    price               REAL NOT NULL DEFAULT 0,
    trigger_price       REAL NOT NULL DEFAULT 0,
    price_type          TEXT NOT NULL DEFAULT '',
    variety             TEXT NOT NULL DEFAULT '',
    validity            TEXT NOT NULL DEFAULT '',
    strategy            TEXT NOT NULL DEFAULT '',
    modify_requested_fields TEXT NOT NULL DEFAULT '[]',
    modify_baseline_json TEXT NOT NULL DEFAULT '{}',
    broker_order_id     TEXT,
    prepared_at         TEXT NOT NULL,
    invoked_at          TEXT,
    completed_at        TEXT,
    error_kind          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_dispatch_attempts_selector_state
    ON dispatch_attempts (adapter_id, account_id, business_date, dispatch_state, prepared_at);

CREATE TABLE IF NOT EXISTS dispatch_items (
    attempt_id          TEXT NOT NULL,
    item_index          INTEGER NOT NULL CHECK (item_index >= 0),
    symbol              TEXT NOT NULL DEFAULT '',
    exchange            TEXT NOT NULL DEFAULT '',
    product             TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL DEFAULT '',
    quantity            REAL NOT NULL DEFAULT 0,
    price               REAL NOT NULL DEFAULT 0,
    trigger_price       REAL NOT NULL DEFAULT 0,
    price_type          TEXT NOT NULL DEFAULT '',
    variety             TEXT NOT NULL DEFAULT '',
    validity            TEXT NOT NULL DEFAULT '',
    strategy            TEXT NOT NULL DEFAULT '',
    broker_order_id     TEXT,
    PRIMARY KEY (attempt_id, item_index),
    FOREIGN KEY (attempt_id) REFERENCES dispatch_attempts(attempt_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dispatch_items_attempt_order
    ON dispatch_items (attempt_id, broker_order_id)
    WHERE broker_order_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS orders_current (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    business_date       TEXT NOT NULL,
    broker_order_id     TEXT NOT NULL,
    attempt_id          TEXT,
    origin              TEXT NOT NULL,
    symbol              TEXT NOT NULL DEFAULT '',
    exchange            TEXT NOT NULL DEFAULT '',
    product             TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL DEFAULT '',
    status_raw          TEXT NOT NULL DEFAULT '',
    status_normalized   TEXT NOT NULL DEFAULT 'UNKNOWN',
    quantity            REAL NOT NULL DEFAULT 0,
    filled_quantity     REAL NOT NULL DEFAULT 0,
    price               REAL NOT NULL DEFAULT 0,
    trigger_price       REAL NOT NULL DEFAULT 0,
    price_type          TEXT NOT NULL DEFAULT '',
    variety             TEXT NOT NULL DEFAULT '',
    validity            TEXT NOT NULL DEFAULT '',
    strategy            TEXT NOT NULL DEFAULT '',
    average_price       REAL NOT NULL DEFAULT 0,
    first_seen_at       TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    terminal_at         TEXT,
    broker_present      INTEGER NOT NULL DEFAULT 0,
    last_broker_seen_at TEXT,
    last_seen_generation INTEGER NOT NULL DEFAULT 0,
    missing_count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (adapter_id, account_id, business_date, broker_order_id),
    FOREIGN KEY (attempt_id) REFERENCES dispatch_attempts(attempt_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_current_local_selector
    ON orders_current (adapter_id, account_id, origin, business_date, broker_order_id);

CREATE TABLE IF NOT EXISTS order_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    business_date       TEXT NOT NULL,
    broker_order_id     TEXT NOT NULL,
    attempt_id          TEXT,
    observed_at         TEXT NOT NULL,
    source              TEXT NOT NULL,
    origin              TEXT NOT NULL,
    status_raw          TEXT NOT NULL DEFAULT '',
    status_normalized   TEXT NOT NULL DEFAULT 'UNKNOWN',
    quantity            REAL NOT NULL DEFAULT 0,
    filled_quantity     REAL NOT NULL DEFAULT 0,
    average_price       REAL NOT NULL DEFAULT 0,
    terminal_at         TEXT,
    broker_present      INTEGER NOT NULL DEFAULT 0,
    fingerprint         TEXT NOT NULL,
    UNIQUE (adapter_id, account_id, business_date, broker_order_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_order_events_selector_order
    ON order_events (adapter_id, account_id, business_date, broker_order_id, event_id);

CREATE TABLE IF NOT EXISTS broker_order_observations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    business_date       TEXT NOT NULL,
    generation          INTEGER NOT NULL CHECK (generation >= 0),
    broker_order_id     TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    symbol              TEXT NOT NULL DEFAULT '',
    exchange            TEXT NOT NULL DEFAULT '',
    product             TEXT NOT NULL DEFAULT '',
    action              TEXT NOT NULL DEFAULT '',
    status_raw          TEXT NOT NULL DEFAULT '',
    status_normalized   TEXT NOT NULL DEFAULT 'UNKNOWN',
    quantity            REAL NOT NULL DEFAULT 0,
    filled_quantity     REAL NOT NULL DEFAULT 0,
    price               REAL NOT NULL DEFAULT 0,
    trigger_price       REAL NOT NULL DEFAULT 0,
    price_type          TEXT NOT NULL DEFAULT '',
    variety             TEXT NOT NULL DEFAULT '',
    validity            TEXT NOT NULL DEFAULT '',
    strategy            TEXT NOT NULL DEFAULT '',
    average_price       REAL NOT NULL DEFAULT 0,
    first_seen_at       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (
        adapter_id, account_id, business_date, generation, broker_order_id
    )
);

CREATE INDEX IF NOT EXISTS idx_broker_order_observations_selector_time
    ON broker_order_observations (
        adapter_id, account_id, business_date, observed_at, broker_order_id
    );

CREATE INDEX IF NOT EXISTS idx_broker_order_observations_selector_generation
    ON broker_order_observations (
        adapter_id, account_id, generation, broker_order_id
    );

CREATE TABLE IF NOT EXISTS snapshot_generations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    generation          INTEGER NOT NULL,
    observed_at         TEXT NOT NULL,
    content_digest      TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (adapter_id, account_id)
);

CREATE TABLE IF NOT EXISTS snapshot_generation_manifests (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    generation          INTEGER NOT NULL CHECK (generation > 0),
    observed_at         TEXT NOT NULL,
    content_digest      TEXT NOT NULL,
    evidence_json       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (adapter_id, account_id, generation)
);

CREATE TABLE IF NOT EXISTS position_generation_observations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    generation          INTEGER NOT NULL CHECK (generation > 0),
    row_key             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    product             TEXT NOT NULL,
    quantity            REAL NOT NULL,
    average_price       REAL NOT NULL DEFAULT 0,
    observed_at         TEXT NOT NULL,
    PRIMARY KEY (adapter_id, account_id, generation, row_key)
);

CREATE TABLE IF NOT EXISTS holding_generation_observations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    generation          INTEGER NOT NULL CHECK (generation > 0),
    row_key             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    quantity            REAL NOT NULL,
    average_price       REAL NOT NULL DEFAULT 0,
    observed_at         TEXT NOT NULL,
    PRIMARY KEY (adapter_id, account_id, generation, row_key)
);

CREATE TABLE IF NOT EXISTS position_observations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    row_key             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    product             TEXT NOT NULL,
    quantity            REAL NOT NULL,
    average_price       REAL NOT NULL DEFAULT 0,
    generation          INTEGER NOT NULL,
    observed_at         TEXT NOT NULL,
    PRIMARY KEY (adapter_id, account_id, row_key)
);

CREATE TABLE IF NOT EXISTS holding_observations (
    adapter_id          TEXT NOT NULL,
    account_id          TEXT NOT NULL,
    row_key             TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    quantity            REAL NOT NULL,
    average_price       REAL NOT NULL DEFAULT 0,
    generation          INTEGER NOT NULL,
    observed_at         TEXT NOT NULL,
    PRIMARY KEY (adapter_id, account_id, row_key)
);

CREATE TABLE IF NOT EXISTS ledger_health (
    singleton           INTEGER PRIMARY KEY CHECK (singleton = 1),
    status              TEXT NOT NULL,
    reason              TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT '',
    attempt_id          TEXT,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispatch_resolutions (
    resolution_id       TEXT PRIMARY KEY,
    attempt_id          TEXT NOT NULL UNIQUE,
    outcome             TEXT NOT NULL,
    broker_order_ids    TEXT NOT NULL DEFAULT '[]',
    broker_order_item_indexes TEXT NOT NULL DEFAULT '[]',
    not_applied_item_indexes TEXT NOT NULL DEFAULT '[]',
    actor_type          TEXT NOT NULL,
    actor_id            TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    evidence_digest     TEXT NOT NULL,
    status              TEXT NOT NULL,
    prepared_at         TEXT NOT NULL,
    snapshot_generation INTEGER,
    snapshot_observed_at TEXT,
    snapshot_content_digest TEXT,
    audit_reference     TEXT NOT NULL DEFAULT '',
    audit_recorded_at   TEXT,
    router_cleared_at   TEXT,
    router_clear_receipt_digest TEXT NOT NULL DEFAULT '',
    router_generation_id TEXT NOT NULL DEFAULT '',
    committed_at        TEXT,
    FOREIGN KEY (attempt_id) REFERENCES dispatch_attempts(attempt_id)
);

CREATE TABLE IF NOT EXISTS dispatch_resolution_revisions (
    revision_id         TEXT PRIMARY KEY,
    resolution_id       TEXT NOT NULL,
    attempt_id          TEXT NOT NULL,
    reason              TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    recorded_at         TEXT NOT NULL
);
"""


class LifecycleStateError(RuntimeError):
    """A dispatch attempt was advanced from an invalid state."""


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _text(value: Any) -> str:
    return str(_enum_value(value) or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dict(dumped)
    legacy_dict = getattr(value, "dict", None)
    if callable(legacy_dict):
        dumped = legacy_dict()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, Mapping):
        return dict(attrs)
    raise TypeError(f"unsupported lifecycle row type: {type(value).__name__}")


def _finite_number(value: Any, *, field: str, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        number = float(_enum_value(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _utc_datetime(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime | str | None = None) -> str:
    return _utc_datetime(value).isoformat()


def _business_date(value: datetime | str | None = None) -> str:
    return _utc_datetime(value).astimezone(_BUSINESS_TZ).date().isoformat()


def _normalise_account(value: Any) -> str:
    return _text(value) or "default"


def _normalise_status(raw: Any, *, quantity: float, filled_quantity: float) -> str:
    try:
        from flinttrade_gateway.reconciliation import normalise_order_status  # noqa: PLC0415

        return normalise_order_status(
            raw,
            quantity=quantity,
            filled_quantity=filled_quantity,
        )
    except ImportError:
        value = _text(raw).upper().replace("-", "_").replace(" ", "_")
        aliases = {
            "COMPLETE": "COMPLETE",
            "COMPLETED": "COMPLETE",
            "FILLED": "COMPLETE",
            "TRADED": "COMPLETE",
            "EXECUTED": "COMPLETE",
            "FULLY_EXECUTED": "COMPLETE",
            "CANCELLED": "CANCELLED",
            "CANCELED": "CANCELLED",
            "DELETED": "CANCELLED",
            "DISABLED": "CANCELLED",
            "REJECTED": "REJECTED",
            "FAILED": "REJECTED",
            "EXPIRED": "EXPIRED",
            "CANCELLATION_REQUESTED": "CANCEL_PENDING",
            "CANCEL_REQUESTED": "CANCEL_PENDING",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "PARTIAL": "PARTIALLY_FILLED",
            "OPEN": "OPEN",
            "PENDING": "PENDING",
            "SUBMITTED": "SUBMITTED",
        }
        if value == "CLOSED":
            if quantity > 0 and math.isclose(quantity, filled_quantity):
                return "COMPLETE"
            if math.isclose(filled_quantity, 0.0):
                return "CANCELLED"
            return "CLOSED"
        return aliases.get(value, "UNKNOWN")


def _canonical_intent(payload: Any) -> dict[str, Any]:
    source = _mapping(payload)
    for nested_key in ("order", "request", "req"):
        nested = source.get(nested_key)
        if isinstance(nested, Mapping):
            source = {**source, **dict(nested)}
            break
    quantity = _finite_number(source.get("quantity", source.get("qty")), field="quantity")
    if quantity < 0:
        raise ValueError("quantity must be non-negative")
    return {
        "symbol": _text(source.get("symbol") or source.get("trading_symbol")),
        "exchange": _text(source.get("exchange") or source.get("segment")).upper(),
        "product": _text(source.get("product")).upper(),
        "action": _text(source.get("action") or source.get("side") or source.get("transaction_type")).upper(),
        "quantity": quantity,
        "price": _finite_number(source.get("price"), field="price"),
        "trigger_price": _finite_number(source.get("trigger_price"), field="trigger_price"),
        "price_type": _text(source.get("price_type") or source.get("pricetype")).upper(),
        "variety": _text(source.get("variety")).upper(),
        "validity": _text(source.get("validity")).upper(),
        "strategy": _text(source.get("strategy") or source.get("strategy_id")),
        "broker_order_id": _text(source.get("orderid") or source.get("order_id")),
    }


def _canonical_modify_requested_fields(payload: Any) -> list[str]:
    source = _mapping(payload)
    raw_fields = source.get("_requested_change_fields", ())
    if raw_fields in (None, ""):
        return []
    if not isinstance(raw_fields, (list, tuple)):
        raise ValueError("_requested_change_fields must be an ordered list")
    fields: list[str] = []
    for raw_field in raw_fields:
        field = _text(raw_field).lower()
        if field == "pricetype":
            field = "price_type"
        if field not in _MODIFY_RECOVERY_FIELDS:
            raise ValueError(f"unsupported modify recovery field {field!r}")
        if field not in fields:
            fields.append(field)
    return sorted(fields)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = _canonical_json(dict(payload))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _recovery_field_equal(field: str, actual: Any, expected: Any) -> bool:
    if field in {"quantity", "price", "trigger_price"}:
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return _text(actual).upper() == _text(expected).upper()


def _canonical_broker_order_id(candidate: Any) -> str:
    if candidate is None or isinstance(candidate, (bool, Mapping, list, tuple, set)):
        return ""
    value = str(candidate)
    if value and value == value.strip() and value.isprintable() and not any(char.isspace() for char in value):
        return value
    return ""


def _broker_order_matches_intent(
    broker_order: Mapping[str, Any],
    intent: Mapping[str, Any],
    *,
    require_material_fields: bool = False,
) -> bool:
    """Return whether broker-observed identity matches one persisted placement intent."""
    text_fields = ("symbol", "exchange", "product", "action")
    material_text_fields = (*text_fields, "price_type", "variety", "validity", "strategy")
    observed_text = {field: _text(broker_order[field]).upper() for field in material_text_fields}
    if require_material_fields and any(value == "UNKNOWN" for value in observed_text.values()):
        return False
    if any(observed_text[field] != _text(intent[field]).upper() for field in text_fields):
        return False
    for field in ("quantity", "price", "trigger_price"):
        observed_number = float(broker_order[field])
        intended_number = float(intent[field])
        if require_material_fields and observed_number != intended_number:
            return False
        if not require_material_fields and not math.isclose(
            observed_number,
            intended_number,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            return False
    for field in ("price_type", "variety", "validity", "strategy"):
        intended = _text(intent[field]).upper()
        observed = observed_text[field]
        if require_material_fields and observed != intended:
            return False
        if not require_material_fields and intended and observed and observed != intended:
            return False
    return True


def _broker_order_matches_core_intent(
    broker_order: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> bool:
    """Return whether a row is too close to an intent to prove non-application."""
    text_fields = ("symbol", "exchange", "product", "action")
    if any(_text(broker_order[field]).upper() != _text(intent[field]).upper() for field in text_fields):
        return False
    return math.isclose(
        float(broker_order["quantity"]),
        float(intent["quantity"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    )


def _broker_order_requested_change_state(
    broker_order: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> str:
    """Classify one modify against its exact requested deltas and pre-write baseline."""
    try:
        requested_fields = json.loads(str(intent["modify_requested_fields"] or "[]"))
        baseline = json.loads(str(intent["modify_baseline_json"] or "{}"))
    except (KeyError, TypeError, json.JSONDecodeError):
        return "unverifiable"
    if (
        not isinstance(requested_fields, list)
        or not requested_fields
        or not all(isinstance(field, str) and field in _MODIFY_RECOVERY_FIELDS for field in requested_fields)
        or not isinstance(baseline, dict)
    ):
        return "unverifiable"

    applied = [
        _recovery_field_equal(field, broker_order[field], intent[field])
        for field in requested_fields
    ]
    if all(applied):
        return "applied"
    baseline_matches = [
        field in baseline and _recovery_field_equal(field, broker_order[field], baseline[field])
        for field in requested_fields
    ]
    if all(baseline_matches):
        return "not_applied"
    if all(applied_match or baseline_match for applied_match, baseline_match in zip(applied, baseline_matches, strict=True)):
        return "partial"
    return "unverifiable"


def _correlation_index(candidate: Any) -> int | None:
    if isinstance(candidate, bool) or candidate is None:
        return None
    value = str(candidate)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or value != str(number):
        return None
    return number - 1


def _broker_order_assignments(result: Any) -> tuple[tuple[str, int | None], ...]:
    """Extract canonical broker IDs and optional zero-based basket indexes."""
    assignments: dict[str, int | None] = {}

    def add(candidate: Any, correlation: Any = None) -> None:
        order_id = _canonical_broker_order_id(candidate)
        if not order_id:
            return
        item_index = _correlation_index(correlation)
        previous = assignments.get(order_id)
        if previous is not None and item_index is not None and previous != item_index:
            raise ValueError("broker acknowledgement assigns one order id to multiple basket items")
        if order_id not in assignments or item_index is not None:
            assignments[order_id] = item_index

    def add_rows(rows: Any) -> None:
        if not isinstance(rows, (list, tuple)):
            return
        for row in rows:
            if isinstance(row, Mapping):
                add(
                    row.get("orderid") or row.get("order_id") or row.get("id"),
                    row.get("correlation_id"),
                )
            else:
                add(row)

    if isinstance(result, Mapping):
        add_rows(result.get("order_results"))
        add_rows(result.get("order_ids"))
        add(result.get("orderid") or result.get("order_id") or result.get("id"))
        data = result.get("data")
        if isinstance(data, Mapping):
            add_rows(data.get("order_results"))
            add_rows(data.get("order_ids"))
            add(data.get("orderid") or data.get("order_id") or data.get("id"))
        else:
            add_rows(data)
    else:
        add(result)
        add(getattr(result, "orderid", None) or getattr(result, "order_id", None) or getattr(result, "id", None))
    return tuple(assignments.items())


def _summary_integer(result: Mapping[str, Any], key: str) -> int | None:
    value = result.get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0:
        return None
    if isinstance(value, str):
        if value != str(number):
            return None
    else:
        try:
            if value != number:
                return None
        except Exception:
            return None
    return number


def _explicit_reducing_noop(operation: str, result: Any) -> bool:
    if operation != "place_reducing_order" or not isinstance(result, Mapping):
        return False
    return (
        result.get("order_ids") == []
        and result.get("errors") == []
        and _summary_integer(result, "total") == 0
        and _summary_integer(result, "success") == 0
    )


def _multi_order_error_kind(
    result: Any,
    *,
    expected_count: int,
    result_count: int,
) -> str:
    if expected_count <= 0:
        raise ValueError("multi-order dispatch contains no persisted item intents")
    if not isinstance(result, Mapping):
        if result_count == expected_count:
            return ""
        raise ValueError("multi-order acknowledgement is incomplete")
    total = _summary_integer(result, "total")
    success = _summary_integer(result, "success")
    errors = result.get("errors")
    has_summary = total is not None or success is not None or errors is not None
    if not has_summary:
        if result_count == expected_count:
            return ""
        raise ValueError("multi-order acknowledgement is incomplete")
    if total != expected_count or success != result_count or not isinstance(errors, list):
        raise ValueError("multi-order acknowledgement summary is inconsistent")
    if len(errors) != total - success or not all(isinstance(error, Mapping) for error in errors):
        raise ValueError("multi-order acknowledgement errors are incomplete")
    if success == 0:
        return "batch_rejected"
    if success < total:
        return "partial_batch"
    return ""


def _normalise_broker_order(value: Any) -> dict[str, Any]:
    row = _mapping(value)
    order_id = _text(row.get("orderid") or row.get("order_id"))
    status_raw = _text(row.get("status"))
    if not order_id:
        raise ValueError("broker order row is missing order id")
    if not status_raw:
        raise ValueError(f"broker order {order_id!r} is missing status")
    quantity = _finite_number(row.get("quantity", row.get("qty")), field="quantity")
    filled = _finite_number(
        row.get("filled_quantity", row.get("filled_qty")),
        field="filled_quantity",
    )
    if quantity < 0 or filled < 0 or filled > quantity:
        raise ValueError(f"broker order {order_id!r} has invalid quantities")
    return {
        "orderid": order_id,
        "symbol": _text(row.get("symbol") or row.get("trading_symbol")),
        "exchange": _text(row.get("exchange") or row.get("segment")).upper(),
        "product": _text(row.get("product")).upper(),
        "action": _text(row.get("action") or row.get("side") or row.get("transaction_type")).upper(),
        "status_raw": status_raw,
        "status_normalized": _normalise_status(status_raw, quantity=quantity, filled_quantity=filled),
        "quantity": quantity,
        "filled_quantity": filled,
        "price": _finite_number(row.get("price"), field="price"),
        "trigger_price": _finite_number(
            row.get("trigger_price", row.get("triggerprice")),
            field="trigger_price",
        ),
        "price_type": _text(row.get("price_type") or row.get("pricetype") or row.get("order_type")).upper(),
        "variety": _text(row.get("variety")).upper(),
        "validity": _text(row.get("validity")).upper(),
        "strategy": _text(row.get("strategy") or row.get("strategy_id")),
        "average_price": _finite_number(
            row.get("average_price", row.get("avg_price")),
            field="average_price",
        ),
    }


def _observation_row(value: Any, *, surface: str) -> dict[str, Any]:
    row = _mapping(value)
    symbol = _text(row.get("symbol") or row.get("trading_symbol")).upper()
    exchange = _text(row.get("exchange") or row.get("segment")).upper()
    product = _text(row.get("product")).upper() if surface == "position" else ""
    if not symbol or not exchange or (surface == "position" and not product):
        raise ValueError(f"{surface} row is missing identity")
    quantity = _finite_number(row.get("quantity"), field="quantity")
    if surface == "holding" and quantity < 0:
        raise ValueError("holding quantity must be non-negative")
    return {
        "key": ":".join((symbol, exchange, product)).rstrip(":"),
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": quantity,
        "average_price": _finite_number(
            row.get("average_price", row.get("avg_price")),
            field="average_price",
        ),
    }


class OrderLifecycleLedger:
    """FULL-sync SQLite order intent ledger and reconciliation provider."""

    def __init__(
        self,
        *,
        ledger_path: Path | str | None = None,
        storage_provider: Callable[[], Any] | None = None,
        lock_provider: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        audit_receipt_verifier: Callable[..., bool] | None = None,
    ) -> None:
        self._ledger_path = Path(ledger_path).expanduser() if ledger_path is not None else None
        # Retained for source compatibility with the earlier provider constructor.
        self._storage_provider = storage_provider
        self._lock_provider = lock_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._audit_receipt_verifier = audit_receipt_verifier
        self._lock = threading.RLock()
        self._outcome_resolution_lock = threading.RLock()
        self._initialise()

    def set_audit_receipt_verifier(self, verifier: Callable[..., bool] | None) -> None:
        """Bind the durable audit store used to authorise outcome finalisation."""
        self._audit_receipt_verifier = verifier

    @contextmanager
    def outcome_resolution_lease(self) -> Iterator[None]:
        """Exclude broker snapshot adoption across one prepare/audit/finalise flow."""
        with self._outcome_resolution_lock:
            yield

    def _path(self) -> Path:
        if self._ledger_path is None:
            from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

            self._ledger_path = workspace_dir() / "order-lifecycle.sqlite3"
        return self._ledger_path

    def _open(self) -> sqlite3.Connection:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise OSError("order lifecycle ledger cannot be a symbolic link")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        os.close(descriptor)
        harden(path)
        connection = open_sqlite(path, durability="full", temp_store="FILE")
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._open()
            try:
                if write:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
                if write:
                    connection.execute("COMMIT")
            except Exception:
                if write and connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
                self._harden_sidecars()

    def _harden_sidecars(self) -> None:
        path = self._path()
        for suffix in ("", "-wal", "-shm", "-journal"):
            candidate = path.with_name(path.name + suffix)
            if candidate.exists() and not candidate.is_symlink():
                harden(candidate)

    def _initialise(self) -> None:
        with self._connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > _SCHEMA_VERSION:
                raise RuntimeError(f"order lifecycle schema {version} is newer than supported {_SCHEMA_VERSION}")
            connection.executescript(_SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            try:
                if version == 0:
                    self._migrate_unversioned_draft(connection)
                self._migrate_schema_v3(connection)
                self._migrate_schema_v4(connection)
                self._migrate_schema_v5(connection)
                self._migrate_schema_v6(connection)
                self._migrate_schema_v7(connection, previous_version=version)
                self._migrate_schema_v8(connection, previous_version=version)
                self._recover_interrupted_dispatches(connection)
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _migrate_schema_v3(connection: sqlite3.Connection) -> None:
        """Add explicit health ownership to ledgers created before schema v3."""
        health_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(ledger_health)").fetchall()}
        if "source" not in health_columns:
            connection.execute("ALTER TABLE ledger_health ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        if "attempt_id" not in health_columns:
            connection.execute("ALTER TABLE ledger_health ADD COLUMN attempt_id TEXT")
        connection.execute(
            """UPDATE ledger_health
               SET source = 'legacy_critical', attempt_id = NULL
               WHERE singleton = 1 AND status = 'CRITICAL' AND source = ''""",
        )

    @staticmethod
    def _migrate_schema_v4(connection: sqlite3.Connection) -> None:
        """Add broker evidence and durable router-clear state to schema v4."""
        order_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(orders_current)").fetchall()}
        order_additions = {
            "trigger_price": "REAL NOT NULL DEFAULT 0",
            "price_type": "TEXT NOT NULL DEFAULT ''",
            "variety": "TEXT NOT NULL DEFAULT ''",
            "validity": "TEXT NOT NULL DEFAULT ''",
            "strategy": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in order_additions.items():
            if column not in order_columns:
                connection.execute(
                    f"ALTER TABLE orders_current ADD COLUMN {column} {definition}"  # noqa: S608
                )

        resolution_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_resolutions)").fetchall()
        }
        resolution_additions = {
            "broker_order_item_indexes": "TEXT NOT NULL DEFAULT '[]'",
            "not_applied_item_indexes": "TEXT NOT NULL DEFAULT '[]'",
            "snapshot_generation": "INTEGER",
            "snapshot_observed_at": "TEXT",
            "router_cleared_at": "TEXT",
        }
        for column, definition in resolution_additions.items():
            if column not in resolution_columns:
                connection.execute(
                    f"ALTER TABLE dispatch_resolutions ADD COLUMN {column} {definition}"  # noqa: S608
                )

    @staticmethod
    def _migrate_schema_v5(connection: sqlite3.Connection) -> None:
        """Add snapshot identity needed to reject stale or conflicting generations."""
        snapshot_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(snapshot_generations)").fetchall()
        }
        if "content_digest" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshot_generations ADD COLUMN content_digest TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _migrate_schema_v6(connection: sqlite3.Connection) -> None:
        """Seed immutable broker identity history from the surviving current projection."""
        connection.execute(
            """INSERT OR IGNORE INTO broker_order_observations (
                   adapter_id, account_id, business_date, generation,
                   broker_order_id, observed_at, symbol, exchange, product,
                   action, quantity, price, trigger_price, price_type,
                   variety, validity, strategy
               )
               SELECT adapter_id, account_id, business_date,
                      MAX(last_seen_generation, 0), broker_order_id,
                      last_broker_seen_at,
                      symbol, exchange, product, action, quantity, price,
                      trigger_price, price_type, variety, validity, strategy
               FROM orders_current
               WHERE last_broker_seen_at IS NOT NULL"""
        )

    @staticmethod
    def _migrate_schema_v7(
        connection: sqlite3.Connection,
        *,
        previous_version: int,
    ) -> None:
        """Add exact-generation evidence and conservative history provenance."""
        attempt_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_attempts)").fetchall()}
        if "history_complete" not in attempt_columns:
            connection.execute("ALTER TABLE dispatch_attempts ADD COLUMN history_complete INTEGER NOT NULL DEFAULT 1")

        resolution_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_resolutions)").fetchall()
        }
        if "snapshot_content_digest" not in resolution_columns:
            connection.execute("ALTER TABLE dispatch_resolutions ADD COLUMN snapshot_content_digest TEXT")

        observation_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(broker_order_observations)").fetchall()
        }
        observation_additions = {
            "status_raw": "TEXT NOT NULL DEFAULT ''",
            "status_normalized": "TEXT NOT NULL DEFAULT 'UNKNOWN'",
            "filled_quantity": "REAL NOT NULL DEFAULT 0",
            "average_price": "REAL NOT NULL DEFAULT 0",
            "first_seen_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in observation_additions.items():
            if column not in observation_columns:
                connection.execute(
                    f"ALTER TABLE broker_order_observations "  # noqa: S608
                    f"ADD COLUMN {column} {definition}"
                )
        connection.execute(
            """UPDATE broker_order_observations AS observation
               SET first_seen_at = COALESCE(
                   NULLIF(first_seen_at, ''),
                   (
                       SELECT MIN(current_order.first_seen_at)
                       FROM orders_current AS current_order
                       WHERE current_order.adapter_id = observation.adapter_id
                         AND current_order.account_id = observation.account_id
                         AND current_order.broker_order_id = observation.broker_order_id
                   ),
                   observed_at
               )
               WHERE first_seen_at = ''"""
        )
        connection.execute(
            """INSERT OR IGNORE INTO snapshot_generation_manifests (
                   adapter_id, account_id, generation, observed_at, content_digest
               )
               SELECT adapter_id, account_id, generation, observed_at, content_digest
               FROM snapshot_generations
               WHERE generation > 0 AND content_digest != ''"""
        )

        if previous_version < 7:
            connection.execute(
                """UPDATE dispatch_attempts AS attempt
                   SET history_complete = 0
                   WHERE dispatch_state IN (?, ?)
                      OR EXISTS (
                          SELECT 1 FROM dispatch_resolutions AS resolution
                          WHERE resolution.attempt_id = attempt.attempt_id
                            AND resolution.status != 'COMMITTED'
                      )""",
                (DISPATCH_INVOKED, DISPATCH_OUTCOME_UNKNOWN),
            )

    def _migrate_schema_v8(
        self,
        connection: sqlite3.Connection,
        *,
        previous_version: int,
    ) -> None:
        """Add immutable snapshot payloads, modify provenance, and router-clear receipts."""
        attempt_columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_attempts)")}
        attempt_additions = {
            "modify_requested_fields": "TEXT NOT NULL DEFAULT '[]'",
            "modify_baseline_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, definition in attempt_additions.items():
            if column not in attempt_columns:
                connection.execute(
                    f"ALTER TABLE dispatch_attempts ADD COLUMN {column} {definition}"  # noqa: S608
                )

        manifest_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(snapshot_generation_manifests)")
        }
        if "evidence_json" not in manifest_columns:
            connection.execute(
                "ALTER TABLE snapshot_generation_manifests ADD COLUMN evidence_json TEXT NOT NULL DEFAULT ''"
            )

        resolution_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(dispatch_resolutions)")
        }
        resolution_additions = {
            "router_clear_receipt_digest": "TEXT NOT NULL DEFAULT ''",
            "router_generation_id": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in resolution_additions.items():
            if column not in resolution_columns:
                connection.execute(
                    f"ALTER TABLE dispatch_resolutions ADD COLUMN {column} {definition}"  # noqa: S608
                )

        invalid_pending = connection.execute(
            """SELECT resolution.*
               FROM dispatch_resolutions AS resolution
               LEFT JOIN snapshot_generation_manifests AS manifest
                 ON manifest.adapter_id = (
                        SELECT attempt.adapter_id FROM dispatch_attempts AS attempt
                        WHERE attempt.attempt_id = resolution.attempt_id
                    )
                AND manifest.account_id = (
                        SELECT attempt.account_id FROM dispatch_attempts AS attempt
                        WHERE attempt.attempt_id = resolution.attempt_id
                    )
                AND manifest.generation = resolution.snapshot_generation
               WHERE resolution.status IN ('PENDING_AUDIT', 'PENDING_ROUTER_CLEAR')
                 AND (
                     ? < 8
                     OR resolution.snapshot_generation IS NULL
                     OR COALESCE(resolution.snapshot_observed_at, '') = ''
                     OR COALESCE(resolution.snapshot_content_digest, '') = ''
                     OR manifest.generation IS NULL
                     OR COALESCE(manifest.evidence_json, '') = ''
                     OR (
                         resolution.status = 'PENDING_ROUTER_CLEAR'
                         AND (
                             COALESCE(resolution.audit_reference, '') = ''
                             OR resolution.audit_recorded_at IS NULL
                         )
                     )
                 )""",
            (previous_version,),
        ).fetchall()
        recorded_at = _utc_iso(self._clock())
        for row in invalid_pending:
            payload = dict(row)
            connection.execute(
                """INSERT INTO dispatch_resolution_revisions (
                       revision_id, resolution_id, attempt_id, reason,
                       payload_json, recorded_at
                   ) VALUES (?, ?, ?, 'schema_v8_evidence_revalidation_required', ?, ?)""",
                (
                    uuid.uuid4().hex,
                    payload["resolution_id"],
                    payload["attempt_id"],
                    _canonical_json(payload),
                    recorded_at,
                ),
            )
            connection.execute(
                """UPDATE dispatch_attempts
                   SET dispatch_state = ?, error_kind = CASE
                       WHEN error_kind = '' THEN 'schema_v8_evidence_revalidation_required'
                       ELSE error_kind END
                   WHERE attempt_id = ?""",
                (
                    DISPATCH_OUTCOME_UNKNOWN,
                    payload["attempt_id"],
                ),
            )
            connection.execute(
                "DELETE FROM dispatch_resolutions WHERE resolution_id = ?",
                (payload["resolution_id"],),
            )

    def _recover_interrupted_dispatches(self, connection: sqlite3.Connection) -> None:
        """Classify attempts left non-terminal by the previous process."""
        observed = _utc_iso(self._clock())
        connection.execute(
            """UPDATE dispatch_attempts
               SET dispatch_state = ?, completed_at = ?,
                   error_kind = 'process_restart_before_invoke'
               WHERE dispatch_state = ?""",
            (
                DISPATCH_FAILED_BEFORE_INVOKE,
                observed,
                DISPATCH_PREPARED,
            ),
        )
        connection.execute(
            """UPDATE dispatch_attempts
               SET dispatch_state = ?, completed_at = ?,
                   error_kind = 'process_restart_after_invoke'
               WHERE dispatch_state = ?""",
            (
                DISPATCH_OUTCOME_UNKNOWN,
                observed,
                DISPATCH_INVOKED,
            ),
        )
        unresolved = connection.execute(
            """SELECT attempt_id, error_kind FROM dispatch_attempts AS a
                   WHERE dispatch_state = ? OR EXISTS (
                   SELECT 1 FROM dispatch_resolutions AS r
                   WHERE r.attempt_id = a.attempt_id AND r.status != 'COMMITTED'
               )
               ORDER BY prepared_at, attempt_id LIMIT 1""",
            (DISPATCH_OUTCOME_UNKNOWN,),
        ).fetchone()
        if unresolved is not None:
            connection.execute(
                """INSERT INTO ledger_health (
                       singleton, status, reason, source, attempt_id, updated_at
                   ) VALUES (1, 'CRITICAL', ?, 'outcome_unknown', ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                       status = CASE
                           WHEN ledger_health.source IN ('', 'outcome_unknown')
                           THEN excluded.status ELSE ledger_health.status END,
                       reason = CASE
                           WHEN ledger_health.source IN ('', 'outcome_unknown')
                           THEN excluded.reason ELSE ledger_health.reason END,
                       source = CASE
                           WHEN ledger_health.source IN ('', 'outcome_unknown')
                           THEN excluded.source ELSE ledger_health.source END,
                       attempt_id = CASE
                           WHEN ledger_health.source IN ('', 'outcome_unknown')
                           THEN excluded.attempt_id ELSE ledger_health.attempt_id END,
                       updated_at = CASE
                           WHEN ledger_health.source IN ('', 'outcome_unknown')
                           THEN excluded.updated_at ELSE ledger_health.updated_at END""",
                (
                    _text(unresolved["error_kind"]) or "unresolved broker outcome after process restart",
                    unresolved["attempt_id"],
                    observed,
                ),
            )

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def _migrate_unversioned_draft(self, connection: sqlite3.Connection) -> None:
        if not self._table_exists(connection, "order_lifecycle"):
            return
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(order_lifecycle)").fetchall()}
        rows = connection.execute("SELECT * FROM order_lifecycle").fetchall()
        for row in rows:
            status_raw = _text(row["status"])
            quantity = _finite_number(row["quantity"], field="quantity")
            filled = _finite_number(row["filled_quantity"], field="filled_quantity")
            observed_at = _text(row["updated_at"] or row["first_seen_at"])
            business_day = _business_date(observed_at)
            origin = _text(row["origin"]) if "origin" in columns else "flinttrade"
            origin = origin or "flinttrade"
            broker_present = int(row["broker_present"]) if "broker_present" in columns else int(row["present"])
            order_id = _text(row["order_id"])
            attempt_id: str | None = None
            if origin != "external":
                attempt_id = "migrated-" + _fingerprint(
                    {
                        "adapter_id": row["adapter_id"],
                        "account_id": row["account_id"],
                        "business_date": business_day,
                        "order_id": order_id,
                    }
                )
                connection.execute(
                    """INSERT OR IGNORE INTO dispatch_attempts (
                           attempt_id, adapter_id, account_id, business_date, operation,
                           dispatch_state, payload_fingerprint, symbol, exchange, product,
                           action, quantity, price, broker_order_id, prepared_at,
                           invoked_at, completed_at
                       ) VALUES (?, ?, ?, ?, 'legacy_import', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        attempt_id,
                        row["adapter_id"],
                        row["account_id"],
                        business_day,
                        DISPATCH_ACKNOWLEDGED,
                        _fingerprint({"legacy_order_id": order_id}),
                        row["symbol"],
                        row["exchange"],
                        row["product"],
                        row["action"],
                        quantity,
                        row["price"],
                        order_id,
                        row["first_seen_at"],
                        row["first_seen_at"],
                        observed_at,
                    ),
                )
            status = _normalise_status(status_raw, quantity=quantity, filled_quantity=filled)
            connection.execute(
                """INSERT OR IGNORE INTO orders_current (
                       adapter_id, account_id, business_date, broker_order_id, attempt_id,
                       origin, symbol, exchange, product, action, status_raw,
                       status_normalized, quantity, filled_quantity, price, average_price,
                       first_seen_at, updated_at, terminal_at, broker_present,
                       last_broker_seen_at, missing_count
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["adapter_id"],
                    row["account_id"],
                    business_day,
                    order_id,
                    attempt_id,
                    origin,
                    row["symbol"],
                    row["exchange"],
                    row["product"],
                    row["action"],
                    status_raw,
                    status,
                    quantity,
                    filled,
                    row["price"],
                    row["average_price"],
                    row["first_seen_at"],
                    observed_at,
                    row["terminal_at"],
                    broker_present,
                    observed_at if broker_present else None,
                    0 if broker_present else 1,
                ),
            )
        if not self._table_exists(connection, "order_lifecycle_events"):
            return
        event_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(order_lifecycle_events)").fetchall()
        }
        events = connection.execute("SELECT * FROM order_lifecycle_events ORDER BY event_id").fetchall()
        for event in events:
            quantity = _finite_number(event["quantity"], field="quantity")
            filled = _finite_number(event["filled_quantity"], field="filled_quantity")
            status_raw = _text(event["status"])
            status = _normalise_status(status_raw, quantity=quantity, filled_quantity=filled)
            origin = _text(event["origin"]) if "origin" in event_columns else "flinttrade"
            broker_present = (
                int(event["broker_present"]) if "broker_present" in event_columns else int(event["present"])
            )
            self._insert_event(
                connection,
                adapter_id=_text(event["adapter_id"]),
                account_id=_normalise_account(event["account_id"]),
                business_date=_business_date(event["observed_at"]),
                broker_order_id=_text(event["order_id"]),
                attempt_id=None,
                observed_at=_text(event["observed_at"]),
                source=_text(event["source"]) or "legacy_import",
                origin=origin or "flinttrade",
                status_raw=status_raw,
                status_normalized=status,
                quantity=quantity,
                filled_quantity=filled,
                average_price=(
                    _finite_number(event["average_price"], field="average_price")
                    if "average_price" in event_columns
                    else 0.0
                ),
                terminal_at=event["terminal_at"],
                broker_present=broker_present,
            )

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        adapter_id: str,
        account_id: str,
        business_date: str,
        broker_order_id: str,
        attempt_id: str | None,
        observed_at: str,
        source: str,
        origin: str,
        status_raw: str,
        status_normalized: str,
        quantity: float,
        filled_quantity: float,
        average_price: float,
        terminal_at: str | None,
        broker_present: int,
    ) -> None:
        fingerprint = _fingerprint(
            {
                "origin": origin,
                "status": status_normalized,
                "quantity": quantity,
                "filled_quantity": filled_quantity,
                "average_price": average_price,
                "terminal_at": terminal_at or "",
                "broker_present": int(broker_present),
            }
        )
        connection.execute(
            """INSERT OR IGNORE INTO order_events (
                   adapter_id, account_id, business_date, broker_order_id, attempt_id,
                   observed_at, source, origin, status_raw, status_normalized,
                   quantity, filled_quantity, average_price, terminal_at,
                   broker_present, fingerprint
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                adapter_id,
                account_id,
                business_date,
                broker_order_id,
                attempt_id,
                observed_at,
                source,
                origin,
                status_raw,
                status_normalized,
                quantity,
                filled_quantity,
                average_price,
                terminal_at,
                int(broker_present),
                fingerprint,
            ),
        )

    @staticmethod
    def _append_native_writer_manifest(
        connection: sqlite3.Connection, adapter: str, account: str, observed: str, facts: dict[str, Any],
    ) -> None:
        """Append immutable writer facts in the existing generation transaction."""
        payload = {"schema": "flinttrade.native-writer.v1", **facts}
        previous = connection.execute(
            "SELECT generation, observed_at FROM snapshot_generations WHERE adapter_id=? AND account_id=?",
            (adapter, account),
        ).fetchone()
        generation = (previous["generation"] if previous else 0) + 1
        stamp = max(observed, previous["observed_at"]) if previous else observed
        digest = _fingerprint(payload)
        connection.execute(
            "INSERT INTO snapshot_generation_manifests VALUES (?, ?, ?, ?, ?, ?)",
            (adapter, account, generation, stamp, digest, _canonical_json(payload)),
        )
        connection.execute(
            """INSERT INTO snapshot_generations VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(adapter_id, account_id) DO UPDATE SET generation=excluded.generation,
            observed_at=excluded.observed_at, content_digest=excluded.content_digest""",
            (adapter, account, generation, stamp, digest),
        )

    def native_dispatch_evidence(self, attempt_id: str) -> list[dict[str, Any]]:
        """Read retained non-secret writer facts, checking every relevant seal.

        Native order date and resource/leg identifiers remain unknown unless
        independently observed. This read neither resolves a current account
        alias nor establishes that an acknowledged order executed.

        Args:
            attempt_id: Exact durable attempt identifier.

        Returns:
            Detached chronological prepared/ACK facts; empty for an unknown attempt.

        Raises:
            LifecycleStateError: If a retained manifest fails its integrity check.
        """
        with self._connection() as connection:
            attempt = connection.execute(
                "SELECT adapter_id, account_id FROM dispatch_attempts WHERE attempt_id=?", (attempt_id,),
            ).fetchone()
            if attempt is None:
                return []
            return self._native_writer_rows(connection, attempt["adapter_id"], attempt["account_id"], attempt_id)

    @staticmethod
    def _native_writer_rows(
        connection: sqlite3.Connection, adapter: str, account: str, attempt_id: str | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for row in connection.execute(
            "SELECT generation, evidence_json, content_digest FROM snapshot_generation_manifests "
            "WHERE adapter_id=? AND account_id=? ORDER BY generation", (adapter, account),
        ):
            try:
                if row["evidence_json"]:
                    payload = json.loads(row["evidence_json"])
                    if type(payload) is not dict or _canonical_json(payload) != row["evidence_json"]:
                        raise ValueError
                else:
                    payload = OrderLifecycleLedger._snapshot_payload_from_tables(
                        connection, adapter_id=adapter, account_id=account, generation=row["generation"],
                    )
                if _fingerprint(payload) != row["content_digest"]:
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise LifecycleStateError("native writer manifest integrity failure") from exc
            if (payload.get("schema") == "flinttrade.native-writer.v1"
                    and (attempt_id is None or payload.get("attempt_id") == attempt_id)):
                result.append(payload)
        return result

    def record_native_acknowledgement(self, attempt_id: str, result: Any, *, native_source: object) -> None:
        """Retain a genuine full ACK set independently of legacy state projection.

        A late or multi-ID ACK is still evidence of the same attempt; it cannot
        clear uncertainty or regress a reconciled state. Projection continues
        through the unchanged acknowledge method with its existing guards.

        Args:
            attempt_id: The attempt created in the same verified invocation frame.
            result: Actual scalar or recognised typed adapter acknowledgement.
            native_source: Retained active invocation witness, never a request DTO.

        Raises:
            ValueError: If there is no authentic active ACK frontier or full ID set.
            LifecycleStateError: If the durable attempt/receipt correspondence fails.
        """
        from flinttrade_gateway.writer_provenance import acknowledged_facts  # noqa: PLC0415

        facts = acknowledged_facts(native_source, attempt_id, result)
        with self._connection(write=True) as connection:
            attempt = connection.execute(
                "SELECT adapter_id, account_id FROM dispatch_attempts WHERE attempt_id=?", (attempt_id,),
            ).fetchone()
            if attempt is None:
                raise LifecycleStateError("native acknowledgement attempt is missing")
            rows = self._native_writer_rows(connection, attempt["adapter_id"], attempt["account_id"], attempt_id)
            prepared = [row for row in rows if row["kind"] == "prepared"]
            if len(prepared) != 1 or prepared[0]["facts"]["invocation_id"] != facts["invocation_id"]:
                raise LifecycleStateError("native acknowledgement does not match its original writer")
            self._append_native_writer_manifest(connection, attempt["adapter_id"], attempt["account_id"],
                                                _utc_iso(), facts)

    def prepare_dispatch(
        self,
        *,
        adapter_id: str,
        account_id: str,
        operation: str,
        request_context: Any,
        payload: Any,
        observed_at: datetime | str | None = None,
        native_source: object | None = None,
    ) -> str:
        """Durably record one broker-write attempt and verified native facts atomically."""
        adapter = _text(adapter_id).lower()
        account = _normalise_account(account_id)
        operation = _text(operation)
        if not adapter or not operation:
            raise ValueError("adapter_id and operation are required")
        intent = _canonical_intent(payload)
        requested_modify_fields = (
            _canonical_modify_requested_fields(payload) if operation == "modify_order" else []
        )
        item_intents: tuple[dict[str, Any], ...] = ()
        if operation == "place_multi_order":
            source = _mapping(payload)
            orders = source.get("orders")
            if not isinstance(orders, (list, tuple)):
                raise ValueError("multi-order dispatch requires an ordered list of orders")
            item_intents = tuple(_canonical_intent(order) for order in orders)
        observed = _utc_iso(observed_at)
        business_day = _business_date(observed_at)
        jti = _text(getattr(request_context, "jti", ""))
        attempt_id = uuid.uuid4().hex
        native_facts = None
        if native_source is not None:
            from flinttrade_gateway.writer_provenance import prepared_facts  # noqa: PLC0415

            native_facts = prepared_facts(native_source, adapter_id=adapter, account_id=account,
                                          operation=operation, request_context=request_context,
                                          payload=payload, attempt_id=attempt_id)
        with self._connection(write=True) as connection:
            if native_facts is not None:
                self._append_native_writer_manifest(connection, adapter, account, observed, native_facts)
            modify_baseline: dict[str, Any] = {}
            if operation == "modify_order" and requested_modify_fields:
                target_id = intent["broker_order_id"]
                baseline_row = connection.execute(
                    """SELECT * FROM broker_order_observations
                       WHERE adapter_id = ? AND account_id = ? AND broker_order_id = ?
                         AND observed_at <= ?
                       ORDER BY generation DESC LIMIT 1""",
                    (adapter, account, target_id, observed),
                ).fetchone()
                if baseline_row is not None:
                    modify_baseline = {
                        field: baseline_row[field]
                        for field in requested_modify_fields
                    }
                    requested_modify_fields = [
                        field
                        for field in requested_modify_fields
                        if not _recovery_field_equal(field, baseline_row[field], intent[field])
                    ]
                    modify_baseline = {
                        field: modify_baseline[field]
                        for field in requested_modify_fields
                    }
            requested_modify_json = _canonical_json(requested_modify_fields)
            modify_baseline_json = _canonical_json(modify_baseline)
            connection.execute(
                """INSERT INTO dispatch_attempts (
                       attempt_id, adapter_id, account_id, business_date, operation,
                       dispatch_state, request_jti_hash, actor_type, actor_id,
                       intent_source, payload_fingerprint, symbol, exchange, product,
                       action, quantity, price, trigger_price, price_type, variety,
                       validity, strategy, modify_requested_fields,
                       modify_baseline_json, broker_order_id, prepared_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    attempt_id,
                    adapter,
                    account,
                    business_day,
                    operation,
                    DISPATCH_PREPARED,
                    hashlib.sha256(jti.encode("utf-8")).hexdigest() if jti else "",
                    _text(getattr(request_context, "actor_type", "")),
                    _text(getattr(request_context, "actor_id", "")),
                    _text(getattr(request_context, "intent_source", "")),
                    _fingerprint({
                        "intent": intent,
                        "items": item_intents,
                        "modify_requested_fields": requested_modify_fields,
                        "modify_baseline": modify_baseline,
                    }),
                    intent["symbol"],
                    intent["exchange"],
                    intent["product"],
                    intent["action"],
                    intent["quantity"],
                    intent["price"],
                    intent["trigger_price"],
                    intent["price_type"],
                    intent["variety"],
                    intent["validity"],
                    intent["strategy"],
                    requested_modify_json,
                    modify_baseline_json,
                    intent["broker_order_id"] or None,
                    observed,
                ),
            )
            for item_index, item in enumerate(item_intents):
                connection.execute(
                    """INSERT INTO dispatch_items (
                           attempt_id, item_index, symbol, exchange, product,
                           action, quantity, price, trigger_price, price_type,
                           variety, validity, strategy
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        attempt_id,
                        item_index,
                        item["symbol"],
                        item["exchange"],
                        item["product"],
                        item["action"],
                        item["quantity"],
                        item["price"],
                        item["trigger_price"],
                        item["price_type"],
                        item["variety"],
                        item["validity"],
                        item["strategy"],
                    ),
                )
        return attempt_id

    def _transition_attempt(
        self,
        attempt_id: str,
        *,
        expected: tuple[str, ...],
        target: str,
        observed_at: datetime | str | None,
        error_kind: str = "",
    ) -> None:
        if target not in _DISPATCH_STATES:
            raise ValueError(f"unknown dispatch state {target!r}")
        observed = _utc_iso(observed_at)
        invoked_at = observed if target == DISPATCH_INVOKED else None
        completed_at = (
            observed
            if target
            in {
                DISPATCH_ACKNOWLEDGED,
                DISPATCH_FAILED_BEFORE_INVOKE,
                DISPATCH_OUTCOME_UNKNOWN,
                DISPATCH_CONFIRMED_APPLIED,
                DISPATCH_CONFIRMED_NOT_APPLIED,
                DISPATCH_CONFIRMED_PARTIAL,
            }
            else None
        )
        placeholders = ",".join("?" for _ in expected)
        sql = (
            "UPDATE dispatch_attempts SET dispatch_state = ?, "
            "invoked_at = COALESCE(?, invoked_at), completed_at = COALESCE(?, completed_at), "
            "error_kind = ? WHERE attempt_id = ? AND dispatch_state IN (" + placeholders + ")"
        )
        with self._connection(write=True) as connection:
            cursor = connection.execute(
                sql,
                (target, invoked_at, completed_at, _text(error_kind), _text(attempt_id), *expected),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT dispatch_state FROM dispatch_attempts WHERE attempt_id = ?",
                    (_text(attempt_id),),
                ).fetchone()
                current = "missing" if row is None else str(row["dispatch_state"])
                raise LifecycleStateError(f"dispatch attempt {attempt_id!r} cannot move from {current} to {target}")

    def mark_invoked(
        self,
        attempt_id: str,
        *,
        observed_at: datetime | str | None = None,
    ) -> None:
        self._transition_attempt(
            attempt_id,
            expected=(DISPATCH_PREPARED,),
            target=DISPATCH_INVOKED,
            observed_at=observed_at,
        )

    def mark_failed_before_invoke(
        self,
        attempt_id: str,
        error_kind: str,
        *,
        observed_at: datetime | str | None = None,
    ) -> None:
        self._transition_attempt(
            attempt_id,
            expected=(DISPATCH_PREPARED,),
            target=DISPATCH_FAILED_BEFORE_INVOKE,
            observed_at=observed_at,
            error_kind=error_kind,
        )

    def mark_outcome_unknown(
        self,
        attempt_id: str,
        error_kind: str,
        *,
        observed_at: datetime | str | None = None,
    ) -> None:
        self._transition_attempt(
            attempt_id,
            expected=(DISPATCH_INVOKED,),
            target=DISPATCH_OUTCOME_UNKNOWN,
            observed_at=observed_at,
            error_kind=error_kind,
        )
        observed = _utc_iso(observed_at)
        with self._connection(write=True) as connection:
            self._refresh_outcome_health(connection, observed_at=observed)

    def acknowledge(
        self,
        attempt_id: str,
        result: Any,
        *,
        observed_at: datetime | str | None = None,
        _expected_state: str = DISPATCH_INVOKED,
        _target_state: str = DISPATCH_ACKNOWLEDGED,
        _event_source: str = "gated_dispatch_acknowledged",
    ) -> None:
        """Record an adapter acknowledgement without storing its unrestricted payload."""
        if _expected_state not in _DISPATCH_STATES or _target_state not in _DISPATCH_STATES:
            raise ValueError("invalid internal acknowledgement transition")
        observed = _utc_iso(observed_at)
        with self._connection(write=True) as connection:
            self._acknowledge_in_transaction(
                connection,
                attempt_id=_text(attempt_id),
                result=result,
                observed_at=observed,
                expected_state=_expected_state,
                target_state=_target_state,
                event_source=_event_source,
                require_observed_match=False,
                recovery_business_date=None,
            )

    def _acknowledge_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        attempt_id: str,
        result: Any,
        observed_at: str,
        expected_state: str,
        target_state: str,
        event_source: str,
        require_observed_match: bool,
        recovery_business_date: str | None,
    ) -> None:
        """Apply one acknowledgement inside the caller's SQLite transaction."""
        attempt = connection.execute(
            "SELECT * FROM dispatch_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        if attempt is None or attempt["dispatch_state"] != expected_state:
            current = "missing" if attempt is None else str(attempt["dispatch_state"])
            raise LifecycleStateError(f"dispatch attempt {attempt_id!r} cannot be acknowledged from {current}")
        try:
            assignments = _broker_order_assignments(result)
        except ValueError as exc:
            raise LifecycleStateError(str(exc)) from exc
        result_ids = tuple(order_id for order_id, _item_index in assignments)
        existing_id = _text(attempt["broker_order_id"])
        operation = _text(attempt["operation"])
        is_placement = operation in _REGULAR_PLACEMENT_OPERATIONS
        item_rows = connection.execute(
            "SELECT * FROM dispatch_items WHERE attempt_id = ? ORDER BY item_index",
            (attempt_id,),
        ).fetchall()
        error_kind = ""
        if operation == "place_multi_order":
            try:
                error_kind = _multi_order_error_kind(
                    result,
                    expected_count=len(item_rows),
                    result_count=len(result_ids),
                )
            except ValueError as exc:
                raise LifecycleStateError(str(exc)) from exc
        elif is_placement and len(result_ids) > 1:
            raise LifecycleStateError("broker placement acknowledgement contains multiple order ids")
        elif is_placement and not result_ids and _explicit_reducing_noop(operation, result):
            error_kind = "position_already_flat"
        elif is_placement and not result_ids and not existing_id:
            raise LifecycleStateError("broker placement acknowledgement has no canonical order id")

        resolved_intents: list[tuple[str, Mapping[str, Any], int | None]] = []
        if operation == "place_multi_order":
            resolved_assignments = list(assignments)
            if assignments and all(item_index is None for _order_id, item_index in assignments):
                if len(assignments) == len(item_rows):
                    resolved_assignments = [
                        (order_id, int(item["item_index"]))
                        for (order_id, _item_index), item in zip(assignments, item_rows, strict=True)
                    ]
            used_indexes: set[int] = set()
            for order_id, item_index in resolved_assignments:
                intent: Mapping[str, Any] = attempt
                if item_index is not None:
                    if item_index < 0 or item_index >= len(item_rows) or item_index in used_indexes:
                        raise LifecycleStateError("broker acknowledgement contains an invalid basket correlation")
                    used_indexes.add(item_index)
                    intent = item_rows[item_index]
                resolved_intents.append((order_id, intent, item_index))
        elif is_placement and result_ids:
            resolved_intents.append((result_ids[0], attempt, None))

        observed_orders: dict[str, tuple[sqlite3.Row | None, str]] = {}
        for order_id, intent, item_index in resolved_intents:
            if expected_state == DISPATCH_OUTCOME_UNKNOWN:
                existing_rows = connection.execute(
                    """SELECT * FROM orders_current
                       WHERE adapter_id = ? AND account_id = ? AND broker_order_id = ?
                       ORDER BY broker_present DESC, last_seen_generation DESC,
                                CASE WHEN origin = 'flinttrade' THEN 0 ELSE 1 END,
                                business_date DESC""",
                    (attempt["adapter_id"], attempt["account_id"], order_id),
                ).fetchall()
            else:
                existing_rows = connection.execute(
                    """SELECT * FROM orders_current
                       WHERE adapter_id = ? AND account_id = ? AND business_date = ?
                         AND broker_order_id = ?""",
                    (
                        attempt["adapter_id"],
                        attempt["account_id"],
                        attempt["business_date"],
                        order_id,
                    ),
                ).fetchall()
            existing_order = existing_rows[0] if existing_rows else None
            projection_business_date = (
                recovery_business_date
                if expected_state == DISPATCH_OUTCOME_UNKNOWN and recovery_business_date
                else str(existing_order["business_date"])
                if existing_order is not None
                else str(attempt["business_date"])
            )
            if require_observed_match and (existing_order is None or int(existing_order["broker_present"]) != 1):
                raise LifecycleStateError(f"broker order {order_id!r} has no present broker observation")
            if existing_order is not None and int(existing_order["broker_present"]) == 1:
                if not _broker_order_matches_intent(existing_order, intent):
                    suffix = f" child {item_index}" if item_index is not None else ""
                    raise LifecycleStateError(f"broker order {order_id!r} does not match{suffix} persisted intent")
            for duplicate in existing_rows[1:]:
                duplicate_attempt = _text(duplicate["attempt_id"])
                if duplicate["origin"] == "flinttrade" and duplicate_attempt not in {"", attempt_id}:
                    raise LifecycleStateError("broker order id is already associated with another dispatch attempt")
                connection.execute(
                    """DELETE FROM orders_current
                       WHERE adapter_id = ? AND account_id = ? AND business_date = ?
                         AND broker_order_id = ?""",
                    (
                        attempt["adapter_id"],
                        attempt["account_id"],
                        duplicate["business_date"],
                        order_id,
                    ),
                )
            observed_orders[order_id] = (existing_order, projection_business_date)

        broker_order_id = None
        if operation != "place_multi_order":
            broker_order_id = result_ids[0] if len(result_ids) == 1 else existing_id or None
        if expected_state == DISPATCH_OUTCOME_UNKNOWN:
            completion_at = _text(attempt["completed_at"]) or observed_at
            persisted_error_kind = _text(attempt["error_kind"])
        else:
            completion_at = observed_at
            persisted_error_kind = error_kind
        connection.execute(
            """UPDATE dispatch_attempts
               SET dispatch_state = ?, broker_order_id = ?, completed_at = ?, error_kind = ?
               WHERE attempt_id = ?""",
            (
                target_state,
                broker_order_id,
                completion_at,
                persisted_error_kind,
                attempt_id,
            ),
        )
        for order_id, intent, item_index in resolved_intents:
            if item_index is not None:
                connection.execute(
                    "UPDATE dispatch_items SET broker_order_id = ? WHERE attempt_id = ? AND item_index = ?",
                    (order_id, attempt_id, item_index),
                )
            existing_order, projection_business_date = observed_orders[order_id]
            if existing_order is not None:
                prior_attempt = _text(existing_order["attempt_id"])
                if prior_attempt and prior_attempt != attempt_id:
                    raise LifecycleStateError("broker order id is already associated with another dispatch attempt")
                connection.execute(
                    """UPDATE orders_current SET
                           business_date = ?, attempt_id = ?, origin = 'flinttrade', symbol = ?,
                           exchange = ?, product = ?, action = ?, quantity = ?,
                           price = ?, trigger_price = ?, price_type = ?,
                           variety = ?, validity = ?, strategy = ?, updated_at = ?
                       WHERE adapter_id = ? AND account_id = ? AND business_date = ?
                         AND broker_order_id = ?""",
                    (
                        projection_business_date,
                        attempt_id,
                        intent["symbol"],
                        intent["exchange"],
                        intent["product"],
                        intent["action"],
                        intent["quantity"],
                        intent["price"],
                        intent["trigger_price"],
                        intent["price_type"],
                        intent["variety"],
                        intent["validity"],
                        intent["strategy"],
                        observed_at,
                        attempt["adapter_id"],
                        attempt["account_id"],
                        existing_order["business_date"],
                        order_id,
                    ),
                )
                status_raw = str(existing_order["status_raw"])
                status_normalized = str(existing_order["status_normalized"])
                filled_quantity = float(existing_order["filled_quantity"])
                average_price = float(existing_order["average_price"])
                terminal_at = existing_order["terminal_at"]
                broker_present = int(existing_order["broker_present"])
            else:
                connection.execute(
                    """INSERT INTO orders_current (
                           adapter_id, account_id, business_date, broker_order_id, attempt_id,
                           origin, symbol, exchange, product, action, status_raw,
                           status_normalized, quantity, filled_quantity, price,
                           trigger_price, price_type, variety, validity, strategy, average_price,
                           first_seen_at, updated_at, broker_present
                       ) VALUES (?, ?, ?, ?, ?, 'flinttrade', ?, ?, ?, ?, 'SUBMITTED',
                                 'SUBMITTED', ?, 0, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0)""",
                    (
                        attempt["adapter_id"],
                        attempt["account_id"],
                        projection_business_date,
                        order_id,
                        attempt_id,
                        intent["symbol"],
                        intent["exchange"],
                        intent["product"],
                        intent["action"],
                        intent["quantity"],
                        intent["price"],
                        intent["trigger_price"],
                        intent["price_type"],
                        intent["variety"],
                        intent["validity"],
                        intent["strategy"],
                        attempt["prepared_at"],
                        observed_at,
                    ),
                )
                status_raw = "SUBMITTED"
                status_normalized = "SUBMITTED"
                filled_quantity = 0.0
                average_price = 0.0
                terminal_at = None
                broker_present = 0
            self._insert_event(
                connection,
                adapter_id=attempt["adapter_id"],
                account_id=attempt["account_id"],
                business_date=projection_business_date,
                broker_order_id=order_id,
                attempt_id=attempt_id,
                observed_at=observed_at,
                source=event_source,
                origin="flinttrade",
                status_raw=status_raw,
                status_normalized=status_normalized,
                quantity=float(intent["quantity"]),
                filled_quantity=filled_quantity,
                average_price=average_price,
                terminal_at=terminal_at,
                broker_present=broker_present,
            )

    @staticmethod
    def _resolution_dict(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        for field in (
            "broker_order_ids",
            "broker_order_item_indexes",
            "not_applied_item_indexes",
        ):
            try:
                values = json.loads(str(payload.get(field) or "[]"))
            except json.JSONDecodeError:  # pragma: no cover - database corruption guard
                values = []
            payload[field] = values if isinstance(values, list) else []
        return payload

    @staticmethod
    def _canonical_resolution_indexes(values: Iterable[Any], *, field: str) -> list[int]:
        if isinstance(values, (str, bytes, Mapping)):
            raise ValueError(f"{field} must be an ordered list")
        indexes: list[int] = []
        for value in values:
            if isinstance(value, bool):
                raise ValueError(f"{field} must contain non-negative integers")
            try:
                index = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{field} must contain non-negative integers") from exc
            if index < 0 or str(value) != str(index):
                raise ValueError(f"{field} must contain non-negative integers")
            indexes.append(index)
        if len(set(indexes)) != len(indexes):
            raise ValueError(f"{field} must not contain duplicates")
        return indexes

    @staticmethod
    def _snapshot_payload_from_tables(
        connection: sqlite3.Connection,
        *,
        adapter_id: str,
        account_id: str,
        generation: int,
    ) -> dict[str, list[dict[str, Any]]]:
        order_rows = connection.execute(
            """SELECT broker_order_id, symbol, exchange, product, action,
                      status_raw, status_normalized, quantity, filled_quantity,
                      price, trigger_price, price_type, variety, validity,
                      strategy, average_price, first_seen_at
               FROM broker_order_observations
               WHERE adapter_id = ? AND account_id = ? AND generation = ?
               ORDER BY broker_order_id""",
            (adapter_id, account_id, generation),
        ).fetchall()
        position_rows = connection.execute(
            """SELECT row_key, symbol, exchange, product, quantity, average_price
               FROM position_generation_observations
               WHERE adapter_id = ? AND account_id = ? AND generation = ?
               ORDER BY row_key""",
            (adapter_id, account_id, generation),
        ).fetchall()
        holding_rows = connection.execute(
            """SELECT row_key, symbol, exchange, quantity, average_price
               FROM holding_generation_observations
               WHERE adapter_id = ? AND account_id = ? AND generation = ?
               ORDER BY row_key""",
            (adapter_id, account_id, generation),
        ).fetchall()
        return {
            "orders": [
                {
                    "orderid": row["broker_order_id"],
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "product": row["product"],
                    "action": row["action"],
                    "status_raw": row["status_raw"],
                    "status_normalized": row["status_normalized"],
                    "quantity": float(row["quantity"]),
                    "filled_quantity": float(row["filled_quantity"]),
                    "price": float(row["price"]),
                    "trigger_price": float(row["trigger_price"]),
                    "price_type": row["price_type"],
                    "variety": row["variety"],
                    "validity": row["validity"],
                    "strategy": row["strategy"],
                    "average_price": float(row["average_price"]),
                    "first_seen_at": row["first_seen_at"],
                }
                for row in order_rows
            ],
            "positions": [
                {
                    "key": row["row_key"],
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "product": row["product"],
                    "quantity": float(row["quantity"]),
                    "average_price": float(row["average_price"]),
                }
                for row in position_rows
            ],
            "holdings": [
                {
                    "key": row["row_key"],
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "product": "",
                    "quantity": float(row["quantity"]),
                    "average_price": float(row["average_price"]),
                }
                for row in holding_rows
            ],
        }

    @classmethod
    def _verify_snapshot_evidence(
        cls,
        connection: sqlite3.Connection,
        *,
        adapter_id: str,
        account_id: str,
        generation: int,
        content_digest: str,
        evidence_json: str,
    ) -> None:
        if not evidence_json:
            raise LifecycleStateError(
                "snapshot evidence predates immutable generation payloads; adopt a newer forced snapshot"
            )
        try:
            stored_payload = json.loads(evidence_json)
        except json.JSONDecodeError as exc:
            raise LifecycleStateError("snapshot evidence payload is corrupt") from exc
        if not isinstance(stored_payload, dict) or _canonical_json(stored_payload) != evidence_json:
            raise LifecycleStateError("snapshot evidence payload is not canonical")
        actual_payload = cls._snapshot_payload_from_tables(
            connection,
            adapter_id=adapter_id,
            account_id=account_id,
            generation=generation,
        )
        if actual_payload != stored_payload or _fingerprint(actual_payload) != content_digest:
            raise LifecycleStateError(
                "snapshot evidence rows no longer match their immutable generation manifest"
            )

    @staticmethod
    def _fresh_snapshot_evidence(
        connection: sqlite3.Connection,
        *,
        attempt: sqlite3.Row,
        required_generation: int | None = None,
    ) -> tuple[int, str, str]:
        if required_generation is None:
            snapshot = connection.execute(
                """SELECT generation, observed_at, content_digest, evidence_json
                   FROM snapshot_generation_manifests
                   WHERE adapter_id = ? AND account_id = ?
                   ORDER BY generation DESC LIMIT 1""",
                (attempt["adapter_id"], attempt["account_id"]),
            ).fetchone()
        else:
            snapshot = connection.execute(
                """SELECT generation, observed_at, content_digest, evidence_json
                   FROM snapshot_generation_manifests
                   WHERE adapter_id = ? AND account_id = ? AND generation = ?""",
                (
                    attempt["adapter_id"],
                    attempt["account_id"],
                    required_generation,
                ),
            ).fetchone()
        unknown_at = _text(attempt["completed_at"] or attempt["invoked_at"])
        if (
            snapshot is None
            or not unknown_at
            or _utc_datetime(str(snapshot["observed_at"])) <= _utc_datetime(unknown_at)
            or not _text(snapshot["content_digest"])
        ):
            raise LifecycleStateError("outcome resolution requires a newer reconciliation snapshot for this account")
        OrderLifecycleLedger._verify_snapshot_evidence(
            connection,
            adapter_id=str(attempt["adapter_id"]),
            account_id=str(attempt["account_id"]),
            generation=int(snapshot["generation"]),
            content_digest=str(snapshot["content_digest"]),
            evidence_json=str(snapshot["evidence_json"] or ""),
        )
        return (
            int(snapshot["generation"]),
            str(snapshot["observed_at"]),
            str(snapshot["content_digest"]),
        )

    @staticmethod
    def _fresh_present_orders(
        connection: sqlite3.Connection,
        *,
        attempt: sqlite3.Row,
        generation: int,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """SELECT * FROM broker_order_observations
               WHERE adapter_id = ? AND account_id = ? AND generation = ?""",
            (
                attempt["adapter_id"],
                attempt["account_id"],
                generation,
            ),
        ).fetchall()

    @staticmethod
    def _broker_orders_first_observed_after_invocation(
        connection: sqlite3.Connection,
        *,
        attempt: sqlite3.Row,
        generation: int,
    ) -> list[sqlite3.Row]:
        """Return durable broker observations that could belong to this attempt."""
        invoked_at = _text(attempt["invoked_at"])
        if not invoked_at:
            raise LifecycleStateError("dispatch attempt has no durable invocation timestamp")
        return connection.execute(
            """SELECT * FROM broker_order_observations
               WHERE adapter_id = ? AND account_id = ?
                 AND generation <= ? AND first_seen_at > ?""",
            (
                attempt["adapter_id"],
                attempt["account_id"],
                generation,
                invoked_at,
            ),
        ).fetchall()

    @staticmethod
    def _fresh_target_order(
        connection: sqlite3.Connection,
        *,
        attempt: sqlite3.Row,
        generation: int,
    ) -> sqlite3.Row:
        target_id = _canonical_broker_order_id(attempt["broker_order_id"])
        if not target_id:
            raise LifecycleStateError(
                "operation-specific evidence is unavailable because the target order id is missing"
            )
        row = connection.execute(
            """SELECT * FROM broker_order_observations
               WHERE adapter_id = ? AND account_id = ?
                 AND broker_order_id = ? AND generation = ?""",
            (
                attempt["adapter_id"],
                attempt["account_id"],
                target_id,
                generation,
            ),
        ).fetchone()
        if row is None:
            raise LifecycleStateError(f"target broker order {target_id!r} has no fresh operation-specific evidence")
        return row

    def _validate_resolution_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        attempt: sqlite3.Row,
        outcome: str,
        broker_order_ids: list[str],
        broker_order_item_indexes: list[int],
        not_applied_item_indexes: list[int],
        generation: int,
    ) -> None:
        if int(attempt["history_complete"]) != 1 and (
            outcome in {"confirmed_not_applied", "confirmed_partial"} or not_applied_item_indexes
        ):
            raise LifecycleStateError(
                "broker identity history is incomplete; negative recovery evidence is unavailable"
            )
        operation = _text(attempt["operation"])
        present_orders = self._fresh_present_orders(
            connection,
            attempt=attempt,
            generation=generation,
        )
        present_by_id = {str(row["broker_order_id"]): row for row in present_orders}
        historical_orders = self._broker_orders_first_observed_after_invocation(
            connection,
            attempt=attempt,
            generation=generation,
        )

        if operation in _REGULAR_PLACEMENT_OPERATIONS:
            intents = (
                connection.execute(
                    "SELECT * FROM dispatch_items WHERE attempt_id = ? ORDER BY item_index",
                    (attempt["attempt_id"],),
                ).fetchall()
                if operation == "place_multi_order"
                else [attempt]
            )
            applied_pairs = (
                list(zip(broker_order_item_indexes, broker_order_ids, strict=True))
                if operation == "place_multi_order"
                else [(0, broker_order_ids[0])]
                if broker_order_ids
                else []
            )
            for item_index, order_id in applied_pairs:
                row = present_by_id.get(order_id)
                if row is None:
                    raise LifecycleStateError(f"broker order {order_id!r} has no present broker observation")
                if not _broker_order_matches_intent(
                    row,
                    intents[item_index],
                    require_material_fields=True,
                ):
                    child = f" child {item_index}" if operation == "place_multi_order" else ""
                    raise LifecycleStateError(f"broker order {order_id!r} does not match{child} persisted intent")
                first_seen_at = _text(row["first_seen_at"])
                invoked_at = _text(attempt["invoked_at"])
                if not first_seen_at or not invoked_at or _utc_datetime(first_seen_at) <= _utc_datetime(invoked_at):
                    child = f" child {item_index}" if operation == "place_multi_order" else ""
                    raise LifecycleStateError(
                        f"broker order {order_id!r}{child} was not first observed after invocation"
                    )

            applied_ids = set(broker_order_ids)
            absent_indexes = (
                not_applied_item_indexes
                if operation == "place_multi_order"
                else [0]
                if outcome == "confirmed_not_applied"
                else []
            )
            for item_index in absent_indexes:
                intent = intents[item_index]
                if any(
                    str(row["broker_order_id"]) not in applied_ids and _broker_order_matches_core_intent(row, intent)
                    for row in historical_orders
                ):
                    child = f" child {item_index}" if operation == "place_multi_order" else ""
                    raise LifecycleStateError(
                        f"not-applied{child} evidence conflicts with a durable matching broker order"
                    )
            return

        if operation == "modify_order":
            target = self._fresh_target_order(
                connection,
                attempt=attempt,
                generation=generation,
            )
            change_state = _broker_order_requested_change_state(target, attempt)
            if outcome == "confirmed_applied" and change_state != "applied":
                raise LifecycleStateError("fresh broker order does not contain the requested modification")
            if outcome == "confirmed_not_applied" and change_state != "not_applied":
                raise LifecycleStateError(
                    "fresh broker order does not prove that none of the requested modification applied"
                )
            return

        if operation in {"cancel_order", "cancel_smart_order"}:
            target = self._fresh_target_order(
                connection,
                attempt=attempt,
                generation=generation,
            )
            status = str(target["status_normalized"])
            cancelled = status == "CANCELLED"
            if outcome == "confirmed_applied" and not cancelled:
                raise LifecycleStateError("fresh broker order is not cancelled")
            if outcome == "confirmed_not_applied" and status not in {
                "OPEN",
                "PENDING",
                "SUBMITTED",
                "PARTIALLY_FILLED",
            }:
                raise LifecycleStateError("fresh broker order does not conclusively prove cancellation was not applied")
            return

        raise LifecycleStateError(
            f"operation-specific evidence is not available for {operation!r}; outcome remains blocked"
        )

    def prepare_outcome_resolution(
        self,
        *,
        attempt_id: str,
        adapter_id: str,
        account_id: str,
        business_date: str,
        outcome: str,
        broker_order_ids: Iterable[Any],
        broker_order_item_indexes: Iterable[Any] = (),
        not_applied_item_indexes: Iterable[Any] = (),
        actor_type: str,
        actor_id: str,
        note: str = "",
        required_snapshot_generation: int | None = None,
        observed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Persist one exact operator decision without releasing the write block."""
        attempt_key = _text(attempt_id)
        adapter = _text(adapter_id).lower()
        account = _text(account_id)
        business_day = _text(business_date)
        resolution_outcome = _text(outcome).lower()
        principal_type = _text(actor_type)
        principal_id = _text(actor_id)
        resolution_note = _text(note)
        if resolution_outcome not in _RESOLUTION_OUTCOMES:
            raise ValueError("outcome must be confirmed_applied, confirmed_not_applied, or confirmed_partial")
        if not attempt_key or not adapter or not account or not business_day:
            raise ValueError("attempt_id, adapter_id, account_id, and business_date are required")
        if not principal_type or not principal_id:
            raise ValueError("actor_type and actor_id are required")
        if len(resolution_note) > 500:
            raise ValueError("note must not exceed 500 characters")
        if isinstance(broker_order_ids, (str, bytes, Mapping)):
            raise ValueError("broker_order_ids must be an ordered list")
        canonical_ids: list[str] = []
        for candidate in broker_order_ids:
            order_id = _canonical_broker_order_id(candidate)
            if not order_id:
                raise ValueError("broker_order_ids must contain canonical non-empty strings")
            canonical_ids.append(order_id)
        if len(set(canonical_ids)) != len(canonical_ids):
            raise ValueError("broker_order_ids must not contain duplicates")
        canonical_item_indexes = self._canonical_resolution_indexes(
            broker_order_item_indexes,
            field="broker_order_item_indexes",
        )
        canonical_not_applied_indexes = self._canonical_resolution_indexes(
            not_applied_item_indexes,
            field="not_applied_item_indexes",
        )

        observed = _utc_iso(observed_at)
        with self._outcome_resolution_lock, self._connection(write=True) as connection:
            attempt = connection.execute(
                "SELECT * FROM dispatch_attempts WHERE attempt_id = ?",
                (attempt_key,),
            ).fetchone()
            if attempt is None:
                raise LifecycleStateError(f"dispatch attempt {attempt_key!r} does not exist")
            expected_selector = (
                str(attempt["adapter_id"]),
                str(attempt["account_id"]),
                str(attempt["business_date"]),
            )
            if expected_selector != (adapter, account, business_day):
                raise LifecycleStateError("resolution selector does not match dispatch attempt")
            if attempt["dispatch_state"] not in {
                DISPATCH_OUTCOME_UNKNOWN,
                DISPATCH_CONFIRMED_APPLIED,
                DISPATCH_CONFIRMED_NOT_APPLIED,
                DISPATCH_CONFIRMED_PARTIAL,
            }:
                raise LifecycleStateError(f"dispatch attempt {attempt_key!r} is not awaiting outcome resolution")
            operation = _text(attempt["operation"])
            is_placement = operation in _REGULAR_PLACEMENT_OPERATIONS
            item_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM dispatch_items WHERE attempt_id = ?",
                    (attempt_key,),
                ).fetchone()[0]
            )
            if resolution_outcome in {"confirmed_not_applied", "confirmed_partial"} and not resolution_note:
                raise ValueError(f"{resolution_outcome} requires a non-empty operator note")
            if not is_placement and (canonical_ids or canonical_item_indexes or canonical_not_applied_indexes):
                raise ValueError("non-placement recovery does not accept broker order or basket correlations")
            if resolution_outcome == "confirmed_partial" and operation != "place_multi_order":
                raise ValueError("confirmed_partial is only valid for multi-order recovery")

            if operation == "place_multi_order":
                if operation == "place_multi_order" and item_count == 0:
                    raise ValueError(f"{resolution_outcome} multi-order requires at least one persisted child intent")
                if len(canonical_ids) != len(canonical_item_indexes):
                    raise ValueError("each applied broker order id requires one explicit child index")
                all_indexes = set(range(item_count))
                applied_indexes = set(canonical_item_indexes)
                absent_indexes = set(canonical_not_applied_indexes)
                if not (applied_indexes | absent_indexes) == all_indexes or applied_indexes & absent_indexes:
                    raise ValueError("applied and not-applied indexes must partition every persisted child")
                if resolution_outcome == "confirmed_applied" and (applied_indexes != all_indexes or absent_indexes):
                    raise ValueError("confirmed_applied must map every basket child as applied")
                if resolution_outcome == "confirmed_not_applied" and (
                    absent_indexes != all_indexes or applied_indexes or canonical_ids
                ):
                    raise ValueError("confirmed_not_applied must map every basket child as not applied")
                if resolution_outcome == "confirmed_partial" and (not applied_indexes or not absent_indexes):
                    raise ValueError("confirmed_partial requires both applied and not-applied children")
                assignments = sorted(
                    zip(canonical_item_indexes, canonical_ids, strict=True),
                    key=lambda assignment: assignment[0],
                )
                canonical_item_indexes = [index for index, _order_id in assignments]
                canonical_ids = [order_id for _index, order_id in assignments]
                canonical_not_applied_indexes.sort()
            elif is_placement:
                if canonical_item_indexes or canonical_not_applied_indexes:
                    raise ValueError("basket child indexes are only valid for multi-order recovery")
                expected_ids = 1 if resolution_outcome == "confirmed_applied" else 0
                if len(canonical_ids) != expected_ids:
                    raise ValueError(f"{resolution_outcome} placement requires exactly {expected_ids} broker_order_ids")

            existing = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE attempt_id = ?",
                (attempt_key,),
            ).fetchone()
            existing_payload: dict[str, Any] | None = None
            if existing is not None:
                existing_payload = self._resolution_dict(existing)
                expected_existing = {
                    "outcome": resolution_outcome,
                    "broker_order_ids": canonical_ids,
                    "broker_order_item_indexes": canonical_item_indexes,
                    "not_applied_item_indexes": canonical_not_applied_indexes,
                    "actor_type": principal_type,
                    "actor_id": principal_id,
                    "note": resolution_note,
                }
                same_decision = not any(existing_payload[key] != value for key, value in expected_existing.items())
                if existing_payload["status"] in {"PENDING_ROUTER_CLEAR", "COMMITTED"}:
                    if not same_decision:
                        raise LifecycleStateError(
                            "dispatch attempt already has a different committed outcome resolution"
                        )
                    return existing_payload
                if existing_payload["status"] != "PENDING_AUDIT":
                    raise LifecycleStateError("dispatch attempt has an invalid pending outcome resolution")
                previous_generation = int(existing_payload.get("snapshot_generation") or 0)
                if required_snapshot_generation is None or required_snapshot_generation <= previous_generation:
                    raise LifecycleStateError(
                        "pending outcome resolution requires a newer forced reconciliation generation"
                    )

            generation, snapshot_observed_at, snapshot_content_digest = self._fresh_snapshot_evidence(
                connection,
                attempt=attempt,
                required_generation=required_snapshot_generation,
            )
            self._validate_resolution_evidence(
                connection,
                attempt=attempt,
                outcome=resolution_outcome,
                broker_order_ids=canonical_ids,
                broker_order_item_indexes=canonical_item_indexes,
                not_applied_item_indexes=canonical_not_applied_indexes,
                generation=generation,
            )

            evidence = {
                "attempt_id": attempt_key,
                "adapter_id": adapter,
                "account_id": account,
                "business_date": business_day,
                "operation": operation,
                "outcome": resolution_outcome,
                "broker_order_ids": canonical_ids,
                "broker_order_item_indexes": canonical_item_indexes,
                "not_applied_item_indexes": canonical_not_applied_indexes,
                "snapshot_generation": generation,
                "snapshot_observed_at": snapshot_observed_at,
                "snapshot_content_digest": snapshot_content_digest,
                "actor_type": principal_type,
                "actor_id": principal_id,
                "note": resolution_note,
            }
            evidence_digest = _fingerprint(evidence)
            resolution_id = uuid.uuid4().hex
            if existing is not None and existing_payload is not None:
                same_decision = (
                    existing_payload["outcome"] == resolution_outcome
                    and existing_payload["broker_order_ids"] == canonical_ids
                    and existing_payload["broker_order_item_indexes"] == canonical_item_indexes
                    and existing_payload["not_applied_item_indexes"] == canonical_not_applied_indexes
                    and existing_payload["actor_type"] == principal_type
                    and existing_payload["actor_id"] == principal_id
                    and existing_payload["note"] == resolution_note
                )
                connection.execute(
                    """INSERT INTO dispatch_resolution_revisions (
                           revision_id, resolution_id, attempt_id, reason,
                           payload_json, recorded_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex,
                        existing_payload["resolution_id"],
                        attempt_key,
                        "fresh_evidence_retry" if same_decision else "operator_superseded",
                        json.dumps(
                            existing_payload,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ),
                        observed,
                    ),
                )
                connection.execute(
                    "DELETE FROM dispatch_resolutions WHERE resolution_id = ?",
                    (existing_payload["resolution_id"],),
                )
            connection.execute(
                """INSERT INTO dispatch_resolutions (
                       resolution_id, attempt_id, outcome, broker_order_ids,
                       broker_order_item_indexes, not_applied_item_indexes,
                       actor_type, actor_id, note, evidence_digest, status, prepared_at,
                       snapshot_generation, snapshot_observed_at, snapshot_content_digest
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_AUDIT', ?, ?, ?, ?)""",
                (
                    resolution_id,
                    attempt_key,
                    resolution_outcome,
                    json.dumps(canonical_ids, separators=(",", ":")),
                    json.dumps(canonical_item_indexes, separators=(",", ":")),
                    json.dumps(canonical_not_applied_indexes, separators=(",", ":")),
                    principal_type,
                    principal_id,
                    resolution_note,
                    evidence_digest,
                    observed,
                    generation,
                    snapshot_observed_at,
                    snapshot_content_digest,
                ),
            )
            row = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE resolution_id = ?",
                (resolution_id,),
            ).fetchone()
            assert row is not None
            return self._resolution_dict(row)

    def _verify_resolution_binding(
        self,
        connection: sqlite3.Connection,
        *,
        resolution: sqlite3.Row,
        audit_reference: str,
    ) -> tuple[sqlite3.Row, dict[str, Any], int]:
        """Re-verify the exact snapshot, decision digest, and durable audit receipt."""
        attempt = connection.execute(
            "SELECT * FROM dispatch_attempts WHERE attempt_id = ?",
            (resolution["attempt_id"],),
        ).fetchone()
        if attempt is None:
            raise LifecycleStateError("resolution dispatch attempt no longer exists")
        resolution_payload = self._resolution_dict(resolution)
        outcome = str(resolution["outcome"])
        operation = _text(attempt["operation"])
        resolution_generation = int(resolution["snapshot_generation"] or 0)
        resolution_observed_at = _text(resolution["snapshot_observed_at"])
        resolution_content_digest = _text(resolution["snapshot_content_digest"])
        if resolution_generation <= 0 or not resolution_observed_at or not resolution_content_digest:
            raise LifecycleStateError(
                "outcome resolution is not bound to immutable snapshot evidence; prepare a new audited revision"
            )
        exact_generation, snapshot_observed_at, snapshot_content_digest = self._fresh_snapshot_evidence(
            connection,
            attempt=attempt,
            required_generation=resolution_generation,
        )
        if snapshot_observed_at != resolution_observed_at or snapshot_content_digest != resolution_content_digest:
            raise LifecycleStateError("outcome resolution immutable snapshot identity does not match its manifest")
        bound_evidence_digest = _fingerprint(
            {
                "attempt_id": str(attempt["attempt_id"]),
                "adapter_id": str(attempt["adapter_id"]),
                "account_id": str(attempt["account_id"]),
                "business_date": str(attempt["business_date"]),
                "operation": operation,
                "outcome": outcome,
                "broker_order_ids": resolution_payload["broker_order_ids"],
                "broker_order_item_indexes": resolution_payload["broker_order_item_indexes"],
                "not_applied_item_indexes": resolution_payload["not_applied_item_indexes"],
                "snapshot_generation": exact_generation,
                "snapshot_observed_at": snapshot_observed_at,
                "snapshot_content_digest": snapshot_content_digest,
                "actor_type": str(resolution["actor_type"]),
                "actor_id": str(resolution["actor_id"]),
                "note": str(resolution["note"]),
            }
        )
        if bound_evidence_digest != str(resolution["evidence_digest"]):
            raise LifecycleStateError("outcome resolution evidence digest does not match its immutable snapshot")
        self._validate_resolution_evidence(
            connection,
            attempt=attempt,
            outcome=outcome,
            broker_order_ids=resolution_payload["broker_order_ids"],
            broker_order_item_indexes=resolution_payload["broker_order_item_indexes"],
            not_applied_item_indexes=resolution_payload["not_applied_item_indexes"],
            generation=exact_generation,
        )

        stored_audit_reference = _text(resolution["audit_reference"])
        if stored_audit_reference and stored_audit_reference != audit_reference:
            raise LifecycleStateError("durable audit receipt does not match the finalised resolution")
        verifier = self._audit_receipt_verifier
        if not callable(verifier):
            raise LifecycleStateError("durable audit receipt verifier is unavailable")
        try:
            receipt_valid = bool(
                verifier(
                    audit_reference,
                    event_type="ORDER_OUTCOME_RESOLUTION_AUTHORISED",
                    resolution_id=str(resolution["resolution_id"]),
                    evidence_digest=str(resolution["evidence_digest"]),
                )
            )
        except Exception as exc:
            raise LifecycleStateError("durable audit receipt could not be verified") from exc
        if not receipt_valid:
            raise LifecycleStateError("durable audit receipt is invalid")
        return attempt, resolution_payload, exact_generation

    def finalize_outcome_resolution(
        self,
        resolution_id: str,
        *,
        audit_reference: str,
        observed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Commit one audited decision while retaining the router-clear block."""
        resolution_key = _text(resolution_id)
        audit_key = _text(audit_reference)
        if not audit_key:
            raise ValueError("audit_reference is required")
        observed = _utc_iso(observed_at)
        with self._outcome_resolution_lock, self._connection(write=True) as connection:
            resolution = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE resolution_id = ?",
                (resolution_key,),
            ).fetchone()
            if resolution is None:
                raise LifecycleStateError(f"outcome resolution {resolution_key!r} does not exist")
            if resolution["status"] == "COMMITTED":
                return self._resolution_dict(resolution)
            if resolution["status"] not in {"PENDING_AUDIT", "PENDING_ROUTER_CLEAR"}:
                raise LifecycleStateError("outcome resolution has an invalid durable status")
            attempt, resolution_payload, _exact_generation = self._verify_resolution_binding(
                connection,
                resolution=resolution,
                audit_reference=audit_key,
            )
            if resolution["status"] == "PENDING_ROUTER_CLEAR":
                return resolution_payload
            outcome = str(resolution["outcome"])
            broker_ids = resolution_payload["broker_order_ids"]
            item_indexes = resolution_payload["broker_order_item_indexes"]
            not_applied_indexes = resolution_payload["not_applied_item_indexes"]
            operation = _text(attempt["operation"])
            current_state = str(attempt["dispatch_state"])

            if outcome == "confirmed_applied" and current_state == DISPATCH_OUTCOME_UNKNOWN:
                if operation == "place_multi_order":
                    item_count = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM dispatch_items WHERE attempt_id = ?",
                            (resolution["attempt_id"],),
                        ).fetchone()[0]
                    )
                    result: Any = {
                        "order_ids": broker_ids,
                        "order_results": [
                            {"order_id": order_id, "correlation_id": str(index + 1)}
                            for index, order_id in zip(item_indexes, broker_ids, strict=True)
                        ],
                        "errors": [
                            {"error_code": "OPERATOR_CONFIRMED_NOT_APPLIED", "correlation_id": str(index + 1)}
                            for index in not_applied_indexes
                        ],
                        "total": item_count,
                        "success": len(broker_ids),
                    }
                elif operation in _REGULAR_PLACEMENT_OPERATIONS:
                    result = broker_ids[0]
                else:
                    result = {}
                self._acknowledge_in_transaction(
                    connection,
                    attempt_id=str(resolution["attempt_id"]),
                    result=result,
                    observed_at=observed,
                    expected_state=DISPATCH_OUTCOME_UNKNOWN,
                    target_state=DISPATCH_CONFIRMED_APPLIED,
                    event_source="operator_confirmed_applied",
                    require_observed_match=False,
                    recovery_business_date=_business_date(str(resolution["snapshot_observed_at"])),
                )
            elif outcome == "confirmed_applied" and current_state != DISPATCH_CONFIRMED_APPLIED:
                raise LifecycleStateError(f"dispatch attempt cannot finalise applied resolution from {current_state}")
            elif outcome == "confirmed_partial" and current_state == DISPATCH_OUTCOME_UNKNOWN:
                item_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM dispatch_items WHERE attempt_id = ?",
                        (resolution["attempt_id"],),
                    ).fetchone()[0]
                )
                result = {
                    "order_ids": broker_ids,
                    "order_results": [
                        {"order_id": order_id, "correlation_id": str(index + 1)}
                        for index, order_id in zip(item_indexes, broker_ids, strict=True)
                    ],
                    "errors": [
                        {"error_code": "OPERATOR_CONFIRMED_NOT_APPLIED", "correlation_id": str(index + 1)}
                        for index in not_applied_indexes
                    ],
                    "total": item_count,
                    "success": len(broker_ids),
                }
                self._acknowledge_in_transaction(
                    connection,
                    attempt_id=str(resolution["attempt_id"]),
                    result=result,
                    observed_at=observed,
                    expected_state=DISPATCH_OUTCOME_UNKNOWN,
                    target_state=DISPATCH_CONFIRMED_PARTIAL,
                    event_source="operator_confirmed_partial",
                    require_observed_match=False,
                    recovery_business_date=_business_date(str(resolution["snapshot_observed_at"])),
                )
            elif outcome == "confirmed_partial" and current_state != DISPATCH_CONFIRMED_PARTIAL:
                raise LifecycleStateError(f"dispatch attempt cannot finalise partial resolution from {current_state}")
            elif outcome == "confirmed_not_applied":
                if current_state == DISPATCH_OUTCOME_UNKNOWN:
                    connection.execute(
                        """UPDATE dispatch_attempts
                           SET dispatch_state = ?
                           WHERE attempt_id = ? AND dispatch_state = ?""",
                        (
                            DISPATCH_CONFIRMED_NOT_APPLIED,
                            resolution["attempt_id"],
                            DISPATCH_OUTCOME_UNKNOWN,
                        ),
                    )
                elif current_state != DISPATCH_CONFIRMED_NOT_APPLIED:
                    raise LifecycleStateError(
                        f"dispatch attempt cannot finalise not-applied resolution from {current_state}"
                    )

            connection.execute(
                """UPDATE dispatch_resolutions
                   SET status = 'PENDING_ROUTER_CLEAR', audit_reference = ?,
                       audit_recorded_at = ?
                   WHERE resolution_id = ? AND status = 'PENDING_AUDIT'""",
                (audit_key, observed, resolution_key),
            )
            self._refresh_outcome_health(connection, observed_at=observed)
            pending_clear = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE resolution_id = ?",
                (resolution_key,),
            ).fetchone()
            assert pending_clear is not None
            return self._resolution_dict(pending_clear)

    def complete_outcome_resolution(
        self,
        resolution_id: str,
        *,
        router_clear_receipt: Any = None,
        router_clear_verifier: Callable[..., bool] | None = None,
        observed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Release one resolution only after its exact router fault was handled."""
        resolution_key = _text(resolution_id)
        observed = _utc_iso(observed_at)
        with self._outcome_resolution_lock, self._connection(write=True) as connection:
            resolution = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE resolution_id = ?",
                (resolution_key,),
            ).fetchone()
            if resolution is None:
                raise LifecycleStateError(f"outcome resolution {resolution_key!r} does not exist")
            if resolution["status"] == "COMMITTED":
                return self._resolution_dict(resolution)
            if resolution["status"] != "PENDING_ROUTER_CLEAR":
                raise LifecycleStateError("outcome resolution cannot complete before audit and router clear")
            attempt, _resolution_payload, _generation = self._verify_resolution_binding(
                connection,
                resolution=resolution,
                audit_reference=_text(resolution["audit_reference"]),
            )
            selector = f"{attempt['adapter_id']}:{attempt['account_id']}"
            if (
                isinstance(router_clear_receipt, bool)
                or router_clear_receipt is None
                or not callable(router_clear_verifier)
            ):
                raise LifecycleStateError(
                    "bound router-clear proof requires a verifiable router-clear receipt"
                )
            try:
                receipt_valid = bool(
                    router_clear_verifier(
                        router_clear_receipt,
                        resolution_id=resolution_key,
                        attempt_id=str(attempt["attempt_id"]),
                        selector=selector,
                    )
                )
            except Exception as exc:
                raise LifecycleStateError("bound router-clear proof could not be verified") from exc
            if not receipt_valid:
                raise LifecycleStateError(
                    "bound router-clear proof is invalid: router-clear receipt was not verified"
                )
            try:
                receipt_payload = _mapping(router_clear_receipt)
            except TypeError as exc:
                raise LifecycleStateError("bound router-clear proof is not canonical") from exc
            router_generation_id = _text(receipt_payload.get("router_generation"))
            if (
                _text(receipt_payload.get("resolution_id")) != resolution_key
                or _text(receipt_payload.get("attempt_id")) != str(attempt["attempt_id"])
                or _text(receipt_payload.get("selector")) != selector
                or not _text(receipt_payload.get("receipt_id"))
                or not router_generation_id
            ):
                raise LifecycleStateError("bound router-clear proof does not match the durable resolution")
            try:
                receipt_digest = _fingerprint(receipt_payload)
            except (TypeError, ValueError) as exc:
                raise LifecycleStateError("bound router-clear proof is not canonical") from exc
            connection.execute(
                """UPDATE dispatch_resolutions
                   SET status = 'COMMITTED', router_cleared_at = ?, committed_at = ?,
                       router_clear_receipt_digest = ?, router_generation_id = ?
                   WHERE resolution_id = ? AND status = 'PENDING_ROUTER_CLEAR'""",
                (observed, observed, receipt_digest, router_generation_id, resolution_key),
            )
            self._refresh_outcome_health(connection, observed_at=observed)
            committed = connection.execute(
                "SELECT * FROM dispatch_resolutions WHERE resolution_id = ?",
                (resolution_key,),
            ).fetchone()
            assert committed is not None
            return self._resolution_dict(committed)

    def record_dispatched_order(
        self,
        *,
        adapter_id: str,
        account_id: str,
        order_id: str,
        order: Any,
        source: str = "gated_dispatch_compatibility",
        observed_at: datetime | str | None = None,
    ) -> None:
        """Compatibility bridge for callers being moved to router instrumentation."""

        class _CompatibilityContext:
            jti = ""
            actor_type = "compatibility"
            actor_id = ""
            intent_source = source

        attempt_id = self.prepare_dispatch(
            adapter_id=adapter_id,
            account_id=account_id,
            operation="place_order",
            request_context=_CompatibilityContext(),
            payload=order,
            observed_at=observed_at,
        )
        self.mark_invoked(attempt_id, observed_at=observed_at)
        self.acknowledge(attempt_id, order_id, observed_at=observed_at)

    def mark_health_critical(
        self,
        reason: str,
        *,
        observed_at: datetime | str | None = None,
    ) -> None:
        with self._connection(write=True) as connection:
            connection.execute(
                """INSERT INTO ledger_health (
                       singleton, status, reason, source, attempt_id, updated_at
                   ) VALUES (1, 'CRITICAL', ?, 'manual_critical', NULL, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                       status = excluded.status,
                       reason = excluded.reason,
                       source = excluded.source,
                       attempt_id = excluded.attempt_id,
                       updated_at = excluded.updated_at""",
                (_text(reason), _utc_iso(observed_at)),
            )

    @staticmethod
    def _refresh_outcome_health(
        connection: sqlite3.Connection,
        *,
        observed_at: str,
    ) -> None:
        unresolved = connection.execute(
            """SELECT attempt_id, error_kind FROM dispatch_attempts AS a
               WHERE dispatch_state = ? OR EXISTS (
                   SELECT 1 FROM dispatch_resolutions AS r
                   WHERE r.attempt_id = a.attempt_id AND r.status != 'COMMITTED'
               )
               ORDER BY prepared_at, attempt_id LIMIT 1""",
            (DISPATCH_OUTCOME_UNKNOWN,),
        ).fetchone()
        current = connection.execute("SELECT status, source FROM ledger_health WHERE singleton = 1").fetchone()
        if unresolved is not None:
            if (
                current is not None
                and current["status"] == "CRITICAL"
                and current["source"]
                not in {
                    "",
                    "outcome_unknown",
                }
            ):
                return
            connection.execute(
                """INSERT INTO ledger_health (
                       singleton, status, reason, source, attempt_id, updated_at
                   ) VALUES (1, 'CRITICAL', ?, 'outcome_unknown', ?, ?)
                   ON CONFLICT(singleton) DO UPDATE SET
                       status = excluded.status,
                       reason = excluded.reason,
                       source = excluded.source,
                       attempt_id = excluded.attempt_id,
                       updated_at = excluded.updated_at""",
                (
                    _text(unresolved["error_kind"]) or "broker outcome unknown",
                    unresolved["attempt_id"],
                    observed_at,
                ),
            )
            return
        if current is not None and current["source"] == "outcome_unknown":
            connection.execute(
                """UPDATE ledger_health
                   SET status = 'HEALTHY', reason = '', source = '',
                       attempt_id = NULL, updated_at = ?
                   WHERE singleton = 1 AND source = 'outcome_unknown'""",
                (observed_at,),
            )

    def assert_write_ready(self) -> None:
        with self._connection() as connection:
            row = connection.execute("SELECT status, reason FROM ledger_health WHERE singleton = 1").fetchone()
            unresolved = connection.execute(
                """SELECT 1 FROM dispatch_attempts AS a
                   WHERE dispatch_state = ? OR EXISTS (
                       SELECT 1 FROM dispatch_resolutions AS r
                       WHERE r.attempt_id = a.attempt_id AND r.status != 'COMMITTED'
                   ) LIMIT 1""",
                (DISPATCH_OUTCOME_UNKNOWN,),
            ).fetchone()
        if unresolved is not None:
            raise LifecycleStateError("order lifecycle ledger requires reconciliation: broker outcome unknown")
        if row is not None and row["status"] == "CRITICAL":
            raise LifecycleStateError(f"order lifecycle ledger requires reconciliation: {row['reason']}")

    def record_broker_snapshot(
        self,
        *,
        adapter_id: str,
        account_id: str,
        orders: Iterable[Any],
        positions: Iterable[Any],
        holdings: Iterable[Any],
        observed_at: datetime | str | None = None,
    ) -> int:
        """Record broker observations without replacing FlintTrade-origin intent."""
        adapter = _text(adapter_id).lower()
        account = _normalise_account(account_id)
        if not adapter:
            raise ValueError("adapter_id is required")
        observed = _utc_iso(observed_at)
        business_day = _business_date(observed_at)
        normalised_orders = sorted(
            (_normalise_broker_order(row) for row in orders),
            key=lambda row: row["orderid"],
        )
        if len({row["orderid"] for row in normalised_orders}) != len(normalised_orders):
            raise ValueError("broker snapshot contains duplicate order ids")
        position_rows = sorted(
            (_observation_row(row, surface="position") for row in positions),
            key=lambda row: row["key"],
        )
        holding_rows = sorted(
            (_observation_row(row, surface="holding") for row in holdings),
            key=lambda row: row["key"],
        )
        if len({row["key"] for row in position_rows}) != len(position_rows):
            raise ValueError("broker snapshot contains duplicate position keys")
        if len({row["key"] for row in holding_rows}) != len(holding_rows):
            raise ValueError("broker snapshot contains duplicate holding keys")
        with self._outcome_resolution_lock, self._connection(write=True) as connection:
            evidence_orders: list[dict[str, Any]] = []
            for order in normalised_orders:
                prior_first_seen = connection.execute(
                    """SELECT MIN(first_seen_at) AS first_seen_at
                       FROM broker_order_observations
                       WHERE adapter_id = ? AND account_id = ? AND broker_order_id = ?
                         AND first_seen_at != ''""",
                    (adapter, account, order["orderid"]),
                ).fetchone()
                first_seen_at = (
                    str(prior_first_seen["first_seen_at"])
                    if prior_first_seen is not None and prior_first_seen["first_seen_at"]
                    else observed
                )
                evidence_orders.append({**order, "first_seen_at": first_seen_at})
            evidence_payload = {
                "orders": evidence_orders,
                "positions": position_rows,
                "holdings": holding_rows,
            }
            evidence_json = _canonical_json(evidence_payload)
            content_digest = _fingerprint(evidence_payload)
            prior_generation = connection.execute(
                """SELECT generation, observed_at, content_digest
                   FROM snapshot_generations
                   WHERE adapter_id = ? AND account_id = ?""",
                (adapter, account),
            ).fetchone()
            if prior_generation is not None:
                prior_observed = _utc_datetime(str(prior_generation["observed_at"]))
                current_observed = _utc_datetime(observed)
                if current_observed < prior_observed:
                    raise LifecycleStateError("broker snapshot is older than the latest adopted observation")
                if current_observed == prior_observed:
                    if str(prior_generation["content_digest"] or "") == content_digest:
                        manifest = connection.execute(
                            """SELECT observed_at, content_digest, evidence_json
                               FROM snapshot_generation_manifests
                               WHERE adapter_id = ? AND account_id = ? AND generation = ?""",
                            (adapter, account, int(prior_generation["generation"])),
                        ).fetchone()
                        if manifest is None or not str(manifest["evidence_json"] or ""):
                            raise LifecycleStateError(
                                "latest broker snapshot lacks immutable evidence; adopt a newer observation"
                            )
                        if (
                            str(manifest["observed_at"]) != observed
                            or str(manifest["content_digest"]) != content_digest
                            or str(manifest["evidence_json"]) != evidence_json
                        ):
                            raise LifecycleStateError("latest broker snapshot conflicts with its immutable manifest")
                        self._verify_snapshot_evidence(
                            connection,
                            adapter_id=adapter,
                            account_id=account,
                            generation=int(prior_generation["generation"]),
                            content_digest=content_digest,
                            evidence_json=evidence_json,
                        )
                        return int(prior_generation["generation"])
                    raise LifecycleStateError("broker snapshot conflicts with an observation at the same timestamp")
            generation = (int(prior_generation["generation"]) if prior_generation else 0) + 1
            connection.execute(
                """INSERT INTO snapshot_generation_manifests (
                       adapter_id, account_id, generation, observed_at,
                       content_digest, evidence_json
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (adapter, account, generation, observed, content_digest, evidence_json),
            )
            connection.execute(
                """INSERT INTO snapshot_generations (
                       adapter_id, account_id, generation, observed_at, content_digest
                   ) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(adapter_id, account_id) DO UPDATE SET
                       generation = excluded.generation,
                       observed_at = excluded.observed_at,
                       content_digest = excluded.content_digest""",
                (adapter, account, generation, observed, content_digest),
            )
            connection.execute(
                """UPDATE orders_current
                   SET broker_present = 0, missing_count = missing_count + 1, updated_at = ?
                   WHERE adapter_id = ? AND account_id = ?""",
                (observed, adapter, account),
            )
            for order in evidence_orders:
                first_seen_at = str(order["first_seen_at"])
                connection.execute(
                    """INSERT INTO broker_order_observations (
                           adapter_id, account_id, business_date, generation,
                           broker_order_id, observed_at, symbol, exchange,
                           product, action, status_raw, status_normalized,
                           quantity, filled_quantity, price, trigger_price,
                           price_type, variety, validity, strategy,
                           average_price, first_seen_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        adapter,
                        account,
                        business_day,
                        generation,
                        order["orderid"],
                        observed,
                        order["symbol"],
                        order["exchange"],
                        order["product"],
                        order["action"],
                        order["status_raw"],
                        order["status_normalized"],
                        order["quantity"],
                        order["filled_quantity"],
                        order["price"],
                        order["trigger_price"],
                        order["price_type"],
                        order["variety"],
                        order["validity"],
                        order["strategy"],
                        order["average_price"],
                        first_seen_at,
                    ),
                )
                existing_rows = connection.execute(
                    """SELECT * FROM orders_current
                       WHERE adapter_id = ? AND account_id = ? AND broker_order_id = ?
                       ORDER BY CASE WHEN origin = 'flinttrade' THEN 0 ELSE 1 END,
                                broker_present DESC, last_seen_generation DESC,
                                business_date DESC""",
                    (adapter, account, order["orderid"]),
                ).fetchall()
                flinttrade_rows = [row for row in existing_rows if row["origin"] == "flinttrade"]
                if len({_text(row["attempt_id"]) for row in flinttrade_rows}) > 1:
                    raise LifecycleStateError(
                        f"broker order {order['orderid']!r} is associated with multiple dispatch attempts"
                    )
                existing = flinttrade_rows[0] if flinttrade_rows else (existing_rows[0] if existing_rows else None)
                projection_business_day = str(existing["business_date"]) if existing is not None else business_day
                for duplicate in existing_rows:
                    if existing is not None and duplicate["business_date"] == existing["business_date"]:
                        continue
                    if duplicate["origin"] == "flinttrade":
                        raise LifecycleStateError(
                            f"broker order {order['orderid']!r} has conflicting FlintTrade projections"
                        )
                    connection.execute(
                        """DELETE FROM orders_current
                           WHERE adapter_id = ? AND account_id = ? AND business_date = ?
                             AND broker_order_id = ? AND origin = 'external'""",
                        (adapter, account, duplicate["business_date"], order["orderid"]),
                    )
                if existing is None:
                    terminal_at = observed if order["status_normalized"] in _TERMINAL_STATUSES else None
                    connection.execute(
                        """INSERT INTO orders_current (
                               adapter_id, account_id, business_date, broker_order_id,
                               origin, symbol, exchange, product, action, status_raw,
                               status_normalized, quantity, filled_quantity, price,
                               trigger_price, price_type, variety, validity, strategy,
                               average_price, first_seen_at, updated_at, terminal_at,
                               broker_present, last_broker_seen_at, last_seen_generation,
                               missing_count
                           ) VALUES (?, ?, ?, ?, 'external',
                                     ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                                     1, ?, ?, 0)""",
                        (
                            adapter,
                            account,
                            projection_business_day,
                            order["orderid"],
                            order["symbol"],
                            order["exchange"],
                            order["product"],
                            order["action"],
                            order["status_raw"],
                            order["status_normalized"],
                            order["quantity"],
                            order["filled_quantity"],
                            order["price"],
                            order["trigger_price"],
                            order["price_type"],
                            order["variety"],
                            order["validity"],
                            order["strategy"],
                            order["average_price"],
                            first_seen_at,
                            observed,
                            terminal_at,
                            observed,
                            generation,
                        ),
                    )
                    origin = "external"
                    attempt_id = None
                    quantity = order["quantity"]
                    status_raw = order["status_raw"]
                    status_normalized = order["status_normalized"]
                    filled_quantity = order["filled_quantity"]
                    average_price = order["average_price"]
                else:
                    existing_terminal = existing["terminal_at"] is not None
                    regresses_terminal = existing_terminal and order["status_normalized"] not in _TERMINAL_STATUSES
                    regresses_fill = order["filled_quantity"] < float(existing["filled_quantity"])
                    if regresses_terminal or regresses_fill:
                        status_raw = str(existing["status_raw"])
                        status_normalized = str(existing["status_normalized"])
                        filled_quantity = float(existing["filled_quantity"])
                        average_price = float(existing["average_price"])
                        terminal_at = existing["terminal_at"]
                    else:
                        status_raw = order["status_raw"]
                        status_normalized = order["status_normalized"]
                        filled_quantity = order["filled_quantity"]
                        average_price = order["average_price"]
                        terminal_at = existing["terminal_at"]
                        if terminal_at is None and status_normalized in _TERMINAL_STATUSES:
                            terminal_at = observed
                    quantity = float(existing["quantity"]) if existing["origin"] == "flinttrade" else order["quantity"]
                    connection.execute(
                        """UPDATE orders_current SET
                               symbol = ?, exchange = ?, product = ?, action = ?,
                               status_raw = ?, status_normalized = ?, quantity = ?,
                               filled_quantity = ?, price = ?, trigger_price = ?,
                               price_type = ?, variety = ?, validity = ?, strategy = ?,
                               average_price = ?, updated_at = ?, terminal_at = ?,
                               broker_present = 1, last_broker_seen_at = ?,
                               last_seen_generation = ?, missing_count = 0
                           WHERE adapter_id = ? AND account_id = ? AND business_date = ?
                             AND broker_order_id = ?""",
                        (
                            order["symbol"],
                            order["exchange"],
                            order["product"],
                            order["action"],
                            status_raw,
                            status_normalized,
                            quantity,
                            filled_quantity,
                            order["price"],
                            order["trigger_price"],
                            order["price_type"],
                            order["variety"],
                            order["validity"],
                            order["strategy"],
                            average_price,
                            observed,
                            terminal_at,
                            observed,
                            generation,
                            adapter,
                            account,
                            projection_business_day,
                            order["orderid"],
                        ),
                    )
                    origin = str(existing["origin"])
                    attempt_id = existing["attempt_id"]
                self._insert_event(
                    connection,
                    adapter_id=adapter,
                    account_id=account,
                    business_date=projection_business_day,
                    broker_order_id=order["orderid"],
                    attempt_id=attempt_id,
                    observed_at=observed,
                    source="broker_snapshot",
                    origin=origin,
                    status_raw=status_raw,
                    status_normalized=status_normalized,
                    quantity=quantity,
                    filled_quantity=filled_quantity,
                    average_price=average_price,
                    terminal_at=terminal_at,
                    broker_present=1,
                )
            for row in position_rows:
                connection.execute(
                    """INSERT INTO position_generation_observations (
                           adapter_id, account_id, generation, row_key, symbol,
                           exchange, product, quantity, average_price, observed_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        adapter,
                        account,
                        generation,
                        row["key"],
                        row["symbol"],
                        row["exchange"],
                        row["product"],
                        row["quantity"],
                        row["average_price"],
                        observed,
                    ),
                )
            for row in holding_rows:
                connection.execute(
                    """INSERT INTO holding_generation_observations (
                           adapter_id, account_id, generation, row_key, symbol,
                           exchange, quantity, average_price, observed_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        adapter,
                        account,
                        generation,
                        row["key"],
                        row["symbol"],
                        row["exchange"],
                        row["quantity"],
                        row["average_price"],
                        observed,
                    ),
                )
            for table, rows in (
                ("position_observations", position_rows),
                ("holding_observations", holding_rows),
            ):
                connection.execute(
                    f"DELETE FROM {table} WHERE adapter_id = ? AND account_id = ?",  # noqa: S608
                    (adapter, account),
                )
                for row in rows:
                    if table == "position_observations":
                        connection.execute(
                            """INSERT INTO position_observations (
                                   adapter_id, account_id, row_key, symbol, exchange,
                                   product, quantity, average_price, generation, observed_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                adapter,
                                account,
                                row["key"],
                                row["symbol"],
                                row["exchange"],
                                row["product"],
                                row["quantity"],
                                row["average_price"],
                                generation,
                                observed,
                            ),
                        )
                    else:
                        connection.execute(
                            """INSERT INTO holding_observations (
                                   adapter_id, account_id, row_key, symbol, exchange,
                                   quantity, average_price, generation, observed_at
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                adapter,
                                account,
                                row["key"],
                                row["symbol"],
                                row["exchange"],
                                row["quantity"],
                                row["average_price"],
                                generation,
                                observed,
                            ),
                        )
        return generation

    async def refresh_observations(
        self,
        read_owner: BrokerReadOwner,
        port: BrokerReadPort,
        *,
        history: TradeHistoryRequest | None = None,
        lots: LotSizeRequest | None = None,
        margin: MarginRequest | None = None,
        ledger: LedgerRequest | None = None,
        timeout_seconds: float = 30.0,
        read_plan: object | None = None,
        quotes: object | None = None,
    ) -> CanonicalObservationSnapshot:
        """Append an authorised read capture to this owner's existing manifest.

        There is intentionally no JSON/upload/paid-boolean ingestion interface.
        This does not advance dispatch state, clear unknown writes, or release
        holds. The old order reconciliation/resolution evidence stays separate.

        Args:
            read_owner: Exact current registry-bound observation owner.
            port: Its exact account-bound read port.
            history: Optional bounded native history selection.
            lots: Optional exact contract selection.
            margin: Optional order-margin estimate selection.
            ledger: Optional bounded account-posting selection.
            timeout_seconds: Finite positive collector deadline, at most sixty seconds.

        Returns:
            The reconstructed immutable retained view, without admission authority.

        Raises:
            LifecycleStateError: If ownership, capture type, source generation or
                manifest integrity cannot be established.
            sqlite3.Error: If the atomic durable append fails.
        """
        from flinttrade_core.broker_read_port import BrokerObservationSnapshot, BrokerReadFailure
        from flinttrade_gateway.broker_read_service import BrokerReadOwner

        if type(read_owner) is not BrokerReadOwner:
            raise LifecycleStateError("canonical refresh requires the bound read owner")
        captured = await read_owner.capture_observations(
            port, history=history, lots=lots, margin=margin, ledger=ledger, timeout_seconds=timeout_seconds,
            read_plan=read_plan, quotes=quotes,
        )
        if type(captured) is BrokerReadFailure:
            raise LifecycleStateError(f"observation refresh refused: {captured.code.value}")
        if type(captured) is not BrokerObservationSnapshot:
            raise LifecycleStateError("invalid owner observation")
        binding = (captured.provenance, captured.provider_account_id)
        if read_owner.observation_binding(port) != binding:
            raise LifecycleStateError("observation source retired")
        selector = captured.provenance.selector
        payload = json.loads(json.dumps(asdict(captured), default=self._observation_json_default))
        payload["schema"] = "flinttrade.canonical-observations.v1"
        evidence_json = _canonical_json(payload)
        digest = _fingerprint(payload)
        with self._outcome_resolution_lock, self._connection(write=True) as connection:
            previous = connection.execute(
                "SELECT generation, observed_at FROM snapshot_generations WHERE adapter_id=? AND account_id=?",
                (selector.adapter_id, selector.account_id),
            ).fetchone()
            if previous is not None and _utc_datetime(previous["observed_at"]) > _utc_datetime(captured.finished_at):
                raise LifecycleStateError("observation precedes current canonical generation")
            generation = (previous["generation"] if previous else 0) + 1
            if read_owner.observation_binding(port) != binding:
                raise LifecycleStateError("observation source retired")
            connection.execute(
                "INSERT INTO snapshot_generation_manifests VALUES (?, ?, ?, ?, ?, ?)",
                (selector.adapter_id, selector.account_id, generation, captured.finished_at, digest, evidence_json),
            )
            connection.execute(
                """INSERT INTO snapshot_generations VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(adapter_id, account_id) DO UPDATE SET generation=excluded.generation,
                observed_at=excluded.observed_at, content_digest=excluded.content_digest""",
                (selector.adapter_id, selector.account_id, generation, captured.finished_at, digest),
            )
        return self.observation_snapshot(selector)

    @staticmethod
    def _observation_json_default(value):
        if type(value) is uuid.UUID:
            return str(value)
        raise TypeError("noncanonical observation primitive")

    def observation_snapshot(
        self,
        selector: BrokerSelector,
        *,
        read_owner: BrokerReadOwner | None = None,
        port: BrokerReadPort | None = None,
        max_age_seconds: float | None = None,
    ) -> CanonicalObservationSnapshot:
        """Read immutable retained observations; no refresh, login or authority.

        Args:
            selector: Exact public account selector whose retained facts are inspected.
            read_owner: Optional actual owner for a local current-source check.
            port: That owner's bound port, required for a current-source check.
            max_age_seconds: Explicit finite positive freshness bound when an owner is supplied.

        Returns:
            Retained executions, independent histories, constraints and uncertainty.
            Source freshness never grants entry permission or clears obligations.

        Raises:
            ValueError: If the selector, owner or requested freshness bound is invalid.
            LifecycleStateError: If a stored generation fails its integrity check.
            sqlite3.Error: If the durable owner cannot read its existing ledger.
        """
        from flinttrade_core.broker_identity import BrokerSelector
        from flinttrade_core.broker_read_port import (
            AccountPostingSnapshot,
            CanonicalFillSnapshot,
            CanonicalObservationSnapshot,
            CapturedReadSurface,
            FeeObservationSnapshot,
            FeeObservationState,
            InstrumentLotSizeSnapshot,
            MarginRequest,
            MarginSnapshot,
            ObservationCoverage,
            OrderFillReconciliation,
            RetainedContractObservation,
            RetainedMarginObservation,
            RetainedReadSurface,
            RetainedTradeObservation,
            TradeSnapshot,
        )

        if type(selector) is not BrokerSelector:
            raise ValueError("exact selector required")
        selector.__post_init__()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT generation, evidence_json, content_digest FROM snapshot_generation_manifests
                WHERE adapter_id=? AND account_id=? ORDER BY generation""",
                (selector.adapter_id, selector.account_id),
            ).fetchall()
            all_orders = connection.execute(
                "SELECT * FROM orders_current WHERE adapter_id=? AND account_id=?",
                (selector.adapter_id, selector.account_id),
            ).fetchall()
            writer_rows = self._native_writer_rows(connection, selector.adapter_id, selector.account_id)
            verified = []
            for row in rows:
                try:
                    if row["evidence_json"]:
                        payload = json.loads(row["evidence_json"])
                        if type(payload) is not dict or _canonical_json(payload) != row["evidence_json"]:
                            raise ValueError
                    else:
                        # Legacy v8 manifests may lack the immutable payload.
                        # Their independent generation rows must still explain
                        # the original digest; a lost modern capture cannot.
                        payload = self._snapshot_payload_from_tables(
                            connection,
                            adapter_id=selector.adapter_id,
                            account_id=selector.account_id,
                            generation=row["generation"],
                        )
                    if _fingerprint(payload) != row["content_digest"]:
                        raise ValueError
                except (ValueError, TypeError) as exc:
                    raise LifecycleStateError("canonical observation manifest integrity failure") from exc
                verified.append((row, payload))
        from .native_scope_reducer import NativeScopeIndex

        native_scopes = NativeScopeIndex(writer_rows, verified, selector.adapter_id)
        fills = {}
        immutable_facts = {}
        trade_history = []
        fees = {}
        postings = {}
        coverage_history = []
        unallocated = {}
        retained_contracts, retained_margins = {}, {}
        contract_history, margin_history = [], []
        surface_history = []
        provider_accounts = set()
        conflicts = set()
        missing = {"lifetime_coverage_unavailable", "paid_allocation_producer_unavailable", "custody_not_evaluated"}
        latest = {}
        generation = 0
        for row, payload in verified:
            if payload.get("schema") != "flinttrade.canonical-observations.v1":
                continue
            latest = payload
            generation = row["generation"]
            provider_accounts.add(payload["provider_account_id"])
            provenance_json = _canonical_json(payload["provenance"])
            for item in payload.get("contracts", ()):
                contract = InstrumentLotSizeSnapshot(**item)
                retained_contracts[
                    (payload["provider_account_id"], contract.symbol, contract.exchange, contract.instrument_id or "")
                ] = contract
                contract_history.append(
                    RetainedContractObservation(generation, payload["provider_account_id"], provenance_json, contract)
                )
            for item in payload.get("margins", ()):
                margin = MarginSnapshot(**{**item, "request": MarginRequest(**item["request"])})
                retained_margins[(payload["provider_account_id"], _fingerprint(item["request"]))] = margin
                margin_history.append(
                    RetainedMarginObservation(generation, payload["provider_account_id"], provenance_json, margin)
                )
            for item in payload["coverage"]:
                coverage_history.append(
                    ObservationCoverage(
                        **{
                            **item,
                            "pages": tuple(item["pages"]),
                            "missing_intervals": tuple(item["missing_intervals"]),
                            "issues": tuple(item["issues"]),
                            "generation": generation,
                            "provider_account_id": payload["provider_account_id"],
                            "started_at": payload["started_at"],
                            "finished_at": payload["finished_at"],
                            "provenance_json": _canonical_json(payload["provenance"]),
                        }
                    )
                )
            for item in payload.get("surfaces", ()):
                original = item["coverage"]
                surface_coverage = ObservationCoverage(**{
                    **original, "pages": tuple(original["pages"]),
                    "missing_intervals": tuple(original["missing_intervals"]), "issues": tuple(original["issues"]),
                    "generation": generation, "provider_account_id": payload["provider_account_id"],
                    "provenance_json": provenance_json,
                })
                surface_history.append(RetainedReadSurface(
                    generation, payload["provider_account_id"], provenance_json,
                    CapturedReadSurface(item["surface"], item["family"], item["value_json"], surface_coverage),
                ))
            for posting in payload.get("account_postings", ()):
                postings.setdefault(_fingerprint(posting), AccountPostingSnapshot(**posting))
            for raw in payload["trades"]:
                trade = TradeSnapshot(**raw)
                owner_attempt, native_order_scope = native_scopes.allocation(payload["provider_account_id"], trade)
                trade_history.append(
                    RetainedTradeObservation(generation, payload["provider_account_id"], provenance_json, trade)
                )
                complete_identity = all((trade.fill_id, trade.orderid, trade.trade_date, trade.broker_exchange_segment))
                namespace = (
                    (
                        selector.adapter_id,
                        payload["provider_account_id"],
                        trade.trade_date,
                        trade.broker_exchange_segment,
                        trade.orderid,
                        trade.fill_id,
                        trade.fill_leg or "",
                        *(native_order_scope or ()),
                    )
                    if complete_identity
                    else (
                        "unallocated_observation",
                        selector.adapter_id,
                        payload["provider_account_id"],
                        _fingerprint(raw),
                    )
                )
                native = json.loads(trade.raw_observation_json or "{}").get("broker_fields", {})
                if selector.adapter_id == "dhan":
                    for component in (
                        "sebiTax",
                        "stt",
                        "brokerageCharges",
                        "serviceTax",
                        "exchangeTransactionCharges",
                        "stampDuty",
                    ):
                        if component not in native:
                            continue
                        value = native[component]
                        try:
                            if type(value) not in (str, int, float) or not Decimal(str(value)).is_finite():
                                raise ValueError
                            amount = str(value)
                        except (ValueError, InvalidOperation):
                            missing.add("malformed_fee_observation")
                            continue
                        fee_key = (*namespace, component, amount)
                        if fee_key not in fees:
                            fees[fee_key] = FeeObservationSnapshot(
                                namespace,
                                component,
                                amount,
                                FeeObservationState.PAYMENT_UNKNOWN,
                                hashlib.sha256(trade.raw_observation_json.encode()).hexdigest(),
                            )
                if not complete_identity:
                    missing.add("fill_identity_unavailable")
                    unallocated.setdefault(
                        namespace,
                        RetainedTradeObservation(generation, payload["provider_account_id"], provenance_json, trade),
                    )
                    continue
                quantity = Decimal(trade.quantity)
                if (
                    not quantity.is_finite()
                    or quantity <= 0
                    or quantity.adjusted() > 18
                    or quantity != quantity.to_integral_value()
                    or len(trade.quantity) > 64
                ):
                    missing.add("fill_quantity_unavailable")
                    unallocated.setdefault(
                        namespace,
                        RetainedTradeObservation(generation, payload["provider_account_id"], provenance_json, trade),
                    )
                    continue
                if owner_attempt is None:
                    missing.add("unallocated_fills")
                fill = CanonicalFillSnapshot(namespace, trade, owner_attempt, native_order_scope)
                established = immutable_facts.setdefault(namespace, {})
                observation = json.loads(trade.raw_observation_json or "{}")
                for section, observed, keys in (
                    ("semantic", asdict(trade), (
                        "orderid",
                        "symbol",
                        "instrument_id",
                        "exchange",
                        "action",
                        "quantity",
                        "price",
                        "product",
                        "exchange_order_id",
                        "broker_exchange_segment",
                        "broker_product_type",
                        "multiplier",
                        "fx_rate",
                    )),
                    ("raw", observation, ("option_type", "expiry", "strike_price", "underlying")),
                    ("native", observation.get("broker_fields", {}),
                            (
                                "drvExpiryDate",
                                "drvOptionType",
                                "drvStrikePrice",
                                "optTp",
                                "exp",
                                "expDt",
                                "stkPrc",
                                "lotSz",
                                "brdLtQty",
                                "multiplier",
                                "genNum",
                                "genDen",
                                "prcNum",
                                "prcDen",
                                "precision",
                                "securityId",
                                "tok",
                                "exSeg",
                                "exchangeSegment",
                                "prod",
                                "productType",
                            ),
                    ),
                ):
                    for key in keys:
                        if key not in observed or observed[key] is None:
                            continue
                        fact_key = (section, key)
                        if fact_key in established and established[fact_key] != observed[key]:
                            conflicts.add("immutable_fill_conflict:" + _fingerprint({"namespace": namespace}))
                        else:
                            established[fact_key] = observed[key]
                # Keep one execution and the latest compatible independent
                # observation. Raw originals and disagreements remain in history;
                # a missing field never erases an established comparison fact.
                if namespace not in fills or (
                    "immutable_fill_conflict:" + _fingerprint({"namespace": namespace}) not in conflicts
                ):
                    fills[namespace] = fill
        conflicts.update(native_scopes.conflicts)
        if len(provider_accounts) > 1:
            conflicts.add("provider_account_rebound")
            fills = {key: replace(fill, owner_attempt_id=None) if fill.native_order_scope is None else fill
                     for key, fill in fills.items()}
        coverage = tuple(item for item in coverage_history if item.generation == generation)
        contracts = tuple(retained_contracts[key] for key in sorted(retained_contracts))
        margins = tuple(retained_margins[key] for key in sorted(retained_margins))
        if contracts and not latest.get("contracts"):
            missing.add("contract_not_recollected")
        if margins and not latest.get("margins"):
            missing.add("margin_not_recollected")
        for contract in contracts:
            if not all((contract.source_revision, contract.source_digest, contract.observed_at, contract.valid_until)):
                missing.add("contract_version_or_freshness_unavailable")
            else:
                try:
                    if (
                        not _utc_datetime(contract.observed_at)
                        <= datetime.now(UTC)
                        <= _utc_datetime(contract.valid_until)
                    ):
                        missing.add("contract_stale")
                except (ValueError, TypeError):
                    missing.add("contract_freshness_invalid")
            if contract.raw_tick_unit in (None, "unknown"):
                missing.add("contract_raw_tick_unit_unavailable")
        for estimate in margins:
            missing.add("standalone_short_margin_unverified")
            raw = json.loads(estimate.raw_observation_json or "{}")
            value = raw.get("brokerage")
            if type(value) in (str, int, float):
                try:
                    if Decimal(str(value)).is_finite():
                        key = ("margin_estimate", _fingerprint(asdict(estimate.request)))
                        fees[key] = FeeObservationSnapshot(
                            key,
                            "brokerage",
                            str(value),
                            FeeObservationState.ESTIMATED,
                            hashlib.sha256(estimate.raw_observation_json.encode()).hexdigest(),
                        )
                except InvalidOperation:
                    missing.add("malformed_fee_estimate")
        source_current = False
        order_fills = []
        # This reducer never adds the cumulative order value to unique fills.
        # It retains the unexplained remainder independently for qualification.
        context = Context(
            prec=128,
            rounding=ROUND_HALF_EVEN,
            Emin=-999999,
            Emax=999999,
            capitals=1,
            clamp=0,
            flags=[],
            traps=[InvalidOperation],
        )
        with localcontext(context):
            for scope, resource in sorted(native_scopes.resources.items()):
                unique = sum((Decimal(fill.trade.quantity) for fill in fills.values()
                              if fill.native_order_scope == scope and fill.owner_attempt_id == resource["attempt"]),
                             Decimal(0))
                cumulative = resource["high_water"]
                if cumulative is None:
                    missing.add("native_cumulative_quantity_unavailable")
                    cumulative = Decimal(0)
                remainder = max(Decimal(0), cumulative - unique)
                if remainder:
                    missing.add("cumulative_fill_not_explained_by_unique_fills")
                order_fills.append(OrderFillReconciliation(resource["resource"]["order_id"], str(unique),
                    str(cumulative), str(remainder), scope, None if resource["ambiguous"] else resource["attempt"]))
            scoped_attempts = {resource["attempt"] for resource in native_scopes.resources.values()}
            for row in sorted(all_orders, key=lambda item: (item["business_date"], item["broker_order_id"])):
                cumulative = Decimal(str(row["filled_quantity"]))
                if row["attempt_id"] in scoped_attempts and cumulative == 0:
                    continue  # Empty legacy ACK is not an additional native resource.
                missing.add("cumulative_native_scope_unavailable")
                if cumulative:
                    missing.add("cumulative_fill_not_explained_by_unique_fills")
                observation_scope = ("legacy-business-date", selector.adapter_id, selector.account_id,
                                     row["business_date"], row["broker_order_id"])
                order_fills.append(OrderFillReconciliation(row["broker_order_id"], "0", str(cumulative),
                                                          str(cumulative), observation_scope=observation_scope))
            unscoped = {}
            for fill in fills.values():
                if fill.native_order_scope is not None:
                    continue
                # Even unallocated executions must never merge across account,
                # execution day, segment or fill leg merely by scalar order ID.
                key = (fill.namespace[1], fill.trade.trade_date or "", fill.trade.broker_exchange_segment or "",
                       fill.trade.orderid, fill.trade.fill_leg or "")
                unscoped[key] = unscoped.get(key, Decimal(0)) + Decimal(fill.trade.quantity)
            for key, quantity in sorted(unscoped.items()):
                order_fills.append(OrderFillReconciliation(key[3], str(quantity), "0", "0",
                                                          observation_scope=("unallocated-execution", *key)))
        if read_owner is not None and latest:
            from flinttrade_gateway.broker_read_service import BrokerReadOwner

            if type(read_owner) is not BrokerReadOwner:
                raise ValueError("exact read owner required")
            if type(max_age_seconds) not in (int, float) or not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
                raise ValueError("explicit positive freshness bound required")
            current = read_owner.observation_binding(port)
            if type(current) is tuple:
                current_provenance = json.loads(json.dumps(asdict(current[0]), default=self._observation_json_default))
                age = (datetime.now(UTC) - _utc_datetime(latest["started_at"])).total_seconds()
                source_current = (
                    current_provenance == latest["provenance"]
                    and current[1] == latest["provider_account_id"]
                    and 0 <= age <= max_age_seconds
                )
        return CanonicalObservationSnapshot(
            selector,
            generation,
            tuple(fills[key] for key in sorted(fills)),
            coverage,
            tuple(sorted(conflicts)),
            tuple(sorted(missing)),
            source_current=source_current,
            evidence_json=_canonical_json(latest),
            fees=tuple(fees[key] for key in sorted(fees)),
            contracts=contracts,
            margins=margins,
            order_fills=tuple(order_fills),
            account_postings=tuple(postings[key] for key in sorted(postings)),
            coverage_history=tuple(coverage_history),
            unallocated_trades=tuple(unallocated[key] for key in sorted(unallocated)),
            contract_history=tuple(contract_history),
            margin_history=tuple(margin_history),
            trade_history=tuple(trade_history),
            surfaces=tuple(item.observation for item in surface_history if item.generation == generation),
            surface_history=tuple(surface_history),
        )

    def latest_snapshot_generation(self, *, adapter_id: str, account_id: str) -> int | None:
        """Return the latest adopted broker snapshot generation for one selector."""
        adapter = _text(adapter_id).lower()
        account = _normalise_account(account_id)
        if not adapter:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT generation FROM snapshot_generations WHERE adapter_id = ? AND account_id = ?",
                (adapter, account),
            ).fetchone()
        return int(row["generation"]) if row is not None else None

    def __call__(self, session: Any) -> LocalStateSnapshot:
        """Return independent FlintTrade-origin state for one selector."""
        from flinttrade_gateway.reconciliation import LocalStateSnapshot  # noqa: PLC0415

        adapter = _text(getattr(session, "adapter_id", "")).lower()
        if not adapter:
            return LocalStateSnapshot()
        account = _normalise_account(getattr(session, "account_id", ""))
        business_day = _business_date(self._clock())
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT broker_order_id, symbol, exchange, product, action,
                          status_normalized, quantity, filled_quantity, price,
                          average_price
                   FROM orders_current
                   WHERE adapter_id = ? AND account_id = ? AND origin = 'flinttrade'
                     AND business_date = ?
                   ORDER BY broker_order_id""",
                (adapter, account, business_day),
            ).fetchall()
        orders = tuple(
            {
                "orderid": row["broker_order_id"],
                "symbol": row["symbol"],
                "exchange": row["exchange"],
                "product": row["product"],
                "action": row["action"],
                "status": row["status_normalized"],
                "quantity": float(row["quantity"]),
                "filled_quantity": float(row["filled_quantity"]),
                "price": float(row["price"]),
                "average_price": float(row["average_price"]),
            }
            for row in rows
        )
        return LocalStateSnapshot(orders=orders)

    def native_command_observation(
        self, selector: BrokerSelector, *, actor: str, intent_source: str,
        intent: dict[str, Any], generation: int, evidence_digest: str, max_age_seconds: float,
    ) -> dict[str, Any]:
        """Resolve one command against this ledger's bounded, sealed observation.

        This read never dispatches, acknowledges or invents a native identity
        day. All acknowledged children require exact invocation/resource scope
        and independent quantity observations. Missing production date producers
        remain unavailable; synthetic native scope stays explicitly synthetic.

        Args:
            selector: Exact historical account selected by the command owner.
            actor: Original authenticated bounded producer identity.
            intent_source: Original command correlation, not a caller label.
            intent: Complete canonical order retained before invocation.
            generation: Already inspected canonical generation.
            evidence_digest: Digest of that generation's complete payload.
            max_age_seconds: Explicit configured freshness limit.

        Returns:
            Detached evidence, including terminal status and a monotonic fill
            constraint; it is not financial settlement or permission. A complete
            exact-resource semantic contradiction is explicitly conflicting,
            never zero-fill settlement evidence even when its fills are zero.

        Raises:
            ValueError: Required source, child, date, identity or comparison
                operands are unavailable, partial, stale or not attributable.
        """
        from fractions import Fraction

        from flinttrade_gateway.native_scope_primitives import scope_key, validate_resources

        snapshot = self.observation_snapshot(selector)
        payload = json.loads(snapshot.evidence_json)
        if (snapshot.generation != generation or _fingerprint(payload) != evidence_digest
                or snapshot.conflicts or snapshot.unallocated_trades
                or not 0 <= (datetime.now(UTC) - _utc_datetime(payload["started_at"])).total_seconds()
                <= max_age_seconds):
            raise ValueError("native command observation unavailable or stale")
        budget = json.loads(payload.get("read_budget_json") or "null")
        if type(budget) is not dict or budget["issues"]:
            raise ValueError("complete bounded read required")
        surfaces: dict[str, list[dict[str, Any]]] = {}
        for surface in snapshot.surfaces:
            if surface.surface not in {"orders", "positions", "holdings", "trades"}:
                continue
            coverage = surface.coverage
            if (surface.surface in surfaces or coverage.availability != "available"
                    or coverage.provider_account_id != payload["provider_account_id"]
                    or coverage.page_model != "unpaged_observation" and surface.surface != "trades"
                    or any(issue in coverage.issues for issue in (
                        "read_deadline_exceeded", "read_budget_exceeded", "page_budget_exceeded"))
                    or surface.value_json is None):
                raise ValueError("complete command read surfaces required")
            values = json.loads(surface.value_json)
            if type(values) is not list or coverage.returned_count != len(values):
                raise ValueError("command surface count unavailable")
            surfaces[surface.surface] = values
        if set(surfaces) != {"orders", "positions", "holdings", "trades"}:
            raise ValueError("complete command read plan required")
        attempts = [attempt for attempt in self.list_dispatch_attempts()
                    if attempt["adapter_id"] == selector.adapter_id and attempt["account_id"] == selector.account_id
                    and attempt["actor_id"] == actor and attempt["intent_source"] == intent_source]
        if len(attempts) != 1 or attempts[0]["operation"] != "place_order":
            raise ValueError("unique original invocation required")
        attempt = attempts[0]
        manifests = self.native_dispatch_evidence(attempt["attempt_id"])
        prepared = [item["facts"] for item in manifests if item["kind"] == "prepared"]
        acks = [item for item in manifests if item["kind"] == "acknowledged"]
        if (len(prepared) != 1 or len(acks) != 1
                or any(item["kind"] == "uncertain_acknowledgement" for item in manifests)):
            raise ValueError("complete native acknowledgement required")
        facts, ack = prepared[0], acks[0]
        provenance = payload["provenance"]
        if (facts["intent"] != intent or facts["provider_account_id"] != payload["provider_account_id"]
                or facts["selector"] != provenance["selector"]
                or any(facts["session_version"][key] != provenance[key] for key in (
                    "registry_version", "credential_version", "workspace_version", "broker_workspace_version"))
                or ack["invocation_id"] != facts["invocation_id"] or ack.get("native_scope_ack_matches") is not True):
            raise ValueError("native writer and read owner correspondence unavailable")
        origin = ack["native_scope_observation"]
        scope = json.loads(payload.get("native_scope_json") or "null")
        if type(scope) is not dict or scope["availability"] != "available":
            raise ValueError("independent native identity-day required")
        records = [record for record in scope["records"] if record["invocation_id"] == facts["invocation_id"]]
        if len(records) != 1:
            raise ValueError("complete current resource set required")
        current = records[0]
        if (any(current[key] != origin[key] for key in (
                "source_id", "provenance", "label", "invocation_id", "signed_intent_hash", "order_ids"))
                or set(ack["order_ids"]) != set(current["order_ids"])):
            raise ValueError("native resource source or ACK set changed")
        before = {scope_key(resource): resource for resource in validate_resources(origin["resources"])}
        resources = validate_resources(current["resources"])
        if set(before) != {scope_key(resource) for resource in resources} or len(resources) != len(ack["order_ids"]):
            raise ValueError("complete exact child resource set required")
        # Validate every child's ownership before interpreting any semantic
        # contradiction. A foreign/missing sibling cannot qualify a prefix.
        children: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for resource in resources:
            if (resource["native_account"] != facts["provider_account_id"]
                    or resource["family"] != "ordinary" or resource["segment"] != facts["native_segment"]
                    or resource["exchange_order_id"] != before[scope_key(resource)]["exchange_order_id"]):
                raise ValueError("native resource changed")
            orders = [order for order in surfaces["orders"] if order["orderid"] == resource["order_id"]]
            if len(orders) != 1:
                raise ValueError("acknowledged child missing or repeated")
            order = orders[0]
            if (order["exchange_order_id"] != resource["exchange_order_id"]
                    or order["broker_account_id"] != resource["native_account"]
                    or order["broker_exchange_segment"] != resource["segment"]):
                raise ValueError("observed native resource identity differs")
            children.append((resource, order))
        filled, quantity, terminal = 0, Fraction(0), True
        conflicts: set[str] = set()
        for resource, order in children:
            if any(order[key] is None for key in ("symbol", "exchange", "product", "action", "pricetype")):
                raise ValueError("observed signed terms unavailable")
            q, f = Fraction(order["quantity"]), Fraction(order["filled_quantity"])
            price, signed_price = Fraction(order["price"]), Fraction(intent["price"])
            if resource["filled_quantity"] is None:
                raise ValueError("independent child quantities unavailable")
            constraints = [item for item in snapshot.order_fills if item.owner_attempt_id == attempt["attempt_id"]
                           and item.native_order_scope == (selector.adapter_id, *scope_key(resource))]
            if len(constraints) != 1:
                raise ValueError("cumulative resource evidence unavailable")
            native_fill = Fraction(resource["filled_quantity"])
            high_water = Fraction(constraints[0].cumulative_high_water)
            status = order["status"]
            if status not in {
                "TRANSIT", "OPEN", "PENDING", "PARTIAL", "TRADED", "FILLED", "COMPLETE",
                "REJECTED", "CANCELLED", "EXPIRED",
            }:
                raise ValueError("native lifecycle unavailable")
            # These are the existing comparisons, not a new raw-field policy.
            # Their operands now belong to the complete exact original ACK set.
            for key in ("symbol", "exchange", "product", "action", "pricetype"):
                if order[key] != intent[key]:
                    conflicts.add(f"signed_{key}_mismatch")
            if price != signed_price:
                conflicts.add("signed_price_mismatch")
            if q.denominator != 1 or f.denominator != 1 or not 0 <= f <= q or q <= 0:
                conflicts.add("independent_child_quantities_invalid")
            if f != native_fill:
                conflicts.add("independent_child_fill_mismatch")
            if high_water != f:
                conflicts.add("cumulative_resource_fill_mismatch")
            if (status in {"TRADED", "FILLED", "COMPLETE"} and f != q) or (status == "REJECTED" and f):
                conflicts.add("native_lifecycle_quantity_mismatch")
            terminal = terminal and status in {"REJECTED", "CANCELLED", "EXPIRED", "TRADED", "FILLED", "COMPLETE"}
            quantity += q
            # Never truncate invalid fractional/negative observations into fills;
            # keep the independently established integer high-water instead.
            filled += int(max(native_fill, high_water, f if f.denominator == 1 and f >= 0 else 0))
        if quantity != int(intent["quantity"]):
            conflicts.add("signed_quantity_mismatch")
        conflicting = bool(conflicts)
        evidence = {"attempt_id": attempt["attempt_id"], "order_ids": ack["order_ids"], "resources": resources,
                "generation": generation, "evidence_digest": evidence_digest, "filled_quantity": filled,
                "terminal": terminal, "zero_fill_terminal": not conflicting and terminal and filled == 0
                and not any(resource["executions"] for resource in resources)
                and not any(surfaces[name] for name in ("positions", "holdings", "trades")),
                "provenance": current["provenance"]}
        if conflicting:
            # Only this canonical owner classifies explicit comparisons. A
            # generic exception or unavailable capture is never a conflict.
            evidence.update(conflicting=True, conflict=min(conflicts), conflicts=sorted(conflicts),
                            observed_quantity=int(quantity) if quantity.denominator == 1 else str(quantity),
                            signed_quantity=int(intent["quantity"]))
        return evidence

    def list_dispatch_attempts(self) -> list[dict[str, Any]]:
        """Return non-secret attempt state for diagnostics and tests."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT attempt_id, adapter_id, account_id, business_date,
                          operation, dispatch_state, history_complete,
                          request_jti_hash, actor_type,
                          actor_id, intent_source, broker_order_id, prepared_at,
                          invoked_at, completed_at, error_kind
                   FROM dispatch_attempts ORDER BY prepared_at, attempt_id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def list_unresolved_outcomes(self) -> list[dict[str, Any]]:
        """Return operator-safe intent details for every unresolved broker outcome."""
        with self._connection() as connection:
            attempts = connection.execute(
                """SELECT attempt_id, adapter_id, account_id, business_date,
                          operation, dispatch_state, history_complete,
                          intent_source, symbol, exchange,
                          product, action, quantity, price, trigger_price, price_type,
                          variety, validity, strategy, prepared_at, invoked_at,
                          completed_at AS unknown_at, error_kind
                   FROM dispatch_attempts
                   WHERE dispatch_state = ? OR EXISTS (
                       SELECT 1 FROM dispatch_resolutions AS r
                       WHERE r.attempt_id = dispatch_attempts.attempt_id
                         AND r.status != 'COMMITTED'
                   )
                   ORDER BY prepared_at, attempt_id""",
                (DISPATCH_OUTCOME_UNKNOWN,),
            ).fetchall()
            results: list[dict[str, Any]] = []
            for attempt in attempts:
                row = dict(attempt)
                operation = str(attempt["operation"])
                if operation == "place_multi_order":
                    supported_outcomes = [
                        "confirmed_applied",
                        "confirmed_not_applied",
                        "confirmed_partial",
                    ]
                elif operation in {
                    "place_order",
                    "place_reducing_order",
                    "modify_order",
                    "cancel_order",
                    "cancel_smart_order",
                }:
                    supported_outcomes = ["confirmed_applied", "confirmed_not_applied"]
                else:
                    supported_outcomes = []
                history_complete = int(attempt["history_complete"]) == 1
                if not history_complete:
                    supported_outcomes = [outcome for outcome in supported_outcomes if outcome == "confirmed_applied"]
                row["recovery_supported_outcomes"] = supported_outcomes
                if not history_complete:
                    row["recovery_blocked_reason"] = (
                        "Broker identity history is incomplete after ledger migration; "
                        "negative and partial-negative recovery remain fail-closed."
                    )
                elif not supported_outcomes:
                    row["recovery_blocked_reason"] = (
                        "No operation-specific broker evidence is recorded for this write type; "
                        "the outcome remains fail-closed."
                    )
                else:
                    row["recovery_blocked_reason"] = ""
                items = connection.execute(
                    """SELECT item_index, symbol, exchange, product, action,
                              quantity, price, trigger_price, price_type, variety,
                              validity, strategy
                       FROM dispatch_items WHERE attempt_id = ? ORDER BY item_index""",
                    (attempt["attempt_id"],),
                ).fetchall()
                resolution = connection.execute(
                    "SELECT * FROM dispatch_resolutions WHERE attempt_id = ?",
                    (attempt["attempt_id"],),
                ).fetchone()
                row["items"] = [dict(item) for item in items]
                row["resolution"] = (
                    {
                        key: value
                        for key, value in self._resolution_dict(resolution).items()
                        if key
                        in {
                            "resolution_id",
                            "outcome",
                            "broker_order_ids",
                            "broker_order_item_indexes",
                            "not_applied_item_indexes",
                            "note",
                            "evidence_digest",
                            "status",
                            "prepared_at",
                            "snapshot_generation",
                            "snapshot_observed_at",
                            "snapshot_content_digest",
                        }
                    }
                    if resolution is not None
                    else None
                )
                results.append(row)
        return results

    def is_outcome_resolved(self, attempt_id: str) -> bool:
        """Return whether one decision can authorise its exact router-fault clear."""
        with self._connection() as connection:
            row = connection.execute(
                """SELECT a.dispatch_state, a.history_complete,
                          r.status, r.outcome, r.not_applied_item_indexes
                   FROM dispatch_attempts AS a
                   JOIN dispatch_resolutions AS r ON r.attempt_id = a.attempt_id
                   WHERE a.attempt_id = ?""",
                (_text(attempt_id),),
            ).fetchone()
        if row is None:
            return False
        try:
            not_applied_indexes = json.loads(str(row["not_applied_item_indexes"] or "[]"))
        except json.JSONDecodeError:
            return False
        negative_evidence = (
            str(row["outcome"]) in {"confirmed_not_applied", "confirmed_partial"}
            or isinstance(not_applied_indexes, list)
            and bool(not_applied_indexes)
        )
        return bool(
            row["status"] in {"PENDING_ROUTER_CLEAR", "COMMITTED"}
            and row["dispatch_state"]
            in {
                DISPATCH_CONFIRMED_APPLIED,
                DISPATCH_CONFIRMED_NOT_APPLIED,
                DISPATCH_CONFIRMED_PARTIAL,
            }
            and (int(row["history_complete"]) == 1 or not negative_evidence)
        )

    def outcome_resolution_binding(self, attempt_id: str) -> dict[str, str] | None:
        """Return the exact pending-clear identity a router generation may receipt."""
        attempt_key = _text(attempt_id)
        with self._connection() as connection:
            row = connection.execute(
                """SELECT attempt.attempt_id, attempt.adapter_id, attempt.account_id,
                          resolution.resolution_id, resolution.status,
                          resolution.audit_reference, resolution.snapshot_generation,
                          resolution.snapshot_content_digest
                   FROM dispatch_attempts AS attempt
                   JOIN dispatch_resolutions AS resolution
                     ON resolution.attempt_id = attempt.attempt_id
                   WHERE attempt.attempt_id = ?""",
                (attempt_key,),
            ).fetchone()
        if (
            row is None
            or row["status"] != "PENDING_ROUTER_CLEAR"
            or not _text(row["audit_reference"])
            or int(row["snapshot_generation"] or 0) <= 0
            or not _text(row["snapshot_content_digest"])
            or not self.is_outcome_resolved(attempt_key)
        ):
            return None
        return {
            "attempt_id": str(row["attempt_id"]),
            "resolution_id": str(row["resolution_id"]),
            "selector": f"{row['adapter_id']}:{row['account_id']}",
            "status": str(row["status"]),
        }

    def list_order_events(
        self,
        *,
        adapter_id: str,
        account_id: str,
        order_id: str,
    ) -> list[dict[str, Any]]:
        """Return ordered lifecycle events for diagnostics and tests."""
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT observed_at, source, origin, status_normalized AS status,
                          quantity, filled_quantity, average_price, terminal_at,
                          broker_present
                   FROM order_events
                   WHERE adapter_id = ? AND account_id = ? AND broker_order_id = ?
                   ORDER BY event_id""",
                (_text(adapter_id).lower(), _normalise_account(account_id), _text(order_id)),
            ).fetchall()
        return [dict(row) for row in rows]


# Compatibility import retained while app/adapters move to the canonical name.
JournalLocalStateProvider = OrderLifecycleLedger

__all__ = [
    "DISPATCH_ACKNOWLEDGED",
    "DISPATCH_CONFIRMED_APPLIED",
    "DISPATCH_CONFIRMED_NOT_APPLIED",
    "DISPATCH_CONFIRMED_PARTIAL",
    "DISPATCH_FAILED_BEFORE_INVOKE",
    "DISPATCH_INVOKED",
    "DISPATCH_OUTCOME_UNKNOWN",
    "DISPATCH_PREPARED",
    "JournalLocalStateProvider",
    "LifecycleStateError",
    "OrderLifecycleLedger",
]
