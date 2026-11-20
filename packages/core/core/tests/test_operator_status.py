"""Operator status document: one authenticated read of state that already has an owner.

The route projects those owners. It does not place an order, latch the kill
switch, start or stop a strategy, write the order ledger, or refresh a broker
token.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from flinttrade_engine.laya import DecisionStatus, process_laya, reset_process_laya_for_tests
from flinttrade_engine.local_state_provider import (
    DISPATCH_ACKNOWLEDGED,
    DISPATCH_CONFIRMED_APPLIED,
    DISPATCH_CONFIRMED_NOT_APPLIED,
    DISPATCH_CONFIRMED_PARTIAL,
    DISPATCH_FAILED_BEFORE_INVOKE,
    DISPATCH_INVOKED,
    DISPATCH_OUTCOME_UNKNOWN,
    DISPATCH_PREPARED,
    NON_TERMINAL_DISPATCH_STATES,
    OrderLifecycleLedger,
)
from flinttrade_engine.safety import KillSwitch, SafetySystem
from flinttrade_engine.scheduler import StrategyRunner, StrategyScheduler
from flinttrade_engine.strategy_runner import UserStrategyRunner
from flinttrade_gateway.models import AccountStatus

_IST = ZoneInfo("Asia/Kolkata")
_SECRET = "super-secret-token-do-not-leak"
_OTHER_ACCOUNT = "BOB-ACCOUNT-9f3c"


def _account(adapter_id: str, account_id: str, status: AccountStatus, *, error: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        adapter_id=adapter_id,
        account_id=account_id,
        status=status,
        error_message=error,
        label="vault-label-do-not-leak",
    )


def _selector(adapter_id: str, account_id: str) -> SimpleNamespace:
    return SimpleNamespace(adapter_id=adapter_id, account_id=account_id)


class _Registry:
    def __init__(self, accounts: list[Any], sessions: list[Any] | None = None, *, boom: str | None = None) -> None:
        self.accounts = accounts
        self.sessions = list(sessions or [])
        self.boom = boom

    def list_accounts(self) -> list[Any]:
        if self.boom == "accounts":
            raise RuntimeError(f"broker {_SECRET}")
        return self.accounts

    def list_read_smoke_sessions(self) -> list[Any]:
        if self.boom == "reads":
            raise RuntimeError(f"read {_SECRET}")
        return self.sessions


class _Router:
    def __init__(self, mapping: dict[str, tuple[str, ...]], *, boom: bool = False) -> None:
        self.mapping = mapping
        self.boom = boom

    def authorised_selectors(self, actor_id: str) -> tuple[str, ...]:
        if self.boom:
            raise RuntimeError(f"acl {_SECRET}")
        return self.mapping[actor_id]


class _Auth:
    def __init__(self, blocked: str | None = None, *, boom: bool = False) -> None:
        self.blocked = blocked
        self.boom = boom

    def migration_blocked(self) -> str | None:
        if self.boom:
            raise RuntimeError(f"migration {_SECRET}")
        return self.blocked

    def current_session_binding(self) -> None:
        return None

    def get_password_changed_at(self) -> float:
        return 0.0


class _Ledger:
    def __init__(self, rows: list[dict[str, Any]], *, boom: bool = False) -> None:
        self.rows = rows
        self.boom = boom
        self.writes = 0

    def list_dispatch_attempts(self) -> list[dict[str, Any]]:
        if self.boom:
            raise RuntimeError(f"ledger {_SECRET}")
        return self.rows

    def prepare_dispatch(self, *_args: Any, **_kwargs: Any) -> None:
        self.writes += 1
        raise AssertionError("dispatch write")


class _Strategies:
    def __init__(self, rows: list[dict[str, Any]] | None = None, *, boom: bool = False) -> None:
        self.rows = list(rows or [])
        self.boom = boom
        self.started: list[str] = []

    def list_strategies(self) -> list[dict[str, Any]]:
        if self.boom:
            raise RuntimeError(f"strategy {_SECRET}")
        return self.rows

    def start(self, strategy_id: str) -> None:
        self.started.append(strategy_id)
        raise AssertionError("strategy start")

    def stop(self, strategy_id: str) -> None:
        raise AssertionError("strategy stop")

    def stop_all(self) -> list[str]:
        raise AssertionError("strategy stop all")


class _Scheduler:
    def __init__(self, rows: dict[str, dict[str, Any]] | None = None, *, boom: bool = False) -> None:
        self.rows = dict(rows or {})
        self.boom = boom

    def status(self) -> dict[str, dict[str, Any]]:
        if self.boom:
            raise RuntimeError(f"runner {_SECRET}")
        return self.rows

    def start_all(self) -> None:
        raise AssertionError("runner start")

    def stop_all(self) -> None:
        raise AssertionError("runner stop")


def _attempt(adapter_id: str, account_id: str, state: str) -> dict[str, str]:
    return {"adapter_id": adapter_id, "account_id": account_id, "dispatch_state": state}


def _app(config: dict[str, Any]) -> Flask:
    from flinttrade_core.health_routes import health_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config.update(config)
    flask_app.register_blueprint(health_bp)
    return flask_app


def _token(username: str, *, mode: str = "practice", live_mode_unlocked: bool = False) -> str:
    from flinttrade_core.auth_routes import _create_token

    return _create_token(username, mode=mode, live_mode_unlocked=live_mode_unlocked)


def _headers(username: str = "alice", *, mode: str = "practice", live_mode_unlocked: bool = False) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(username, mode=mode, live_mode_unlocked=live_mode_unlocked)}"}


def _body(client: Any, headers: dict[str, str] | None = None, query: str = "") -> dict[str, Any]:
    response = client.get(f"/api/v1/operator/status{query}", headers=headers or _headers())
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.headers.get("Cache-Control") == "no-store"
    payload = response.get_json()
    assert payload is not None
    assert payload["status"] == "success"
    assert _SECRET not in response.get_data(as_text=True)
    return payload["data"]


def _base_config(**overrides: Any) -> dict[str, Any]:
    registry = _Registry(
        [
            _account("dhan", "ALICE1", AccountStatus.connected),
            _account("dhan", _OTHER_ACCOUNT, AccountStatus.connected, error=f"token {_SECRET}"),
        ],
        [
            (
                _selector("dhan", "ALICE1"),
                SimpleNamespace(access_token=_SECRET, extra={"read_smoke_ok": True}),
            )
        ],
    )
    config: dict[str, Any] = {
        "REGISTRY": registry,
        "BROKER_ROUTER": _Router({"alice": ("dhan:ALICE1",), "bob": (f"dhan:{_OTHER_ACCOUNT}",)}),
        "ORDER_LIFECYCLE_LEDGER": _Ledger(
            [
                _attempt("dhan", "ALICE1", DISPATCH_OUTCOME_UNKNOWN),
                _attempt("dhan", "ALICE1", DISPATCH_PREPARED),
                _attempt("dhan", "ALICE1", DISPATCH_INVOKED),
                _attempt("dhan", "ALICE1", DISPATCH_ACKNOWLEDGED),
                _attempt("dhan", "ALICE1", DISPATCH_CONFIRMED_APPLIED),
                _attempt("dhan", "ALICE1", DISPATCH_FAILED_BEFORE_INVOKE),
                _attempt("dhan", _OTHER_ACCOUNT, DISPATCH_OUTCOME_UNKNOWN),
            ]
        ),
        "SAFETY": SafetySystem(),
        "STRATEGY_RUNNER": _Strategies(
            [
                {
                    "strategy_id": "alpha",
                    "name": "Alpha",
                    "state": "unknown",
                    "reason": "tree_unreadable",
                    "ownership_retained": True,
                    "log_path": f"/tmp/{_SECRET}.log",
                    "pid": 4242,
                }
            ]
        ),
        "SCHEDULER": _Scheduler(
            {
                "wheel": {
                    "state": "PAUSED",
                    "process_state": "running",
                    "reason": "running",
                    "lifecycle": "PAUSED",
                    "ownership_retained": False,
                    "tick_count": 4,
                }
            }
        ),
        "AUTH_SERVICE": _Auth(),
    }
    config.update(overrides)
    return config


@pytest.fixture(autouse=True)
def _reset_laya() -> None:
    reset_process_laya_for_tests()
    yield
    reset_process_laya_for_tests()


def test_dispatch_non_terminal_states_are_the_ledger_set() -> None:
    """The count uses the ledger's own non-terminal set, not a second list."""
    assert NON_TERMINAL_DISPATCH_STATES == frozenset(
        {
            DISPATCH_PREPARED,
            DISPATCH_INVOKED,
            DISPATCH_ACKNOWLEDGED,
            DISPATCH_OUTCOME_UNKNOWN,
        }
    )
    for terminal in (
        DISPATCH_FAILED_BEFORE_INVOKE,
        DISPATCH_CONFIRMED_APPLIED,
        DISPATCH_CONFIRMED_NOT_APPLIED,
        DISPATCH_CONFIRMED_PARTIAL,
    ):
        assert terminal not in NON_TERMINAL_DISPATCH_STATES


class TestSectionReaders:
    """Each section calls its owner and fails closed when that owner cannot be read."""

    def test_dispatch_counts_only_the_authorised_selector(self) -> None:
        from flinttrade_core.operator_status import project_dispatch

        ledger = _Ledger(
            [
                _attempt("dhan", "ALICE1", DISPATCH_OUTCOME_UNKNOWN),
                _attempt("dhan", "ALICE1", DISPATCH_PREPARED),
                _attempt("dhan", "ALICE1", DISPATCH_CONFIRMED_APPLIED),
                _attempt("dhan", _OTHER_ACCOUNT, DISPATCH_OUTCOME_UNKNOWN),
                _attempt("dhan", _OTHER_ACCOUNT, DISPATCH_INVOKED),
            ]
        )
        projected = project_dispatch(ledger, {"dhan:ALICE1"})
        assert projected == {"status": "ok", "outcome_unknown": 1, "non_terminal": 2}
        assert ledger.writes == 0

    def test_dispatch_follows_the_ledger_constant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from flinttrade_core.operator_status import project_dispatch

        monkeypatch.setattr(
            "flinttrade_engine.local_state_provider.NON_TERMINAL_DISPATCH_STATES",
            frozenset(),
        )
        projected = project_dispatch(
            _Ledger([_attempt("dhan", "ALICE1", DISPATCH_PREPARED)]),
            {"dhan:ALICE1"},
        )
        assert projected["non_terminal"] == 0
        assert projected["outcome_unknown"] == 0

    def test_dispatch_unknown_when_the_ledger_cannot_be_read(self) -> None:
        from flinttrade_core.operator_status import project_dispatch

        assert project_dispatch(None, {"dhan:ALICE1"}) == {"status": "unknown", "reason": "unavailable"}
        assert project_dispatch(_Ledger([], boom=True), {"dhan:ALICE1"}) == {
            "status": "unknown",
            "reason": "unavailable",
        }
        assert "outcome_unknown" not in project_dispatch(None, {"dhan:ALICE1"})

    def test_dispatch_unscoped_does_not_count_anyone(self) -> None:
        from flinttrade_core.operator_status import project_dispatch

        projected = project_dispatch(_Ledger([_attempt("dhan", "ALICE1", DISPATCH_OUTCOME_UNKNOWN)]), "unscoped")
        assert projected == {"status": "unknown", "reason": "unscoped"}
        assert "outcome_unknown" not in projected

    def test_broker_status_is_the_account_status_for_authorised_selectors_only(self) -> None:
        from flinttrade_core.operator_status import project_broker

        registry = _Registry(
            [
                _account("dhan", "ALICE1", AccountStatus.connected),
                _account("dhan", _OTHER_ACCOUNT, AccountStatus.error, error=_SECRET),
                _account("kotakneo", "ALICE2", AccountStatus.token_expired),
            ]
        )
        projected = project_broker(registry, {"dhan:ALICE1", "kotakneo:ALICE2"})
        assert projected == {
            "status": "ok",
            "accounts": [
                {"selector": "dhan:ALICE1", "status": "connected"},
                {"selector": "kotakneo:ALICE2", "status": "token_expired"},
            ],
        }
        assert _OTHER_ACCOUNT not in str(projected)
        assert _SECRET not in str(projected)

    def test_broker_unknown_when_the_registry_cannot_be_read(self) -> None:
        from flinttrade_core.operator_status import project_broker

        assert project_broker(None, {"dhan:ALICE1"})["reason"] == "unavailable"
        assert project_broker(_Registry([], boom="accounts"), {"dhan:ALICE1"}) == {
            "status": "unknown",
            "reason": "unavailable",
        }
        assert "accounts" not in project_broker(None, set())

    def test_connected_read_uses_the_read_smoke_list(self) -> None:
        from flinttrade_core.operator_status import project_connected_read

        registry = _Registry(
            [],
            [(_selector("dhan", "ALICE1"), SimpleNamespace(access_token=_SECRET))],
        )
        assert project_connected_read(registry, {"dhan:ALICE1"}) == {"status": "ok", "value": True}
        assert project_connected_read(registry, {"dhan:OTHER"}) == {"status": "ok", "value": False}
        assert project_connected_read(registry, "unscoped") == {"status": "unknown", "reason": "unscoped"}
        assert project_connected_read(None, {"dhan:ALICE1"}) == {"status": "unknown", "reason": "unavailable"}
        unreadable = project_connected_read(_Registry([], boom="reads"), {"dhan:ALICE1"})
        assert unreadable == {"status": "unknown", "reason": "unavailable"}
        assert unreadable.get("value") is not True

    def test_kill_switch_reads_the_latch_and_does_not_invent_inactive(self) -> None:
        from flinttrade_core.operator_status import project_kill_switch

        safety = SafetySystem()
        safety.l5_kill._active = True
        safety.l5_kill._reason = "operator halt"
        assert project_kill_switch(safety) == {"status": "ok", "active": True, "reason": "operator halt"}
        assert project_kill_switch(None) == {"status": "unknown", "reason": "unavailable"}
        assert "active" not in project_kill_switch(None)

        class _Boom:
            @property
            def is_active(self) -> bool:
                raise RuntimeError(_SECRET)

            @property
            def reason(self) -> str:
                raise RuntimeError(_SECRET)

        assert project_kill_switch(SimpleNamespace(l5_kill=_Boom())) == {
            "status": "unknown",
            "reason": "unavailable",
        }

    def test_strategy_rows_keep_unknown_and_drop_paths(self) -> None:
        from flinttrade_core.operator_status import project_strategy

        uploaded = _Strategies(
            [
                {
                    "strategy_id": "alpha",
                    "state": "unknown",
                    "reason": "tree_unreadable",
                    "ownership_retained": True,
                    "log_path": f"/tmp/{_SECRET}.log",
                }
            ]
        )
        scheduler = _Scheduler(
            {
                "wheel": {
                    "process_state": "running",
                    "reason": "running",
                    "lifecycle": "PAUSED",
                }
            }
        )
        projected = project_strategy(uploaded, scheduler)
        assert projected == {
            "status": "ok",
            "rows": [
                {
                    "kind": "uploaded",
                    "id": "alpha",
                    "status": "unknown",
                    "reason": "tree_unreadable",
                    "lifecycle": None,
                    "ownership_retained": True,
                },
                {
                    "kind": "runner",
                    "id": "wheel",
                    "status": "running",
                    "reason": "running",
                    "lifecycle": "PAUSED",
                    "ownership_retained": False,
                },
            ],
        }
        assert _SECRET not in str(projected)
        assert project_strategy(None, None) == {"status": "unknown", "reason": "unavailable"}
        assert "rows" not in project_strategy(None, None)
        assert project_strategy(_Strategies(boom=True), scheduler)["status"] == "unknown"

    def test_migration_blocked_is_the_account_service_value(self) -> None:
        from flinttrade_core.operator_status import project_migration

        assert project_migration(_Auth(None)) == {"status": "ok", "value": None}
        assert project_migration(_Auth("two_operators")) == {"status": "ok", "value": "two_operators"}
        assert project_migration(_Auth("raw database error")) == {"status": "unknown", "reason": "unavailable"}
        assert project_migration(None) == {"status": "unknown", "reason": "unavailable"}
        assert project_migration(_Auth(boom=True))["status"] == "unknown"
        assert "value" not in project_migration(None)

    def test_session_projects_admit_session(self) -> None:
        from flinttrade_core.operator_status import project_session

        weekday = datetime(2026, 11, 10, 10, 0, tzinfo=_IST)
        opened = project_session("NSE", None, weekday)
        assert opened["status"] == "ok"
        assert opened["exchange"] == "NSE"
        assert opened["phase"] == "continuous"
        assert opened["order_entry"] == "open"
        assert opened["reason"] == "within_hours"
        assert opened["order_close"].endswith("15:30:00+05:30")

        weekend = project_session("nse", None, datetime(2026, 11, 14, 10, 0, tzinfo=_IST))
        assert weekend["order_entry"] == "closed"
        assert weekend["reason"] == "weekend"
        assert weekend["phase"] == "closed"

    def test_session_unknown_when_the_decision_cannot_be_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from flinttrade_core.operator_status import project_session

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(f"calendar {_SECRET}")

        monkeypatch.setattr("flinttrade_engine.market_hours.admit_session", _boom)
        projected = project_session("NSE", None, datetime(2026, 11, 10, 10, 0, tzinfo=_IST))
        assert projected == {"status": "unknown", "reason": "unavailable"}
        assert _SECRET not in str(projected)

    def test_laya_projects_the_decision_model(self) -> None:
        from flinttrade_core.operator_status import project_laya

        process_laya().set_status(DecisionStatus.READY)
        ready = project_laya()
        assert ready == {"status": "ready", "reason_code": None, "live_qualified": True}
        process_laya().apply_runtime_status(DecisionStatus.DEGRADED, live_qualified=False)
        process_laya().set_runtime_reason("still_loading", 8000)
        # Ready and Degraded clear a reason. Down keeps the code the probe recorded.
        process_laya().apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        process_laya().set_runtime_reason("still_loading", 8000)
        down = project_laya()
        assert down == {"status": "down", "reason_code": "still_loading", "live_qualified": False}

    def test_laya_unknown_is_not_ready_or_down(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from flinttrade_core.operator_status import project_laya

        def _boom() -> None:
            raise RuntimeError(f"laya {_SECRET}")

        monkeypatch.setattr("flinttrade_engine.laya.process_laya", _boom)
        projected = project_laya()
        assert projected == {"status": "unknown", "reason_code": "unavailable", "live_qualified": None}
        assert projected["status"] != "ready"
        assert projected["live_qualified"] is not True


class TestOperatorStatusRoute:
    """The HTTP document is a pure read with the same session boundary as other status routes."""

    def test_route_is_not_public(self) -> None:
        from flinttrade_core.public_routes import is_public_route

        assert is_public_route("GET", "/api/v1/operator/status") is False
        assert is_public_route("HEAD", "/api/v1/operator/status") is False

    def test_document_projects_each_owner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "flinttrade_core.operator_status._now",
            lambda: datetime(2026, 11, 10, 10, 0, tzinfo=_IST),
        )
        process_laya().set_status(DecisionStatus.READY)
        safety = SafetySystem()
        safety.l5_kill._active = False
        safety.l5_kill._reason = ""
        client = _app(_base_config(SAFETY=safety, AUTH_SERVICE=_Auth("two_operators"))).test_client()
        data = _body(client, _headers(mode="practice"), "?exchange=nse")
        assert data["mode"] == {"status": "ok", "value": "practice"}
        assert data["live_unlocked"] == {"status": "ok", "value": False}
        assert data["connected_read"] == {"status": "ok", "value": True}
        assert data["laya"] == {"status": "ready", "reason_code": None, "live_qualified": True}
        assert data["kill_switch"] == {"status": "ok", "active": False, "reason": ""}
        assert data["session"]["reason"] == "within_hours"
        assert data["session"]["order_entry"] == "open"
        assert data["broker"]["accounts"] == [{"selector": "dhan:ALICE1", "status": "connected"}]
        assert data["dispatch"] == {"status": "ok", "outcome_unknown": 1, "non_terminal": 4}
        assert data["strategy"]["rows"][0]["status"] == "unknown"
        assert data["strategy"]["rows"][0]["ownership_retained"] is True
        assert data["strategy"]["rows"][1]["lifecycle"] == "PAUSED"
        assert data["migration_blocked"] == {"status": "ok", "value": "two_operators"}
        assert _OTHER_ACCOUNT not in str(data)

    def test_mode_header_does_not_override_the_session_claim(self) -> None:
        client = _app(_base_config()).test_client()
        headers = _headers(mode="practice")
        headers["X-FlintTrade-Mode"] = "live"
        data = _body(client, headers)
        assert data["mode"]["value"] == "practice"
        assert data["live_unlocked"]["value"] is False

    def test_connected_read_is_not_a_mode(self) -> None:
        client = _app(_base_config()).test_client()
        data = _body(client, _headers(mode="Connected (read)"))
        assert data["mode"] == {"status": "unknown", "reason": "unavailable"}
        assert data["mode"].get("value") != "live"
        assert data["connected_read"]["value"] is True

    def test_live_unlock_comes_from_the_session_claim(self) -> None:
        client = _app(_base_config()).test_client()
        data = _body(client, _headers(mode="live", live_mode_unlocked=True))
        assert data["mode"]["value"] == "live"
        assert data["live_unlocked"]["value"] is True

    def test_other_operator_accounts_are_absent(self) -> None:
        client = _app(_base_config()).test_client()
        alice = _body(client, _headers("alice"))
        bob = _body(client, _headers("bob"))
        assert alice["broker"]["accounts"] == [{"selector": "dhan:ALICE1", "status": "connected"}]
        assert bob["broker"]["accounts"] == [{"selector": f"dhan:{_OTHER_ACCOUNT}", "status": "connected"}]
        assert _OTHER_ACCOUNT not in str(alice)
        assert "ALICE1" not in str(bob)
        assert alice["dispatch"]["outcome_unknown"] == 1
        assert bob["dispatch"]["outcome_unknown"] == 1
        assert bob["connected_read"]["value"] is False

    def test_unreadable_section_keeps_the_others(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom() -> None:
            raise RuntimeError(f"laya {_SECRET}")

        monkeypatch.setattr("flinttrade_engine.laya.process_laya", _boom)
        client = _app(
            _base_config(
                REGISTRY=_Registry([], boom="accounts"),
                ORDER_LIFECYCLE_LEDGER=_Ledger([], boom=True),
                STRATEGY_RUNNER=_Strategies(boom=True),
                SCHEDULER=_Scheduler(boom=True),
                AUTH_SERVICE=_Auth(boom=True),
                SAFETY=SimpleNamespace(l5_kill=SimpleNamespace()),
            )
        ).test_client()
        # A kill switch without the latch properties is unreadable. The mode
        # claim is still the session.
        response = client.get("/api/v1/operator/status", headers=_headers())
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert _SECRET not in text
        assert "RuntimeError" not in text
        assert "Traceback" not in text
        data = response.get_json()["data"]
        assert data["mode"]["value"] == "practice"
        assert data["laya"] == {"status": "unknown", "reason_code": "unavailable", "live_qualified": None}
        assert data["broker"] == {"status": "unknown", "reason": "unavailable"}
        assert data["dispatch"] == {"status": "unknown", "reason": "unavailable"}
        assert data["strategy"] == {"status": "unknown", "reason": "unavailable"}
        assert data["migration_blocked"] == {"status": "unknown", "reason": "unavailable"}
        assert data["kill_switch"]["status"] == "unknown"
        assert data["kill_switch"].get("active") is not False

    def test_invalid_exchange_is_unknown_and_is_not_echoed(self) -> None:
        client = _app(_base_config()).test_client()
        response = client.get(
            "/api/v1/operator/status",
            query_string={"exchange": f"NSE {_SECRET}"},
            headers=_headers(),
        )
        text = response.get_data(as_text=True)
        assert response.status_code == 200
        assert _SECRET not in text
        assert response.get_json()["data"]["session"] == {"status": "unknown", "reason": "unavailable"}

    def test_post_is_not_a_status_write(self) -> None:
        client = _app(_base_config()).test_client()
        response = client.post("/api/v1/operator/status", headers=_headers(), json={})
        assert response.status_code == 405

    def test_no_session_is_unscoped_not_another_operators_book(self) -> None:
        client = _app(_base_config()).test_client()
        response = client.get("/api/v1/operator/status")
        # This app has no global session check. The handler still withholds
        # account-scoped sections when the request has no session identity.
        assert response.status_code == 200
        data = response.get_json()["data"]
        assert data["broker"] == {"status": "unknown", "reason": "unscoped"}
        assert data["dispatch"] == {"status": "unknown", "reason": "unscoped"}
        assert data["connected_read"] == {"status": "unknown", "reason": "unscoped"}
        assert _OTHER_ACCOUNT not in response.get_data(as_text=True)
        assert "ALICE1" not in response.get_data(as_text=True)

    def test_read_does_not_call_mutating_entry_points(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        calls: list[str] = []

        def _forbid(name: str) -> Any:
            def _wrapped(*_args: Any, **_kwargs: Any) -> None:
                calls.append(name)
                raise AssertionError(name)

            return _wrapped

        monkeypatch.setattr(KillSwitch, "activate", _forbid("kill-switch"))
        monkeypatch.setattr(KillSwitch, "reset", _forbid("kill-switch-reset"))
        monkeypatch.setattr(KillSwitch, "broker_write_admission", _forbid("kill-switch-admission"))
        monkeypatch.setattr("flinttrade_engine.laya.Laya.admit", _forbid("admit"))
        monkeypatch.setattr("flinttrade_engine.laya.Laya.admit_reduce_only", _forbid("admit-reduce"))
        monkeypatch.setattr(UserStrategyRunner, "start", _forbid("strategy-start"))
        monkeypatch.setattr(UserStrategyRunner, "stop", _forbid("strategy-stop"))
        monkeypatch.setattr(UserStrategyRunner, "stop_all", _forbid("strategy-stop-all"))
        monkeypatch.setattr(StrategyRunner, "start", _forbid("runner-start"))
        monkeypatch.setattr(StrategyRunner, "stop", _forbid("runner-stop"))
        monkeypatch.setattr(OrderLifecycleLedger, "prepare_dispatch", _forbid("ledger-prepare"))
        monkeypatch.setattr(OrderLifecycleLedger, "mark_invoked", _forbid("ledger-invoke"))
        monkeypatch.setattr(OrderLifecycleLedger, "acknowledge", _forbid("ledger-ack"))
        monkeypatch.setattr(OrderLifecycleLedger, "mark_outcome_unknown", _forbid("ledger-unknown"))
        monkeypatch.setattr(OrderLifecycleLedger, "mark_failed_before_invoke", _forbid("ledger-failed"))
        monkeypatch.setattr(OrderLifecycleLedger, "prepare_outcome_resolution", _forbid("ledger-resolve"))
        monkeypatch.setattr("flinttrade_engine.safety.gate_order", _forbid("gate-order"))
        monkeypatch.setattr("flinttrade_engine.safety.gate_broker_write", _forbid("gate-write"))
        monkeypatch.setattr(
            "flinttrade_gateway.connected_read_smoke.run_connected_read_smoke",
            _forbid("read-smoke"),
        )
        monkeypatch.setattr(
            "flinttrade_core.laya_runtime.refresh_process_laya_status",
            _forbid("laya-refresh"),
        )

        ledger = OrderLifecycleLedger(ledger_path=tmp_path / "orders.sqlite")
        before = _ledger_dump(ledger)
        rotator = SimpleNamespace(refresh_token=_forbid("refresh-token"))
        runner = UserStrategyRunner(tmp_path / "strategies")
        scheduler = StrategyScheduler()
        client = _app(
            _base_config(
                ORDER_LIFECYCLE_LEDGER=ledger,
                STRATEGY_RUNNER=runner,
                SCHEDULER=scheduler,
                CREDENTIALS_ROTATOR=rotator,
            )
        ).test_client()
        data = _body(client)
        after = _ledger_dump(ledger)
        assert after == before
        assert calls == []
        assert data["strategy"]["rows"] == []
        assert data["dispatch"] == {"status": "ok", "outcome_unknown": 0, "non_terminal": 0}
        assert rotator.refresh_token is not None


def _ledger_dump(ledger: OrderLifecycleLedger) -> list[tuple[Any, ...]]:
    path = ledger._path()
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        dumped: list[tuple[Any, ...]] = [("tables", tuple(tables))]
        for name in tables:
            rows = connection.execute(f"SELECT * FROM {name}").fetchall()  # noqa: S608 - test snapshot of known tables
            dumped.append((name, tuple(tuple(row) for row in rows)))
        dumped.append(("user_version", connection.execute("PRAGMA user_version").fetchone()[0]))
        return dumped
    finally:
        connection.close()


def test_full_app_requires_a_credential_and_withholds_accounts_from_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Global session auth applies. An API key is not an operator identity."""
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["REGISTRY"] = _Registry([_account("dhan", _OTHER_ACCOUNT, AccountStatus.connected, error=_SECRET)])
    app.config["ORDER_LIFECYCLE_LEDGER"] = _Ledger([_attempt("dhan", _OTHER_ACCOUNT, DISPATCH_OUTCOME_UNKNOWN)])
    client = app.test_client()
    missing = client.get("/api/v1/operator/status")
    assert missing.status_code == 401
    assert _OTHER_ACCOUNT not in missing.get_data(as_text=True)

    monkeypatch.setenv("FLINTTRADE_API_KEY", "operator-status-test-key")
    keyed = client.get("/api/v1/operator/status", headers={"X-API-Key": "operator-status-test-key"})
    assert keyed.status_code == 200
    text = keyed.get_data(as_text=True)
    assert _OTHER_ACCOUNT not in text
    assert _SECRET not in text
    data = keyed.get_json()["data"]
    assert data["broker"]["reason"] == "unscoped"
    assert data["dispatch"]["reason"] == "unscoped"
    assert "outcome_unknown" not in data["dispatch"]
