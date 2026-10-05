"""Offline bounded model accounting and single-request provider evidence."""

from __future__ import annotations

import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from flinttrade_ai.llm_client import LLMClient, LLMConfig, LLMMessage, LLMResponse
from flinttrade_ai.run_store import AgentRunStore
from flinttrade_core import practice_agent_runtime as runtime

pytestmark = pytest.mark.unit


def _model():
    return importlib.import_module("flinttrade_core.practice_agent_model")


def test_model_limits_have_explicit_bounded_defaults():
    config = runtime.validate_practice_config({"symbols": ["RELIANCE"]})
    assert config["model_call_limit"] == 500
    assert config["model_output_limit"] == 512


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_call_limit", True),
        ("model_call_limit", 0),
        ("model_call_limit", 10_001),
        ("model_call_limit", 1.0),
        ("model_call_limit", "500"),
        ("model_output_limit", True),
        ("model_output_limit", 15),
        ("model_output_limit", 4097),
        ("model_output_limit", 512.0),
        ("model_output_limit", None),
    ],
)
def test_model_limits_reject_unbounded_or_coerced_values(field, value):
    with pytest.raises(ValueError, match=field):
        runtime.validate_practice_config({"symbols": ["RELIANCE"], field: value})


@pytest.mark.parametrize("call_limit,output_limit", [(1, 16), (10_000, 4096)])
def test_model_limits_accept_both_boundaries(call_limit, output_limit):
    result = runtime.validate_practice_config(
        {
            "symbols": ["RELIANCE"],
            "model_call_limit": call_limit,
            "model_output_limit": output_limit,
        }
    )
    assert result["model_call_limit"] == call_limit
    assert result["model_output_limit"] == output_limit


def _observed(tmp_path, *, limit=3, output=64, client=None):
    store = AgentRunStore(tmp_path / "model_runs.sqlite")
    config = runtime.validate_practice_config(
        {
            "symbols": ["RELIANCE"],
            "model_call_limit": limit,
            "model_output_limit": output,
        }
    )
    row = store.create_run(run_id="model-run", mode="practice", config=config)
    run = runtime._Run(row["run_id"], "operator", config, row["created_at"])
    supervisor = SimpleNamespace(store=store)
    # Isolate accounting from admission here; runtime integration tests exercise
    # the real safety, session, ownership and calendar checks at this boundary.
    supervisor._model_brake = lambda run, operation: None
    supervisor._event = lambda run, kind, data: runtime.PracticeAgentSupervisor._event(supervisor, run, kind, data)
    run.model_budget = _model().PracticeModelBudget(
        limit,
        output,
        event_sink=lambda kind, data: supervisor._event(run, kind, data),
    )
    if client is None:
        client = SimpleNamespace(chat=lambda _messages: LLMResponse(content="HOLD"))
    return runtime._ObservedLLM(supervisor, run, client), run, store


def test_reservations_are_durable_before_each_call_and_share_reflection_limit(tmp_path):
    observed, run, store = _observed(tmp_path, limit=2)
    seen = []

    def chat(_messages):
        reservations = [row for row in store.events(run.run_id) if row["kind"] == "model_attempt_reserved"]
        seen.append(reservations[-1]["data"])
        assert len(reservations) == len(seen)
        return LLMResponse(content="HOLD")

    observed.client.chat = chat
    try:
        observed.chat([LLMMessage("user", "private prompt must never be stored")])
        run.learning_active = True
        observed.chat([LLMMessage("user", "private reflection")])
        with pytest.raises(_model().ModelBudgetExhausted):
            observed.chat([])
        assert [item["operation"] for item in seen] == ["analysis", "reflection"]
        assert [item["model_calls_used"] for item in seen] == [1, 2]
        assert run.model_budget.snapshot()["model_calls_remaining"] == 0
        assert run.model_budget.exhausted
        assert run.stop.is_set()
        assert "private prompt" not in repr(store.events(run.run_id))
        assert "private reflection" not in repr(store.events(run.run_id))
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["raises", "error", "empty"])
def test_failed_and_unknown_provider_attempts_still_consume_limit(tmp_path, failure):
    def chat(_messages):
        if failure == "raises":
            raise OSError("private-provider-detail")
        return LLMResponse(
            content="" if failure == "empty" else "HOLD", error="private-provider-detail" if failure == "error" else ""
        )

    observed, run, store = _observed(tmp_path, limit=1, client=SimpleNamespace(chat=chat))
    try:
        with pytest.raises(RuntimeError, match="configured_model_unavailable"):
            observed.chat([])
        assert run.model_budget.snapshot()["model_calls_used"] == 1
        with pytest.raises(_model().ModelBudgetExhausted):
            observed.chat([])
        assert len([e for e in store.events(run.run_id) if e["kind"] == "model_attempt_reserved"]) == 1
        assert "private-provider-detail" not in repr(store.events(run.run_id))
    finally:
        store.close()


def test_evidence_failure_prevents_provider_and_does_not_increment(tmp_path, monkeypatch):
    called = []
    observed, run, store = _observed(tmp_path, client=SimpleNamespace(chat=lambda _messages: called.append(True)))

    def fail(*_args, **_kwargs):
        raise OSError("private-storage-detail")

    monkeypatch.setattr(store, "append_event", fail)
    try:
        with pytest.raises(RuntimeError, match="practice_model_evidence_unavailable"):
            observed.chat([])
        assert called == []
        assert run.model_budget.snapshot()["model_calls_used"] == 0
        assert run.model_budget.snapshot()["status"] == "evidence_unavailable"
        assert run.stop.is_set() and run.evidence_failed
    finally:
        store.close()


def test_concurrent_analysis_and_reflection_cannot_overrun_shared_budget(tmp_path):
    observed, run, store = _observed(tmp_path, limit=5)
    entered = []
    entered_lock = threading.Lock()

    def chat(_messages):
        with entered_lock:
            entered.append(1)
        return LLMResponse(content="HOLD")

    def call(_index):
        try:
            observed.chat([])
        except _model().ModelBudgetExhausted:
            return False
        return True

    observed.client.chat = chat
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(call, range(40)))
        assert sum(results) == len(entered) == 5
        reservations = [e["data"] for e in store.events(run.run_id) if e["kind"] == "model_attempt_reserved"]
        assert [e["model_calls_used"] for e in reservations] == [1, 2, 3, 4, 5]
    finally:
        store.close()


@pytest.mark.parametrize("response_kind", ["reasoning_empty", "http_failure", "success"])
def test_frozen_production_client_issues_one_request_without_fallback_or_reasoning_retry(
    tmp_path, monkeypatch, response_kind
):
    initial = LLMConfig(provider="openai", model="original-model", api_key="synthetic-key", reasoning_max_tokens=8192)
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: initial))
    source = LLMClient(fallback_config=LLMConfig(provider="anthropic", model="fallback-model"))
    frozen = _model().freeze_practice_client(source, output_limit=64)
    requests = []

    def transport(request):
        requests.append(request)
        if response_kind == "http_failure":
            return httpx.Response(503, json={"error": {"message": "private-provider-response"}})
        message = (
            {"content": "HOLD"}
            if response_kind == "success"
            else {"content": "", "reasoning_content": "private reasoning"}
        )
        return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "length"}]})

    # Exercise the real HTTP transport and LLMClient retry branches, not chat mocks.
    frozen._http._default = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(
        LLMConfig, "from_env", classmethod(lambda cls: LLMConfig(provider="anthropic", model="changed-model"))
    )
    initial.model = "also-mutated"
    observed, run, store = _observed(tmp_path, client=frozen)
    try:
        if response_kind == "success":
            observed.chat([LLMMessage("user", "private model prompt")], max_tokens=4096)
        else:
            with pytest.raises(RuntimeError, match="configured_model_unavailable"):
                observed.chat([LLMMessage("user", "private model prompt")], max_tokens=4096)
        assert len(requests) == 1
        payload = json.loads(requests[0].content)
        assert payload["model"] == "original-model"
        assert payload["max_tokens"] == 64
        assert frozen.config.reasoning_max_tokens == 0
        assert frozen.fallback_config is None
        assert source.fallback_config is not None
        assert initial.reasoning_max_tokens == 8192
        evidence = repr(store.events(run.run_id))
        assert "private" not in evidence and "synthetic-key" not in evidence
    finally:
        store.close()
        frozen.close()
        source.close()


def test_injected_client_seam_is_not_replaced_by_production_client():
    fake = SimpleNamespace(chat=lambda _messages: LLMResponse(content="HOLD"))
    assert _model().freeze_practice_client(fake, output_limit=64) is fake


@pytest.mark.parametrize("provider", ["anthropic", "ollama"])
def test_each_provider_transport_obeys_the_reserved_output_cap(tmp_path, monkeypatch, provider):
    from contextlib import contextmanager

    from flinttrade_core import ollama_runtime

    @contextmanager
    def session(_model_name):
        yield SimpleNamespace(base_url="http://127.0.0.1:11434", model="managed-model")

    monkeypatch.setattr(ollama_runtime, "managed_ollama_session", session)
    source = LLMClient(config=LLMConfig(provider=provider, model="original-model", api_key="synthetic-key"))
    frozen = _model().freeze_practice_client(source, output_limit=64)
    calls = []

    def transport(request):
        reservations = [e for e in store.events(run.run_id) if e["kind"] == "model_attempt_reserved"]
        assert len(reservations) == len(calls) + 1
        calls.append(json.loads(request.content))
        if provider == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "HOLD"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "HOLD"}}]})

    if provider == "ollama":
        frozen._http._managed_ollama.close()
        frozen._http._managed_ollama = httpx.Client(transport=httpx.MockTransport(transport))
    else:
        frozen._http._default = httpx.Client(transport=httpx.MockTransport(transport))
    observed, run, store = _observed(tmp_path, client=frozen)
    try:
        assert observed.chat([LLMMessage("user", "private prompt")], None, 4096).content == "HOLD"
        assert len(calls) == 1
        assert calls[0]["max_tokens"] == 64
        assert calls[0]["model"] == ("managed-model" if provider == "ollama" else "original-model")
    finally:
        store.close()
        frozen.close()
        source.close()


@pytest.mark.parametrize("positional", [False, True])
def test_frozen_model_override_is_refused_without_transport_io_or_source_mutation(tmp_path, positional):
    original = LLMConfig(provider="openai", model="frozen-model")
    source = LLMClient(config=original)
    frozen = _model().freeze_practice_client(source, output_limit=64)
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "HOLD"}}]})

    frozen._http._default = httpx.Client(transport=httpx.MockTransport(transport))
    observed, run, store = _observed(tmp_path, client=frozen)
    try:
        with pytest.raises(RuntimeError):
            if positional:
                observed.chat([], None, 64, "different-model")
            else:
                observed.chat([], model="different-model")
        assert requests == []
        assert original.model == frozen.config.model == "frozen-model"
        assert original.reasoning_max_tokens == 8192
    finally:
        store.close()
        frozen.close()
        source.close()


@pytest.mark.parametrize(
    "content", ['{"win_rate":"PRIVATE_REFLECTION_VALUE"}', "PRIVATE_REFLECTION_VALUE invalid json"]
)
async def test_malformed_reflection_content_is_not_written_to_logs(tmp_path, caplog, content):
    from flinttrade_ai.trade_reflection import ReflectionConfig, TradeReflector

    observed, run, store = _observed(
        tmp_path, client=SimpleNamespace(chat=lambda _messages: LLMResponse(content=content))
    )
    run.learning_active = True
    try:
        reflector = TradeReflector(config=ReflectionConfig(min_trades_for_reflection=1), llm_client=observed)
        result = await reflector.reflect_batch([{"symbol": "RELIANCE", "pnl": 1, "pnl_pct": 1}])
        assert result is not None
        assert "PRIVATE_REFLECTION_VALUE" not in caplog.text
        assert run.model_budget.snapshot()["model_calls_used"] == 1
    finally:
        store.close()
