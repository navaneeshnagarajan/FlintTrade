"""Offline ownership and recovery checks for the real Practice supervisor."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, time as wall_time
from types import SimpleNamespace

import jwt
import pytest
from flask import Flask

from flinttrade_ai.run_store import AgentRunStore
from flinttrade_core import agent_routes, ai_broker_context, auth_routes, order_routes
from flinttrade_core import practice_agent_runtime as runtime
from flinttrade_core.ai_broker_context import BrokerAnalysisContext
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_engine.laya import DecisionStatus, process_laya
from flinttrade_engine.safety import SafetySystem

from flinttrade_core.practice_agent_runtime import validate_practice_config

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("body", [
    None, [], {"symbols": "RELIANCE"}, {"symbols": [42]}, {"symbols": []},
    {"symbols": ["RELIANCE"], "cycle_interval_sec": True},
    {"symbols": ["RELIANCE"], "max_position_size": 1.5},
    {"symbols": ["RELIANCE"], "stop_loss_pct": float("nan")},
    {"symbols": ["RELIANCE"], "take_profit_pct": float("inf")},
    {"symbols": ["RELIANCE"], "daily_stop_loss": 0},
    {"symbols": ["RELIANCE"], "exchange": "UNKNOWN"},
    {"symbols": ["RELIANCE"], "product": "BO"},
    {"symbols": ["RELIANCE"], "mode": "live"},
    {"symbols": ["RELIANCE"], "broker": "live-broker"},
    {"symbols": ["RELIANCE"], "cycle_interval_sec": 86400},
    {"symbols": ["RELIANCE"] * 21},
])
def test_config_rejects_ambiguous_or_unbounded_input(body):
    with pytest.raises(ValueError):
        validate_practice_config(body)


def test_config_preserves_explicit_zero_rejection_and_normalises_symbols():
    config = validate_practice_config({"symbols": [" reliance ", "TCS", "RELIANCE"]})
    assert config["symbols"] == ["RELIANCE", "TCS"]
    assert config["exchange"] == "NSE"
    assert config["cycle_interval_sec"] == 60
    with pytest.raises(ValueError):
        validate_practice_config({"symbols": ["RELIANCE"], "max_position_size": 0})


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "Practice worker did not reach the expected state"


class _NeverLive:
    def __getattr__(self, name):
        raise AssertionError(f"Practice touched Live dependency {name}")


@pytest.fixture
def desk(tmp_path, monkeypatch, backend_lease_proof):
    key = "synthetic-practice-supervisor-key-never-production"
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: key)
    monkeypatch.setattr(auth_routes, "_get_auth_service", lambda: None)
    state = SimpleNamespace(
        now=datetime.fromisoformat("2026-09-30T10:00:00+05:30"),
        revoked=set(), enabled=True, signal="HOLD", reads=0, learning=None,
        release=threading.Event(), analysis_entered=threading.Event(), delayed=False,
    )
    monkeypatch.setattr(auth_routes, "_is_jti_revoked", lambda jti: jti in state.revoked)
    monkeypatch.setattr(agent_routes, "_agent_flag_enabled", lambda: state.enabled)
    monkeypatch.setattr(agent_routes, "_build_vault", lambda: None)
    monkeypatch.setattr(agent_routes, "_build_skills_workspace", lambda: None)
    monkeypatch.setattr(agent_routes, "_build_learning_memory", lambda: state.learning)

    def chat(_messages):
        if state.delayed:
            state.analysis_entered.set()
            assert state.release.wait(10), "test forgot to release the offline LLM"
        return SimpleNamespace(content=state.signal)

    state.llm = SimpleNamespace(chat=chat)
    monkeypatch.setattr(agent_routes, "_build_llm", lambda: state.llm)
    app = Flask(__name__)
    sandbox = SandboxEngine(str(tmp_path / "sandbox.sqlite"), initial_capital=100_000)
    store = AgentRunStore(tmp_path / "runs.sqlite")
    app.config.update(
        TESTING=True, DATA_SANDBOX_ENGINE=sandbox, PRACTICE_AGENT_RUN_STORE=store,
        BACKEND_LEASE_PROOF=backend_lease_proof, RUNTIME_ACCEPTING_REQUESTS=True,
        RATE_LIMITER=RateLimiter(), TIME_SCHEDULER=SimpleNamespace(
            now_ist=lambda: state.now,
            get_market_session=lambda *_args, **_kwargs: (wall_time(9, 15), wall_time(15, 30)),
        ), BROKER_ROUTER=_NeverLive(), OPENALGO_CLIENT=_NeverLive(), CLIENT=_NeverLive(),
        TICK_RECORDER=None, SAFETY=SafetySystem(),
    )
    app.register_blueprint(order_routes.orders_bp)
    for path, method, function in (
        ("/start", "POST", runtime.start_practice_agent),
        ("/stop", "POST", runtime.stop_practice_agent),
        ("/status", "GET", runtime.practice_agent_status),
        ("/runs", "GET", runtime.list_practice_runs),
        ("/runs/<run_id>/events", "GET", runtime.practice_run_events),
        ("/runs/<run_id>/resolve", "POST", runtime.resolve_practice_run),
    ):
        app.add_url_rule(path, view_func=function, methods=[method])
    process_laya().set_status(DecisionStatus.READY)

    def collect(symbol, exchange):
        state.reads += 1
        now = datetime.now(UTC).isoformat()
        instrument = {"symbol": symbol, "exchange": exchange, "instrument_id": None}
        return BrokerAnalysisContext({
            "symbol": symbol, "exchange": exchange,
            "quote": {"value": {"instrument": instrument, "available": True,
                                "ltp": 123.5, "open": 120, "high": 124, "low": 119,
                                "volume": 10, "prev_close": 120}, "observed_at": now},
            "depth": {"value": {"instrument": instrument, "bids": [], "asks": []}, "observed_at": now},
            "historical": {"value": {"instrument": instrument, "interval": "5m", "bars": [
                {"timestamp": now, "open": 120, "high": 124, "low": 119, "close": 123.5, "volume": 10}
                for _ in range(60)
            ]}},
        }, {"event_id": "synthetic-observation", "input_digest": "b" * 64})

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", collect)

    def token(**changes):
        claims = {"sub": "operator", "jti": "practice-session", "type": "session", "mode": "practice",
                  "iat": int(time.time()), "exp": int(time.time()) + 3600}
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="HS256")

    state.app, state.sandbox, state.store, state.token = app, sandbox, store, token
    state.headers = {"Authorization": "Bearer " + token()}
    state.client = app.test_client()
    with app.app_context():
        state.owner = auth_routes.verify_operator_session_token(token()).actor_ref
    yield state
    state.release.set()
    runtime.shutdown_practice_agent(app, timeout=5)
    supervisor = app.extensions.get("practice_agent_supervisor")
    if supervisor and supervisor.run and supervisor.run.thread:
        assert not supervisor.run.thread.is_alive(), "test leaked a Practice worker"
    sandbox.close()
    store.close()


def _start(desk, **config):
    return desk.client.post("/start", headers=desk.headers, json={"symbols": ["RELIANCE"], **config})


def _supervisor(desk):
    return desk.app.extensions["practice_agent_supervisor"]


def _run_finished(desk):
    return _supervisor(desk).run.thread is not None and not _supervisor(desk).run.thread.is_alive()


@pytest.mark.parametrize("claims,code", [
    ({"mode": "live"}, 403), ({"mode": "explore"}, 403),
    ({"type": "reset"}, 401), ({"setup_session": True}, 401),
    ({"exp": 1}, 401), ({"exp": None}, 401), ({"jti": ""}, 401),
])
def test_every_control_requires_full_practice_session(desk, claims, code):
    headers = {"Authorization": "Bearer " + desk.token(**claims)}
    for path, method in (("/start", "POST"), ("/stop", "POST"), ("/status", "GET"), ("/runs", "GET"),
                         ("/runs/example/events", "GET"), ("/runs/example/resolve", "POST")):
        result = desk.client.open(path, method=method, headers=headers, json={"symbols": ["RELIANCE"]})
        assert result.status_code == code
    assert desk.store.list_runs() == []


def test_closed_market_waits_without_analysis_and_stop_is_interruptible(desk):
    desk.now = desk.now.replace(hour=20)
    result = _start(desk, cycle_interval_sec=3600)
    assert result.status_code == 202, result.get_json()
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    assert desk.reads == 0
    assert _start(desk).status_code == 409
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "stopped"
    assert row["snapshot"]["running"] is False
    assert runtime.shutdown_practice_agent(desk.app, timeout=1)


def test_real_cycle_fills_then_stop_squares_off_and_persists_evidence(desk):
    desk.signal = "BUY"
    response = _start(desk)
    assert response.status_code == 202, response.get_json()
    run_id = response.get_json()["data"]["run_id"]
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert desk.sandbox.get_positions()[0]["net_qty"] == 1
    assert desk.client.post("/stop", headers=desk.headers, json={"square_off": False}).status_code == 400
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    assert desk.sandbox.get_positions() == []
    assert len(desk.sandbox.get_trades()) == 2
    row = desk.store.get_run(run_id)
    assert row["status"] == "stopped"
    assert row["snapshot"]["cycle_count"] == 1
    assert row["snapshot"]["shutdown_complete"] is True
    kinds = [event["kind"] for event in desk.store.events(run_id)]
    assert kinds.count("dispatch_started") == 2
    assert kinds.count("dispatch_result") == 2
    assert "cycle_finished" in kinds
    assert "session_flat" in kinds
    assert desk.token() not in repr(row) + repr(desk.store.events(run_id))


@pytest.mark.parametrize("revoked", [False, True])
def test_stop_or_revocation_during_delayed_analysis_never_enters(desk, revoked):
    desk.signal, desk.delayed = "BUY", True
    assert _start(desk).status_code == 202
    assert desk.analysis_entered.wait(3)
    if revoked:
        desk.revoked.add("practice-session")
    else:
        assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
        assert runtime.shutdown_practice_agent(desk.app, timeout=0.01) is False
        assert _supervisor(desk).run.thread.is_alive()
    desk.release.set()
    _wait_for(lambda: _run_finished(desk))
    assert desk.sandbox.get_orders() == []
    assert desk.store.list_runs()[0]["status"] in {"stopped", "failed"}


@pytest.mark.parametrize("change", ["disabled", "closed", "square_off_lead"])
def test_runtime_entry_authority_is_rechecked_after_delayed_analysis(desk, change):
    desk.signal, desk.delayed = "BUY", True
    assert _start(desk).status_code == 202
    assert desk.analysis_entered.wait(3)
    if change == "disabled":
        desk.enabled = False
    elif change == "closed":
        desk.now = desk.now.replace(hour=16)
    else:
        desk.now = desk.now.replace(hour=15, minute=16)
    desk.release.set()
    if change == "disabled":
        _wait_for(lambda: _run_finished(desk))
    else:
        _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    assert desk.sandbox.get_orders() == []


def test_prior_day_analysis_cannot_enter_a_later_open_session(desk):
    desk.signal, desk.delayed = "BUY", True
    assert _start(desk, cycle_interval_sec=1).status_code == 202
    assert desk.analysis_entered.wait(3)
    desk.now = datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    desk.release.set()
    _wait_for(lambda: len(desk.sandbox.get_orders()) == 1)
    run = _supervisor(desk).run
    events = desk.store.events(run.run_id)
    sessions = [index for index, event in enumerate(events) if event["kind"] == "session_started"]
    dispatches = [index for index, event in enumerate(events) if event["kind"] == "dispatch_started"]
    assert len(sessions) == 2
    assert len(dispatches) == 1
    assert dispatches[0] > sessions[1]


def test_external_flattening_requires_reconciliation_of_retained_tracker(desk):
    desk.signal = "BUY"
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    result = desk.client.post("/api/v1/orders/place", headers=desk.headers, json={
        "symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "SELL",
        "quantity": 1, "pricetype": "MARKET", "price": 123.5, "price_basis": "ltp",
    })
    assert result.status_code == 200, result.get_json()
    assert desk.sandbox.get_positions() == []
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "reconciliation_required"
    assert row["snapshot"]["active_positions"]
    assert len(desk.sandbox.get_orders()) == 2
    result = desk.client.post(f"/runs/{row['run_id']}/resolve", headers=desk.headers)
    assert result.status_code == 200, result.get_json()
    assert result.get_json()["data"]["active_positions"] == {}
    assert result.get_json()["data"]["position_details"] == {}


def test_revoked_position_is_retained_and_requires_flat_reconciliation(desk):
    desk.signal = "BUY"
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    desk.revoked.add("practice-session")
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "reconciliation_required"
    assert desk.sandbox.get_positions()[0]["net_qty"] == 1
    assert len(desk.sandbox.get_orders()) == 1
    assert not runtime.shutdown_practice_agent(desk.app, timeout=0.1)
    fresh = {"Authorization": "Bearer " + desk.token(jti="fresh")}
    result = desk.client.post(f"/runs/{row['run_id']}/resolve", headers=fresh)
    assert result.status_code == 409
    assert len(desk.sandbox.get_orders()) == 1


def test_crash_recovery_does_not_replay_and_requires_explicit_flat_resolve(desk):
    config = {**validate_practice_config({"symbols": ["RELIANCE"]}), "owner": desk.owner}
    desk.store.create_run(run_id="interrupted", mode="practice", config=config)
    desk.store.update_run("interrupted", status="running", snapshot={"cycle_count": 3})
    status = desk.client.get("/status", headers=desk.headers)
    assert status.get_json()["data"]["status"] == "reconciliation_required"
    assert _start(desk).status_code == 409
    assert desk.sandbox.get_orders() == []
    result = desk.client.post("/runs/interrupted/resolve", headers=desk.headers)
    assert result.status_code == 200
    assert result.get_json()["data"]["status"] == "stopped"
    assert result.get_json()["data"]["mode"] == "practice"
    desk.now = desk.now.replace(hour=20)
    assert _start(desk).status_code == 202


def test_ownership_filters_history_status_events_and_resolve(desk):
    config = {"owner": "another-operator", "symbols": ["OTHER"]}
    desk.store.create_run(run_id="private-run", mode="practice", config=config)
    assert desk.client.get("/runs", headers=desk.headers).get_json()["data"] == []
    assert desk.client.get("/status", headers=desk.headers).get_json()["data"]["status"] == "idle"
    assert desk.client.get("/runs/private-run/events", headers=desk.headers).status_code == 404
    assert desk.client.post("/runs/private-run/resolve", headers=desk.headers).status_code == 404


def test_day_boundary_closes_positions_and_next_day_resets_only_when_flat(desk):
    desk.signal = "BUY"
    assert _start(desk, cycle_interval_sec=1).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    desk.now = desk.now.replace(hour=15, minute=16)
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    assert desk.sandbox.get_positions() == []
    assert _supervisor(desk).run.trader.state.trade_counts["RELIANCE"] == 1
    desk.signal = "HOLD"
    desk.now = datetime.fromisoformat("2026-10-01T10:00:00+05:30")
    _wait_for(lambda: _supervisor(desk).run.status == "running")
    _wait_for(lambda: _supervisor(desk).run.trader.state.cycle_count == 1)
    assert _supervisor(desk).run.trader.state.trade_counts["RELIANCE"] == 0
    assert len(desk.sandbox.get_orders()) == 2


def test_unavailable_configured_data_fails_visibly_without_orders(desk, monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("credential-looking-provider-details-must-not-persist")

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", unavailable)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "failed"
    assert "market data unavailable" in row["error"]
    assert "credential-looking" not in repr(row) + repr(desk.store.events(row["run_id"]))
    assert desk.sandbox.get_orders() == []


def test_missing_history_brakes_before_valid_quote_can_trigger_entry(desk, monkeypatch):
    original = ai_broker_context.collect_configured_broker_context

    def incomplete(symbol, exchange):
        context = original(symbol, exchange)
        context.market_data.pop("historical")
        return context

    desk.signal = "BUY"
    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", incomplete)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "failed"
    assert "market data unavailable" in row["error"]
    assert desk.sandbox.get_orders() == []


def test_evidence_failure_brakes_orders_and_requires_reconciliation(desk, monkeypatch):
    original = desk.store.append_event

    def fail_after_cycle(run_id, *, kind, data):
        if kind == "cycle_finished":
            raise OSError("synthetic evidence write failure")
        return original(run_id, kind=kind, data=data)

    monkeypatch.setattr(desk.store, "append_event", fail_after_cycle)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    assert _supervisor(desk).run.evidence_failed
    assert desk.store.list_runs()[0]["status"] == "reconciliation_required"
    assert desk.sandbox.get_orders() == []
    assert not runtime.shutdown_practice_agent(desk.app, timeout=0.1)


def test_feature_disable_stops_waiting_worker_and_missing_calendar_refuses(desk):
    desk.now = desk.now.replace(hour=20)
    desk.enabled = False
    assert _start(desk).status_code == 403
    desk.enabled = True
    scheduler = desk.app.config.pop("TIME_SCHEDULER")
    assert _start(desk).status_code == 503
    desk.app.config["TIME_SCHEDULER"] = scheduler
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    desk.enabled = False
    _wait_for(lambda: _run_finished(desk))
    assert desk.store.list_runs()[0]["status"] == "stopped"


@pytest.mark.parametrize("url", ["/runs?limit=0", "/runs?limit=101", "/runs?limit=nan", "/runs/x/events?after=-1"])
def test_history_queries_are_bounded(desk, url):
    assert desk.client.get(url, headers=desk.headers).status_code == 400


def test_fallback_hold_signal_remains_json_serialisable(desk):
    desk.signal = "not-a-trading-signal"
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    run = _supervisor(desk).run
    cycles = [event for event in desk.store.events(run.run_id) if event["kind"] == "cycle_finished"]
    assert cycles[0]["data"]["actions"]["RELIANCE"]["signal"] == "HOLD"
    assert run.status == "running"
    assert desk.sandbox.get_orders() == []


def test_terminal_evidence_failure_never_releases_durable_or_memory_fence(desk, monkeypatch):
    desk.now = desk.now.replace(hour=20)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    original = desk.store.append_event

    def fail_terminal(run_id, *, kind, data):
        if kind == "status_changed" and data["status"] == "stopped":
            raise OSError("synthetic terminal event failure")
        return original(run_id, kind=kind, data=data)

    monkeypatch.setattr(desk.store, "append_event", fail_terminal)
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    run = _supervisor(desk).run
    assert run.status == "reconciliation_required"
    assert desk.store.get_run(run.run_id)["status"] == "stopping"
    assert _start(desk).status_code == 409
    assert desk.sandbox.get_orders() == []
    monkeypatch.setattr(desk.store, "append_event", original)
    assert desk.client.post(f"/runs/{run.run_id}/resolve", headers=desk.headers).status_code == 200
    assert desk.store.get_run(run.run_id)["status"] == "stopped"


def test_shutdown_before_first_start_is_a_permanent_app_brake(desk):
    assert runtime.shutdown_practice_agent(desk.app)
    assert _start(desk).status_code == 409
    assert desk.store.list_runs() == []


def test_shutdown_closes_store_once_only_after_worker_finishes(desk, monkeypatch):
    desk.delayed = True
    assert _start(desk).status_code == 202
    assert desk.analysis_entered.wait(3)
    calls = []
    original = desk.store.close

    def close():
        calls.append(True)
        original()

    monkeypatch.setattr(desk.store, "close", close)
    assert not runtime.shutdown_practice_agent(desk.app, timeout=0.01)
    assert not calls
    desk.release.set()
    assert runtime.shutdown_practice_agent(desk.app, timeout=3)
    assert calls == [True]
    assert runtime.shutdown_practice_agent(desk.app, timeout=0)
    assert calls == [True]
    monkeypatch.setattr(desk.store, "close", original)


def test_real_closed_trade_learning_persists_and_reopens_offline(desk, tmp_path):
    from flinttrade_ai.memory import TradedMemory

    memory_path = str(tmp_path / "lessons")
    desk.learning = TradedMemory(persist_dir=memory_path)

    def chat(messages):
        if "retrospection" in messages[0].content:
            assert desk.sandbox.get_positions() == [], "learning preceded safe square-off"
            return SimpleNamespace(content='{"recommendations":["Review the opening range before entry"]}')
        return SimpleNamespace(content="BUY")

    desk.llm.chat = chat
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "stopped"
    assert len(desk.sandbox.get_trades()) == 2
    restored = TradedMemory(persist_dir=memory_path)
    try:
        lessons = restored.retrieve("opening range", symbol="RELIANCE")
        assert any("opening range" in lesson.content for lesson in lessons)
        assert lessons[0].metadata["source"] == "autonomous-agent-session"
    finally:
        restored.close()


@pytest.mark.parametrize("laya_status,quantity,code", [
    (DecisionStatus.DOWN, 1, "laya_denied"), (DecisionStatus.DEGRADED, 4, "laya_clamp"),
])
def test_cycle_preserves_denial_or_clamp_in_durable_evidence(desk, laya_status, quantity, code):
    desk.signal = "BUY"
    process_laya().set_status(laya_status)
    assert _start(desk, max_position_size=quantity).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    row = desk.store.list_runs()[0]
    results = [event["data"] for event in desk.store.events(row["run_id"]) if event["kind"] == "dispatch_result"]
    assert len(results) == 1
    assert results[0]["response"]["code"] == code
    assert desk.sandbox.get_orders() == []


def test_concurrent_start_requests_create_exactly_one_worker(desk):
    desk.now = desk.now.replace(hour=20)
    barrier = threading.Barrier(2)
    codes = []

    def start():
        with desk.app.test_client() as client:
            barrier.wait()
            codes.append(client.post("/start", headers=desk.headers, json={"symbols": ["RELIANCE"]}).status_code)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert sorted(codes) == [202, 409]
    assert len(desk.store.list_runs()) == 1


def test_startup_evidence_failure_keeps_durable_reconciliation_fence(desk, monkeypatch):
    original = desk.store.append_event

    def fail_start(run_id, *, kind, data):
        if kind == "run_started":
            raise OSError("synthetic startup evidence failure")
        return original(run_id, kind=kind, data=data)

    monkeypatch.setattr(desk.store, "append_event", fail_start)
    assert _start(desk).status_code == 503
    row = desk.store.list_runs()[0]
    assert row["status"] == "reconciliation_required"
    assert row["snapshot"]["shutdown_complete"] is True
    assert desk.sandbox.get_orders() == []
    # This database fence must survive replacement of the original in-memory
    # owner, not merely prevent another start on that Python object.
    with pytest.raises(RuntimeError, match="unresolved interruption"):
        desk.store.create_run(run_id="replacement", mode="practice", config={"owner": desk.owner})
    monkeypatch.setattr(desk.store, "append_event", original)
    assert desk.client.post(f"/runs/{row['run_id']}/resolve", headers=desk.headers).status_code == 200


@pytest.mark.parametrize("authority", ["missing", "revoked", "draining"])
def test_recovery_requires_current_accepting_backend_before_mutating_rows(desk, authority):
    desk.store.create_run(run_id="interrupted", mode="practice", config={"owner": desk.owner})
    if authority == "missing":
        desk.app.config.pop("BACKEND_LEASE_PROOF")
    elif authority == "revoked":
        desk.app.config["BACKEND_LEASE_PROOF"].revoke()
    else:
        desk.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    assert desk.client.get("/status", headers=desk.headers).status_code == 503
    assert desk.store.get_run("interrupted")["status"] == "starting"
    assert desk.store.events("interrupted") == []
    assert "practice_agent_supervisor" not in desk.app.extensions


def test_second_supervisor_cannot_recover_or_release_a_live_owner(desk):
    from filelock import Timeout

    desk.now = desk.now.replace(hour=20)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    run_id = _supervisor(desk).run.run_id
    contender = AgentRunStore(desk.store.database_path)
    try:
        with pytest.raises(Timeout):
            runtime.PracticeAgentSupervisor(desk.app, contender)
        assert contender.get_run(run_id)["status"] == "waiting"
        assert not any(event["kind"] == "recovered" for event in contender.events(run_id))
        assert runtime.shutdown_practice_agent(desk.app, timeout=3)
        successor = runtime.PracticeAgentSupervisor(desk.app, contender)
        assert contender.get_run(run_id)["status"] == "stopped"
        assert successor.shutdown(0)
    finally:
        contender.close()


def test_runtime_lock_remains_owned_until_blocked_model_close_finishes(desk):
    from filelock import Timeout

    entered, release = threading.Event(), threading.Event()

    def close():
        entered.set()
        assert release.wait(10), "test forgot to release model cleanup"

    desk.llm.close = close
    desk.now = desk.now.replace(hour=20)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    assert not runtime.shutdown_practice_agent(desk.app, timeout=0.01)
    assert entered.wait(3)
    contender = AgentRunStore(desk.store.database_path)
    try:
        with pytest.raises(Timeout):
            runtime.PracticeAgentSupervisor(desk.app, contender)
        assert _supervisor(desk).run.cleanup_complete is False
    finally:
        release.set()
        assert runtime.shutdown_practice_agent(desk.app, timeout=3)
        contender.close()


@pytest.mark.parametrize("failure", ["raises", "error_response", "empty_response"])
def test_model_failure_brakes_and_records_unavailability_instead_of_healthy_hold(desk, failure):
    def unavailable(_messages):
        if failure == "raises":
            raise OSError("private-provider-detail-must-not-persist")
        return SimpleNamespace(content="BUY" if failure == "error_response" else " ",
                               error="private-provider-detail-must-not-persist" if failure == "error_response" else "")

    desk.llm.chat = unavailable
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert row["status"] == "failed"
    assert "Configured model unavailable" in row["error"]
    assert any(event["kind"] == "model_unavailable" and event["data"]["operation"] == "analysis" for event in events)
    assert "private-provider-detail" not in repr(row) + repr(events)
    assert desk.sandbox.get_orders() == []


def test_model_construction_failure_is_visible_without_persisting_provider_details(desk, monkeypatch):
    def unavailable():
        raise OSError("private-provider-detail-must-not-persist")

    monkeypatch.setattr(agent_routes, "_build_llm", unavailable)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert row["status"] == "failed"
    assert "Configured model unavailable" in row["error"]
    assert any(event["kind"] == "model_unavailable" and event["data"]["operation"] == "construction" for event in events)
    assert "private-provider-detail" not in repr(row) + repr(events)
    assert desk.sandbox.get_orders() == []


def test_stop_publishes_last_worker_snapshot_without_reading_mutable_state(desk):
    desk.signal = "BUY"
    assert _start(desk, cycle_interval_sec=1).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    run = _supervisor(desk).run

    class WorkerOwnedPositions(dict):
        def items(self):
            assert threading.current_thread() is run.thread, "request thread read worker-owned positions"
            return super().items()

    desk.delayed = True
    assert desk.analysis_entered.wait(3)
    run.trader.state.position_details = WorkerOwnedPositions(run.trader.state.position_details)
    response = desk.client.post("/stop", headers=desk.headers, json={})
    try:
        assert response.status_code == 200, response.get_json()
        assert response.get_json()["data"]["status"] == "stopping"
        assert response.get_json()["data"]["active_positions"] == {"RELIANCE": 123.5}
    finally:
        desk.release.set()
    _wait_for(lambda: _run_finished(desk))
    assert desk.store.get_run(run.run_id)["snapshot"]["active_positions"] == {}


def test_operator_entry_rationale_persists_with_run_and_reaches_typed_order(desk):
    desk.now = desk.now.replace(hour=20)
    rationale = "Operator opening-range plan\nKeep the configured stop."
    response = _start(desk, entry_rationale="  " + rationale + "  ")
    assert response.status_code == 202, response.get_json()
    run_id = response.get_json()["data"]["run_id"]
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    assert desk.store.get_run(run_id)["config"]["entry_rationale"] == rationale
    status = desk.client.get("/status", headers=desk.headers).get_json()["data"]
    assert status["params"]["entry_rationale"] == rationale
    trader = _supervisor(desk).run.trader
    assert trader.config.entry_rationale == rationale
    assert trader._build_market_order("RELIANCE", "BUY", 1).admission_note == rationale
    assert desk.sandbox.get_orders() == []


def test_model_budget_exhaustion_settles_positions_and_skips_learning(desk):
    desk.signal = "BUY"
    desk.learning = SimpleNamespace(add=lambda *_args, **_kwargs: pytest.fail("Exhausted run must skip reflection"))
    result = _start(desk, model_call_limit=2, model_output_limit=64, cycle_interval_sec=1)
    assert result.status_code == 202, result.get_json()
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert desk.sandbox.get_positions()[0]["net_qty"] == 1
    status = desk.client.get("/status", headers=desk.headers).get_json()["data"]
    assert status["model_usage"]["model_calls_used"] == 1
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert row["status"] == "stopped"
    assert row["snapshot"]["model_usage"] == {
        "model_call_limit": 2, "model_output_limit": 64, "model_calls_used": 2,
        "model_calls_remaining": 0, "status": "exhausted",
    }
    assert desk.sandbox.get_positions() == []
    assert len(desk.sandbox.get_trades()) == 2
    assert len([event for event in events if event["kind"] == "model_attempt_reserved"]) == 2
    assert any(event["kind"] == "session_learning_skipped" and event["data"]["reason"] == "model_limit_exhausted" for event in events)


def test_model_reservation_write_failure_brakes_without_calling_provider(desk, monkeypatch):
    called = []
    desk.llm.chat = lambda _messages: called.append(True)
    original = desk.store.append_event

    def append(run_id, *, kind, data):
        if kind == "model_attempt_reserved":
            raise OSError("synthetic evidence failure")
        return original(run_id, kind=kind, data=data)

    monkeypatch.setattr(desk.store, "append_event", append)
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    assert row["status"] == "reconciliation_required"
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 0
    assert called == []
    assert desk.sandbox.get_orders() == []


def test_single_reserved_model_call_may_enter_before_next_attempt_stops(desk):
    desk.signal = "BUY"
    result = _start(desk, model_call_limit=1, cycle_interval_sec=1)
    assert result.status_code == 202, result.get_json()
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert desk.sandbox.get_positions()[0]["net_qty"] == 1
    assert _supervisor(desk).run.model_budget.exhausted
    assert not _supervisor(desk).run.stop.is_set()
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert row["status"] == "stopped" and row["error"] is None
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 1
    assert len([e for e in events if e["kind"] == "model_attempt_reserved"]) == 1
    assert any(e["kind"] == "model_limit_exhausted" for e in events)
    assert not any(e["kind"] == "model_unavailable" for e in events)
    assert desk.sandbox.get_positions() == []
    assert len(desk.sandbox.get_trades()) == 2


def test_worker_freezes_production_client_and_closes_original_transport(desk, monkeypatch):
    from flinttrade_ai.llm_client import LLMClient, LLMConfig

    configured = LLMConfig(provider="openai", model="synthetic-model", reasoning_max_tokens=8192)
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: configured))
    source = LLMClient(fallback_config=LLMConfig(provider="anthropic", model="synthetic-fallback"))
    monkeypatch.setattr(agent_routes, "_build_llm", lambda: source)
    desk.now = desk.now.replace(hour=20)
    response = _start(desk, model_output_limit=32)
    assert response.status_code == 202, response.get_json()
    _wait_for(lambda: _supervisor(desk).run.status == "waiting")
    client = _supervisor(desk).run.llm
    assert client is not source
    assert client.config is not configured
    assert client.config.max_tokens == 32
    assert client.config.reasoning_max_tokens == 0
    assert client.fallback_config is None
    assert client._dynamic_config is False
    assert source._http._managed_ollama.is_closed
    assert configured.reasoning_max_tokens == 8192
    assert configured.max_tokens == 4096
    assert desk.client.post("/stop", headers=desk.headers, json={}).status_code == 200
    _wait_for(lambda: _run_finished(desk))
    assert client._http._managed_ollama.is_closed


@pytest.mark.parametrize("brake", ["kill", "stop", "disable", "revoke"])
def test_model_admission_rechecks_safety_after_market_read_without_consuming_budget(desk, monkeypatch, brake):
    collect = ai_broker_context.collect_configured_broker_context
    calls = []

    def brake_after_read(symbol, exchange):
        result = collect(symbol, exchange)
        if brake == "kill":
            desk.app.config["SAFETY"].l5_kill.activate("synthetic model-boundary brake")
        elif brake == "stop":
            _supervisor(desk).run.stop.set()
        elif brake == "disable":
            desk.enabled = False
        else:
            desk.revoked.add("practice-session")
        return result

    monkeypatch.setattr(ai_broker_context, "collect_configured_broker_context", brake_after_read)
    desk.llm.chat = lambda _messages: calls.append(True) or SimpleNamespace(content="BUY")
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert calls == []
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 0
    assert not any(e["kind"] in {"model_attempt_reserved", "model_unavailable"} for e in events)
    if brake == "revoke":
        # The existing read adapter notices revoked authority before decide.
        assert any(e["kind"] == "data_unavailable" and e["data"]["code"] == "practice_session_invalid" for e in events)
    else:
        assert any(e["kind"] == "safety_brake" and e["data"]["operation"] == "analysis" for e in events)
    assert desk.sandbox.get_orders() == []


def test_model_admission_rechecks_kill_between_symbols(desk):
    calls = []

    def chat(_messages):
        calls.append(True)
        desk.app.config["SAFETY"].l5_kill.activate("synthetic between-symbol brake")
        return SimpleNamespace(content="HOLD")

    desk.llm.chat = chat
    assert _start(desk, symbols=["RELIANCE", "TCS"]).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert calls == [True]
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 1
    assert any(e["kind"] == "safety_brake" and e["data"]["code"] == "practice_kill_switch_active" for e in events)
    assert not any(e["kind"] == "model_unavailable" for e in events)
    assert desk.sandbox.get_orders() == []


def test_reflection_skips_after_kill_without_consuming_a_model_attempt(desk):
    desk.signal = "BUY"
    desk.learning = SimpleNamespace(add=lambda *_args, **_kwargs: pytest.fail("Killed run must skip reflection"))
    assert _start(desk).status_code == 202
    _wait_for(lambda: _supervisor(desk).run.snapshot.get("cycle_count") == 1)
    assert desk.sandbox.get_positions()
    desk.app.config["SAFETY"].l5_kill.activate("synthetic reflection brake")
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 1
    assert any(e["kind"] == "session_learning_skipped" and e["data"]["reason"] == "practice_kill_switch_active" for e in events)
    assert desk.sandbox.get_positions() == []


def test_model_admission_rechecks_kill_after_durable_reservation(desk, monkeypatch):
    original = desk.store.append_event
    calls = []

    def latch_after_reservation(run_id, *, kind, data):
        result = original(run_id, kind=kind, data=data)
        if kind == "model_attempt_reserved":
            desk.app.config["SAFETY"].l5_kill.activate("synthetic reservation-boundary brake")
        return result

    monkeypatch.setattr(desk.store, "append_event", latch_after_reservation)
    desk.llm.chat = lambda _messages: calls.append(True) or SimpleNamespace(content="BUY")
    assert _start(desk).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    row = desk.store.list_runs()[0]
    events = desk.store.events(row["run_id"])
    assert calls == []
    assert row["snapshot"]["model_usage"]["model_calls_used"] == 1
    assert len([e for e in events if e["kind"] == "safety_brake"]) == 1
    assert not any(e["kind"] == "model_unavailable" for e in events)
    assert desk.sandbox.get_orders() == []


def test_unexpected_model_response_is_not_written_to_debug_logs(desk, caplog):
    import logging

    from flinttrade_ai import autonomous_agent

    sentinel = "PRIVATE_PROVIDER_TEXT_MUST_NOT_BE_LOGGED"
    desk.signal = sentinel
    caplog.set_level(logging.DEBUG, logger=autonomous_agent.logger.name)
    assert _start(desk, model_call_limit=1, cycle_interval_sec=1).status_code == 202
    _wait_for(lambda: _run_finished(desk))
    assert sentinel not in caplog.text
    assert desk.sandbox.get_orders() == []
