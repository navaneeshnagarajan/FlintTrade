"""Optional training lifecycle: inert HTTP shapes, never real training."""
import pytest

pytestmark = pytest.mark.unit
PIN = "3e7898659344873423a9a09438c80d51bc056655"


def setup(tmp_path, replies, **kwargs):
    from flinttrade_core.training_jobs import TrainingJobs, UnslothTrainingBackend
    calls = []
    def gateway(operation, method, path, payload):
        calls.append((operation, method, path, payload))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    backend = UnslothTrainingBackend(version=PIN, principal_role=kwargs.get("role", "owner"),
        capacity_isolated=kwargs.get("isolated", True), gateway=gateway)
    return TrainingJobs(tmp_path / "jobs.db", backend), calls


def request():
    return {"model_name": "synthetic-model", "local_datasets": ["uploaded-fixture.jsonl"],
            "training_type": "lora", "format_type": "chatml", "is_decision": True}


def test_unknown_start_persists_and_never_blindly_replays(tmp_path):
    jobs, calls = setup(tmp_path, [TimeoutError()])
    record = jobs.start("request-1", request(), lineage={"dataset": "batch-v1"})
    assert record["state"] == "unknown"
    assert jobs.start("request-1", request(), lineage={"dataset": "batch-v1"}) == record
    assert len(calls) == 1
    from flinttrade_core.training_jobs import TrainingJobs
    recovered = TrainingJobs(tmp_path / "jobs.db", jobs.backend)
    assert recovered.get("request-1")["state"] == "unknown"
    with pytest.raises(ValueError, match="identity"):
        recovered.start("request-1", {**request(), "model_name": "changed"}, lineage={"dataset": "batch-v1"})
    assert len(calls) == 1


def test_cancel_ack_is_not_stop_and_status_requires_exact_job(tmp_path):
    jobs, calls = setup(tmp_path, [{"status": "success", "job_id": "remote-1"},
        {"message": "Stop requested; next safe step"}, {"job_id": "other", "status": "completed"},
        {"job_id": "remote-1", "status": "stopped"}])
    jobs.start("request-1", request(), lineage={"dataset": "batch-v1"})
    assert jobs.cancel("request-1")["cancellation"] == "requested"
    assert calls[-1][2:] == ("/api/train/stop", {"expected_job_id": "remote-1", "save": False})
    assert jobs.reconcile("request-1")["state"] == "unknown"
    record = jobs.reconcile("request-1")
    assert record["state"] == "cancelled"
    assert record["cancellation"] == "confirmed"
    assert record["weight_unlearning"] == "unavailable"


@pytest.mark.parametrize("option", ["non-owner", "shared-capacity", "decision-resume", "streaming", "publish"])
def test_unsupported_or_ungranted_operations_make_zero_calls(tmp_path, option):
    jobs, calls = setup(tmp_path, [], role="member" if option == "non-owner" else "owner",
                       isolated=option != "shared-capacity")
    body = request()
    if option == "decision-resume":
        body["resume_from_checkpoint"] = "checkpoint"
    if option == "streaming":
        body["streaming"] = True
    if option == "publish":
        body["push_to_hub"] = True
    with pytest.raises(ValueError):
        jobs.start("request", body, lineage={"dataset": "batch-v1"})
    assert calls == []


def test_http_success_with_error_body_is_failed_not_accepted(tmp_path):
    jobs, _ = setup(tmp_path, [{"status": "error", "message": "not accepted"}])
    assert jobs.start("request", request(), lineage={"dataset": "batch-v1"})["state"] == "failed"
