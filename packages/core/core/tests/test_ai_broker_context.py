"""Native AI input collection exercises real grants, sessions and durable receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from flask import Flask

from flinttrade_core.broker_identity import BrokerSelector, CredentialVersion
from flinttrade_core.broker_read_port import BalanceEvidence, BalanceSnapshot
from flinttrade_core.config import Settings
from flinttrade_core.openalgo_client import OpenAlgoClient
from flinttrade_core.workspace_migrations import broker_workspace_version, compare_and_swap_workspace
from flinttrade_data.audit_logger import AuditLogger
from flinttrade_gateway.broker_read_service import create_broker_read_owner
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.registry import ManagedSessionAuthority, create_owned_registry
from flinttrade_gateway.routing_config import RoutingConfig
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider

_SIGNING_KEY = "synthetic-ai-context-signing-key-at-least-32-bytes"
_SELECTORS = ("dhan:Quotes", "upstox:History", "dhan:Execution")


class _Adapter:
    """Replace external SDK I/O only; the gateway owner still projects all DTOs."""

    def __init__(self):
        self.calls = []
        self.after_read = lambda: None
        self.quote_result = 100.0
        self.balance_available = 500.0
        self.delay = 0.0
        self.history_style = "ascending"

    async def _read(self, session, operation):
        self.calls.append((operation, session.selector, asyncio.get_running_loop()))
        if self.delay:
            await asyncio.sleep(self.delay)
        self.after_read()

    async def quotes(self, session, symbols):
        await self._read(session, "quote")
        exchange, _, symbol = symbols[0].partition(":")
        return [{"symbol": symbol, "exchange": exchange, "ltp": self.quote_result, "available": True}]

    async def historical(self, session, request):
        await self._read(session, "historical")
        start = datetime.fromisoformat(request["start_date"]).replace(tzinfo=UTC)
        result = {
            "symbol": request["symbol"], "exchange": request["exchange"], "interval": request["interval"],
            "bars": [
                {"timestamp": (start + timedelta(minutes=5 * i)).isoformat(),
                 "open": 99.0, "high": 102.0, "low": 98.0, "close": 100.0, "volume": i}
                for i in range(140)
            ],
        }
        if self.history_style == "descending":
            result["bars"].reverse()
        elif self.history_style == "epoch":
            for bar in result["bars"]:
                bar["timestamp"] = str(int(datetime.fromisoformat(bar["timestamp"]).timestamp()))
        elif self.history_style == "future":
            result["bars"][-1]["timestamp"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        return result

    async def balance_snapshot(self, session):
        await self._read(session, "balance")
        evidence = BalanceEvidence.DIRECT if self.balance_available is not None else None
        return BalanceSnapshot(self.balance_available, evidence, None, None, None, None, None, None)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from flinttrade_core import auth_routes
    from flinttrade_core.app import _BrokerRuntimeDependencies

    app = Flask(__name__)
    revoked = set()
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: _SIGNING_KEY)
    monkeypatch.setattr(auth_routes, "_is_jti_revoked", lambda jti: jti in revoked)
    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: None)
    workspace_path = tmp_path / "workspace"

    def initialise(config):
        config["brokers"]["registered"] = list(_SELECTORS)
        config["brokers"]["execution"] = {"default": "dhan:Execution"}
        config["brokers"]["data"].update(
            quote="dhan:Quotes", historical="upstox:History", option_chains="dhan:Quotes", ticks="dhan:Quotes"
        )
        config["brokers"]["account_acls"] = {
            "dhan": {"Quotes": ["operator"], "Execution": ["operator"]},
            "upstox": {"History": ["operator"]},
        }

    workspace = compare_and_swap_workspace(workspace_path, None, initialise)
    config = RoutingConfig.from_workspace(workspace.as_dict()["brokers"])
    registry, publication_owner = create_owned_registry()
    credentials = {}
    for raw in _SELECTORS:
        selector = BrokerSelector(*raw.split(":"))
        credentials[selector] = CredentialVersion(selector, uuid4(), 1)
        authority = ManagedSessionAuthority(credentials[selector], workspace.version, broker_workspace_version(workspace))
        receipt = publication_owner.prepare_session_candidate(
            selector,
            Session("synthetic-test-session", time.time() + 3600, selector.account_id, selector.adapter_id),
            expected_registry=registry.snapshot_selector(selector), authority=authority,
            broker=selector.adapter_id, label=selector.account_id, client=object(),
        )
        publication_owner.publish_prepared_candidate(receipt, current_authority=authority)
    provider = AuthenticatingSessionProvider(
        registry, config.account_acls, workspace_snapshot=workspace, workspace_path=workspace_path,
        credential_version_for=credentials.__getitem__,
    )
    adapter = _Adapter()
    adapters = {"dhan": adapter, "upstox": adapter}
    client = OpenAlgoClient(Settings(openalgo_api_key=""))
    audit_path = tmp_path / "audit"
    audit = AuditLogger(str(audit_path))
    owner = create_broker_read_owner(
        registry=registry, session_provider=provider, adapters=adapters, workspace_path=workspace_path,
        rate_limiter=None, runtime_accepting_requests=lambda: app.config.get("RUNTIME_ACCEPTING_REQUESTS", True),
    )
    dependencies = _BrokerRuntimeDependencies(
        registry, config, workspace.as_dict()["brokers"], provider, adapters, None, None, workspace,
        workspace_path, client, adapters, publication_owner, owner,
    )
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    app.extensions["flinttrade.registry_publication_owner"] = publication_owner
    app.config.update(CLIENT=client, OPENALGO_CLIENT=client, REGISTRY=registry,
                      ACTIVE_BROKER_ADAPTERS=adapters, AUDIT=audit, RUNTIME_ACCEPTING_REQUESTS=True)

    def token(**overrides):
        claims = {"sub": "operator", "jti": "test-session", "type": "session", "mode": "practice",
                  "iat": int(time.time()), "exp": int(time.time()) + 3600, "scopes": ["admin.accounts.read"]}
        claims.update(overrides)
        return jwt.encode(claims, _SIGNING_KEY, algorithm="HS256")

    yield SimpleNamespace(app=app, adapter=adapter, dependencies=dependencies, owner=owner, client=client,
                          audit=audit, audit_path=audit_path, token=token, revoked=revoked, credentials=credentials,
                          workspace_path=workspace_path)
    owner.close(timeout=2.0)
    asyncio.run(client.shutdown())
    audit.close()


def _collect(runtime, token=None, symbol="RELIANCE", exchange="NSE"):
    from flinttrade_core.ai_broker_context import collect_configured_broker_context

    headers = {"Authorization": "Bearer " + (runtime.token() if token is None else token)}
    with runtime.app.test_request_context(headers=headers):
        return collect_configured_broker_context(symbol, exchange)


def test_context_uses_separate_data_and_execution_accounts_and_survives_audit_reopen(runtime):
    result = _collect(runtime)
    context = result.market_data
    assert [(operation, selector) for operation, selector, _ in runtime.adapter.calls] == [
        ("quote", BrokerSelector("dhan", "Quotes")),
        ("historical", BrokerSelector("upstox", "History")),
        ("balance", BrokerSelector("dhan", "Execution")),
    ]
    assert context["quote"]["value"]["ltp"] == 100.0
    assert context["quote"]["source_as_of"] is None
    assert context["quote"]["observed_at"]
    assert context["depth"]["error_code"] == "unsupported"
    assert context["depth"]["value"] is None
    assert context["depth"]["provenance"] is None
    assert context["depth"]["source_as_of"] is None
    assert context["depth"]["observed_at"]
    assert context["balance"]["value"]["available_balance"] == 500.0
    assert context["balance"]["value"]["used_margin"] is None
    assert context["balance"]["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Execution"}
    assert len(context["historical"]["value"]["bars"]) == 128
    assert context["historical"]["omitted_bars"] == 12
    assert context["historical"]["value"]["bars"][0]["volume"] == 12
    canonical = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert result.receipt["input_digest"] == hashlib.sha256(canonical.encode()).hexdigest()
    runtime.audit.close()
    with AuditLogger(str(runtime.audit_path)) as reopened:
        assert reopened.verify_chain()["ok"]
        events = [event for filename in reopened.list_audit_files()
                  for event in reopened.read_day(filename.removeprefix("audit_").removesuffix(".jsonl"))]
    assert len(events) == 1
    assert events[0]["event_id"] == result.receipt["event_id"]
    assert events[0]["market_data"] == context
    assert events[0]["input_digest"] == result.receipt["input_digest"]
    assert "test-session" not in json.dumps(events)


def test_repeated_context_reads_use_the_same_owned_loop_without_openalgo_requests(runtime, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("No OpenAlgo endpoint may be called by native context collection")

    monkeypatch.setattr(runtime.client, "_post", forbidden)
    _collect(runtime)
    _collect(runtime)
    assert len({id(loop) for _, _, loop in runtime.adapter.calls}) == 1


def test_supported_depth_is_bounded_and_has_real_read_provenance(runtime, monkeypatch):
    async def depth(session, request):
        await runtime.adapter._read(session, "depth")
        return {
            "symbol": request.instrument.symbol, "exchange": request.instrument.exchange,
            "bids": [{"price": 99.0 - i, "quantity": i + 1} for i in range(7)],
            "asks": [{"price": 101.0 + i, "quantity": i + 1} for i in range(8)],
        }

    monkeypatch.setattr(runtime.adapter, "depth", depth, raising=False)
    record = _collect(runtime).market_data["depth"]
    assert "error_code" not in record
    assert len(record["value"]["bids"]) == len(record["value"]["asks"]) == 5
    assert (record["omitted_bids"], record["omitted_asks"]) == (2, 3)
    assert record["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Quotes"}


@pytest.mark.parametrize("failure", ["provider", "malformed", "revocation", "generation"])
def test_depth_errors_other_than_unsupported_still_block(runtime, monkeypatch, failure):
    from flinttrade_core.ai_broker_context import BrokerContextError

    async def depth(session, request):
        await runtime.adapter._read(session, "depth")
        if failure == "provider":
            raise OSError("synthetic private provider detail")
        if failure == "revocation":
            runtime.revoked.add("test-session")
        if failure == "generation":
            runtime.app.extensions.pop("flinttrade_broker_dependencies")
        return {"symbol": "WRONG" if failure == "malformed" else request.instrument.symbol,
                "exchange": request.instrument.exchange, "bids": [], "asks": []}

    monkeypatch.setattr(runtime.adapter, "depth", depth, raising=False)
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.list_audit_files() == []
    assert [operation for operation, _, _ in runtime.adapter.calls] == ["quote", "depth"]


@pytest.mark.parametrize("method", ["quotes", "historical", "balance_snapshot"])
def test_unsupported_required_read_still_blocks(runtime, monkeypatch, method):
    from flinttrade_core.ai_broker_context import BrokerContextError

    monkeypatch.setattr(runtime.adapter, method, None)
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.list_audit_files() == []


@pytest.mark.parametrize("claims", [
    {"type": "reset"}, {"jti": ""}, {"sub": ""}, {"mode": "unknown"}, {"exp": 1}, {"scopes": []},
    {"sub": "\ud800"},
])
def test_invalid_or_narrowed_sessions_never_read_broker_data(runtime, claims):
    from flinttrade_core.ai_broker_context import BrokerContextError

    with pytest.raises(BrokerContextError):
        _collect(runtime, token=runtime.token(**claims))
    assert runtime.adapter.calls == []
    assert runtime.audit.list_audit_files() == []


def test_quote_account_acl_cannot_be_borrowed_for_another_operator(runtime):
    from flinttrade_core.ai_broker_context import BrokerContextError

    with pytest.raises(BrokerContextError):
        _collect(runtime, token=runtime.token(sub="another-operator"))
    assert runtime.adapter.calls == []


def test_revocation_during_provider_read_prevents_receipted_context(runtime):
    from flinttrade_core.ai_broker_context import BrokerContextError

    runtime.adapter.after_read = lambda: runtime.revoked.add("test-session")
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.list_audit_files() == []


@pytest.mark.parametrize("failure", ["malformed_quote", "missing_balance", "generation_change", "missing_loop", "shutdown"])
def test_unavailable_or_changed_inputs_never_receive_an_input_receipt(runtime, failure):
    from flinttrade_core.ai_broker_context import BrokerContextError

    if failure == "malformed_quote":
        runtime.adapter.quote_result = float("nan")
    elif failure == "missing_balance":
        runtime.adapter.balance_available = None
    elif failure == "generation_change":
        runtime.adapter.after_read = lambda: runtime.app.extensions.pop("flinttrade_broker_dependencies", None)
    elif failure == "missing_loop":
        runtime.dependencies.openalgo_client = None
    else:
        runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.list_audit_files() == []


def test_receipt_write_failure_returns_only_a_fixed_error(runtime, monkeypatch):
    from flinttrade_core.ai_broker_context import BrokerContextError

    def fail(*args, **kwargs):
        raise OSError("private-provider-response-and-local-path")

    monkeypatch.setattr(runtime.audit, "log_idempotent_event", fail)
    with pytest.raises(BrokerContextError) as caught:
        _collect(runtime)
    assert str(caught.value) == "broker_context_audit_unavailable"


@pytest.mark.parametrize("audit_failure", [False, True])
def test_collected_grants_are_revoked_on_success_and_failure(runtime, monkeypatch, audit_failure):
    from flinttrade_core.ai_broker_context import BrokerContextError
    from flinttrade_core.broker_read_port import BrokerReadErrorCode, BrokerReadFailure, InstrumentRef, QuoteRequest
    from flinttrade_gateway.broker_read_service import BrokerReadOwner

    ports = []
    bind = BrokerReadOwner.bind

    def observe(owner, **kwargs):
        port = bind(owner, **kwargs)
        ports.append(port)
        return port

    monkeypatch.setattr(BrokerReadOwner, "bind", observe)
    if audit_failure:
        monkeypatch.setattr(runtime.audit, "log_idempotent_event", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
        with pytest.raises(BrokerContextError):
            _collect(runtime)
    else:
        _collect(runtime)
    for port in ports:
        assert runtime.client.run_sync(port.quote(QuoteRequest(InstrumentRef("RELIANCE", "NSE")))) == (
            BrokerReadFailure(BrokerReadErrorCode.REVOKED)
        )


@pytest.mark.parametrize("expire_on_verification", [1, 4])
def test_deadline_expiring_inside_authority_check_remains_timeout(runtime, monkeypatch, expire_on_verification):
    from flinttrade_core import ai_broker_context
    from flinttrade_gateway.broker_read_service import BrokerReadOwner

    # First verification is a bind; the fourth is the first provider admission.
    # Change only the collector clock, preserving the real owner/session checks.
    clock = {"now": 100.0, "checks": 0}
    monkeypatch.setattr(ai_broker_context, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    verify = BrokerReadOwner._verified_context

    def expire(owner, *args, **kwargs):
        clock["checks"] += 1
        if clock["checks"] == expire_on_verification:
            clock["now"] = 200.0
        return verify(owner, *args, **kwargs)

    monkeypatch.setattr(BrokerReadOwner, "_verified_context", expire)
    with pytest.raises(ai_broker_context.BrokerContextError) as caught:
        _collect(runtime)
    assert caught.value.code == "broker_context_timeout"
    assert runtime.adapter.calls == []
    assert runtime.audit.list_audit_files() == []


def test_collection_deadline_refuses_slow_provider(runtime, monkeypatch):
    from flinttrade_core import ai_broker_context

    monkeypatch.setattr(ai_broker_context, "_CONTEXT_TIMEOUT_SECONDS", 0.02)
    runtime.adapter.delay = 0.2
    with pytest.raises(ai_broker_context.BrokerContextError) as caught:
        _collect(runtime)
    assert caught.value.code == "broker_context_timeout"
    assert runtime.audit.list_audit_files() == []


@pytest.mark.parametrize("style", ["descending", "epoch"])
def test_history_keeps_newest_bars_in_time_order_across_native_timestamp_formats(runtime, style):
    runtime.adapter.history_style = style
    context = _collect(runtime).market_data
    bars = context["historical"]["value"]["bars"]
    assert [bar["volume"] for bar in bars] == list(range(12, 140))
    assert context["historical"]["source_as_of"] == bars[-1]["timestamp"]


def test_future_history_does_not_enter_the_recorded_model_input(runtime):
    from flinttrade_core.ai_broker_context import BrokerContextError

    runtime.adapter.history_style = "future"
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.list_audit_files() == []


def test_revocation_after_audit_commit_prevents_returning_context(runtime, monkeypatch):
    from flinttrade_core.ai_broker_context import BrokerContextError

    write = runtime.audit.log_idempotent_event

    def revoke_after_write(*args, **kwargs):
        receipt = write(*args, **kwargs)
        runtime.revoked.add("test-session")
        return receipt

    monkeypatch.setattr(runtime.audit, "log_idempotent_event", revoke_after_write)
    with pytest.raises(BrokerContextError):
        _collect(runtime)
    assert runtime.audit.verify_chain()["checked"] == 1


@pytest.mark.parametrize("stream", [False, True])
def test_http_analysis_receives_exact_durable_input_before_model_work(runtime, monkeypatch, stream):
    from flinttrade_ai import team_routes

    observed = []

    async def analyse(symbol, exchange, market_data, **options):
        events = [event for filename in runtime.audit.list_audit_files()
                  for event in runtime.audit.read_day(filename.removeprefix("audit_").removesuffix(".jsonl"))]
        assert len(events) == 1
        assert events[0]["market_data"] == market_data
        observed.append(events[0])
        return SimpleNamespace(to_dict=lambda: {"symbol": symbol, "exchange": exchange, "agent_analyses": []})

    team = SimpleNamespace(analyse_async=analyse, get_recommendation=lambda _: SimpleNamespace(to_dict=lambda: {"action": "HOLD"}))
    monkeypatch.setattr(team_routes, "_get_team", lambda: team)
    runtime.app.register_blueprint(team_routes.team_bp)
    response = runtime.app.test_client().post(
        "/api/v1/ai/team/analyse" + ("/stream" if stream else ""),
        json={"symbol": "RELIANCE", "exchange": "NSE", "context_source": "configured_brokers", "mode": "flat"},
        headers={"Authorization": "Bearer " + runtime.token()},
    )
    assert response.status_code == 200
    if stream:
        frames = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines() if line.startswith("data: ")]
        payload = next(frame["data"] for frame in frames if frame["type"] == "result")
    else:
        payload = response.get_json()["data"]
    assert len(observed) == 1
    assert payload["input_receipt"] == {"event_id": observed[0]["event_id"], "input_digest": observed[0]["input_digest"]}
    assert payload["recommendation"]["action"] == "HOLD"


def test_concrete_dhan_context_records_unsupported_depth_and_exact_account_inputs(runtime, monkeypatch):
    """Exercise the native adapter contract while replacing external SDK I/O only."""
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    sdk_calls = []

    class DhanSDK:
        def __init__(self, account_id):
            self.account_id = account_id

        def quote_data(self, securities):
            sdk_calls.append(("quote", self.account_id, securities))
            return {
                "status": "success",
                "data": {"data": {"NSE_EQ": {"11536": {"last_price": 123.0, "volume": 17}}}},
            }

        def get_fund_limits(self):
            sdk_calls.append(("balance", self.account_id))
            return {"status": "success", "data": {"availabelBalance": 700.0}}

    clients = {account: DhanSDK(account) for account in ("Quotes", "Execution")}
    resolved = []

    def resolve_security(symbol, exchange):
        resolved.append((symbol, exchange))
        return "11536"

    native = DhanAdapter(
        client_factory=lambda session: clients[session.account_id],
        security_resolver=resolve_security,
    )
    runtime.dependencies.adapters["dhan"] = native

    async def no_openalgo(*args, **kwargs):
        pytest.fail("Concrete native context must not call an OpenAlgo endpoint")

    monkeypatch.setattr(runtime.client, "_post", no_openalgo)
    result = _collect(runtime)
    context = result.market_data

    assert sdk_calls == [("quote", "Quotes", {"NSE_EQ": [11536]}), ("balance", "Execution")]
    assert resolved == [("RELIANCE", "NSE")]
    assert [(operation, selector) for operation, selector, _ in runtime.adapter.calls] == [
        ("historical", BrokerSelector("upstox", "History")),
    ]
    assert context["quote"]["value"]["ltp"] == 123.0
    assert context["quote"]["value"]["volume"] == 17
    assert context["quote"]["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Quotes"}
    assert context["depth"]["value"] is None
    assert context["depth"]["provenance"] is None
    assert context["depth"]["error_code"] == "unsupported"
    assert context["balance"]["value"]["available_balance"] == 700.0
    assert context["balance"]["value"]["used_margin"] is None
    assert context["balance"]["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Execution"}
    assert len(context["historical"]["value"]["bars"]) == 128

    events = [event for filename in runtime.audit.list_audit_files()
              for event in runtime.audit.read_day(filename.removeprefix("audit_").removesuffix(".jsonl"))]
    assert len(events) == 1
    assert events[0]["market_data"] == context
    canonical = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    assert result.receipt == {
        "event_id": events[0]["event_id"],
        "input_digest": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    assert runtime.audit.verify_chain()["ok"]
