"""Parent wiring for background emergency broker writes."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

from flask import Flask

from flinttrade_core.app import FlintTradeApp, _bind_runtime_emergency_dispatcher
from flinttrade_engine.safety import L5_EMERGENCY_POLICY


class _ClientLoopOwner:
    def __init__(self) -> None:
        self.calls = 0

    def run_sync(self, awaitable: Any) -> Any:
        self.calls += 1
        return asyncio.run(awaitable)


class _Router:
    default_selector = "openalgo:primary"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute_gated(self, request_ctx: Any, **kwargs: Any) -> dict[str, bool]:
        self.calls.append({"request_ctx": request_ctx, **kwargs})
        return {"ok": True}


class _Safety:
    def __init__(self) -> None:
        self.dispatcher: Any = None

    def bind_emergency_dispatcher(self, dispatcher: Any) -> None:
        self.dispatcher = dispatcher


def test_runtime_dispatcher_binds_fresh_operator_principals(monkeypatch) -> None:
    from flinttrade_engine import safety as safety_module

    minted: list[tuple[str, dict[str, Any], Any, str, str]] = []

    def fake_gate(verb, payload, request_ctx, adapter_id, *, account_id):
        minted.append((verb, dict(payload), request_ctx, adapter_id, account_id))
        return object()

    monkeypatch.setattr(safety_module, "gate_broker_write", fake_gate)
    app = Flask("emergency-parent-wiring")
    router = _Router()
    app.config.update(
        BROKER_ROUTER=router,
        AUTH_SERVICE=SimpleNamespace(get_profile=lambda: {"username": "operator"}),
    )
    safety = _Safety()
    telegram = SimpleNamespace(emergency_dispatcher=None)
    client = _ClientLoopOwner()

    dispatcher = _bind_runtime_emergency_dispatcher(app, safety, telegram, client)
    first = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator request")
    first_jti = minted[0][2].jti
    second = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator retry")

    assert first.complete is True
    assert second.complete is True
    assert safety.dispatcher is dispatcher
    assert telegram.emergency_dispatcher is dispatcher
    assert app.config["EMERGENCY_DISPATCHER"] is dispatcher
    assert [call[0] for call in minted] == [
        "cancel_all_orders",
        "exit_all_positions",
        "cancel_all_orders",
        "exit_all_positions",
    ]
    assert all(call[2].actor_id == "operator" for call in minted)
    assert all(call[2].selector == "openalgo:primary" for call in minted)
    assert all(call[3:] == ("openalgo", "primary") for call in minted)
    assert minted[0][2].jti == minted[1][2].jti
    assert minted[2][2].jti == minted[3][2].jti
    assert minted[2][2].jti != first_jti
    assert client.calls == 4
    assert len(router.calls) == 4


def test_runtime_dispatcher_fails_closed_without_operator_profile() -> None:
    app = Flask("emergency-parent-no-profile")
    router = _Router()
    app.config["BROKER_ROUTER"] = router
    safety = _Safety()
    telegram = SimpleNamespace(emergency_dispatcher=None)

    dispatcher = _bind_runtime_emergency_dispatcher(
        app,
        safety,
        telegram,
        _ClientLoopOwner(),
    )
    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="operator request")

    assert result.complete is False
    assert result.failure_codes == ("target_unavailable", "target_unavailable")
    assert router.calls == []


def test_telegram_polling_starts_only_after_emergency_dispatcher_binding() -> None:
    source = inspect.getsource(FlintTradeApp.start)

    assert source.index("_bind_runtime_emergency_dispatcher(") < source.index(
        "self.telegram.start_background()"
    )
