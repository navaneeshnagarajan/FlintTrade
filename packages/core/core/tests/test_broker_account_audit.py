"""Stable, redacted account evidence and verified delivery regressions."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from flinttrade_core.account_lifecycle_contracts import (
    AccountContractError,
    AccountMutationKind,
    AccountOperationStage,
)
from flinttrade_core.broker_account_audit import (
    ACCOUNT_AUDIT_EVENT_TYPE,
    AccountAuditUnavailable,
    AccountMutationAudit,
    build_account_audit_sink,
)
from flinttrade_data.audit_logger import AuditLogger


def event():
    return AccountMutationAudit(
        event_id=uuid4(), operation_ref="a" * 64, selector_ref="b" * 64,
        actor_ref="c" * 64, session_ref="d" * 64,
        kind=AccountMutationKind.CONNECT, state=AccountOperationStage.COMMITTED,
        expected_credential_generation=0, credential_generation=1,
        expected_workspace_generation=1, workspace_generation=2,
        expected_broker_generation=1, broker_generation=2,
    )


@pytest.mark.parametrize("field,value", [
    ("event_id", "not-an-event"), ("selector_ref", "private-account"),
    ("actor_ref", "private-actor"), ("session_ref", "session:" + "d" * 64),
    ("operation_ref", "A" * 64), ("kind", "connect"), ("state", "committed"),
    ("state", AccountOperationStage.ADMITTED),
    ("expected_credential_generation", True), ("credential_generation", None),
    ("credential_generation", 0), ("workspace_generation", 1),
    ("broker_generation", False),
])
def test_account_audit_rejects_private_or_invalid_evidence(field, value):
    with pytest.raises(AccountContractError, match="account_contract_invalid"):
        replace(event(), **{field: value})


def test_account_audit_exact_round_trip_and_detached_safe_fields():
    value = event()
    assert AccountMutationAudit.from_dict(value.to_dict()) == value
    fields = value.fields()
    assert "event_id" not in fields
    assert {"credentials", "label", "actor", "account_id", "reason", "session_binding"}.isdisjoint(fields)
    fields["actor_ref"] = "changed"
    assert value.fields()["actor_ref"] == "c" * 64


@pytest.mark.parametrize("mutation", ["extend", "digest", "schema", "identity", "counter"])
def test_account_audit_serialised_evidence_cannot_be_extended_or_rebound(mutation):
    body = event().to_dict()
    if mutation == "extend":
        body["credentials"] = "private-secret"
    elif mutation == "digest":
        body["evidence_digest"] = "e" * 64
    elif mutation == "schema":
        body["schema"] = True
    elif mutation == "identity":
        body["event_id"] = str(uuid4())
    else:
        body["workspace_generation"] = 3
    with pytest.raises(AccountContractError, match="account_contract_invalid"):
        AccountMutationAudit.from_dict(body)


def test_account_audit_unknown_outcome_never_claims_commit_versions():
    value = replace(event(), state=AccountOperationStage.AUTHENTICATION_UNKNOWN,
                    credential_generation=None, workspace_generation=None, broker_generation=None)
    assert AccountMutationAudit.from_dict(value.to_dict()) == value
    with pytest.raises(AccountContractError):
        replace(value, credential_generation=1)


@pytest.mark.parametrize("failure", ["wrong_ack", "unverified", "throw"])
def test_account_audit_sink_refuses_false_delivery_without_sink_details(failure):
    value = event()
    logger = Mock()
    logger.log_idempotent_event.return_value = str(value.event_id)
    logger.verify_idempotent_event_receipt.return_value = True
    if failure == "wrong_ack":
        logger.log_idempotent_event.return_value = str(uuid4())
    elif failure == "unverified":
        logger.verify_idempotent_event_receipt.return_value = False
    else:
        logger.log_idempotent_event.side_effect = RuntimeError("private-account private-secret")
    with pytest.raises(AccountAuditUnavailable) as error:
        build_account_audit_sink(logger)(value)
    assert str(error.value) == "account_audit_unavailable"
    assert error.value.__suppress_context__


def test_account_audit_real_sink_deduplicates_after_lost_acknowledgement(tmp_path):
    value = event()
    with AuditLogger(str(tmp_path)) as logger:
        # This append could complete before a process loses the delivery result.
        logger.log_idempotent_event(ACCOUNT_AUDIT_EVENT_TYPE, event_id=str(value.event_id), fields=value.fields())
        assert build_account_audit_sink(logger)(value) == value.event_id
        assert build_account_audit_sink(logger)(value) == value.event_id
        assert logger.verify_chain()["ok"]
    records = [line for path in tmp_path.glob("audit_*.jsonl") for line in path.read_text().splitlines()]
    assert len(records) == 1


def test_account_audit_real_sink_refuses_an_id_bound_to_different_evidence(tmp_path):
    value = event()
    with AuditLogger(str(tmp_path)) as logger:
        logger.log_idempotent_event(ACCOUNT_AUDIT_EVENT_TYPE, event_id=str(value.event_id), fields=value.fields())
        with pytest.raises(AccountAuditUnavailable):
            build_account_audit_sink(logger)(replace(value, actor_ref="e" * 64))
