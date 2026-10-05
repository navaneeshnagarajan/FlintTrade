"""Practice agent uses authenticated canonical admission and real sandbox fills."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from flask import Flask, request

from flinttrade_core import ai_broker_context, auth_routes, order_routes
from flinttrade_core.ai_broker_context import BrokerAnalysisContext
from flinttrade_core.models import Action, Exchange, Order, PriceType, Product
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_engine.laya import DecisionStatus, process_laya
from flinttrade_engine.safety import SafetySystem

_KEY = "practice-agent-synthetic-test-signing-key-32-bytes"


class _LiveSentinel:
    def __init__(self):
        self.accesses = []

    def __getattr__(self, name):
        self.accesses.append(name)
        raise AssertionError("Live handle accessed")


def _module():
    name = "flinttrade_core.practice_agent_adapter"
    assert importlib.util.find_spec(name) is not None, "Practice execution adapter is missing"
    return importlib.import_module(name)


def _order(**overrides):
    body = {"symbol": "RELIANCE", "exchange": Exchange.NSE, "action": Action.BUY,
            "quantity": "1", "product": Product.MIS, "pricetype": PriceType.MARKET}
    body.update(overrides)
    return Order(**body)


def _context(symbol="RELIANCE", exchange="NSE"):
    now = datetime.now(UTC).isoformat()
    instrument = {"symbol": symbol, "exchange": exchange, "instrument_id": None}
    return BrokerAnalysisContext({
        "symbol": symbol, "exchange": exchange,
        "quote": {"value": {"instrument": instrument, "available": True, "ltp": 123.5,
                            "open": 120.0, "high": 124.0, "low": 119.0,
                            "volume": 10, "prev_close": 120.0},
                  "observed_at": now, "source_as_of": None},
        "depth": {"value": {"instrument": instrument, "bids": [{"price": 123.0, "quantity": 2}],
                             "asks": [{"price": 124.0, "quantity": 1}]}, "observed_at": now},
        "historical": {"request": {"interval": "5m"}, "value": {"instrument": instrument, "interval": "5m",
                                  "bars": [{"timestamp": now, "open": 120.0, "high": 124.0,
                                            "low": 119.0, "close": 123.5, "volume": 10}]}},
    }, {"event_id": "synthetic-input-receipt", "input_digest": "a" * 64})


@pytest.fixture
def runtime(tmp_path, monkeypatch, backend_lease_proof):
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: _KEY)
    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: None)
    revoked = set()
    monkeypatch.setattr(auth_routes, "_is_jti_revoked", lambda jti: jti in revoked)
    app = Flask(__name__)
    sandbox = SandboxEngine(str(tmp_path / "practice.sqlite3"), initial_capital=100_000.0)
    sentinels = [_LiveSentinel() for _ in range(3)]
    app.config.update(DATA_SANDBOX_ENGINE=sandbox, RATE_LIMITER=RateLimiter(),
                      BACKEND_LEASE_PROOF=backend_lease_proof, RUNTIME_ACCEPTING_REQUESTS=True,
                      CLIENT=sentinels[0], OPENALGO_CLIENT=sentinels[1], BROKER_ROUTER=sentinels[2],
                      TICK_RECORDER=None, SAFETY=SafetySystem())
    app.register_blueprint(order_routes.orders_bp)
    process_laya().set_status(DecisionStatus.READY)
    state = SimpleNamespace(app=app, sandbox=sandbox, revoked=revoked, sentinels=sentinels,
                            context=_context(), reads=[], events=[], stopped=False)

    def token(**overrides):
        claims = {"sub": "operator", "jti": "practice-session", "type": "session", "mode": "practice",
                  "iat": int(time.time()), "exp": int(time.time()) + 3600, "scopes": ["admin.accounts.read"]}
        claims.update(overrides)
        return jwt.encode(claims, _KEY, algorithm="HS256")

    state.token = token

    def collect(symbol, exchange):
        assert request.headers["Authorization"] == "Bearer " + state.captured_token
        assert request.headers["X-FlintTrade-Mode"] == "practice"
        state.reads.append((symbol, exchange))
        return deepcopy(state.context)

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", collect)

    def create(**kwargs):
        state.captured_token = kwargs.pop("session_token", token())
        return _module().PracticeAgentAdapter(app, state.captured_token, **kwargs)

    state.create = create
    yield state
    assert all(not sentinel.accesses for sentinel in sentinels)
    sandbox.close()


async def test_real_sandbox_fill_uses_observed_price_and_returns_trader_decision(runtime):
    adapter = runtime.create(event_sink=lambda kind, data: runtime.events.append((kind, data)))
    decision = await adapter.route_order(_order(price="9999"))
    assert decision.passed is True
    assert decision.order_response.orderid
    assert decision.order_response.price == 123.5
    assert decision.response["order_id"] == decision.order_response.orderid
    assert runtime.sandbox.get_trades()[0]["price"] == 123.5
    assert decision.response["price_source"] == "ltp"
    assert runtime.sandbox.get_positions()[0]["net_qty"] == 1
    assert [kind for kind, _ in runtime.events] == ["dispatch_started", "dispatch_result"]
    assert runtime.events[0][1]["order"]["price"] == 123.5
    assert runtime.events[0][1]["order"]["price_basis"] == "ltp"
    assert runtime.events[0][1]["quote_observed_at"] == runtime.context.market_data["quote"]["observed_at"]
    assert runtime.events[0][1]["quote_source_as_of"] is None
    assert runtime.events[1][1]["response"]["price_source"] == "ltp"
    assert runtime.sandbox._conn.execute("SELECT price_source, price_age_s FROM trades").fetchone() == ("ltp", None)
    assert runtime.captured_token not in repr(runtime.events)


async def test_receipted_ltp_ignores_caller_price_basis_and_stored_close(runtime, monkeypatch):
    from flinttrade_data import practice_price

    monkeypatch.setattr(practice_price, "lookup_stored_last_close",
                        lambda *_: pytest.fail("Validated agent LTP fell back to stored close"))
    result = await runtime.create().place_order(symbol="RELIANCE", exchange="NSE", product="MIS",
                                                action="BUY", quantity=1, price=9999, price_basis="last_close")
    assert result["status"] == "COMPLETE"
    assert result["fill_price"] == 123.5
    assert result["price_source"] == "ltp"


async def test_reads_reuse_authorised_context_and_preserve_unknown_source_freshness(runtime):
    adapter = runtime.create()
    quotes = await adapter.quotes(symbol="RELIANCE", exchange="NSE")
    depth = await adapter.depth(symbol="RELIANCE", exchange="NSE")
    history = await adapter.history(symbol="RELIANCE", exchange="NSE", interval="5m",
                                    start_date="2026-09-27", end_date="2026-09-30")
    assert quotes["data"]["ltp"] == 123.5
    assert quotes["source_as_of"] is None
    assert depth["data"]["bids"][0]["quantity"] == 2
    assert history["data"]["close"] == [123.5]
    assert runtime.reads == [("RELIANCE", "NSE")]
    assert not hasattr(adapter, "balance")


@pytest.mark.parametrize("claims", [{"mode": "live"}, {"mode": "explore"}, {"type": "reset"},
                                     {"exp": int(time.time()) - 10}, {"exp": None}, {"jti": ""}])
def test_only_full_valid_practice_session_can_construct_adapter(runtime, claims):
    with pytest.raises(_module().PracticeAgentError):
        runtime.create(session_token=runtime.token(**claims))
    assert runtime.sandbox.get_orders() == []


async def test_revocation_is_rechecked_for_each_read_and_dispatch(runtime):
    adapter = runtime.create()
    await adapter.quotes(symbol="RELIANCE", exchange="NSE")
    runtime.revoked.add("practice-session")
    with pytest.raises(_module().PracticeAgentError):
        adapter.validate_session()
    with pytest.raises(_module().PracticeAgentError):
        await adapter.quotes(symbol="RELIANCE", exchange="NSE")
    result = await adapter.route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_session_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_revocation_during_quote_read_blocks_dispatch(runtime, monkeypatch):
    adapter = runtime.create()

    def revoked_read(symbol, exchange):
        runtime.revoked.add("practice-session")
        return runtime.context

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", revoked_read)
    result = await adapter.route_order(_order())
    assert not result.passed
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("patch", [
    {"ltp": None}, {"ltp": 0}, {"ltp": -1}, {"ltp": float("nan")}, {"ltp": float("inf")},
    {"ltp": True}, {"available": False}, {"instrument": {"symbol": "OTHER", "exchange": "NSE"}},
])
async def test_invalid_quote_cannot_fill_sandbox(runtime, patch):
    runtime.context.market_data["quote"]["value"].update(patch)
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert result.response["code"] == "practice_market_data_invalid"
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("stamp", [None, "not-time", "2020-01-01T00:00:00+00:00", "future"])
async def test_missing_stale_or_future_observation_cannot_fill(runtime, stamp):
    if stamp == "future":
        stamp = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    runtime.context.market_data["quote"]["observed_at"] = stamp
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert runtime.sandbox.get_orders() == []


async def test_dispatch_refetches_quote_after_analysis(runtime):
    adapter = runtime.create()
    await adapter.quotes(symbol="RELIANCE", exchange="NSE")
    runtime.context.market_data["quote"]["value"]["ltp"] = 127.0
    result = await adapter.route_order(_order())
    assert result.passed
    assert result.order_response.price == 127.0
    assert len(runtime.reads) == 2


@pytest.mark.parametrize("mode", [DecisionStatus.DOWN, DecisionStatus.READY])
async def test_laya_down_and_clamp_preserved_without_resubmission(runtime, mode):
    process_laya().set_status(mode)
    process_laya().set_decision_client(SimpleNamespace(decide=lambda *_: pytest.fail("Empty note reached host")))
    result = await runtime.create().route_order(_order(quantity="4"))
    assert not result.passed
    assert result.response["code"] == ("laya_denied" if mode == DecisionStatus.DOWN else "laya_clamp")
    if mode == DecisionStatus.READY:
        assert result.response["applied_quantity"] == 1
    assert runtime.sandbox.get_orders() == []
    assert len(runtime.reads) == 1


async def test_rationale_reaches_canonical_laya_proposal(runtime, monkeypatch):
    captured = []
    laya = process_laya()
    laya.set_decision_client(None)
    original = laya.admit

    def observe(proposal):
        captured.append(proposal)
        return original(proposal)

    monkeypatch.setattr(laya, "admit", observe)
    note = "Exit if the opening range breaks."
    await runtime.create().route_order(_order(admission_note=note))
    assert captured[0].rationale == note


async def test_stop_after_quote_and_explicit_close_prevent_writes(runtime, monkeypatch):
    adapter = runtime.create(stop_check=lambda: runtime.stopped)

    def stopping_read(symbol, exchange):
        runtime.stopped = True
        return runtime.context

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", stopping_read)
    result = await adapter.route_order(_order())
    assert result.response["code"] == "practice_stopped"
    runtime.stopped = False
    adapter.close()
    result = await adapter.route_order(_order())
    assert not result.passed
    assert runtime.sandbox.get_orders() == []


async def test_rate_limit_is_canonical_and_not_retried(runtime):
    limiter = runtime.app.config["RATE_LIMITER"]
    limiter.set_user_override("operator", "orders", 1)
    adapter = runtime.create()
    assert (await adapter.route_order(_order())).passed
    result = await adapter.route_order(_order())
    assert not result.passed
    assert result.response["http_status"] == 429
    assert len(runtime.sandbox.get_orders()) == 1


@pytest.mark.parametrize("failure_stage", ["dispatch_started", "dispatch_result"])
async def test_durable_event_failure_latches_reconciliation_and_never_retries(runtime, failure_stage):
    def sink(kind, payload):
        if kind == failure_stage:
            raise OSError("synthetic journal failure")

    adapter = runtime.create(event_sink=sink)
    result = await adapter.route_order(_order())
    assert not result.passed
    assert adapter.reconciliation_required
    assert result.response["code"] == "practice_reconciliation_required"
    first_count = len(runtime.sandbox.get_orders())
    assert first_count == (1 if failure_stage == "dispatch_result" else 0)
    again = await adapter.route_order(_order())
    assert not again.passed
    assert len(runtime.sandbox.get_orders()) == first_count


async def test_unknown_exception_after_fill_never_replays_order(runtime, monkeypatch):
    adapter = runtime.create()
    canonical = order_routes.place_order

    def lost_response():
        canonical()
        raise RuntimeError("synthetic response lost")

    monkeypatch.setattr(order_routes, "place_order", lost_response)
    result = await adapter.route_order(_order())
    assert not result.passed
    assert adapter.reconciliation_required
    assert len(runtime.sandbox.get_orders()) == 1
    assert not (await adapter.route_order(_order())).passed
    assert len(runtime.sandbox.get_orders()) == 1


@pytest.mark.parametrize("missing", ["symbol", "exchange", "product"])
async def test_place_requires_explicit_contract_identity(runtime, missing):
    body = {"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "BUY", "quantity": 1}
    del body[missing]
    result = await runtime.create().place_order(**body)
    assert result["code"] == "practice_order_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_practice_mode_is_immutable_and_live_kwarg_is_refused(runtime):
    adapter = runtime.create()
    assert adapter.mode == "practice"
    with pytest.raises(AttributeError):
        adapter.mode = "live"
    result = await adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY",
                                       quantity=1, mode="live")
    assert result["code"] == "practice_order_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_cancellation_while_reading_never_dispatches_late(runtime, monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()

    def blocked_read(symbol, exchange):
        started.set()
        assert release.wait(timeout=5)
        return runtime.context

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", blocked_read)
    adapter = runtime.create()
    task = asyncio.create_task(adapter.route_order(_order()))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not (await adapter.route_order(_order())).passed
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("change", ["stop", "revoke"])
async def test_authority_is_rechecked_after_laya_before_sandbox_write(runtime, monkeypatch, change):
    adapter = runtime.create(stop_check=lambda: runtime.stopped)
    original = order_routes._admit_place

    def change_during_admission(*args, **kwargs):
        response = original(*args, **kwargs)
        if change == "stop":
            runtime.stopped = True
        else:
            runtime.revoked.add("practice-session")
        return response

    monkeypatch.setattr(order_routes, "_admit_place", change_during_admission)
    decision = await adapter.route_order(_order())
    assert not decision.passed
    assert decision.response["code"] == ("practice_stopped" if change == "stop" else "practice_session_invalid")
    assert runtime.sandbox.get_orders() == []


async def test_stopped_session_can_close_only_a_proven_exact_contract_position(runtime):
    adapter = runtime.create(stop_check=lambda: runtime.stopped)
    assert (await adapter.route_order(_order())).passed
    runtime.stopped = True
    assert not (await adapter.route_order(_order(action=Action.SELL, product=Product.CNC))).passed
    process_laya().set_status(DecisionStatus.DOWN)
    exit_decision = await adapter.route_order(_order(action=Action.SELL))
    assert exit_decision.passed
    assert runtime.sandbox.get_positions() == []
    assert len(runtime.sandbox.get_trades()) == 2
    assert not (await adapter.route_order(_order(action=Action.SELL))).passed
    assert len(runtime.sandbox.get_trades()) == 2


async def test_slow_admission_cannot_use_an_observation_that_has_expired(runtime, monkeypatch):
    adapter = runtime.create()
    original = order_routes._admit_place
    adapter_module = _module()

    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=31)

    def slow_admission(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(adapter_module, "datetime", LaterClock)
        return result

    monkeypatch.setattr(order_routes, "_admit_place", slow_admission)
    decision = await adapter.route_order(_order())
    assert not decision.passed
    assert decision.response["code"] == "practice_market_data_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_signed_session_expiring_during_admission_never_dispatches(runtime, monkeypatch):
    adapter = runtime.create()
    original = order_routes._admit_place

    class ExpiredClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(hours=2)

    def expire_during_admission(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(jwt.api_jwt, "datetime", ExpiredClock)
        return result

    monkeypatch.setattr(order_routes, "_admit_place", expire_during_admission)
    decision = await adapter.route_order(_order())
    assert not decision.passed
    assert decision.response["code"] == "practice_session_invalid"
    assert runtime.sandbox.get_orders() == []


async def test_source_timestamp_when_present_must_not_be_stale(runtime):
    runtime.context.market_data["quote"]["source_as_of"] = "2020-01-01T00:00:00+00:00"
    result = await runtime.create().route_order(_order())
    assert not result.passed
    assert runtime.sandbox.get_orders() == []


async def test_missing_configured_market_data_is_visible_without_direct_fallback(runtime, monkeypatch):
    monkeypatch.undo()
    # Restore only test signing authority; keep the real production collector.
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: _KEY)
    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: None)
    adapter = runtime.create(event_sink=lambda kind, data: runtime.events.append((kind, data)))
    result = await adapter.route_order(_order())
    assert not result.passed
    assert result.response["code"] == "broker_context_unavailable"
    assert runtime.events[-1][0] == "data_unavailable"
    assert runtime.sandbox.get_orders() == []


async def test_unsupported_depth_is_an_explicit_data_error(runtime):
    runtime.context.market_data["depth"]["value"] = None
    adapter = runtime.create(event_sink=lambda kind, data: runtime.events.append((kind, data)))
    with pytest.raises(_module().PracticeAgentError, match="practice_depth_unavailable"):
        await adapter.depth(symbol="RELIANCE", exchange="NSE")
    assert runtime.events[-1][0] == "data_unavailable"
    assert runtime.events[-1][1]["operation"] == "depth"


async def test_noncomplete_or_malformed_success_is_reconciliation_required(runtime, monkeypatch):
    from flask import jsonify

    monkeypatch.setattr(order_routes, "place_order", lambda: (jsonify({"status": "PENDING", "order_id": "pending"}), 200))
    adapter = runtime.create()
    decision = await adapter.route_order(_order())
    assert not decision.passed
    assert adapter.reconciliation_required
    assert not (await adapter.route_order(_order())).passed


async def test_read_client_uses_real_exact_authority_collector_without_live_writes(
    tmp_path, monkeypatch, backend_lease_proof,
):
    from uuid import uuid4

    import httpx

    from flinttrade_core.app import _BrokerRuntimeDependencies
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

    # Only external SDK I/O is substituted. Real grants, version checks, ACLs,
    # signed identity, projection and durable receipt collection remain active.
    calls = []

    class MarketSource:
        async def quotes(self, session, symbols):
            calls.append(("quote", session.selector))
            return [{"symbol": "RELIANCE", "exchange": "NSE", "ltp": 123.5, "available": True}]

        async def historical(self, session, read_request):
            calls.append(("historical", session.selector))
            return {"symbol": "RELIANCE", "exchange": "NSE", "interval": "5m", "bars": [
                {"timestamp": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(), "open": 120.0,
                 "high": 124.0, "low": 119.0, "close": 123.5, "volume": 10},
            ]}

        async def balance_snapshot(self, session):
            calls.append(("balance", session.selector))
            return BalanceSnapshot(500.0, BalanceEvidence.DIRECT, None, None, None, None, None, None)

        async def place_order(self, *args, **kwargs):
            pytest.fail("A broker write was attempted")

    selectors = ("dhan:Quotes", "upstox:History", "dhan:Execution")
    workspace_path = tmp_path / "workspace"

    def configure(config):
        config["brokers"]["registered"] = list(selectors)
        config["brokers"]["execution"] = {"default": "dhan:Execution"}
        config["brokers"]["data"].update(quote="dhan:Quotes", historical="upstox:History",
                                         option_chains="dhan:Quotes", ticks="dhan:Quotes")
        config["brokers"]["account_acls"] = {"dhan": {"Quotes": ["operator"], "Execution": ["operator"]},
                                              "upstox": {"History": ["operator"]}}

    workspace = compare_and_swap_workspace(workspace_path, None, configure)
    routing = RoutingConfig.from_workspace(workspace.as_dict()["brokers"])
    registry, publication = create_owned_registry()
    credentials = {}
    for raw in selectors:
        selector = BrokerSelector(*raw.split(":"))
        credentials[selector] = CredentialVersion(selector, uuid4(), 1)
        authority = ManagedSessionAuthority(credentials[selector], workspace.version, broker_workspace_version(workspace))
        session = Session("synthetic-market-read-session", time.time() + 3600, selector.account_id, selector.adapter_id)
        candidate = publication.prepare_session_candidate(
            selector, session, expected_registry=registry.snapshot_selector(selector), authority=authority,
            broker=selector.adapter_id, label=selector.account_id, client=object(),
        )
        publication.publish_prepared_candidate(candidate, current_authority=authority)
    provider = AuthenticatingSessionProvider(
        registry, routing.account_acls, workspace_snapshot=workspace, workspace_path=workspace_path,
        credential_version_for=credentials.__getitem__,
    )
    app = Flask(__name__)

    class NoNetworkClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            def unexpected_http(request):
                pytest.fail("The read-port integration attempted HTTP I/O")

            super().__init__(**kwargs, trust_env=False, transport=httpx.MockTransport(unexpected_http))

    monkeypatch.setattr(httpx, "AsyncClient", NoNetworkClient)
    client = OpenAlgoClient(Settings(openalgo_api_key=""))
    adapters = {"dhan": MarketSource(), "upstox": MarketSource()}
    owner = create_broker_read_owner(registry=registry, session_provider=provider, adapters=adapters,
                                     workspace_path=workspace_path, rate_limiter=None,
                                     runtime_accepting_requests=lambda: True)
    audit = AuditLogger(str(tmp_path / "audit"))
    sandbox = SandboxEngine(str(tmp_path / "sandbox.sqlite3"), initial_capital=100_000.0)
    dependencies = _BrokerRuntimeDependencies(
        registry, routing, workspace.as_dict()["brokers"], provider, adapters, None, None, workspace,
        workspace_path, client, adapters, publication, owner,
    )
    app.extensions["flinttrade_broker_dependencies"] = dependencies
    app.extensions["flinttrade.registry_publication_owner"] = publication
    live_router = _LiveSentinel()
    app.config.update(CLIENT=client, OPENALGO_CLIENT=client, REGISTRY=registry, ACTIVE_BROKER_ADAPTERS=adapters,
                      AUDIT=audit, RUNTIME_ACCEPTING_REQUESTS=True, DATA_SANDBOX_ENGINE=sandbox,
                      RATE_LIMITER=RateLimiter(), BROKER_ROUTER=live_router, SAFETY=SafetySystem(),
                      BACKEND_LEASE_PROOF=backend_lease_proof)
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: _KEY)
    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: None)
    token = jwt.encode({"sub": "operator", "jti": "exact-account-session", "type": "session", "mode": "practice",
                        "iat": int(time.time()), "exp": int(time.time()) + 3600,
                        "scopes": ["admin.accounts.read"]}, _KEY, algorithm="HS256")
    process_laya().set_status(DecisionStatus.READY)
    try:
        adapter = _module().PracticeAgentAdapter(app, token)
        quote = await adapter.quotes(symbol="RELIANCE", exchange="NSE")
        assert quote["data"]["ltp"] == 123.5
        assert quote["source_as_of"] is None
        assert quote["input_receipt"]["event_id"]
        decision = await adapter.route_order(_order())
        assert decision.passed
        assert decision.order_response.fill_price == 123.5
        assert calls == [
            ("quote", BrokerSelector("dhan", "Quotes")),
            ("historical", BrokerSelector("upstox", "History")),
            ("balance", BrokerSelector("dhan", "Execution")),
        ] * 2
        app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
        assert (await adapter.route_order(_order(action=Action.SELL))).passed
        assert sandbox.get_positions() == []
        assert len(calls) == 6  # Cleanup reused the receipted quote without another broker read.
        assert live_router.accesses == []
    finally:
        owner.close(timeout=2.0)
        await client.shutdown()
        audit.close()
        sandbox.close()


async def test_stop_cleanup_rechecks_books_changed_during_admission(runtime, monkeypatch):
    adapter = runtime.create(stop_check=lambda: runtime.stopped)
    assert (await adapter.route_order(_order())).passed
    runtime.stopped = True
    original = order_routes._admit_place

    def reset_during_admission(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.sandbox.reset()
        return result

    monkeypatch.setattr(order_routes, "_admit_place", reset_during_admission)
    result = await adapter.route_order(_order(action=Action.SELL))
    assert not result.passed
    assert result.response["code"] == "practice_stopped"
    assert runtime.sandbox.get_orders() == []
    assert runtime.sandbox.get_positions() == []


@pytest.mark.parametrize("proof", [None, object()])
def test_adapter_requires_minted_backend_ownership(runtime, proof):
    runtime.app.config["BACKEND_LEASE_PROOF"] = proof
    with pytest.raises(_module().PracticeAgentError, match="practice_runtime_unavailable"):
        runtime.create()
    assert runtime.reads == []
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("accepting", [None, False, 1, "true"])
def test_adapter_requires_explicit_initial_runtime_admission(runtime, accepting):
    runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = accepting
    with pytest.raises(_module().PracticeAgentError, match="practice_runtime_unavailable"):
        runtime.create()
    assert runtime.reads == []


async def test_runtime_retired_during_quote_collection_never_opens_position(runtime, monkeypatch):
    adapter = runtime.create()

    def retire_after_read(symbol, exchange):
        runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
        return runtime.context

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", retire_after_read)
    decision = await adapter.route_order(_order())
    assert not decision.passed
    assert decision.response["code"] == "practice_stopped"
    assert runtime.sandbox.get_orders() == []


@pytest.mark.parametrize("retirement", ["revoke", "drain", "replace"])
async def test_backend_ownership_rechecked_after_laya_before_fill(runtime, monkeypatch, retirement):
    adapter = runtime.create()
    original = order_routes._admit_place

    def retire_during_admission(*args, **kwargs):
        result = original(*args, **kwargs)
        if retirement == "revoke":
            runtime.app.config["BACKEND_LEASE_PROOF"].revoke()
        elif retirement == "drain":
            runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
        else:
            runtime.app.config["BACKEND_LEASE_PROOF"] = object()
        return result

    monkeypatch.setattr(order_routes, "_admit_place", retire_during_admission)
    decision = await adapter.route_order(_order())
    assert not decision.passed
    expected = "practice_stopped" if retirement == "drain" else "practice_runtime_unavailable"
    assert decision.response["code"] == expected
    assert runtime.sandbox.get_orders() == []
    assert runtime.sandbox.get_trades() == []
    assert not (await adapter.route_order(_order())).passed


async def test_backend_retirement_blocks_cached_reads(runtime):
    adapter = runtime.create()
    await adapter.quotes(symbol="RELIANCE", exchange="NSE")
    runtime.app.config["BACKEND_LEASE_PROOF"].revoke()
    with pytest.raises(_module().PracticeAgentError, match="practice_runtime_unavailable"):
        await adapter.depth(symbol="RELIANCE", exchange="NSE")
    assert runtime.reads == [("RELIANCE", "NSE")]


async def test_drain_at_final_guard_permits_only_exact_reduce_only_exit(runtime, monkeypatch):
    adapter = runtime.create()
    assert (await adapter.route_order(_order())).passed
    original = order_routes._admit_place

    def drain_during_admission(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
        return result

    monkeypatch.setattr(order_routes, "_admit_place", drain_during_admission)
    assert (await adapter.route_order(_order(action=Action.SELL))).passed
    assert runtime.sandbox.get_positions() == []
    assert not (await adapter.route_order(_order())).passed
    assert len(runtime.sandbox.get_trades()) == 2


async def test_drain_cleanup_uses_only_fresh_audited_cache_and_cannot_enter(runtime, monkeypatch):
    adapter = runtime.create(event_sink=lambda kind, data: runtime.events.append((kind, data)))
    assert (await adapter.route_order(_order())).passed
    runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    process_laya().set_status(DecisionStatus.DOWN)

    def forbid_read(*args, **kwargs):
        pytest.fail("Drained cleanup attempted a new broker read")

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", forbid_read)
    assert not (await adapter.route_order(_order(action=Action.SELL, product=Product.CNC))).passed
    decision = await adapter.route_order(_order(action=Action.SELL))
    assert decision.passed
    assert decision.order_response.fill_price == 123.5
    assert runtime.sandbox.get_positions() == []
    assert not (await adapter.route_order(_order())).passed
    dispatches = [data for kind, data in runtime.events if kind == "dispatch_started"]
    assert len(dispatches) == 2
    assert dispatches[1]["cached_on_drain"] is True
    assert dispatches[1]["input_receipt"] == dispatches[0]["input_receipt"]
    assert dispatches[1]["quote_observed_at"] == dispatches[0]["quote_observed_at"]


@pytest.mark.parametrize("cache_state", ["absent", "expired_observation", "expired_source"])
async def test_drain_cleanup_without_valid_cached_quote_refuses_without_read(runtime, monkeypatch, cache_state):
    adapter = runtime.create(event_sink=lambda kind, data: runtime.events.append((kind, data)))
    assert (await adapter.route_order(_order())).passed
    if cache_state == "absent":
        adapter._cache.clear()
    else:
        field = "observed_at" if cache_state == "expired_observation" else "source_as_of"
        adapter._cache[("RELIANCE", "NSE")].market_data["quote"][field] = "2020-01-01T00:00:00+00:00"
    runtime.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False

    def forbid_read(*args, **kwargs):
        pytest.fail("Drained cleanup attempted a new broker read")

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", forbid_read)
    decision = await adapter.route_order(_order(action=Action.SELL))
    assert not decision.passed
    assert decision.response["code"] == "practice_market_data_invalid"
    assert len(runtime.sandbox.get_trades()) == 1
    assert runtime.sandbox.get_positions()[0]["net_qty"] == 1
    assert runtime.events[-1][0] == "data_unavailable"


@pytest.mark.parametrize("cancel_stage", ["dispatch_started", "final_admission", "after_fill", "dispatch_result"])
async def test_synchronous_cancellation_seals_adapter_without_replay(runtime, monkeypatch, cancel_stage):
    def cancel_during_evidence(kind, data):
        if kind == cancel_stage:
            asyncio.current_task().cancel()

    if cancel_stage in {"final_admission", "after_fill"}:
        target = "_admit_place" if cancel_stage == "final_admission" else "place_order"
        original = getattr(order_routes, target)

        def cancel_after_canonical_call(*args, **kwargs):
            result = original(*args, **kwargs)
            asyncio.current_task().cancel()
            return result

        monkeypatch.setattr(order_routes, target, cancel_after_canonical_call)

    adapter = runtime.create(event_sink=cancel_during_evidence)
    task = asyncio.create_task(adapter.route_order(_order()))
    with pytest.raises(asyncio.CancelledError):
        await task
    count = len(runtime.sandbox.get_trades())
    assert count == (1 if cancel_stage in {"after_fill", "dispatch_result"} else 0)
    assert adapter.reconciliation_required is (cancel_stage != "dispatch_started")
    assert not (await adapter.route_order(_order())).passed
    assert len(runtime.sandbox.get_trades()) == count


async def test_cancellation_from_final_stop_check_prevents_fill(runtime, monkeypatch):
    admitted = False
    original = order_routes._admit_place

    def record_admission(*args, **kwargs):
        nonlocal admitted
        result = original(*args, **kwargs)
        admitted = True
        return result

    def cancel_at_final_guard():
        if admitted:
            asyncio.current_task().cancel()
        return False

    monkeypatch.setattr(order_routes, "_admit_place", record_admission)
    adapter = runtime.create(stop_check=cancel_at_final_guard)
    task = asyncio.create_task(adapter.route_order(_order()))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.sandbox.get_trades() == []
    assert not (await adapter.route_order(_order())).passed
