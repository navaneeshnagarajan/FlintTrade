"""Tests for the in-process Ditto daily-driver runtime."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_ditto.account_manager import BrokerAccount
from flinttrade_ditto.runtime import DittoCapabilityUnavailable, DittoRuntime
from flinttrade_engine.safety import (
    EmergencyDispatchResult,
    EmergencyVerbOutcome,
    EmergencyWritePolicy,
    set_safety_gate_secret,
)


@pytest.fixture(autouse=True)
def _bind_safety_gate_secret() -> None:
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")


def _account(
    account_id: str,
    *,
    enabled: bool = True,
    is_master: bool = False,
    weight: float = 1.0,
    max_loss_daily: float = 100.0,
) -> BrokerAccount:
    return BrokerAccount(
        account_id=account_id,
        adapter_id="dhan",

        name=account_id.title(),
        enabled=enabled,
        is_master=is_master,
        allocation_weight=weight,
        max_loss_daily=max_loss_daily,
    )


class _FakeWatcher:
    def __init__(
        self,
        account: BrokerAccount,
        *,
        prime_error: Exception | None = None,
        stop_results: list[bool] | None = None,
    ) -> None:
        self.account = account
        self.prime_error = prime_error
        self.stop_results = list(stop_results or [])
        self.callbacks: list[Any] = []
        self.error_callbacks: list[Any] = []
        self.is_running = False
        self.prime_called = False
        self.stop_calls = 0

    def on_change(self, callback: Any) -> None:
        self.callbacks.append(callback)

    def on_error(self, callback: Any) -> None:
        self.error_callbacks.append(callback)

    def prime(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        self.prime_called = True
        if self.prime_error is not None:
            raise self.prime_error
        return {
            ("NSE", "RELIANCE", "MIS"): {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 0,
            }
        }

    def start(self) -> None:
        self.is_running = True

    def stop(self, *, timeout: float = 5.0) -> bool:
        del timeout
        self.stop_calls += 1
        stopped = self.stop_results.pop(0) if self.stop_results else True
        if stopped:
            self.is_running = False
        return stopped

    def emit(self, position: dict[str, Any]) -> None:
        for callback in self.callbacks:
            callback(self.account.account_id, position)

    def emit_error(self) -> None:
        for callback in self.error_callbacks:
            callback(self.account.account_id)


class _CompositeWatcher(_FakeWatcher):
    def prime(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        self.prime_called = True
        if self.prime_error is not None:
            raise self.prime_error
        return {
            ("NSE", "RELIANCE", "MIS"): {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 2,
            }
        }


class _ErrorAwareWatcher(_CompositeWatcher):
    pass


class _FakeRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.contexts: list[Any] = []

    async def place_order(
        self,
        request_ctx: Any,
        *,
        order: Any,
        safety_ctx: Any,
        adapter_id: str,
        account_id: str,
    ) -> str:
        self.contexts.append(request_ctx)
        self.calls.append((adapter_id, account_id, int(order.quantity)))
        return f"order-{account_id}"


class _FakeRouterOwner:
    def __init__(
        self,
        accounts: list[BrokerAccount],
        actor_id: str,
        *,
        risk_by_account: dict[str, dict[str, Any] | Exception] | None = None,
        failed_kill_accounts: set[str] | None = None,
        admission_error_accounts: set[str] | None = None,
        close_results: list[bool | Exception] | None = None,
        backend_lease_proof=None,
    ) -> None:
        self.accounts = accounts
        self.actor_id = actor_id
        self.router = _FakeRouter()
        self.router.backend_lease_proof = backend_lease_proof
        self.closed = False
        self.risk_by_account = risk_by_account or {}
        self.failed_kill_accounts = failed_kill_accounts or set()
        self.admission_error_accounts = admission_error_accounts or set()
        self.close_results = list(close_results or [])
        self.admission_calls: list[tuple[str, int]] = []
        self.kill_call: tuple[str, str, str] | None = None
        self.close_calls = 0

    @contextmanager
    def admit_order(self, account_id: str, order: Any):
        self.admission_calls.append((account_id, int(order.quantity)))
        if account_id in self.admission_error_accounts:
            raise DittoCapabilityUnavailable("mirror order safety admission failed")
        lease = SimpleNamespace(
            reserve=lambda _candidate, _positions: object(),
            acknowledge=lambda _reservation, _result: None,
        )
        yield lease, []

    def run_router_call(self, account_id: str, awaitable: Any) -> Any:
        assert account_id in {account.account_id for account in self.accounts}
        return asyncio.run(awaitable)

    def risk_state(self, account: BrokerAccount) -> dict[str, Any]:
        default = {
            "available_balance": 1000.0,
            "used_margin": 0.0,
            "total_balance": 1000.0,
            "pnl_today": 0.0,
            "positions": 0,
        }
        value = self.risk_by_account.get(account.account_id, default)
        if isinstance(value, Exception):
            raise value
        return {**default, **value}

    def dispatch_kill_all(
        self,
        *,
        actor_id: str,
        jti: str,
        reason: str,
    ) -> EmergencyDispatchResult:
        self.kill_call = (actor_id, jti, reason)
        policy = EmergencyWritePolicy(
            name="ditto_kill_all",
            verbs=("cancel_all_orders", "exit_all_positions"),
        )
        outcomes = []
        for account in self.accounts:
            selector = f"dhan:{account.account_id}"
            failed = account.account_id in self.failed_kill_accounts
            outcomes.extend(
                EmergencyVerbOutcome(
                    verb=verb,
                    succeeded=not failed,
                    failure_code="broker_refused" if failed else "",
                    selector=selector,
                )
                for verb in policy.verbs
            )
        return EmergencyDispatchResult(policy=policy, outcomes=tuple(outcomes))

    def close(self, *, timeout: float = 5.0) -> bool:
        del timeout
        self.close_calls += 1
        outcome = self.close_results.pop(0) if self.close_results else True
        if isinstance(outcome, Exception):
            raise outcome
        closed = outcome
        if closed:
            self.closed = True
        return closed


def test_start_controls_real_position_mirror_and_reports_active(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("one"), _account("two")]
    watchers: list[_FakeWatcher] = []
    owners: list[_FakeRouterOwner] = []

    def watcher_factory(account: BrokerAccount) -> _FakeWatcher:
        watcher = _FakeWatcher(account)
        watchers.append(watcher)
        return watcher

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=watcher_factory,
        router_owner_factory=owner_factory,
    )

    started = runtime.start(
        source_account="master",
        target_accounts=["one", "two"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    assert started["active"] is True
    assert started["lifecycle"] == "active"
    assert started["mode"] == "equal"
    assert watchers[0].prime_called is True
    assert watchers[0].is_running is True

    watchers[0].emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 2,
        }
    )

    assert sorted(owners[0].router.calls) == [
        ("dhan", "one", 2),
        ("dhan", "two", 2),
    ]
    assert sorted(owners[0].admission_calls) == [("one", 2), ("two", 2)]
    assert all(context.actor_type == "human" for context in owners[0].router.contexts)
    assert runtime.status()["mirrored_positions"] == 2

    stopped = runtime.stop()
    assert stopped["active"] is False
    assert stopped["lifecycle"] == "idle"
    assert owners[0].closed is True


@pytest.mark.parametrize(
    ("alias", "api_mode"),
    [
        ("equal", "equal"),
        ("fixed", "equal"),
        ("weighted", "weighted"),
        ("proportional", "weighted"),
    ],
)
def test_runtime_accepts_lowercase_mode_aliases_and_returns_stable_api_value(
    alias: str,
    api_mode: str,
) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=_FakeWatcher,
        router_owner_factory=_FakeRouterOwner,
    )

    status = runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode=alias,
        actor_id="operator-1",
        jti="jwt-1",
    )

    assert status["mode"] == api_mode
    runtime.stop()


@pytest.mark.parametrize(
    "risk_value",
    [
        {"pnl_today": -100.0},
        {"pnl_today": float("nan")},
        RuntimeError("private target risk response"),
    ],
)
def test_target_risk_failure_pauses_delta_before_any_dispatch(
    risk_value: dict[str, Any] | Exception, *, backend_lease_factory
) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _FakeWatcher(accounts[0])
    owner = _FakeRouterOwner(
        accounts[1:],
        "operator-1",
        risk_by_account={"target": risk_value}, backend_lease_proof=backend_lease_factory()
    )
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="equal",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 2,
        }
    )

    status = runtime.status()
    assert owner.admission_calls == []
    assert owner.router.calls == []
    assert status["active"] is False
    assert status["lifecycle"] == "reconciliation-needed"
    assert any("risk" in error.lower() for error in status["errors"])
    runtime.stop()


def test_zero_daily_loss_cap_still_requires_risk_but_does_not_limit_loss(*, backend_lease_factory) -> None:
    accounts = [
        _account("master", is_master=True),
        _account("target", max_loss_daily=0.0),
    ]
    watcher = _FakeWatcher(accounts[0])
    owner = _FakeRouterOwner(
        accounts[1:],
        "operator-1",
        risk_by_account={"target": {"pnl_today": -1_000_000.0}}, backend_lease_proof=backend_lease_factory()
    )
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="equal",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 2,
        }
    )

    assert owner.router.calls == [("dhan", "target", 2)]
    assert runtime.status()["active"] is True
    runtime.stop()


def test_runtime_tracks_same_symbol_products_as_independent_legs(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _CompositeWatcher(accounts[0])
    owner = _FakeRouterOwner(accounts[1:], "operator-1", backend_lease_proof=backend_lease_factory())
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 2,
        }
    )

    assert owner.router.calls == [("dhan", "target", 2)]
    assert runtime._source_quantities == {
        ("NSE", "RELIANCE", "MIS"): 2,
        ("NSE", "RELIANCE", "CNC"): 2,
    }
    runtime.stop()


def test_source_poll_failure_pauses_generation_and_blocks_later_dispatch(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _ErrorAwareWatcher(accounts[0])
    owner = _FakeRouterOwner(accounts[1:], "operator-1", backend_lease_proof=backend_lease_factory())
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watcher.emit_error()
    paused = runtime.status()

    assert paused["active"] is False
    assert paused["lifecycle"] == "reconciliation-needed"
    assert len(paused["errors"]) == 1
    assert "source position state" in paused["errors"][0].lower()
    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 4,
        }
    )
    assert owner.router.calls == []
    stopped = runtime.stop()
    assert stopped["active"] is False
    assert stopped["lifecycle"] == "reconciliation-needed"
    assert owner.closed is True


def test_status_exposes_starting_lifecycle_before_owner_is_ready(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    factory_entered = threading.Event()
    release_factory = threading.Event()
    outcome: list[dict[str, Any] | Exception] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        factory_entered.set()
        assert release_factory.wait(timeout=2.0)
        return _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=_FakeWatcher,
        router_owner_factory=owner_factory,
    )

    def invoke_start() -> None:
        try:
            outcome.append(
                runtime.start(
                    source_account="master",
                    target_accounts=["target"],
                    mode="EQUAL",
                    actor_id="operator-1",
                    jti="jwt-1",
                )
            )
        except Exception as exc:  # noqa: BLE001 - asserted below
            outcome.append(exc)

    thread = threading.Thread(target=invoke_start, daemon=True)
    thread.start()
    assert factory_entered.wait(timeout=1.0)

    starting = runtime.status()
    assert starting["lifecycle"] == "starting"
    assert starting["active"] is False
    assert starting["source_account"] == "master"
    assert starting["target_accounts"] == ["target"]

    release_factory.set()
    thread.join(timeout=2.0)
    try:
        assert len(outcome) == 1
        assert isinstance(outcome[0], dict)
        assert runtime.status()["lifecycle"] == "active"
    finally:
        runtime.stop()


def test_start_rejects_master_target_without_creating_router_owner(*, backend_lease_factory) -> None:
    accounts = [
        _account("source", is_master=True),
        _account("other-master", is_master=True),
    ]
    owner_calls: list[list[BrokerAccount]] = []

    def owner_factory(selected: list[BrokerAccount], _actor_id: str) -> _FakeRouterOwner:
        owner_calls.append(selected)
        return _FakeRouterOwner(selected, "operator-1", backend_lease_proof=backend_lease_factory())

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=_FakeWatcher,
        router_owner_factory=owner_factory,
    )

    with pytest.raises(DittoCapabilityUnavailable, match="target"):
        runtime.start(
            source_account="source",
            target_accounts=["other-master"],
            mode="EQUAL",
            actor_id="operator-1",
            jti="jwt-1",
        )

    assert owner_calls == []
    assert runtime.status()["lifecycle"] == "idle"


def test_start_rejects_any_master_target_before_using_valid_targets() -> None:
    accounts = [
        _account("source", is_master=True),
        _account("valid-target"),
        _account("other-master", is_master=True),
    ]
    owner_calls: list[list[BrokerAccount]] = []
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=_FakeWatcher,
        router_owner_factory=lambda selected, _actor_id: owner_calls.append(selected),
    )

    with pytest.raises(DittoCapabilityUnavailable, match="target"):
        runtime.start(
            source_account="source",
            target_accounts=["valid-target", "other-master"],
            mode="EQUAL",
            actor_id="operator-1",
            jti="jwt-1",
        )

    assert owner_calls == []
    assert runtime.status()["lifecycle"] == "idle"


def test_simultaneous_starts_create_only_one_runtime_generation(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    owner_factory_entered = threading.Event()
    release_first_factory = threading.Event()
    factory_lock = threading.Lock()
    owners: list[_FakeRouterOwner] = []
    outcomes: list[dict[str, Any] | Exception] = []
    factory_calls = 0

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        nonlocal factory_calls
        with factory_lock:
            factory_calls += 1
            call_number = factory_calls
        if call_number == 1:
            owner_factory_entered.set()
            assert release_first_factory.wait(timeout=2.0)
        owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=_FakeWatcher,
        router_owner_factory=owner_factory,
    )

    def invoke_start(jti: str) -> None:
        try:
            outcomes.append(
                runtime.start(
                    source_account="master",
                    target_accounts=["target"],
                    mode="EQUAL",
                    actor_id="operator-1",
                    jti=jti,
                )
            )
        except Exception as exc:  # noqa: BLE001 - outcome is asserted below
            outcomes.append(exc)

    first = threading.Thread(target=invoke_start, args=("jwt-1",), daemon=True)
    second = threading.Thread(target=invoke_start, args=("jwt-2",), daemon=True)
    first.start()
    assert owner_factory_entered.wait(timeout=1.0)
    second.start()
    second.join(timeout=1.0)
    release_first_factory.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    try:
        assert not first.is_alive()
        assert not second.is_alive()
        assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
        failures = [outcome for outcome in outcomes if isinstance(outcome, Exception)]
        assert len(failures) == 1
        assert isinstance(failures[0], DittoCapabilityUnavailable)
        assert "already active" in str(failures[0])
        assert factory_calls == 1
        assert len(owners) == 1
    finally:
        try:
            runtime.stop()
        except DittoCapabilityUnavailable:
            pass
        for owner in owners:
            owner.close()


def test_partial_dispatch_failure_pauses_before_source_reversal(*, backend_lease_factory) -> None:
    rejected_id = "target-private-4821"
    accounts = [_account("master", is_master=True), _account("one"), _account(rejected_id)]
    watchers: list[_FakeWatcher] = []
    owners: list[_FakeRouterOwner] = []

    def watcher_factory(account: BrokerAccount) -> _FakeWatcher:
        watcher = _FakeWatcher(account)
        watchers.append(watcher)
        return watcher

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(
            selected,
            actor_id,
            admission_error_accounts={rejected_id}, backend_lease_proof=backend_lease_factory()
        )
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=watcher_factory,
        router_owner_factory=owner_factory,
    )
    runtime.start(
        source_account="master",
        target_accounts=["one", rejected_id],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watchers[0].emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 2,
        }
    )

    assert sorted(owners[0].admission_calls) == [("one", 2), (rejected_id, 2)]
    assert owners[0].router.calls == [("dhan", "one", 2)]
    paused = runtime.status()
    assert paused["active"] is False
    assert paused["lifecycle"] == "reconciliation-needed"
    assert paused["last_sync"] is None
    assert paused["mirrored_positions"] == 1
    assert paused["target_accounts"] == ["one", rejected_id]
    assert rejected_id not in " ".join(paused["errors"])
    assert any("reconcile" in error.lower() for error in paused["errors"])

    calls_before_reversal = list(owners[0].router.calls)
    watchers[0].emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 0,
        }
    )

    assert owners[0].router.calls == calls_before_reversal
    stopped = runtime.stop()
    assert stopped["lifecycle"] == "reconciliation-needed"


def test_malformed_position_change_pauses_without_dispatching(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _FakeWatcher(accounts[0])
    owner = _FakeRouterOwner(accounts[1:], "operator-1", backend_lease_proof=backend_lease_factory())
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
        }
    )

    status = runtime.status()
    assert status["active"] is False
    assert status["lifecycle"] == "reconciliation-needed"
    assert status["last_sync"] is None
    assert owner.admission_calls == []
    assert owner.router.calls == []
    runtime.stop()


def test_status_exposes_stopping_while_watcher_shutdown_is_in_progress(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    stop_entered = threading.Event()
    release_stop = threading.Event()

    class _BlockingWatcher(_FakeWatcher):
        def stop(self, *, timeout: float = 5.0) -> bool:
            del timeout
            stop_entered.set()
            assert release_stop.wait(timeout=2.0)
            self.is_running = False
            return True

    watcher = _BlockingWatcher(accounts[0])
    owner = _FakeRouterOwner(accounts[1:], "operator-1", backend_lease_proof=backend_lease_factory())
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )
    outcome: list[dict[str, Any] | Exception] = []

    def invoke_stop() -> None:
        try:
            outcome.append(runtime.stop())
        except Exception as exc:  # noqa: BLE001 - asserted below
            outcome.append(exc)

    thread = threading.Thread(target=invoke_stop, daemon=True)
    thread.start()
    assert stop_entered.wait(timeout=1.0)

    stopping = runtime.status()
    assert stopping["active"] is False
    assert stopping["lifecycle"] == "stopping"

    watcher.emit({"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS"})
    assert runtime.status()["lifecycle"] == "stopping"

    release_stop.set()
    thread.join(timeout=2.0)
    assert outcome and isinstance(outcome[0], dict)
    assert runtime.status()["lifecycle"] == "idle"


def test_stop_timeout_retains_generation_for_retry(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watchers: list[_FakeWatcher] = []
    owners: list[_FakeRouterOwner] = []

    def watcher_factory(account: BrokerAccount) -> _FakeWatcher:
        watcher = _FakeWatcher(account, stop_results=[False, False, True])
        watchers.append(watcher)
        return watcher

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=watcher_factory,
        router_owner_factory=owner_factory,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    with pytest.raises(DittoCapabilityUnavailable, match="watcher did not stop"):
        runtime.stop(timeout=0.01)

    assert runtime.status()["active"] is False
    assert runtime.status()["lifecycle"] == "retained-shutdown"
    assert runtime._watcher is watchers[0]
    assert runtime._router_owner is owners[0]
    assert owners[0].close_calls == 0
    assert runtime.shutdown(timeout=0.01) is False
    assert runtime._watcher is watchers[0]
    assert runtime._router_owner is owners[0]

    stopped = runtime.stop(timeout=1.0)

    assert stopped["active"] is False
    assert runtime._watcher is None
    assert runtime._router_owner is None
    assert owners[0].closed is True


def test_router_drain_timeout_retains_owner_and_watcher_for_retry(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _FakeWatcher(accounts[0])
    owner = _FakeRouterOwner(accounts[1:], "operator-1", close_results=[False, True], backend_lease_proof=backend_lease_factory())
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=lambda _selected, _actor_id: owner,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="EQUAL",
        actor_id="operator-1",
        jti="jwt-1",
    )

    with pytest.raises(DittoCapabilityUnavailable, match="router did not drain"):
        runtime.stop(timeout=0.01)

    assert runtime.status()["lifecycle"] == "retained-shutdown"
    assert runtime._watcher is watcher
    assert runtime._mirror is not None
    assert runtime._router_owner is owner
    assert owner.closed is False

    runtime.stop(timeout=1.0)

    assert runtime._watcher is None
    assert runtime._mirror is None
    assert runtime._router_owner is None
    assert owner.closed is True


def test_stale_watcher_callback_cannot_drive_restarted_generation(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watchers: list[_FakeWatcher] = []
    owners: list[_FakeRouterOwner] = []

    def watcher_factory(account: BrokerAccount) -> _FakeWatcher:
        watcher = _FakeWatcher(account)
        watchers.append(watcher)
        return watcher

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=watcher_factory,
        router_owner_factory=owner_factory,
    )
    start_args = {
        "source_account": "master",
        "target_accounts": ["target"],
        "mode": "EQUAL",
        "actor_id": "operator-1",
    }
    runtime.start(**start_args, jti="jwt-1")
    runtime.stop()
    runtime.start(**start_args, jti="jwt-2")
    changed_position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "quantity": 3,
    }

    watchers[0].emit(changed_position)

    assert owners[1].router.calls == []
    watchers[1].emit(changed_position)
    assert owners[1].router.calls == [("dhan", "target", 3)]
    runtime.stop()












def test_start_fails_closed_when_source_cannot_be_primed(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("one")]
    owners: list[_FakeRouterOwner] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda account: _FakeWatcher(
            account,
            prime_error=RuntimeError("source credentials rejected"),
        ),
        router_owner_factory=owner_factory,
    )

    with pytest.raises(DittoCapabilityUnavailable, match="source position state is unavailable"):
        runtime.start(
            source_account="master",
            target_accounts=["one"],
            mode="EQUAL",
            actor_id="operator-1",
            jti="jwt-1",
        )

    assert runtime.status()["active"] is False
    assert owners[0].closed is True


def test_risk_snapshot_uses_real_managed_account_state(*, backend_lease_factory) -> None:
    accounts = [_account("one"), _account("two", enabled=False)]
    readings = {
        "one": {
            "available_balance": 600.0,
            "used_margin": 400.0,
            "total_balance": 1000.0,
            "pnl_today": 25.0,
            "positions": 2,
        },
        "two": {
            "available_balance": 1500.0,
            "used_margin": 500.0,
            "total_balance": 2000.0,
            "pnl_today": -40.0,
            "positions": 1,
        },
    }
    owners: list[_FakeRouterOwner] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(selected, actor_id, risk_by_account=readings, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        router_owner_factory=owner_factory,
    )

    snapshot = runtime.risk_snapshot()

    assert snapshot["complete"] is True
    assert snapshot["aggregate_capital"] == 3000.0
    assert snapshot["aggregate_pnl"] == -15.0
    assert snapshot["accounts"][0]["margin_used_pct"] == 40.0
    assert snapshot["accounts"][1]["positions"] == 1
    assert owners[0].closed is True


def test_risk_snapshot_is_unavailable_when_any_account_read_fails(*, backend_lease_factory) -> None:
    accounts = [_account("one"), _account("two")]
    readings: dict[str, dict[str, Any] | Exception] = {
        "one": {
            "available_balance": 600.0,
            "used_margin": 400.0,
            "total_balance": 1000.0,
            "pnl_today": 25.0,
            "positions": 2,
        },
        "two": RuntimeError("broker timed out with secret response"),
    }

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        router_owner_factory=lambda selected, actor_id: _FakeRouterOwner(
            selected,
            actor_id,
            risk_by_account=readings, backend_lease_proof=backend_lease_factory()
        ),
    )

    with pytest.raises(DittoCapabilityUnavailable, match="managed-account risk state is unavailable"):
        runtime.risk_snapshot()


def test_risk_snapshot_retains_failed_router_cleanup_and_retries_it(*, backend_lease_factory) -> None:
    private_account_id = "private-risk-account-6721"
    private_detail = "broker loop close exposed private credentials"
    accounts = [_account(private_account_id)]
    readings = {
        private_account_id: {
            "available_balance": 600.0,
            "used_margin": 400.0,
            "total_balance": 1000.0,
            "pnl_today": 25.0,
            "positions": 2,
        }
    }
    owners: list[_FakeRouterOwner] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        close_results: list[bool | Exception] | None = None
        if not owners:
            close_results = [RuntimeError(f"{private_detail}: {private_account_id}"), True]
        owner = _FakeRouterOwner(
            selected,
            actor_id,
            risk_by_account=readings,
            close_results=close_results, backend_lease_proof=backend_lease_factory()
        )
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        router_owner_factory=owner_factory,
    )

    with pytest.raises(DittoCapabilityUnavailable, match="cleanup") as exc_info:
        runtime.risk_snapshot()

    assert private_account_id not in str(exc_info.value)
    assert private_detail not in str(exc_info.value)
    assert owners[0].close_calls == 1
    assert runtime._retained_router_owners == [owners[0]]
    assert runtime.status()["lifecycle"] == "retained-shutdown"

    snapshot = runtime.risk_snapshot()

    assert snapshot["complete"] is True
    assert owners[0].close_calls == 2
    assert len(owners) == 2
    assert owners[1].closed is True
    assert runtime._retained_router_owners == []
    assert runtime.status()["lifecycle"] == "idle"


def test_kill_all_waits_for_in_flight_delta_and_blocks_callbacks_after_flatten(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    watcher = _FakeWatcher(accounts[0])
    admission_entered = threading.Event()
    release_admission = threading.Event()
    owners: list[_FakeRouterOwner] = []

    class _BlockingMirrorOwner(_FakeRouterOwner):
        @contextmanager
        def admit_order(self, account_id: str, order: Any):
            self.admission_calls.append((account_id, int(order.quantity)))
            admission_entered.set()
            assert release_admission.wait(timeout=2.0)
            lease = SimpleNamespace(
                reserve=lambda _candidate, _positions: object(),
                acknowledge=lambda _reservation, _result: None,
            )
            yield lease, []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner: _FakeRouterOwner
        if not owners:
            owner = _BlockingMirrorOwner(selected, actor_id)
            owner.router.backend_lease_proof = backend_lease_factory()
        else:
            owner = _FakeRouterOwner(selected, actor_id, backend_lease_proof=backend_lease_factory())
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: watcher,
        router_owner_factory=owner_factory,
    )
    runtime.start(
        source_account="master",
        target_accounts=["target"],
        mode="equal",
        actor_id="operator-1",
        jti="jwt-start",
    )

    callback_thread = threading.Thread(
        target=lambda: watcher.emit(
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 2,
            }
        ),
        daemon=True,
    )
    kill_outcome: list[dict[str, Any] | Exception] = []

    def invoke_kill_all() -> None:
        try:
            kill_outcome.append(
                runtime.kill_all(
                    actor_id="operator-1",
                    jti="jwt-kill",
                    reason="Operator confirmed Ditto flatten",
                )
            )
        except Exception as exc:  # noqa: BLE001 - asserted below
            kill_outcome.append(exc)

    callback_thread.start()
    assert admission_entered.wait(timeout=1.0)
    kill_thread = threading.Thread(target=invoke_kill_all, daemon=True)
    kill_thread.start()
    wait_deadline = time.monotonic() + 1.0
    while runtime.status()["active"] and time.monotonic() < wait_deadline:
        time.sleep(0.001)

    assert runtime.status()["active"] is False
    assert kill_thread.is_alive()
    assert len(owners) == 1
    release_admission.set()
    callback_thread.join(timeout=2.0)
    kill_thread.join(timeout=2.0)

    assert not callback_thread.is_alive()
    assert not kill_thread.is_alive()
    assert kill_outcome and isinstance(kill_outcome[0], dict)
    assert kill_outcome[0]["mirror_quiesced"] is True
    assert owners[0].router.calls == [("dhan", "target", 2)]
    assert owners[0].closed is True
    assert owners[1].kill_call == (
        "operator-1",
        "jwt-kill",
        "Operator confirmed Ditto flatten",
    )

    watcher.emit(
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 4,
        }
    )
    assert owners[0].router.calls == [("dhan", "target", 2)]


def test_kill_all_deactivates_the_mirror_when_quiesce_refuses(*, backend_lease_factory) -> None:
    accounts = [_account("master", is_master=True), _account("target")]
    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        watcher_factory=lambda _account: _FakeWatcher(accounts[0]),
        router_owner_factory=lambda selected, actor: _FakeRouterOwner(selected, actor, backend_lease_proof=backend_lease_factory()),
    )

    def _refuse(*, timeout: float) -> dict[str, Any]:
        del timeout
        raise DittoCapabilityUnavailable("mirror dispatch did not quiesce")

    # Emulate a live mirror whose stop() refuses before flipping _active — the
    # "starting"/"stopping" guards do exactly this. The flatten must still leave
    # the mirror deactivated so it cannot keep issuing orders during escalation.
    runtime._active = True  # noqa: SLF001 - emulate a live mirror
    runtime.stop = _refuse  # type: ignore[assignment]

    with pytest.raises(DittoCapabilityUnavailable, match="account-wide kill switch") as exc_info:
        runtime.kill_all(actor_id="operator-1", jti="jwt-kill", reason="flatten")

    assert "deactivated" in str(exc_info.value)
    assert runtime._active is False  # noqa: SLF001


def test_kill_all_includes_disabled_accounts_and_reports_partial_outcome(*, backend_lease_factory) -> None:
    accounts = [_account("one"), _account("two", enabled=False), _account("three")]
    owners: list[_FakeRouterOwner] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(
            selected,
            actor_id,
            failed_kill_accounts={"two"}, backend_lease_proof=backend_lease_factory()
        )
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        router_owner_factory=owner_factory,
    )

    result = runtime.kill_all(
        actor_id="operator-1",
        jti="jwt-1",
        reason="Operator confirmed Ditto flatten",
    )

    assert result["complete"] is False
    assert result["accounts_affected"] == 3
    assert result["emergency_actions"]["completed_target_count"] == 2
    assert {account.account_id for account in owners[0].accounts} == {"one", "two", "three"}
    assert owners[0].kill_call == (
        "operator-1",
        "jwt-1",
        "Operator confirmed Ditto flatten",
    )
    assert owners[0].closed is True


def test_kill_all_reports_incomplete_until_retained_router_cleanup_succeeds(*, backend_lease_factory) -> None:
    accounts = [_account("one")]
    owners: list[_FakeRouterOwner] = []

    def owner_factory(selected: list[BrokerAccount], actor_id: str) -> _FakeRouterOwner:
        owner = _FakeRouterOwner(
            selected,
            actor_id,
            close_results=[False, True] if not owners else None, backend_lease_proof=backend_lease_factory()
        )
        owners.append(owner)
        return owner

    runtime = DittoRuntime(
        account_provider=lambda: accounts,
        router_owner_factory=owner_factory,
    )

    first = runtime.kill_all(
        actor_id="operator-1",
        jti="jwt-1",
        reason="Operator confirmed Ditto flatten",
    )

    assert first["emergency_actions"]["complete"] is True
    assert first["cleanup_complete"] is False
    assert first["complete"] is False
    assert owners[0].close_calls == 1
    assert runtime._retained_router_owners == [owners[0]]
    assert runtime.status()["lifecycle"] == "retained-shutdown"

    second = runtime.kill_all(
        actor_id="operator-1",
        jti="jwt-2",
        reason="Operator confirmed Ditto flatten retry",
    )

    assert owners[0].close_calls == 2
    assert len(owners) == 2
    assert owners[1].closed is True
    assert second["cleanup_complete"] is True
    assert second["complete"] is True
    assert runtime._retained_router_owners == []
    assert runtime.status()["lifecycle"] == "idle"


def test_kill_all_refuses_empty_managed_account_scope() -> None:
    runtime = DittoRuntime(account_provider=list)

    with pytest.raises(DittoCapabilityUnavailable, match="no managed accounts"):
        runtime.kill_all(actor_id="operator-1", jti="jwt-1", reason="confirmed")








def test_runtime_exposes_current_owner_reconciliation_targets() -> None:
    runtime = DittoRuntime(account_provider=list)
    expected = [(object(), object())]
    owner = SimpleNamespace(reconciliation_targets=lambda: expected)

    assert runtime.reconciliation_targets() == []
    with runtime._lock:
        runtime._router_owner = owner
    assert runtime.reconciliation_targets() == expected
