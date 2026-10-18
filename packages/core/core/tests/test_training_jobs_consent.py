"""Real consent/usage composition; synthetic ledger grants and inert transport."""
from datetime import UTC, datetime, timedelta
from uuid import UUID
import pytest

pytestmark = pytest.mark.integration


def test_training_actual_send_reuses_consent_and_usage_and_revocation_blocks(tmp_path):
    from flinttrade_core.training_jobs import LearningTrainingGateway
    from flinttrade_core.learning_consent import DatasetScope, DatasetRecord, Recipient, LearningConsentLedger, LearningRefused
    from flinttrade_core.service_connections import ServiceConnectionRef
    from flinttrade_core.service_providers import PermissionState, UsageRights, RightsGrant, RightsBasis, LicenceFact, intersect_rights
    from flinttrade_core.service_usage import ServiceUsageLedger
    from flinttrade_core.service_usage_contracts import BudgetPolicy, TariffSnapshot, UsageAmounts, USAGE_DIMENSIONS
    from flinttrade_core.evaluation import canonical
    now = datetime(2026, 1, 1, tzinfo=UTC)
    connection = ServiceConnectionRef("llm:custom", UUID("4c0687bf-c7b2-455b-9a43-3220121d40ab"))
    usage = ServiceUsageLedger(tmp_path / "usage", clock=lambda: now)
    usage.configure_budget(BudgetPolicy(connection, "USD", now, now + timedelta(days=1),
        {key: 100000 for key in USAGE_DIMENSIONS}), expected_revision=0)
    consent = LearningConsentLedger(tmp_path / "consent", usage=usage, clock=lambda: now)
    scope = DatasetScope("data", "1", ("paper:fixture",), ("paper",), ("run",), ("fixture",),
                         ("input",), ("development",), "redacted", now, now + timedelta(days=1))
    recipient = Recipient(connection, "revision-1", "owner", "cred-1", "api-key",
        "https://example.invalid/api/train/start", "region", "terms-1", "model", "model-v1", "training.start", ())
    rights = intersect_rights(RightsGrant("fixture", RightsBasis.LICENCE,
        UsageRights(training_distillation=PermissionState.ALLOWED, output_use=PermissionState.ALLOWED,
                    retention=PermissionState.ALLOWED),
        (LicenceFact("fixture", "document", "fixture", "https://example.invalid", "1", "a" * 64,
                     now.isoformat(), RightsBasis.LICENCE),)))
    grant = consent.grant(scope=scope, recipient=recipient, purpose="fine-tuning", operations=("training.start",),
        approver="fixture-operator", valid_from=now, valid_until=now + timedelta(hours=1),
        limits={key: 10000 for key in USAGE_DIMENSIONS}, max_rows=10, max_trials=10,
        retention="delete-after-1-day", derivatives="same-scope", confirmation="synthetic-consent", objective="fixture")
    payload = {"model_name": "model", "start_request_id": "attempt-1"}
    wire = canonical(payload).encode()
    record = DatasetRecord("row", "paper:fixture", "paper", "run", "fixture", now, "development", {"input": 1}, rights)
    batch = consent.batch(scope, (record,), wire, transform="redacted")
    def context(operation, method, path, exact_bytes):
        return dict(grant_id=grant, batch_id=batch, recipient=recipient, current_recipient=lambda: recipient,
            attempt_id="attempt-1", request_id="request", run_id="run", trial_id="trial",
            reservation=UsageAmounts(requests=1, bytes=len(wire), input_tokens=10, output_tokens=10, concurrency=1),
            tariff=TariffSnapshot(connection.provider_id, "model", "model-v1", "operator", "fixture", "USD",
                                  now, now + timedelta(days=1), {}),
            controls={key: "hard-local" for key in USAGE_DIMENSIONS}, controls_evidence="fixture:caps",
            rights_check=lambda manifest: True)
    calls = []
    gateway = LearningTrainingGateway(consent=consent, context=context,
        transport=lambda method, path, body: calls.append((method, path, body)) or {"status": "pending", "job_id": "remote"})
    try:
        gateway("training.start", "POST", "/api/train/start", payload)
        assert len(calls) == 1
        assert consent.receipt("attempt-1")["batch_id"] == batch
        assert usage.get_attempt("attempt-1").state == "UNKNOWN"
        consent.revoke(grant, actor="fixture-operator")
        with pytest.raises(LearningRefused):
            gateway("training.start", "POST", "/api/train/start", payload)
        assert len(calls) == 1
        with pytest.raises(ValueError, match="management"):
            gateway("training.cancel", "POST", "/api/train/stop", {"expected_job_id": "remote", "save": False})
    finally:
        consent.close()
        usage.close()
