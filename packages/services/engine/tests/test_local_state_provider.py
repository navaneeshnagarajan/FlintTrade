"""Durable selector-scoped order lifecycle ledger tests."""

from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import flinttrade_engine.local_state_provider as lifecycle_module
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway.reconciliation import LocalStateSnapshot, build_report

JournalLocalStateProvider = lifecycle_module.JournalLocalStateProvider
OrderLifecycleLedger = getattr(
    lifecycle_module,
    "OrderLifecycleLedger",
    lifecycle_module.JournalLocalStateProvider,
)

pytestmark = pytest.mark.unit

OBSERVED_AT = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)


class _Session:
    def __init__(self, account_id: str = "personal", adapter_id: str = "dhan") -> None:
        self.account_id = account_id
        self.adapter_id = adapter_id


def _provider(tmp_path) -> OrderLifecycleLedger:
    return OrderLifecycleLedger(
        ledger_path=tmp_path / "order-lifecycle.sqlite3",
        clock=lambda: OBSERVED_AT,
        audit_receipt_verifier=_verify_audit_receipt,
    )


def _audit_reference(resolution: dict[str, object]) -> str:
    return f"audit:{resolution['evidence_digest']}"


def _verify_audit_receipt(
    audit_reference: str,
    *,
    event_type: str,
    resolution_id: str,
    evidence_digest: str,
) -> bool:
    return (
        event_type == "ORDER_OUTCOME_RESOLUTION_AUTHORISED"
        and bool(resolution_id)
        and audit_reference == f"audit:{evidence_digest}"
    )


def _router_clear_receipt(
    resolution: dict[str, object],
    *,
    selector: str = "dhan:personal",
) -> dict[str, str]:
    return {
        "receipt_id": f"clear:{resolution['resolution_id']}",
        "resolution_id": str(resolution["resolution_id"]),
        "attempt_id": str(resolution["attempt_id"]),
        "selector": selector,
        "router_generation": "test-router-generation",
    }


def _verify_router_clear_receipt(
    receipt: object,
    *,
    resolution_id: str,
    attempt_id: str,
    selector: str,
) -> bool:
    return bool(
        isinstance(receipt, dict)
        and receipt.get("receipt_id") == f"clear:{resolution_id}"
        and receipt.get("resolution_id") == resolution_id
        and receipt.get("attempt_id") == attempt_id
        and receipt.get("selector") == selector
        and receipt.get("router_generation") == "test-router-generation"
    )


def _finalize_and_complete(
    provider: OrderLifecycleLedger,
    pending: dict[str, object],
) -> dict[str, object]:
    finalised = provider.finalize_outcome_resolution(
        str(pending["resolution_id"]),
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT,
    )
    assert finalised["status"] == "PENDING_ROUTER_CLEAR"
    attempt = next(
        attempt
        for attempt in provider.list_dispatch_attempts()
        if attempt["attempt_id"] == finalised["attempt_id"]
    )
    selector = f"{attempt['adapter_id']}:{attempt['account_id']}"
    return provider.complete_outcome_resolution(
        str(pending["resolution_id"]),
        router_clear_receipt=_router_clear_receipt(finalised, selector=selector),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=OBSERVED_AT,
    )


def _request_context(*, jti: str = "jti-sensitive-value") -> RequestContext:
    return RequestContext(
        jti=jti,
        actor_type="human",
        actor_id="operator-1",
        mode="live",
        intent_source="manual",
        selector="dhan:personal",
    )


def _intent(**overrides: object) -> dict[str, object]:
    return {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "quantity": 5,
        "price": 2500.5,
        **overrides,
    }


def _acknowledged_order(
    provider: OrderLifecycleLedger,
    *,
    account_id: str = "personal",
    order_id: str = "ORD-1",
) -> str:
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id=account_id,
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)
    provider.acknowledge(attempt_id, order_id, observed_at=OBSERVED_AT)
    return attempt_id


def test_missing_ledger_starts_with_empty_snapshot(tmp_path) -> None:
    snapshot = _provider(tmp_path)(_Session())

    assert isinstance(snapshot, LocalStateSnapshot)
    assert snapshot == LocalStateSnapshot()


def test_dispatch_attempt_is_durable_selector_scoped_and_does_not_store_raw_jti(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _acknowledged_order(provider)

    restarted = _provider(tmp_path)
    snapshot = restarted(_Session("personal", "dhan"))
    assert snapshot.orders == (
        {
            "orderid": "ORD-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "SUBMITTED",
            "quantity": 5.0,
            "filled_quantity": 0.0,
            "price": 2500.5,
            "average_price": 0.0,
        },
    )
    assert restarted(_Session("family", "dhan")).orders == ()
    assert restarted(_Session("personal", "upstox")).orders == ()

    attempts = restarted.list_dispatch_attempts()
    assert attempts[0]["attempt_id"] == attempt_id
    assert attempts[0]["dispatch_state"] == "ACKNOWLEDGED"
    assert attempts[0]["request_jti_hash"] != "jti-sensitive-value"
    assert "jti-sensitive-value" not in (tmp_path / "order-lifecycle.sqlite3").read_bytes().decode(
        "utf-8", errors="ignore"
    )


def test_prepared_invoked_and_lost_response_state_are_distinct_and_durable(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "PREPARED"

    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "INVOKED"

    provider.mark_outcome_unknown(attempt_id, "broker_timeout", observed_at=OBSERVED_AT)
    restarted = _provider(tmp_path)
    attempt = restarted.list_dispatch_attempts()[0]
    assert attempt["dispatch_state"] == "OUTCOME_UNKNOWN"
    assert attempt["error_kind"] == "broker_timeout"
    assert restarted(_Session()).orders == ()


def _unknown_attempt(
    provider: OrderLifecycleLedger,
    *,
    adapter_id: str = "dhan",
    account_id: str = "personal",
    operation: str = "place_order",
    payload: object | None = None,
) -> str:
    attempt_id = provider.prepare_dispatch(
        adapter_id=adapter_id,
        account_id=account_id,
        operation=operation,
        request_context=_request_context(),
        payload=payload or _intent(),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)
    provider.mark_outcome_unknown(attempt_id, "broker_timeout", observed_at=OBSERVED_AT)
    return attempt_id


def _record_broker_order(
    provider: OrderLifecycleLedger,
    *,
    order_id: str,
    adapter_id: str = "dhan",
    account_id: str = "personal",
    observed_at: datetime = OBSERVED_AT + timedelta(minutes=1),
    **overrides: object,
) -> None:
    _record_broker_orders(
        provider,
        adapter_id=adapter_id,
        account_id=account_id,
        orders=[{"orderid": order_id, **overrides}],
        observed_at=observed_at,
    )


def _record_broker_orders(
    provider: OrderLifecycleLedger,
    *,
    orders: list[dict[str, object]],
    adapter_id: str = "dhan",
    account_id: str = "personal",
    observed_at: datetime = OBSERVED_AT + timedelta(minutes=1),
) -> None:
    provider.record_broker_snapshot(
        adapter_id=adapter_id,
        account_id=account_id,
        orders=[
            {
                **_intent(status="OPEN", filled_quantity=0),
                **order,
            }
            for order in orders
        ],
        positions=[],
        holdings=[],
        observed_at=observed_at,
    )


def _record_empty_snapshot(
    provider: OrderLifecycleLedger,
    *,
    adapter_id: str = "dhan",
    account_id: str = "personal",
    observed_at: datetime = OBSERVED_AT + timedelta(minutes=1),
) -> None:
    provider.record_broker_snapshot(
        adapter_id=adapter_id,
        account_id=account_id,
        orders=[],
        positions=[],
        holdings=[],
        observed_at=observed_at,
    )


def _mutate_generation_evidence(
    path,
    *,
    surface: str,
    mutation: str,
) -> None:
    table, key_column, value_column = {
        "order": ("broker_order_observations", "broker_order_id", "price"),
        "position": ("position_generation_observations", "row_key", "quantity"),
        "holding": ("holding_generation_observations", "row_key", "quantity"),
    }[surface]
    with sqlite3.connect(path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({table})"  # noqa: S608 - closed test-only table map
            )
        ]
        row = connection.execute(
            f"""SELECT * FROM {table}
                WHERE adapter_id = 'dhan' AND account_id = 'personal'
                  AND generation = 1 LIMIT 1"""  # noqa: S608 - closed test-only table map
        ).fetchone()
        assert row is not None
        key = row[columns.index(key_column)]
        if mutation == "add":
            values = list(row)
            values[columns.index(key_column)] = f"{key}-ADDED"
            placeholders = ",".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO {table} VALUES ({placeholders})",  # noqa: S608 - closed test-only table map
                values,
            )
        elif mutation == "remove":
            connection.execute(
                f"""DELETE FROM {table}
                    WHERE adapter_id = 'dhan' AND account_id = 'personal'
                      AND generation = 1 AND {key_column} = ?""",  # noqa: S608 - closed test-only table map
                (key,),
            )
        else:
            connection.execute(
                f"""UPDATE {table} SET {value_column} = {value_column} + 1
                    WHERE adapter_id = 'dhan' AND account_id = 'personal'
                      AND generation = 1 AND {key_column} = ?""",  # noqa: S608 - closed test-only table map
                (key,),
            )


def test_confirmed_applied_recovery_stays_blocked_until_audit_then_restores_order(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(provider, order_id="RECOVERED-1")

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["RECOVERED-1"],
        actor_type="human",
        actor_id="operator-1",
        note="Verified in the broker order book",
        observed_at=OBSERVED_AT,
    )

    assert pending["status"] == "PENDING_AUDIT"
    assert pending["evidence_digest"]
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        provider.assert_write_ready()

    committed = _finalize_and_complete(provider, pending)

    assert committed["status"] == "COMMITTED"
    assert committed["outcome"] == "confirmed_applied"
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_APPLIED"
    assert provider(_Session()).orders[0]["orderid"] == "RECOVERED-1"
    provider.assert_write_ready()


def test_applied_recovery_preserves_original_unknown_time_and_error_until_router_clear(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(provider, order_id="RECOVERED-2")
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["RECOVERED-2"],
        actor_type="human",
        actor_id="operator-1",
        note="Verified in the fresh broker order book",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )

    provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    unresolved = provider.list_unresolved_outcomes()[0]
    assert unresolved["unknown_at"] == OBSERVED_AT.isoformat()
    assert unresolved["error_kind"] == "broker_timeout"
    assert unresolved["resolution"]["status"] == "PENDING_ROUTER_CLEAR"


def test_outcome_finalisation_rejects_the_ledgers_own_evidence_digest_as_audit_receipt(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book contains no matching order",
        observed_at=OBSERVED_AT,
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="audit receipt"):
        provider.finalize_outcome_resolution(
            pending["resolution_id"],
            audit_reference=pending["evidence_digest"],
            observed_at=OBSERVED_AT,
        )

    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"


def test_confirmed_applied_requires_a_matching_present_broker_observation(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)

    with pytest.raises(lifecycle_module.LifecycleStateError, match="broker observation"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["UNOBSERVED-1"],
            actor_type="human",
            actor_id="operator-1",
            observed_at=OBSERVED_AT,
        )

    _record_broker_order(
        provider,
        order_id="MISMATCH-1",
        symbol="TCS",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["MISMATCH-1"],
            actor_type="human",
            actor_id="operator-1",
            observed_at=OBSERVED_AT,
        )

    assert provider.list_unresolved_outcomes()[0]["resolution"] is None


def test_confirmed_applied_rejects_an_order_first_observed_before_invocation(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="PREEXISTING-1",
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(provider, order_id="PREEXISTING-1")

    with pytest.raises(lifecycle_module.LifecycleStateError, match="first observed after invocation"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["PREEXISTING-1"],
            actor_type="human",
            actor_id="operator-1",
            note="Checked the broker order book",
            observed_at=OBSERVED_AT,
        )


def test_confirmed_applied_requires_every_material_broker_identity_field(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        payload=_intent(
            price_type="LIMIT",
            variety="REGULAR",
            validity="DAY",
            strategy="manual-alpha",
        ),
    )
    _record_broker_order(provider, order_id="MISSING-FIELDS-1")

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["MISSING-FIELDS-1"],
            actor_type="human",
            actor_id="operator-1",
            note="Broker omitted material identity fields",
            observed_at=OBSERVED_AT,
        )


@pytest.mark.parametrize("field", ["price_type", "variety", "validity", "strategy"])
@pytest.mark.parametrize("persisted_value", ["", "UNKNOWN"])
def test_confirmed_applied_rejects_declared_unknown_material_evidence(
    tmp_path,
    field: str,
    persisted_value: str,
) -> None:
    provider = _provider(tmp_path)
    intent = _intent(
        trigger_price=0,
        price_type="LIMIT",
        variety="REGULAR",
        validity="DAY",
        strategy="manual-alpha",
    )
    intent[field] = persisted_value
    attempt_id = _unknown_attempt(provider, payload=intent)
    _record_broker_order(
        provider,
        order_id="DECLARED-UNKNOWN-1",
        **{**intent, field: "UNKNOWN"},
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["DECLARED-UNKNOWN-1"],
            actor_type="human",
            actor_id="operator-1",
            note="Broker declared material evidence unavailable",
            observed_at=OBSERVED_AT,
        )


def test_confirmed_applied_accepts_exact_non_unknown_material_evidence(tmp_path) -> None:
    provider = _provider(tmp_path)
    intent = _intent(
        trigger_price=0,
        price_type="LIMIT",
        variety="REGULAR",
        validity="DAY",
        strategy="manual-alpha",
    )
    attempt_id = _unknown_attempt(provider, payload=intent)
    _record_broker_order(provider, order_id="EXACT-MATCH-1", **intent)

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["EXACT-MATCH-1"],
        actor_type="human",
        actor_id="operator-1",
        note="Every material field matches persisted intent",
        observed_at=OBSERVED_AT,
    )

    assert pending["status"] == "PENDING_AUDIT"


def test_outcome_recovery_requires_audit_and_exact_attempt_selector(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match dispatch attempt"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Fresh broker order book contains no matching order",
            observed_at=OBSERVED_AT,
        )

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book contains no matching order",
        observed_at=OBSERVED_AT,
    )
    with pytest.raises(ValueError, match="audit_reference"):
        provider.finalize_outcome_resolution(
            pending["resolution_id"],
            audit_reference="",
            observed_at=OBSERVED_AT,
        )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        provider.assert_write_ready()

    _finalize_and_complete(provider, pending)
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_NOT_APPLIED"
    assert provider(_Session()).orders == ()
    provider.assert_write_ready()


def test_resolving_one_unknown_attempt_does_not_clear_another(tmp_path) -> None:
    provider = _provider(tmp_path)
    first = _unknown_attempt(provider)
    second = _unknown_attempt(provider, payload=_intent(symbol="TCS"))
    _record_empty_snapshot(provider)

    pending = provider.prepare_outcome_resolution(
        attempt_id=first,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book contains no matching order",
        observed_at=OBSERVED_AT,
    )
    _finalize_and_complete(provider, pending)

    states = {row["attempt_id"]: row["dispatch_state"] for row in provider.list_dispatch_attempts()}
    assert states[first] == "CONFIRMED_NOT_APPLIED"
    assert states[second] == "OUTCOME_UNKNOWN"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        provider.assert_write_ready()


def test_unresolved_outcome_listing_exposes_intent_without_raw_request_jti(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)

    rows = provider.list_unresolved_outcomes()

    assert rows == [
        {
            "attempt_id": attempt_id,
            "adapter_id": "dhan",
            "account_id": "personal",
            "business_date": "2026-07-15",
            "operation": "place_order",
            "dispatch_state": "OUTCOME_UNKNOWN",
            "history_complete": 1,
            "intent_source": "manual",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 5.0,
            "price": 2500.5,
            "trigger_price": 0.0,
            "price_type": "",
            "variety": "",
            "validity": "",
            "strategy": "",
            "prepared_at": OBSERVED_AT.isoformat(),
            "invoked_at": OBSERVED_AT.isoformat(),
            "unknown_at": OBSERVED_AT.isoformat(),
            "error_kind": "broker_timeout",
            "recovery_supported_outcomes": [
                "confirmed_applied",
                "confirmed_not_applied",
            ],
            "recovery_blocked_reason": "",
            "items": [],
            "resolution": None,
        }
    ]
    assert "jti-sensitive-value" not in repr(rows)


def test_confirmed_applied_multi_order_maps_each_verified_id_to_its_child_intent(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", action="BUY", quantity=1),
                _intent(symbol="TCS", action="SELL", quantity=2),
            ],
        },
    )
    _record_broker_orders(
        provider,
        adapter_id="upstox",
        orders=[
            {
                "orderid": "BASKET-1",
                "symbol": "RELIANCE",
                "action": "BUY",
                "quantity": 1,
            },
            {
                "orderid": "BASKET-2",
                "symbol": "TCS",
                "action": "SELL",
                "quantity": 2,
            },
        ],
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="upstox",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["BASKET-1", "BASKET-2"],
        broker_order_item_indexes=[0, 1],
        actor_type="human",
        actor_id="operator-1",
        observed_at=OBSERVED_AT,
    )

    _finalize_and_complete(provider, pending)

    orders = {row["orderid"]: row for row in provider(_Session(adapter_id="upstox")).orders}
    assert orders["BASKET-1"]["symbol"] == "RELIANCE"
    assert orders["BASKET-1"]["action"] == "BUY"
    assert orders["BASKET-2"]["symbol"] == "TCS"
    assert orders["BASKET-2"]["action"] == "SELL"


def test_confirmed_applied_multi_order_rejects_wrong_explicit_child_correlation(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", action="BUY", quantity=1),
                _intent(symbol="TCS", action="SELL", quantity=2),
            ],
        },
    )
    _record_broker_orders(
        provider,
        adapter_id="upstox",
        orders=[
            {
                "orderid": "BASKET-1",
                "symbol": "RELIANCE",
                "action": "BUY",
                "quantity": 1,
            },
            {
                "orderid": "BASKET-2",
                "symbol": "TCS",
                "action": "SELL",
                "quantity": 2,
            },
        ],
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match child"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["BASKET-1", "BASKET-2"],
            broker_order_item_indexes=[1, 0],
            actor_type="human",
            actor_id="operator-1",
            observed_at=OBSERVED_AT,
        )


def test_not_applied_requires_post_unknown_snapshot_and_operator_note(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)

    with pytest.raises(lifecycle_module.LifecycleStateError, match="newer reconciliation snapshot"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Checked broker order book",
            observed_at=OBSERVED_AT,
        )

    _record_empty_snapshot(provider, observed_at=OBSERVED_AT)
    with pytest.raises(lifecycle_module.LifecycleStateError, match="newer reconciliation snapshot"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Checked broker order book",
            observed_at=OBSERVED_AT,
        )

    _record_empty_snapshot(provider)
    with pytest.raises(ValueError, match="operator note"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            observed_at=OBSERVED_AT,
        )


def test_resolution_requires_the_generation_returned_by_forced_reconciliation(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    generation = provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[],
        positions=[],
        holdings=[],
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )

    assert generation == 1
    assert provider.latest_snapshot_generation(adapter_id="dhan", account_id="personal") == 1
    with pytest.raises(lifecycle_module.LifecycleStateError, match="newer reconciliation snapshot"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Forced reconciliation generation did not adopt",
            required_snapshot_generation=2,
            observed_at=OBSERVED_AT,
        )


def test_rollover_evidence_keeps_exact_attempt_identity_without_requiring_same_business_date(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    applied_attempt = _unknown_attempt(provider)
    not_applied_attempt = _unknown_attempt(provider, account_id="secondary")
    after_ist_rollover = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)

    _record_broker_order(
        provider,
        order_id="ROLLOVER-APPLIED-1",
        observed_at=after_ist_rollover,
    )
    _record_empty_snapshot(
        provider,
        account_id="secondary",
        observed_at=after_ist_rollover,
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="selector"):
        provider.prepare_outcome_resolution(
            attempt_id=applied_attempt,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-16",
            outcome="confirmed_applied",
            broker_order_ids=["ROLLOVER-APPLIED-1"],
            actor_type="human",
            actor_id="operator-1",
            required_snapshot_generation=1,
            observed_at=after_ist_rollover,
        )

    applied = provider.prepare_outcome_resolution(
        attempt_id=applied_attempt,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["ROLLOVER-APPLIED-1"],
        actor_type="human",
        actor_id="operator-1",
        required_snapshot_generation=1,
        observed_at=after_ist_rollover,
    )
    not_applied = provider.prepare_outcome_resolution(
        attempt_id=not_applied_attempt,
        adapter_id="dhan",
        account_id="secondary",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The fresh post-rollover broker order book is empty",
        required_snapshot_generation=1,
        observed_at=after_ist_rollover,
    )

    assert applied["snapshot_observed_at"] == after_ist_rollover.isoformat()
    assert not_applied["snapshot_observed_at"] == after_ist_rollover.isoformat()


def test_positive_rollover_recovery_keeps_one_current_date_order_with_attempt_provenance(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    after_ist_rollover = datetime(2026, 7, 15, 19, 0, tzinfo=timezone.utc)
    _record_broker_order(
        provider,
        order_id="ROLLOVER-CANONICAL-1",
        observed_at=after_ist_rollover,
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["ROLLOVER-CANONICAL-1"],
        actor_type="human",
        actor_id="operator-1",
        note="The post-rollover order belongs to the pre-rollover dispatch attempt",
        required_snapshot_generation=1,
        observed_at=after_ist_rollover,
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=after_ist_rollover,
    )
    provider.complete_outcome_resolution(
        pending["resolution_id"],
        router_clear_receipt=_router_clear_receipt(finalised),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=after_ist_rollover,
    )

    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        current_rows = connection.execute(
            """SELECT business_date, origin, attempt_id, broker_present,
                      last_seen_generation, first_seen_at
               FROM orders_current
               WHERE adapter_id = 'dhan' AND account_id = 'personal'
                 AND broker_order_id = 'ROLLOVER-CANONICAL-1'"""
        ).fetchall()
        event_rows = connection.execute(
            """SELECT business_date, origin, attempt_id
               FROM order_events
               WHERE adapter_id = 'dhan' AND account_id = 'personal'
                 AND broker_order_id = 'ROLLOVER-CANONICAL-1'
               ORDER BY event_id"""
        ).fetchall()

    assert current_rows == [
        (
            "2026-07-16",
            "flinttrade",
            attempt_id,
            1,
            1,
            after_ist_rollover.isoformat(),
        )
    ]
    assert event_rows[-1] == ("2026-07-16", "flinttrade", attempt_id)


def test_positive_rollover_recovery_moves_an_existing_prior_day_projection_to_current_state(
    tmp_path,
) -> None:
    before_ist_rollover = datetime(2026, 7, 15, 18, 20, tzinfo=timezone.utc)
    after_ist_rollover = datetime(2026, 7, 15, 18, 40, tzinfo=timezone.utc)
    provider = OrderLifecycleLedger(
        ledger_path=tmp_path / "order-lifecycle.sqlite3",
        clock=lambda: after_ist_rollover,
        audit_receipt_verifier=_verify_audit_receipt,
    )
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=before_ist_rollover,
    )
    provider.mark_invoked(attempt_id, observed_at=before_ist_rollover + timedelta(minutes=1))
    provider.mark_outcome_unknown(
        attempt_id,
        "broker_timeout",
        observed_at=before_ist_rollover + timedelta(minutes=2),
    )
    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        connection.execute(
            """INSERT INTO orders_current (
                   adapter_id, account_id, business_date, broker_order_id,
                   attempt_id, origin, symbol, exchange, product, action,
                   quantity, price, first_seen_at, updated_at
               ) VALUES ('dhan', 'personal', '2026-07-15', 'ROLLOVER-STALE-1',
                         ?, 'flinttrade', 'RELIANCE', 'NSE', 'MIS', 'BUY',
                         5, 2500.5, ?, ?)""",
            (attempt_id, before_ist_rollover.isoformat(), before_ist_rollover.isoformat()),
        )

    _record_broker_order(
        provider,
        order_id="ROLLOVER-STALE-1",
        observed_at=after_ist_rollover,
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["ROLLOVER-STALE-1"],
        actor_type="human",
        actor_id="operator-1",
        note="The post-rollover broker snapshot proves the stale projection applied",
        required_snapshot_generation=1,
        observed_at=after_ist_rollover,
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=after_ist_rollover,
    )
    provider.complete_outcome_resolution(
        pending["resolution_id"],
        router_clear_receipt=_router_clear_receipt(finalised),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=after_ist_rollover,
    )

    attempts = provider.list_dispatch_attempts()
    assert attempts[0]["attempt_id"] == attempt_id
    assert attempts[0]["business_date"] == "2026-07-15"
    assert [row["orderid"] for row in provider(_Session()).orders] == ["ROLLOVER-STALE-1"]
    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        rows = connection.execute(
            """SELECT business_date, origin, attempt_id
               FROM orders_current WHERE broker_order_id = 'ROLLOVER-STALE-1'"""
        ).fetchall()
    assert rows == [("2026-07-16", "flinttrade", attempt_id)]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", 2501.0),
        ("price", 2500.5000000001),
        ("trigger_price", 2491.0),
        ("price_type", "MARKET"),
        ("variety", "AMO"),
        ("validity", "IOC"),
        ("strategy", "other-strategy"),
    ],
)
def test_applied_correlation_rejects_broker_observable_field_mismatch(
    tmp_path,
    field: str,
    value: object,
) -> None:
    provider = _provider(tmp_path)
    intent = _intent(
        trigger_price=2490,
        price_type="SL",
        variety="REGULAR",
        validity="DAY",
        strategy="opening-breakout",
    )
    attempt_id = _unknown_attempt(provider, payload=intent)
    broker_order = {**intent, field: value}
    _record_broker_order(provider, order_id="MISMATCH-FIELD", **broker_order)

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not match"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=["MISMATCH-FIELD"],
            actor_type="human",
            actor_id="operator-1",
            note="Checked broker order book",
            observed_at=OBSERVED_AT,
        )


def test_partial_multi_order_partitions_every_child_and_records_only_applied_ids(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", action="BUY", quantity=1),
                _intent(symbol="TCS", action="SELL", quantity=2),
            ],
        },
    )
    _record_broker_orders(
        provider,
        adapter_id="upstox",
        orders=[
            {
                "orderid": "PARTIAL-1",
                "symbol": "RELIANCE",
                "action": "BUY",
                "quantity": 1,
            }
        ],
    )

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="upstox",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_partial",
        broker_order_ids=["PARTIAL-1"],
        broker_order_item_indexes=[0],
        not_applied_item_indexes=[1],
        actor_type="human",
        actor_id="operator-1",
        note="Broker order book contains only the first basket child",
        observed_at=OBSERVED_AT,
    )

    assert pending["broker_order_item_indexes"] == [0]
    assert pending["not_applied_item_indexes"] == [1]
    committed = _finalize_and_complete(provider, pending)

    assert committed["status"] == "COMMITTED"
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_PARTIAL"
    assert provider(_Session(adapter_id="upstox")).orders == (
        {
            "orderid": "PARTIAL-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "OPEN",
            "quantity": 1.0,
            "filled_quantity": 0.0,
            "price": 2500.5,
            "average_price": 0.0,
        },
    )


def test_partial_multi_order_rejects_unpartitioned_or_observed_not_applied_child(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={
            "_op": "place_multi_order",
            "orders": [_intent(symbol="RELIANCE"), _intent(symbol="TCS")],
        },
    )
    _record_broker_orders(
        provider,
        adapter_id="upstox",
        orders=[
            {"orderid": "PARTIAL-1", "symbol": "RELIANCE"},
            {"orderid": "HIDDEN-2", "symbol": "TCS"},
        ],
    )

    with pytest.raises(ValueError, match="partition every persisted child"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_partial",
            broker_order_ids=["PARTIAL-1"],
            broker_order_item_indexes=[0],
            not_applied_item_indexes=[],
            actor_type="human",
            actor_id="operator-1",
            note="Checked broker order book",
            observed_at=OBSERVED_AT,
        )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="not-applied child 1"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_partial",
            broker_order_ids=["PARTIAL-1"],
            broker_order_item_indexes=[0],
            not_applied_item_indexes=[1],
            actor_type="human",
            actor_id="operator-1",
            note="Checked broker order book",
            observed_at=OBSERVED_AT,
        )


def test_modify_and_cancel_recovery_require_operation_specific_fresh_evidence(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="TARGET-1",
        price=2500,
        quantity=5,
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    modify_attempt = _unknown_attempt(
        provider,
        operation="modify_order",
        payload={
            "_op": "modify",
            "order_id": "TARGET-1",
            "price": 2510,
            "quantity": 3,
            "_requested_change_fields": ["price", "quantity"],
        },
    )
    _record_broker_order(
        provider,
        order_id="TARGET-1",
        price=2510,
        quantity=3,
    )
    modify = provider.prepare_outcome_resolution(
        attempt_id=modify_attempt,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book shows the requested modification",
        observed_at=OBSERVED_AT,
    )
    _finalize_and_complete(provider, modify)

    cancel_attempt = _unknown_attempt(
        provider,
        operation="cancel_order",
        payload={"_op": "cancel", "order_id": "TARGET-1"},
    )
    _record_broker_order(
        provider,
        order_id="TARGET-1",
        price=2510,
        quantity=3,
        status="CANCELLED",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    cancel = provider.prepare_outcome_resolution(
        attempt_id=cancel_attempt,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book shows the target cancelled",
        observed_at=OBSERVED_AT,
    )
    _finalize_and_complete(provider, cancel)


def test_modify_not_applied_rejects_mixed_requested_field_evidence(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="TARGET-MIXED",
        price=2500,
        quantity=5,
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    attempt_id = _unknown_attempt(
        provider,
        operation="modify_order",
        payload={
            "_op": "modify",
            "order_id": "TARGET-MIXED",
            "price": 2510,
            "quantity": 3,
            "_requested_change_fields": ["price", "quantity"],
        },
    )
    _record_broker_order(
        provider,
        order_id="TARGET-MIXED",
        price=2500,
        quantity=3,
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not prove"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Only part of the requested modification is visible",
            observed_at=OBSERVED_AT,
        )


def test_cancel_pending_cannot_be_confirmed_not_applied(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        operation="cancel_order",
        payload={"_op": "cancel", "order_id": "TARGET-PENDING"},
    )
    _record_broker_order(
        provider,
        order_id="TARGET-PENDING",
        status="CANCELLATION_REQUESTED",
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not conclusively prove"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Cancellation remains pending",
            observed_at=OBSERVED_AT,
        )


def test_unsupported_extended_operation_cannot_be_guessed_applied(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        operation="place_conditional_trigger",
        payload={
            "_op": "place_conditional_trigger",
            "condition": {"type": "price", "value": 2500},
            "orders": [_intent()],
        },
    )
    _record_empty_snapshot(provider)

    listed = provider.list_unresolved_outcomes()[0]
    assert listed["recovery_supported_outcomes"] == []
    assert "fail-closed" in listed["recovery_blocked_reason"]

    with pytest.raises(lifecycle_module.LifecycleStateError, match="operation-specific evidence"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Checked regular order book only",
            observed_at=OBSERVED_AT,
        )


def test_finalisation_remains_blocked_and_listed_until_router_clear_is_completed(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book contains no matching order",
        observed_at=OBSERVED_AT,
    )

    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT,
    )

    assert finalised["status"] == "PENDING_ROUTER_CLEAR"
    assert provider.is_outcome_resolved(attempt_id) is True
    assert provider.list_unresolved_outcomes()[0]["resolution"]["status"] == "PENDING_ROUTER_CLEAR"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        provider.assert_write_ready()

    with pytest.raises(lifecycle_module.LifecycleStateError, match="router-clear receipt"):
        provider.complete_outcome_resolution(
            pending["resolution_id"],
            observed_at=OBSERVED_AT,
        )

    mismatched_receipt = _router_clear_receipt(finalised)
    mismatched_receipt["attempt_id"] = "different-attempt"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="router-clear receipt"):
        provider.complete_outcome_resolution(
            pending["resolution_id"],
            router_clear_receipt=mismatched_receipt,
            router_clear_verifier=_verify_router_clear_receipt,
            observed_at=OBSERVED_AT,
        )

    completed = provider.complete_outcome_resolution(
        pending["resolution_id"],
        router_clear_receipt=_router_clear_receipt(finalised),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=OBSERVED_AT,
    )
    assert completed["status"] == "COMMITTED"
    assert provider.list_unresolved_outcomes() == []
    provider.assert_write_ready()


def test_pending_router_clear_survives_restart_and_remains_retryable(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker order book contains no matching order",
        observed_at=OBSERVED_AT,
    )
    provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT,
    )

    restarted = _provider(tmp_path)

    assert restarted.list_unresolved_outcomes()[0]["resolution"]["status"] == ("PENDING_ROUTER_CLEAR")
    assert restarted.is_outcome_resolved(attempt_id) is True
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        restarted.assert_write_ready()

    finalised = restarted.list_unresolved_outcomes()[0]["resolution"]
    restarted.complete_outcome_resolution(
        pending["resolution_id"],
        router_clear_receipt=_router_clear_receipt({**finalised, "attempt_id": attempt_id}),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=OBSERVED_AT,
    )
    restarted.assert_write_ready()


def test_applied_resolution_rolls_back_as_one_transaction_when_finalisation_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(provider, order_id="ATOMIC-1")
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["ATOMIC-1"],
        actor_type="human",
        actor_id="operator-1",
        observed_at=OBSERVED_AT,
    )

    def fail_health_refresh(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated final commit failure")

    monkeypatch.setattr(provider, "_refresh_outcome_health", fail_health_refresh)
    with pytest.raises(OSError, match="simulated final commit failure"):
        provider.finalize_outcome_resolution(
            pending["resolution_id"],
            audit_reference=_audit_reference(pending),
            observed_at=OBSERVED_AT,
        )

    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"
    unresolved = provider.list_unresolved_outcomes()
    assert unresolved[0]["resolution"]["status"] == "PENDING_AUDIT"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        provider.assert_write_ready()


def test_finalisation_uses_the_audited_immutable_generation_not_a_newer_snapshot(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Initial fresh order book was empty",
        observed_at=OBSERVED_AT,
    )
    _record_broker_order(
        provider,
        order_id="LATE-ORDER-1",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    assert finalised["status"] == "PENDING_ROUTER_CLEAR"
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_NOT_APPLIED"
    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        manifests = connection.execute(
            """SELECT generation, observed_at, content_digest
               FROM snapshot_generation_manifests
               ORDER BY generation"""
        ).fetchall()
    assert [manifest[0] for manifest in manifests] == [1, 2]
    assert manifests[0][2] == pending["snapshot_content_digest"]
    assert manifests[0][2] != manifests[1][2]


@pytest.mark.parametrize("surface", ["order", "position", "holding"])
@pytest.mark.parametrize("mutation", ["add", "remove", "change"])
def test_finalisation_recomputes_every_exact_generation_evidence_row(
    tmp_path,
    surface: str,
    mutation: str,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{
            "orderid": "IMMUTABLE-1",
            **_intent(status="OPEN", filled_quantity=0),
        }],
        positions=[{
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 5,
            "average_price": 2500,
        }],
        holdings=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "quantity": 2,
            "average_price": 3500,
        }],
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["IMMUTABLE-1"],
        actor_type="human",
        actor_id="operator-1",
        note="All exact generation rows were present at prepare",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _mutate_generation_evidence(
        tmp_path / "order-lifecycle.sqlite3",
        surface=surface,
        mutation=mutation,
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="evidence rows"):
        provider.finalize_outcome_resolution(
            pending["resolution_id"],
            audit_reference=_audit_reference(pending),
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )

    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"
    assert provider.list_unresolved_outcomes()[0]["resolution"]["status"] == "PENDING_AUDIT"


def test_completion_revalidates_bound_generation_after_router_clear(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{
            "orderid": "COMPLETE-IMMUTABLE-1",
            **_intent(status="OPEN", filled_quantity=0),
        }],
        positions=[{
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 5,
        }],
        holdings=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "quantity": 2,
        }],
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["COMPLETE-IMMUTABLE-1"],
        actor_type="human",
        actor_id="operator-1",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _mutate_generation_evidence(
        tmp_path / "order-lifecycle.sqlite3",
        surface="holding",
        mutation="change",
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="evidence rows"):
        provider.complete_outcome_resolution(
            pending["resolution_id"],
            router_clear_receipt=_router_clear_receipt(finalised),
            router_clear_verifier=_verify_router_clear_receipt,
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )

    assert provider.list_unresolved_outcomes()[0]["resolution"]["status"] == "PENDING_ROUTER_CLEAR"


def test_finalisation_uses_exact_generation_operation_status_evidence(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        operation="cancel_order",
        payload=_intent(orderid="CANCEL-TARGET-1"),
    )
    _record_broker_order(
        provider,
        order_id="CANCEL-TARGET-1",
        status="OPEN",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The target remained open in the forced reconciliation",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _record_broker_order(
        provider,
        order_id="CANCEL-TARGET-1",
        status="CANCELLED",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    assert finalised["snapshot_generation"] == 1
    assert finalised["snapshot_content_digest"] == pending["snapshot_content_digest"]
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "CONFIRMED_NOT_APPLIED"


def test_historical_matching_broker_order_blocks_later_not_applied_decision(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(
        provider,
        order_id="FILLED-THEN-GONE",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
        status="COMPLETE",
        filled_quantity=5,
    )
    _record_empty_snapshot(
        provider,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="durable matching broker order"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Latest order book is empty",
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )


def test_later_identity_change_cannot_erase_historical_matching_broker_order(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(
        provider,
        order_id="REUSED-BROKER-ID",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
        status="COMPLETE",
        filled_quantity=5,
    )
    _record_broker_order(
        provider,
        order_id="REUSED-BROKER-ID",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
        symbol="TCS",
        status="OPEN",
        filled_quantity=0,
    )
    _record_empty_snapshot(
        provider,
        observed_at=OBSERVED_AT + timedelta(minutes=3),
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="durable matching broker order"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Latest order book is empty after the broker changed the row identity",
            observed_at=OBSERVED_AT + timedelta(minutes=3),
        )


def test_pre_existing_matching_order_remains_eligible_for_negative_recovery(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="PRE-EXISTING-MATCH",
        observed_at=OBSERVED_AT - timedelta(minutes=2),
    )
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(
        provider,
        order_id="PRE-EXISTING-MATCH",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _record_empty_snapshot(
        provider,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The only matching broker order predates this dispatch attempt",
        required_snapshot_generation=3,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    assert pending["outcome"] == "confirmed_not_applied"


def test_schema_v5_backfill_uses_last_broker_observation_time_for_latest_identity(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="V5-REUSED-ID",
        symbol="TCS",
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(
        provider,
        order_id="V5-REUSED-ID",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM broker_order_observations")
        connection.execute("PRAGMA user_version = 5")

    restarted = _provider(tmp_path)
    with sqlite3.connect(path) as connection:
        observed_at = connection.execute(
            """SELECT observed_at FROM broker_order_observations
               WHERE broker_order_id = 'V5-REUSED-ID'"""
        ).fetchone()
    assert observed_at == ((OBSERVED_AT + timedelta(minutes=1)).isoformat(),)

    _record_empty_snapshot(
        restarted,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="history is incomplete"):
        restarted.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="Latest order book is empty after migration",
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )


def test_schema_v6_migration_blocks_negative_evidence_but_allows_exact_positive_proof(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    not_applied_attempt = _unknown_attempt(provider)
    partial_attempt = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", action="BUY", quantity=1),
                _intent(symbol="TCS", action="SELL", quantity=2),
            ],
        },
    )
    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE snapshot_generation_manifests")
        connection.execute("ALTER TABLE dispatch_attempts DROP COLUMN history_complete")
        connection.execute("ALTER TABLE dispatch_resolutions DROP COLUMN snapshot_content_digest")
        for column in (
            "status_raw",
            "status_normalized",
            "filled_quantity",
            "average_price",
            "first_seen_at",
        ):
            connection.execute(f"ALTER TABLE broker_order_observations DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 6")

    restarted = _provider(tmp_path)
    attempts = {attempt["attempt_id"]: attempt for attempt in restarted.list_dispatch_attempts()}
    assert attempts[not_applied_attempt]["history_complete"] == 0
    assert attempts[partial_attempt]["history_complete"] == 0
    with sqlite3.connect(path) as connection:
        observation_columns = {row[1] for row in connection.execute("PRAGMA table_info(broker_order_observations)")}
        resolution_columns = {row[1] for row in connection.execute("PRAGMA table_info(dispatch_resolutions)")}
        assert {
            "status_raw",
            "status_normalized",
            "filled_quantity",
            "average_price",
            "first_seen_at",
        }.issubset(observation_columns)
        assert "snapshot_content_digest" in resolution_columns
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
    unresolved = {attempt["attempt_id"]: attempt for attempt in restarted.list_unresolved_outcomes()}
    assert unresolved[not_applied_attempt]["recovery_supported_outcomes"] == ["confirmed_applied"]
    assert "history" in unresolved[not_applied_attempt]["recovery_blocked_reason"]

    _record_empty_snapshot(restarted)
    _record_broker_orders(
        restarted,
        adapter_id="upstox",
        orders=[
            {
                "orderid": "MIGRATED-PARTIAL-1",
                "symbol": "RELIANCE",
                "action": "BUY",
                "quantity": 1,
            }
        ],
    )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="history is incomplete"):
        restarted.prepare_outcome_resolution(
            attempt_id=not_applied_attempt,
            adapter_id="dhan",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_not_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            note="The latest order book is empty",
            required_snapshot_generation=1,
            observed_at=OBSERVED_AT + timedelta(minutes=1),
        )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="history is incomplete"):
        restarted.prepare_outcome_resolution(
            attempt_id=partial_attempt,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_partial",
            broker_order_ids=["MIGRATED-PARTIAL-1"],
            broker_order_item_indexes=[0],
            not_applied_item_indexes=[1],
            actor_type="human",
            actor_id="operator-1",
            note="Only the first child is visible",
            required_snapshot_generation=1,
            observed_at=OBSERVED_AT + timedelta(minutes=1),
        )

    _record_broker_order(
        restarted,
        order_id="MIGRATED-POSITIVE-1",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    positive = restarted.prepare_outcome_resolution(
        attempt_id=not_applied_attempt,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["MIGRATED-POSITIVE-1"],
        actor_type="human",
        actor_id="operator-1",
        note="An exact matching broker order proves application",
        required_snapshot_generation=2,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    fresh_attempt = _unknown_attempt(restarted, account_id="fresh-account")
    fresh = {attempt["attempt_id"]: attempt for attempt in restarted.list_dispatch_attempts()}

    assert positive["outcome"] == "confirmed_applied"
    assert fresh[fresh_attempt]["history_complete"] == 1


def test_schema_v6_migration_archives_unauditable_positive_router_clear(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(provider, order_id="LEGACY-POSITIVE-1")
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["LEGACY-POSITIVE-1"],
        actor_type="human",
        actor_id="operator-1",
        note="Legacy positive decision",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    assert finalised["status"] == "PENDING_ROUTER_CLEAR"

    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """UPDATE dispatch_resolutions
               SET evidence_digest = '', snapshot_content_digest = NULL,
                   audit_reference = '', audit_recorded_at = NULL
               WHERE resolution_id = ?""",
            (pending["resolution_id"],),
        )
        connection.execute("PRAGMA user_version = 6")
    restarted = _provider(tmp_path)

    assert restarted.list_dispatch_attempts()[0]["history_complete"] == 0
    assert restarted.list_dispatch_attempts()[0]["dispatch_state"] == "OUTCOME_UNKNOWN"
    assert not restarted.is_outcome_resolved(attempt_id)
    unresolved = restarted.list_unresolved_outcomes()[0]
    assert unresolved["resolution"] is None
    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not exist"):
        restarted.complete_outcome_resolution(
            pending["resolution_id"],
            router_clear_receipt=_router_clear_receipt(pending),
            router_clear_verifier=_verify_router_clear_receipt,
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )
    with sqlite3.connect(path) as connection:
        archived = connection.execute(
            """SELECT reason FROM dispatch_resolution_revisions
               WHERE resolution_id = ?""",
            (pending["resolution_id"],),
        ).fetchall()
    assert archived == [("schema_v8_evidence_revalidation_required",)]

    _record_broker_order(
        restarted,
        order_id="LEGACY-POSITIVE-1",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    fresh = restarted.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["LEGACY-POSITIVE-1"],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh audited positive decision",
        required_snapshot_generation=2,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )
    assert fresh["resolution_id"] != pending["resolution_id"]
    committed = _finalize_and_complete(restarted, fresh)
    assert committed["status"] == "COMMITTED"
    restarted.assert_write_ready()


def test_stale_or_same_time_conflicting_snapshot_cannot_supersede_newer_evidence(tmp_path) -> None:
    provider = _provider(tmp_path)
    generation = provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{"orderid": "NEWEST-1", **_intent(status="OPEN")}],
        positions=[],
        holdings=[],
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="older"):
        _record_empty_snapshot(
            provider,
            observed_at=OBSERVED_AT + timedelta(minutes=1),
        )
    with pytest.raises(lifecycle_module.LifecycleStateError, match="same timestamp"):
        _record_empty_snapshot(
            provider,
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )

    assert generation == 1
    assert provider.latest_snapshot_generation(adapter_id="dhan", account_id="personal") == 1


def test_fresh_evidence_can_auditably_supersede_pending_decision(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider, observed_at=OBSERVED_AT + timedelta(minutes=1))
    original = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Initial order book was empty",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _record_broker_order(
        provider,
        order_id="LATE-APPLIED-1",
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    replacement = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["LATE-APPLIED-1"],
        actor_type="human",
        actor_id="operator-1",
        note="Fresh broker evidence superseded the unaudited decision",
        required_snapshot_generation=2,
        observed_at=OBSERVED_AT + timedelta(minutes=2),
    )

    assert replacement["resolution_id"] != original["resolution_id"]
    assert replacement["outcome"] == "confirmed_applied"
    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        revision = connection.execute("SELECT resolution_id, reason FROM dispatch_resolution_revisions").fetchone()
    assert revision == (original["resolution_id"], "operator_superseded")


def test_empty_multi_order_cannot_be_resolved_as_applied_without_broker_ids(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        adapter_id="upstox",
        operation="place_multi_order",
        payload={"_op": "place_multi_order", "orders": []},
    )

    with pytest.raises(ValueError, match="at least one persisted child intent"):
        provider.prepare_outcome_resolution(
            attempt_id=attempt_id,
            adapter_id="upstox",
            account_id="personal",
            business_date="2026-07-15",
            outcome="confirmed_applied",
            broker_order_ids=[],
            actor_type="human",
            actor_id="operator-1",
            observed_at=OBSERVED_AT,
        )


def test_restart_marks_prepared_attempt_failed_before_invoke(tmp_path) -> None:
    provider = _provider(tmp_path)
    provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )

    restarted = _provider(tmp_path)

    attempt = restarted.list_dispatch_attempts()[0]
    assert attempt["dispatch_state"] == "FAILED_BEFORE_INVOKE"
    assert attempt["error_kind"] == "process_restart_before_invoke"
    restarted.assert_write_ready()


def test_restart_marks_invoked_attempt_unknown_and_blocks_writes(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    restarted = _provider(tmp_path)

    attempt = restarted.list_dispatch_attempts()[0]
    assert attempt["dispatch_state"] == "OUTCOME_UNKNOWN"
    assert attempt["error_kind"] == "process_restart_after_invoke"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        restarted.assert_write_ready()


def test_failure_before_invocation_is_not_misreported_as_unknown_broker_outcome(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )

    provider.mark_failed_before_invoke(attempt_id, "adapter_unavailable", observed_at=OBSERVED_AT)

    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "FAILED_BEFORE_INVOKE"
    assert provider(_Session()).orders == ()


def test_multi_order_acknowledgement_preserves_each_correlated_intent(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="upstox",
        account_id="personal",
        operation="place_multi_order",
        request_context=_request_context(),
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", action="BUY", quantity=1, price=2500),
                _intent(symbol="TCS", action="SELL", quantity=2, price=3500),
            ],
        },
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    provider.acknowledge(
        attempt_id,
        {
            "order_ids": ["BASKET-2", "BASKET-1"],
            "order_results": [
                {"order_id": "BASKET-2", "correlation_id": "2"},
                {"order_id": "BASKET-1", "correlation_id": "1"},
            ],
            "errors": [],
            "total": 2,
            "success": 2,
        },
        observed_at=OBSERVED_AT,
    )

    orders = {row["orderid"]: row for row in provider(_Session(adapter_id="upstox")).orders}
    assert orders["BASKET-1"] | {"orderid": "BASKET-1"} == {
        "orderid": "BASKET-1",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "status": "SUBMITTED",
        "quantity": 1.0,
        "filled_quantity": 0.0,
        "price": 2500.0,
        "average_price": 0.0,
    }
    assert orders["BASKET-2"]["symbol"] == "TCS"
    assert orders["BASKET-2"]["action"] == "SELL"
    assert orders["BASKET-2"]["quantity"] == 2.0
    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "ACKNOWLEDGED"
    provider.assert_write_ready()


def test_partial_multi_order_acknowledgement_maps_success_by_correlation(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="upstox",
        account_id="personal",
        operation="place_multi_order",
        request_context=_request_context(),
        payload={
            "_op": "place_multi_order",
            "orders": [
                _intent(symbol="RELIANCE", quantity=1),
                _intent(symbol="TCS", action="SELL", quantity=2),
            ],
        },
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    provider.acknowledge(
        attempt_id,
        {
            "order_ids": ["BASKET-2"],
            "order_results": [{"order_id": "BASKET-2", "correlation_id": "2"}],
            "errors": [{"error_code": "REJECTED", "correlation_id": "1"}],
            "total": 2,
            "success": 1,
        },
        observed_at=OBSERVED_AT,
    )

    assert provider(_Session(adapter_id="upstox")).orders == (
        {
            "orderid": "BASKET-2",
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "status": "SUBMITTED",
            "quantity": 2.0,
            "filled_quantity": 0.0,
            "price": 2500.5,
            "average_price": 0.0,
        },
    )
    attempt = provider.list_dispatch_attempts()[0]
    assert attempt["dispatch_state"] == "ACKNOWLEDGED"
    assert attempt["error_kind"] == "partial_batch"
    provider.assert_write_ready()


def test_explicit_reducing_order_noop_is_acknowledged_without_fabricating_order(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="upstox",
        account_id="personal",
        operation="place_reducing_order",
        request_context=_request_context(),
        payload={"_op": "place_reducing_order", **_intent()},
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    provider.acknowledge(
        attempt_id,
        {"order_ids": [], "errors": [], "total": 0, "success": 0},
        observed_at=OBSERVED_AT,
    )

    attempt = provider.list_dispatch_attempts()[0]
    assert attempt["dispatch_state"] == "ACKNOWLEDGED"
    assert attempt["error_kind"] == "position_already_flat"
    assert provider(_Session(adapter_id="upstox")).orders == ()
    provider.assert_write_ready()


def test_cancel_sweep_may_acknowledge_multiple_affected_order_ids(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="upstox",
        account_id="personal",
        operation="cancel_all_orders",
        request_context=_request_context(),
        payload={"_op": "cancel_all_orders"},
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    provider.acknowledge(
        attempt_id,
        {"order_ids": ["ORD-1", "ORD-2"], "errors": [], "total": 2, "success": 2},
        observed_at=OBSERVED_AT,
    )

    assert provider.list_dispatch_attempts()[0]["dispatch_state"] == "ACKNOWLEDGED"
    assert provider(_Session(adapter_id="upstox")).orders == ()
    provider.assert_write_ready()


def test_ordinary_placement_without_order_id_remains_ambiguous(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    with pytest.raises(
        lifecycle_module.LifecycleStateError,
        match="placement acknowledgement has no canonical order id",
    ):
        provider.acknowledge(attempt_id, {"status": "success"}, observed_at=OBSERVED_AT)


def test_unresolved_acknowledged_order_survives_empty_snapshots_and_restart(tmp_path) -> None:
    provider = _provider(tmp_path)
    _acknowledged_order(provider, order_id="LOCAL-ONLY")

    for minute in (31, 32):
        provider.record_broker_snapshot(
            adapter_id="dhan",
            account_id="personal",
            orders=[],
            positions=[],
            holdings=[],
            observed_at=datetime(2026, 7, 15, 9, minute, tzinfo=timezone.utc),
        )

    restarted = _provider(tmp_path)
    local = restarted(_Session())
    assert [order["orderid"] for order in local.orders] == ["LOCAL-ONLY"]
    report = build_report(
        adapter_id="dhan",
        account_id="personal",
        generated_at=datetime(2026, 7, 15, 9, 33, tzinfo=timezone.utc),
        broker_orders=[],
        local_state=local,
    )
    assert report.clean is False
    assert report.orders_diff[0].discrepancy == "exists_only_in_flinttrade"


def test_reconciliation_snapshot_excludes_prior_business_dates(tmp_path) -> None:
    prior_day = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)
    provider = _provider(tmp_path)
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=prior_day,
    )
    provider.mark_invoked(attempt_id, observed_at=prior_day)
    provider.acknowledge(attempt_id, "PRIOR-DAY", observed_at=prior_day)
    _acknowledged_order(provider, order_id="CURRENT-DAY")

    assert [order["orderid"] for order in provider(_Session()).orders] == ["CURRENT-DAY"]


def test_broker_only_order_remains_external_observation_not_local_truth(tmp_path) -> None:
    provider = _provider(tmp_path)
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[
            {
                "orderid": "EXTERNAL-1",
                "symbol": "SBIN",
                "exchange": "NSE",
                "product": "CNC",
                "action": "BUY",
                "status": "OPEN",
                "quantity": 1,
                "filled_quantity": 0,
            }
        ],
        positions=[],
        holdings=[],
        observed_at=OBSERVED_AT,
    )

    assert _provider(tmp_path)(_Session()).orders == ()
    events = provider.list_order_events(adapter_id="dhan", account_id="personal", order_id="EXTERNAL-1")
    assert events[0]["origin"] == "external"
    assert events[0]["broker_present"] == 1


def test_acknowledgement_promotes_a_racing_broker_observation_without_status_regression(
    tmp_path,
) -> None:
    provider = _provider(tmp_path)
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[
            {
                "orderid": "RACE-1",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "action": "BUY",
                "status": "COMPLETE",
                "quantity": 5,
                "filled_quantity": 5,
                "price": 2500.5,
                "average_price": 2499.75,
            }
        ],
        positions=[],
        holdings=[],
        observed_at=OBSERVED_AT,
    )
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(attempt_id, observed_at=OBSERVED_AT)

    provider.acknowledge(attempt_id, "RACE-1", observed_at=OBSERVED_AT)

    assert provider(_Session()).orders == (
        {
            "orderid": "RACE-1",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "status": "COMPLETE",
            "quantity": 5.0,
            "filled_quantity": 5.0,
            "price": 2500.5,
            "average_price": 2499.75,
        },
    )
    events = provider.list_order_events(
        adapter_id="dhan",
        account_id="personal",
        order_id="RACE-1",
    )
    assert [event["origin"] for event in events] == ["external", "flinttrade"]
    assert [event["status"] for event in events] == ["COMPLETE", "COMPLETE"]


def test_broker_order_id_cannot_be_reassigned_to_another_dispatch_attempt(tmp_path) -> None:
    provider = _provider(tmp_path)
    _acknowledged_order(provider, order_id="DUPLICATE-1")
    second_attempt = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(jti="second-jti"),
        payload=_intent(symbol="TCS"),
        observed_at=OBSERVED_AT,
    )
    provider.mark_invoked(second_attempt, observed_at=OBSERVED_AT)

    with pytest.raises(
        lifecycle_module.LifecycleStateError,
        match="already associated with another dispatch attempt",
    ):
        provider.acknowledge(second_attempt, "DUPLICATE-1", observed_at=OBSERVED_AT)

    attempts = {attempt["attempt_id"]: attempt for attempt in provider.list_dispatch_attempts()}
    assert attempts[second_attempt]["dispatch_state"] == "INVOKED"
    assert provider(_Session()).orders[0]["symbol"] == "RELIANCE"


def test_broker_observation_advances_only_matching_flinttrade_order(tmp_path) -> None:
    provider = _provider(tmp_path)
    _acknowledged_order(provider)
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[
            {
                "orderid": "ORD-1",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "action": "BUY",
                "status": "COMPLETE",
                "quantity": 5,
                "filled_quantity": 5,
                "average_price": 2499.75,
            }
        ],
        positions=[
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 5,
            }
        ],
        holdings=[],
        observed_at=datetime(2026, 7, 15, 9, 31, tzinfo=timezone.utc),
    )

    order = provider(_Session()).orders[0]
    assert order["status"] == "COMPLETE"
    assert order["filled_quantity"] == 5.0
    events = provider.list_order_events(adapter_id="dhan", account_id="personal", order_id="ORD-1")
    assert [event["status"] for event in events] == ["SUBMITTED", "COMPLETE"]
    assert events[-1]["terminal_at"] == datetime(2026, 7, 15, 9, 31, tzinfo=timezone.utc).isoformat()
    # Broker positions/holdings are observations, not independent FlintTrade truth.
    assert provider(_Session()).positions == ()


def test_terminal_or_fill_regression_is_not_adopted(tmp_path) -> None:
    provider = _provider(tmp_path)
    _acknowledged_order(provider)
    common = {
        "adapter_id": "dhan",
        "account_id": "personal",
        "positions": [],
        "holdings": [],
    }
    provider.record_broker_snapshot(
        orders=[
            {
                **_intent(status="COMPLETE"),
                "orderid": "ORD-1",
                "filled_quantity": 5,
            }
        ],
        observed_at=datetime(2026, 7, 15, 9, 31, tzinfo=timezone.utc),
        **common,
    )
    provider.record_broker_snapshot(
        orders=[
            {
                **_intent(status="OPEN"),
                "orderid": "ORD-1",
                "filled_quantity": 0,
            }
        ],
        observed_at=datetime(2026, 7, 15, 9, 32, tzinfo=timezone.utc),
        **common,
    )

    order = provider(_Session()).orders[0]
    assert order["status"] == "COMPLETE"
    assert order["filled_quantity"] == 5.0
    assert [
        event["status"]
        for event in provider.list_order_events(adapter_id="dhan", account_id="personal", order_id="ORD-1")
    ] == ["SUBMITTED", "COMPLETE"]


def test_colon_bearing_and_underscore_accounts_never_collide(tmp_path) -> None:
    provider = _provider(tmp_path)
    _acknowledged_order(provider, account_id="acct:a", order_id="COLON")
    _acknowledged_order(provider, account_id="acct_a", order_id="UNDERSCORE")

    assert provider(_Session("acct:a")).orders[0]["orderid"] == "COLON"
    assert provider(_Session("acct_a")).orders[0]["orderid"] == "UNDERSCORE"


def test_two_provider_instances_deduplicate_identical_lifecycle_event(tmp_path) -> None:
    first = _provider(tmp_path)
    _acknowledged_order(first)
    snapshot = {
        "adapter_id": "dhan",
        "account_id": "personal",
        "orders": [
            {
                "orderid": "ORD-1",
                **_intent(status="OPEN"),
                "filled_quantity": 0,
            }
        ],
        "positions": [],
        "holdings": [],
        "observed_at": datetime(2026, 7, 15, 9, 31, tzinfo=timezone.utc),
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda provider: provider.record_broker_snapshot(**snapshot), (first, _provider(tmp_path))))

    events = first.list_order_events(adapter_id="dhan", account_id="personal", order_id="ORD-1")
    assert [event["status"] for event in events] == ["SUBMITTED", "OPEN"]


def test_unversioned_draft_rows_migrate_without_dropping_absent_nonterminal_order(tmp_path) -> None:
    path = tmp_path / "order-lifecycle.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE order_lifecycle (
            adapter_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL DEFAULT '',
            exchange TEXT NOT NULL DEFAULT '',
            product TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            filled_quantity REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            average_price REAL NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            terminal_at TEXT,
            present INTEGER NOT NULL DEFAULT 1,
            raw_json TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (adapter_id, account_id, order_id)
        );
        CREATE TABLE order_lifecycle_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            adapter_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            filled_quantity REAL NOT NULL DEFAULT 0,
            terminal_at TEXT,
            present INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}'
        );
        INSERT INTO order_lifecycle VALUES (
            'dhan', 'personal', 'LEGACY-1', 'TCS', 'NSE', 'MIS', 'BUY',
            'OPEN', 2, 0, 0, 0,
            '2026-07-15T09:00:00+00:00', '2026-07-15T09:01:00+00:00', NULL, 0, '{}'
        );
        INSERT INTO order_lifecycle_events (
            adapter_id, account_id, order_id, observed_at, source, status,
            quantity, filled_quantity, terminal_at, present, fingerprint, raw_json
        ) VALUES (
            'dhan', 'personal', 'LEGACY-1', '2026-07-15T09:01:00+00:00',
            'broker_snapshot_absent', 'OPEN', 2, 0, NULL, 0, 'legacy-fingerprint', '{}'
        );
        """
    )
    connection.commit()
    connection.close()

    # Pin the clock to the migrated rows' business date — __call__ scopes the
    # snapshot to the current business date, so a real-time clock would drop
    # these 2026-07-15 rows on any later calendar day (a date-rollover flake).
    provider = OrderLifecycleLedger(ledger_path=path, clock=lambda: OBSERVED_AT)

    assert provider(_Session()).orders[0]["orderid"] == "LEGACY-1"
    assert (
        provider.list_order_events(adapter_id="dhan", account_id="personal", order_id="LEGACY-1")[0]["status"] == "OPEN"
    )
    with sqlite3.connect(path) as migrated:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 8


def test_schema_v2_unknown_health_migrates_without_releasing_write_block(tmp_path) -> None:
    provider = _provider(tmp_path)
    _unknown_attempt(provider)
    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE ledger_health_v2 (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                status TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            INSERT INTO ledger_health_v2
                SELECT singleton, status, reason, updated_at FROM ledger_health;
            DROP TABLE ledger_health;
            ALTER TABLE ledger_health_v2 RENAME TO ledger_health;
            PRAGMA user_version = 2;
            """
        )

    restarted = _provider(tmp_path)

    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        restarted.assert_write_ready()
    with sqlite3.connect(path) as migrated:
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(ledger_health)")}
        assert {"source", "attempt_id"}.issubset(columns)
        health = migrated.execute("SELECT status, source, attempt_id FROM ledger_health WHERE singleton = 1").fetchone()
        assert health is not None
        assert health[0:2] == ("CRITICAL", "legacy_critical")
        assert health[2] is None
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 8

    with pytest.raises(lifecycle_module.LifecycleStateError, match="broker outcome unknown"):
        restarted.assert_write_ready()


def test_schema_v3_migrates_resolution_and_broker_evidence_columns(tmp_path) -> None:
    provider = _provider(tmp_path)
    path = tmp_path / "order-lifecycle.sqlite3"
    del provider
    with sqlite3.connect(path) as connection:
        for column in ("trigger_price", "price_type", "variety", "validity", "strategy"):
            connection.execute(f"ALTER TABLE orders_current DROP COLUMN {column}")
        for column in (
            "broker_order_item_indexes",
            "not_applied_item_indexes",
            "snapshot_generation",
            "snapshot_observed_at",
            "router_cleared_at",
        ):
            connection.execute(f"ALTER TABLE dispatch_resolutions DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 3")

    _provider(tmp_path)

    with sqlite3.connect(path) as migrated:
        order_columns = {row[1] for row in migrated.execute("PRAGMA table_info(orders_current)")}
        resolution_columns = {row[1] for row in migrated.execute("PRAGMA table_info(dispatch_resolutions)")}
        assert {"trigger_price", "price_type", "variety", "validity", "strategy"}.issubset(order_columns)
        assert {
            "broker_order_item_indexes",
            "not_applied_item_indexes",
            "snapshot_generation",
            "snapshot_observed_at",
            "router_cleared_at",
        }.issubset(resolution_columns)
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 8


@pytest.mark.parametrize("mutation", ["extra_order", "changed_position", "deleted_holding"])
def test_finalisation_rejects_mutated_exact_generation_evidence(tmp_path, mutation: str) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(
        provider,
        operation="cancel_order",
        payload=_intent(orderid="MUTATION-TARGET"),
    )
    provider.record_broker_snapshot(
        adapter_id="dhan",
        account_id="personal",
        orders=[{
            **_intent(),
            "orderid": "MUTATION-TARGET",
            "status": "OPEN",
            "filled_quantity": 0,
        }],
        positions=[{
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 5,
            "average_price": 2500.5,
        }],
        holdings=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "quantity": 2,
            "average_price": 3500,
        }],
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The target remained open in the forced snapshot",
        required_snapshot_generation=1,
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )

    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        if mutation == "extra_order":
            connection.execute(
                """INSERT INTO broker_order_observations
                   SELECT adapter_id, account_id, business_date, generation,
                          'FORGED-EXTRA', observed_at, symbol, exchange, product,
                          action, status_raw, status_normalized, quantity,
                          filled_quantity, price, trigger_price, price_type,
                          variety, validity, strategy, average_price, first_seen_at
                   FROM broker_order_observations
                   WHERE broker_order_id = 'MUTATION-TARGET'"""
            )
        elif mutation == "changed_position":
            table = (
                "position_generation_observations"
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'position_generation_observations'"
                ).fetchone()
                else "position_observations"
            )
            connection.execute(f"UPDATE {table} SET quantity = quantity + 1")  # noqa: S608
        else:
            table = (
                "holding_generation_observations"
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'holding_generation_observations'"
                ).fetchone()
                else "holding_observations"
            )
            connection.execute(f"DELETE FROM {table}")  # noqa: S608

    with pytest.raises(lifecycle_module.LifecycleStateError, match="snapshot evidence"):
        provider.finalize_outcome_resolution(
            pending["resolution_id"],
            audit_reference=_audit_reference(pending),
            observed_at=OBSERVED_AT + timedelta(minutes=2),
        )


def test_schema_v8_archives_unproved_pending_resolution_and_requires_fresh_audit(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The forced broker snapshot was empty",
        required_snapshot_generation=1,
    )
    provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
    )

    path = tmp_path / "order-lifecycle.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """UPDATE dispatch_resolutions
               SET snapshot_generation = NULL,
                   snapshot_observed_at = NULL,
                   snapshot_content_digest = NULL,
                   audit_reference = '',
                   audit_recorded_at = NULL
               WHERE resolution_id = ?""",
            (pending["resolution_id"],),
        )
        connection.execute(
            "UPDATE dispatch_attempts SET dispatch_state = 'ACKNOWLEDGED' WHERE attempt_id = ?",
            (attempt_id,),
        )
        connection.execute("PRAGMA user_version = 7")

    restarted = OrderLifecycleLedger(
        ledger_path=path,
        clock=lambda: OBSERVED_AT,
        audit_receipt_verifier=lambda *_args, **_kwargs: False,
    )
    unresolved = restarted.list_unresolved_outcomes()[0]
    assert unresolved["resolution"] is None
    assert unresolved["dispatch_state"] == "OUTCOME_UNKNOWN"
    with pytest.raises(lifecycle_module.LifecycleStateError, match="requires reconciliation"):
        restarted.assert_write_ready()
    with sqlite3.connect(path) as connection:
        revision = connection.execute(
            "SELECT resolution_id, reason FROM dispatch_resolution_revisions ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()
    assert revision == (pending["resolution_id"], "schema_v8_evidence_revalidation_required")
    with pytest.raises(lifecycle_module.LifecycleStateError, match="does not exist"):
        restarted.complete_outcome_resolution(pending["resolution_id"])

    _record_empty_snapshot(restarted, observed_at=OBSERVED_AT + timedelta(minutes=2))
    replacement = restarted.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="A new forced snapshot is required after migration",
        required_snapshot_generation=2,
    )
    assert replacement["resolution_id"] != pending["resolution_id"]
    with pytest.raises(lifecycle_module.LifecycleStateError, match="audit receipt is invalid"):
        restarted.finalize_outcome_resolution(
            replacement["resolution_id"],
            audit_reference="always-rejected",
        )


def test_completion_requires_bound_router_generation_clear_proof(tmp_path) -> None:
    provider = _provider(tmp_path)
    attempt_id = _unknown_attempt(provider)
    _record_empty_snapshot(provider)
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The forced broker snapshot was empty",
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
    )

    with pytest.raises(lifecycle_module.LifecycleStateError, match="router-clear proof"):
        provider.complete_outcome_resolution(finalised["resolution_id"])

    committed = provider.complete_outcome_resolution(
        finalised["resolution_id"],
        router_clear_receipt=_router_clear_receipt(finalised),
        router_clear_verifier=_verify_router_clear_receipt,
    )
    assert committed["status"] == "COMMITTED"


def test_positive_recovery_across_ist_rollover_has_one_visible_flinttrade_projection(tmp_path) -> None:
    before_rollover = datetime(2026, 7, 15, 18, 20, tzinfo=timezone.utc)
    after_rollover = datetime(2026, 7, 15, 18, 40, tzinfo=timezone.utc)
    provider = OrderLifecycleLedger(
        ledger_path=tmp_path / "order-lifecycle.sqlite3",
        clock=lambda: after_rollover,
        audit_receipt_verifier=_verify_audit_receipt,
    )
    attempt_id = provider.prepare_dispatch(
        adapter_id="dhan",
        account_id="personal",
        operation="place_order",
        request_context=_request_context(),
        payload=_intent(),
        observed_at=before_rollover,
    )
    provider.mark_invoked(attempt_id, observed_at=before_rollover + timedelta(minutes=1))
    provider.mark_outcome_unknown(
        attempt_id,
        "broker_timeout",
        observed_at=before_rollover + timedelta(minutes=2),
    )
    _record_broker_order(
        provider,
        order_id="ROLLOVER-RECOVERED",
        observed_at=after_rollover,
    )
    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_applied",
        broker_order_ids=["ROLLOVER-RECOVERED"],
        actor_type="human",
        actor_id="operator-1",
        note="The post-rollover broker snapshot contains the exact order",
        required_snapshot_generation=1,
        observed_at=after_rollover,
    )
    finalised = provider.finalize_outcome_resolution(
        pending["resolution_id"],
        audit_reference=_audit_reference(pending),
        observed_at=after_rollover,
    )
    provider.complete_outcome_resolution(
        pending["resolution_id"],
        router_clear_receipt=_router_clear_receipt(finalised),
        router_clear_verifier=_verify_router_clear_receipt,
        observed_at=after_rollover,
    )

    assert [row["orderid"] for row in provider(_Session()).orders] == ["ROLLOVER-RECOVERED"]
    with sqlite3.connect(tmp_path / "order-lifecycle.sqlite3") as connection:
        rows = connection.execute(
            """SELECT business_date, origin, attempt_id
               FROM orders_current WHERE broker_order_id = 'ROLLOVER-RECOVERED'"""
        ).fetchall()
    assert rows == [("2026-07-16", "flinttrade", attempt_id)]


@pytest.mark.parametrize(
    ("outcome", "post_quantity", "post_price"),
    [
        ("confirmed_applied", 3, 2510),
        ("confirmed_not_applied", 2, 2500),
    ],
)
def test_full_shape_modify_recovery_compares_only_actual_operator_deltas(
    tmp_path,
    outcome: str,
    post_quantity: int,
    post_price: int,
) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="MODIFY-FULL-SHAPE",
        quantity=2,
        price=2500,
        price_type="LIMIT",
        strategy="",
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    attempt_id = _unknown_attempt(
        provider,
        operation="modify_order",
        payload={
            "_op": "modify",
            "order_id": "MODIFY-FULL-SHAPE",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "product": "MIS",
            "quantity": 3,
            "price": 2510,
            "price_type": "LIMIT",
            "strategy": "Flint",
            "_requested_change_fields": [
                "symbol",
                "exchange",
                "action",
                "product",
                "quantity",
                "price",
                "price_type",
            ],
        },
    )
    _record_broker_order(
        provider,
        order_id="MODIFY-FULL-SHAPE",
        quantity=post_quantity,
        price=post_price,
        price_type="LIMIT",
        strategy="",
    )

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome=outcome,
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The forced snapshot conclusively shows the requested price and quantity state",
        required_snapshot_generation=2,
    )
    assert pending["status"] == "PENDING_AUDIT"


def test_explicit_zero_modify_delta_is_checked_as_requested_change(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="MODIFY-ZERO",
        trigger_price=10,
        observed_at=OBSERVED_AT - timedelta(minutes=1),
    )
    attempt_id = _unknown_attempt(
        provider,
        operation="modify_order",
        payload={
            "_op": "modify",
            "order_id": "MODIFY-ZERO",
            "trigger_price": 0,
            "_requested_change_fields": ["trigger_price"],
        },
    )
    _record_broker_order(provider, order_id="MODIFY-ZERO", trigger_price=10)

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="The explicit zero trigger-price replacement did not apply",
        required_snapshot_generation=2,
    )
    assert pending["status"] == "PENDING_AUDIT"


def test_reobserved_preexisting_match_does_not_block_negative_placement_recovery(tmp_path) -> None:
    provider = _provider(tmp_path)
    _record_broker_order(
        provider,
        order_id="PREEXISTING-MATCH",
        observed_at=OBSERVED_AT - timedelta(minutes=2),
    )
    attempt_id = _unknown_attempt(provider)
    _record_broker_order(
        provider,
        order_id="PREEXISTING-MATCH",
        observed_at=OBSERVED_AT + timedelta(minutes=1),
    )
    _record_empty_snapshot(provider, observed_at=OBSERVED_AT + timedelta(minutes=2))

    pending = provider.prepare_outcome_resolution(
        attempt_id=attempt_id,
        adapter_id="dhan",
        account_id="personal",
        business_date="2026-07-15",
        outcome="confirmed_not_applied",
        broker_order_ids=[],
        actor_type="human",
        actor_id="operator-1",
        note="Only a broker order first seen before invocation matched the intent",
        required_snapshot_generation=3,
    )
    assert pending["status"] == "PENDING_AUDIT"


def test_compatibility_name_points_to_canonical_ledger() -> None:
    assert JournalLocalStateProvider is OrderLifecycleLedger


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="platform lacks symlink support")
def test_symbolic_link_ledger_is_rejected(tmp_path) -> None:
    target = tmp_path / "target.sqlite3"
    target.touch()
    link = tmp_path / "order-lifecycle.sqlite3"
    link.symlink_to(target)

    with pytest.raises(OSError, match="symbolic link"):
        OrderLifecycleLedger(ledger_path=link)


def test_corrupt_ledger_fails_closed_instead_of_returning_empty_truth(tmp_path) -> None:
    path = tmp_path / "order-lifecycle.sqlite3"
    path.write_bytes(b"not a sqlite database")

    with pytest.raises(sqlite3.DatabaseError):
        OrderLifecycleLedger(ledger_path=path)
