"""Learning consent at actual sends, with inert callbacks and fresh ledgers."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from flinttrade_core.service_connections import ServiceConnectionRef
from flinttrade_core.service_providers import (
    LicenceFact, PermissionState, RightsBasis, RightsGrant, UsageRights, intersect_rights,
)
from flinttrade_core.service_usage import ServiceUsageLedger
from flinttrade_core.service_usage_contracts import BudgetPolicy, TariffSnapshot, UsageAmounts, USAGE_DIMENSIONS

NOW = datetime(2026, 1, 1, tzinfo=UTC)
CONNECTION = ServiceConnectionRef("llm:openai", UUID("4c0687bf-c7b2-455b-9a43-3220121d40ab"))


def setup_gate(tmp_path):
    from flinttrade_core.learning_consent import LearningConsentLedger, DatasetScope, Recipient
    usage = ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW)
    usage.configure_budget(BudgetPolicy(CONNECTION, "USD", NOW, NOW + timedelta(days=1),
                                       {key: 100000 for key in USAGE_DIMENSIONS}), expected_revision=0)
    gate = LearningConsentLedger(tmp_path / "consent", usage=usage, clock=lambda: NOW)
    scope = DatasetScope("history", "1", ("paper:fixture",), ("paper",), ("run-a",),
                         ("journal",), ("symbol", "pnl"), ("train",), "redacted-v1", NOW, NOW + timedelta(days=1))
    recipient = Recipient(CONNECTION, "1", "principal-fixture", "credential-generation-1", "api-key",
                          "https://example.invalid/v1/chat/completions", "test-region", "terms-1", "model", "1",
                          "chat", ())
    return gate, usage, scope, recipient


def rights():
    return intersect_rights(RightsGrant("fixture", RightsBasis.LICENCE,
        UsageRights(output_use=PermissionState.ALLOWED, retention=PermissionState.ALLOWED,
                    training_distillation=PermissionState.ALLOWED),
        (LicenceFact("fixture", "document", "fixture", "https://example.invalid", "1", "a" * 64,
                     NOW.isoformat(), RightsBasis.LICENCE),)))


def grant(gate, scope, recipient, **changes):
    values = dict(scope=scope, recipient=recipient, purpose="reflection", operations=("chat",),
                  approver="operator-fixture", valid_from=NOW, valid_until=NOW + timedelta(hours=1),
                  limits={key: 10000 for key in USAGE_DIMENSIONS}, max_rows=2, max_trials=2,
                  retention="fixture:delete-after-1-day", derivatives="same-scope-no-publication",
                  confirmation="fixture-confirmation", objective="checked lessons")
    values.update(changes)
    return gate.grant(**values)


def batch(gate, scope, identity="row-1", *, account="paper:fixture", payload=b"fixture"):
    from flinttrade_core.learning_consent import DatasetRecord
    record = DatasetRecord(identity, account, "paper", "run-a", "journal", NOW, "train",
                           {"symbol": "FIXTURE", "pnl": 1}, rights())
    return gate.batch(scope, (record,), payload, transform="redacted-v1")


def dispatch(gate, grant_id, batch_id, recipient, attempt="attempt-1", send=lambda: "accepted", **changes):
    values = dict(grant_id=grant_id, batch_id=batch_id, recipient=recipient, current_recipient=lambda: recipient,
                  purpose="reflection", operation="chat", payload=b"fixture", attempt_id=attempt,
                  request_id=attempt, run_id="run-a", trial_id=attempt,
                  reservation=UsageAmounts(requests=1, bytes=7, input_tokens=20, output_tokens=20, concurrency=1),
                  tariff=TariffSnapshot(CONNECTION.provider_id, "model", "1", "operator", "fixture", "USD",
                                       NOW, NOW + timedelta(days=1), {}),
                  controls={key: "hard-local" for key in USAGE_DIMENSIONS},
                  controls_evidence="fixture:qualified-caps", send=send, rights_check=lambda manifest: True)
    values.update(changes)
    return gate.dispatch(**values)


@pytest.mark.integration
def test_matching_future_records_consume_original_limits_and_revocation_blocks_send(tmp_path):
    from flinttrade_core.learning_consent import LearningRefused
    gate, usage, scope, recipient = setup_gate(tmp_path)
    sent = []
    grant_id = grant(gate, scope, recipient)
    first = batch(gate, scope)
    dispatch(gate, grant_id, first, recipient, send=lambda: sent.append("one"))
    second = batch(gate, scope, "row-2")
    dispatch(gate, grant_id, second, recipient, "attempt-2", send=lambda: sent.append("two"))
    with pytest.raises(LearningRefused, match="limit"):
        dispatch(gate, grant_id, second, recipient, "attempt-3", send=lambda: sent.append("bad"))
    assert sent == ["one", "two"]
    gate.revoke(grant_id, actor="operator-fixture")
    with pytest.raises(LearningRefused, match="revoked"):
        dispatch(gate, grant_id, first, recipient, "attempt-4", send=lambda: sent.append("bad"))
    state = gate.status(grant_id)
    assert state["egress_blocked"] is True
    assert state["remote_cancellation"] == "not-requested"
    assert state["deletion"] == "not-requested"
    assert state["weight_unlearning"] == "unavailable"
    assert gate.receipt("attempt-1")["batch_id"] == first
    assert usage.get_attempt("attempt-1").state == "UNKNOWN"


@pytest.mark.integration
def test_expanded_scope_missing_limits_and_payload_substitution_never_send(tmp_path):
    from flinttrade_core.learning_consent import LearningRefused
    gate, usage, scope, recipient = setup_gate(tmp_path)
    with pytest.raises(ValueError, match="limits"):
        grant(gate, scope, recipient, limits={"requests": 10})
    with pytest.raises(LearningRefused, match="scope"):
        batch(gate, scope, account="paper:other")
    grant_id, batch_id = grant(gate, scope, recipient), batch(gate, scope)
    for changes in ({"payload": b"substitution"}, {"purpose": "teacher"},
                    {"controls": {key: "observational" for key in USAGE_DIMENSIONS}}):
        with pytest.raises(LearningRefused):
            dispatch(gate, grant_id, batch_id, recipient, send=lambda: pytest.fail("forbidden send"), **changes)
    assert usage.list_attempts() == ()


@pytest.mark.integration
def test_real_reflector_and_llm_http_send_recheck_consent_no_retry_or_fallback(tmp_path):
    import asyncio
    import hashlib
    import httpx
    from flinttrade_ai.learning_dispatch import LearningBinding
    from flinttrade_ai.llm_client import LLMClient, LLMConfig
    from flinttrade_ai.trade_reflection import ReflectionConfig, TradeReflector
    from flinttrade_core.learning_consent import DatasetRecord

    gate, usage, scope, recipient = setup_gate(tmp_path)
    grant_id = grant(gate, scope, recipient)
    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "", "reasoning_content": "fixture"},
                                                      "finish_reason": "length"}]})
    binding = LearningBinding(gate, grant_id, scope, recipient, lambda: recipient, lambda manifest: True,
        lambda wire: UsageAmounts(requests=1, concurrency=1, bytes=len(wire), input_tokens=2000, output_tokens=100),
        TariffSnapshot(CONNECTION.provider_id, "model", "1", "operator", "fixture", "USD",
                       NOW, NOW + timedelta(days=1), {}),
        {key: "hard-local" for key in USAGE_DIMENSIONS}, "fixture:qualified", "run-a", "trial-a")
    with LLMClient(LLMConfig(provider="custom", host="https://example.invalid", model="model", max_tokens=100),
                   fallback_config=LLMConfig(provider="custom", host="https://fallback.invalid", model="model"),
                   learning_binding=binding, http_transport=httpx.MockTransport(transport)) as llm:
        trades = [{"symbol": "FIXTURE", "pnl": 1}]
        records = (DatasetRecord("row", "paper:fixture", "paper", "run-a", "journal", NOW, "train", trades[0], rights()),)
        reflector = TradeReflector(ReflectionConfig(min_trades_for_reflection=1), llm, learning_records=records)
        assert asyncio.run(reflector.reflect_batch(trades)) is not None
        assert len(sent) == 1  # no reasoning-budget retry, no fallback
        attempt = usage.list_attempts()[0]
        receipt = gate.receipt(attempt.attempt_id)
        assert receipt["payload_hash"] == hashlib.sha256(sent[0].content).hexdigest()
        gate.revoke(grant_id, actor="operator-fixture")
        assert asyncio.run(reflector.reflect_batch(trades)) is not None  # local path remains usable
        assert len(sent) == 1


@pytest.mark.integration
def test_restart_stale_recipient_and_unknown_retry_cannot_reset_limits(tmp_path):
    from dataclasses import replace
    from flinttrade_core.learning_consent import LearningConsentLedger, LearningRefused
    gate, usage, scope, recipient = setup_gate(tmp_path)
    grant_id, batch_id = grant(gate, scope, recipient), batch(gate, scope)
    with pytest.raises(LearningRefused):
        dispatch(gate, grant_id, batch_id, recipient, current_recipient=lambda: replace(recipient, connection_revision="2"))
    with pytest.raises(TimeoutError):
        dispatch(gate, grant_id, batch_id, recipient, send=lambda: (_ for _ in ()).throw(TimeoutError()))
    gate.close()
    reopened = LearningConsentLedger(tmp_path / "consent", usage=usage, clock=lambda: NOW)
    assert reopened.receipt("attempt-1")["outcome"] == "invoked-or-unknown"
    with pytest.raises(LearningRefused, match="already"):
        dispatch(reopened, grant_id, batch_id, recipient)
    assert usage.get_attempt("attempt-1").state == "UNKNOWN"


@pytest.mark.integration
def test_concurrent_sends_and_grant_replacement_preserve_cumulative_accounting(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from flinttrade_core.learning_consent import LearningRefused
    gate, usage, scope, recipient = setup_gate(tmp_path)
    original = grant(gate, scope, recipient, max_rows=1)
    frozen = batch(gate, scope)
    sent = []
    def invoke(attempt):
        try:
            dispatch(gate, original, frozen, recipient, attempt, send=lambda: sent.append(attempt))
        except LearningRefused:
            return "blocked"
        return "sent"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, ("one", "two")))
    assert sorted(outcomes) == ["blocked", "sent"]
    assert len(sent) == 1
    replacement = grant(gate, scope, recipient, max_rows=1, supersedes=original)
    assert gate.status(original)["egress_blocked"] is True
    assert gate.status(replacement)["grant"]["revision"] == 2
    with pytest.raises(LearningRefused, match="limit"):
        dispatch(gate, replacement, frozen, recipient, "three", send=lambda: pytest.fail("reset counters"))
    gate.lifecycle(original, operation="remote_cancellation", state="requested", evidence_ref="fixture:cancel")
    gate.lifecycle(original, operation="deletion", state="partial", evidence_ref="fixture:delete")
    status = gate.status(original)
    assert status["remote_cancellation"] == "requested"
    assert status["deletion"] == "partial"
    assert status["weight_unlearning"] == "unavailable"
