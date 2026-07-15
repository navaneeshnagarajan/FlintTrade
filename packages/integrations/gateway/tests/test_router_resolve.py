"""T3 (gap G2): config-driven BrokerRouter._resolve + RoutingHint.

The router resolves a routing key to a concrete ``(adapter_id, account_id)`` from
the operator's RoutingConfig, with per-call RoutingHint overrides — without
regressing the legacy explicit-target dispatch (covered by test_router.py) or the
verify-then-consume safety ordering.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, set_safety_gate_secret
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingHint

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


def _config() -> RoutingConfig:
    return RoutingConfig.from_workspace(
        {
            "registered": ["dhan:personal"],
            "account_acls": {"dhan": {"personal": ["user-1"]}},
            "execution": {"default": "dhan:personal"},
            "data": {
                "ticks": "dhan:personal",
                "historical": "dhan:personal",
                "option_chains": "dhan:personal",
                "quote": "dhan:personal",
            },
            "failover": {"enabled": False, "order": []},
            "cost_aware": {"enabled": False, "tasks": []},
        }
    )


def test_authorised_selectors_returns_every_registered_actor_account_in_config_order() -> None:
    config = RoutingConfig.from_workspace(
        {
            "registered": ["dhan:primary", "upstox:secondary", "dhan:read-only"],
            "account_acls": {
                "dhan": {
                    "primary": ["user-1"],
                    "read-only": ["someone-else"],
                },
                "upstox": {"secondary": ["user-1", "someone-else"]},
            },
            "execution": {"default": "dhan:primary"},
            "data": {
                "ticks": "dhan:read-only",
                "historical": "dhan:read-only",
                "option_chains": "dhan:read-only",
                "quote": "dhan:read-only",
            },
            "failover": {"enabled": False, "order": []},
            "cost_aware": {"enabled": False, "tasks": []},
        }
    )
    router = _router(_FakeAdapter(), config=config)

    assert router.authorised_selectors("user-1") == (
        "dhan:primary",
        "upstox:secondary",
    )
    assert router.authorised_selectors("unknown") == ()


def test_registered_selectors_is_an_immutable_config_snapshot() -> None:
    config = _config()
    router = _router(_FakeAdapter(), config=config)

    assert router.registered_selectors == ("dhan:personal",)
    assert isinstance(router.registered_selectors, tuple)
    assert _router(_FakeAdapter()).registered_selectors == ()


def test_registered_selectors_excludes_adapters_absent_from_the_generation() -> None:
    config = RoutingConfig.from_workspace(
        {
            "registered": ["dhan:personal", "indmoney:family"],
            "account_acls": {
                "dhan": {"personal": ["user-1"]},
                "indmoney": {"family": ["user-1"]},
            },
            "execution": {"default": "dhan:personal"},
            "data": {
                "ticks": "dhan:personal",
                "historical": "dhan:personal",
                "option_chains": "dhan:personal",
                "quote": "dhan:personal",
            },
            "failover": {"enabled": False, "order": []},
            "cost_aware": {"enabled": False, "tasks": []},
        }
    )
    router = _router(_FakeAdapter(), config=config)

    assert router.registered_selectors == ("dhan:personal",)


class _FakeAdapter:
    def __init__(self) -> None:
        self.placed: list[object] = []

    async def place_order(self, session, order, *, _router_token=None):
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.placed.append(order)
        return "BROKER-OID-1"


def _session() -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="personal",
        adapter_id="dhan",
    )


def _order() -> object:
    return types.SimpleNamespace(symbol="RELIANCE", quantity=10, side="BUY", exchange="NSE")


def _ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def _router(adapter: _FakeAdapter, *, config: RoutingConfig | None = None) -> BrokerRouter:
    return BrokerRouter(
        {"dhan": adapter},
        lambda _ctx, _aid, _acct: _session(),
        config=config,
    )


# --- _resolve unit behaviour --------------------------------------------


def test_resolve_hint_overrides_both() -> None:
    router = _router(_FakeAdapter())  # no config needed: hint supplies both
    assert router._resolve(
        "execution", _order(), RoutingHint(adapter_id="dhan", account_id="personal")
    ) == ("dhan", "personal")


def test_resolve_from_config_when_no_hint() -> None:
    router = _router(_FakeAdapter(), config=_config())
    assert router._resolve("data.ticks", None, None) == ("dhan", "personal")
    assert router._resolve("execution", _order(), None) == ("dhan", "personal")


def test_resolve_hint_account_overrides_parsed() -> None:
    router = _router(_FakeAdapter(), config=_config())
    # config resolves account 'personal'; the hint forces 'family'.
    assert router._resolve("execution", _order(), RoutingHint(account_id="family")) == (
        "dhan",
        "family",
    )


def test_resolve_unknown_routing_key_raises() -> None:
    router = _router(_FakeAdapter(), config=_config())
    with pytest.raises(ValueError, match="unknown routing key"):
        router._resolve("data.bogus", None, None)


def test_resolve_without_config_or_hint_raises() -> None:
    router = _router(_FakeAdapter())  # no config
    with pytest.raises(ValueError, match="no RoutingConfig"):
        router._resolve("execution", _order(), None)


def test_resolve_account_defaults_when_absent() -> None:
    router = _router(_FakeAdapter())
    # adapter override only, no config, no account hint -> account defaults.
    assert router._resolve("execution", _order(), RoutingHint(adapter_id="dhan")) == (
        "dhan",
        "default",
    )


# --- place_order through the resolved path -------------------------------


async def test_place_order_via_hint_resolves_and_dispatches() -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, config=_config())
    order = _order()
    ctx = SafetyContext.mint(
        order, mode="live", user_jti="jti-1", adapter_id="dhan", account_id="personal", actor_type="human"
    )
    result = await router.place_order(
        _ctx(), order=order, safety_ctx=ctx, hint=RoutingHint(adapter_id="dhan", account_id="personal")
    )
    assert result == "BROKER-OID-1"
    assert adapter.placed == [order]


async def test_place_order_via_hint_still_enforces_safety() -> None:
    # A ctx minted for 'upstox' must not fire when the hint resolves to 'dhan'.
    adapter = _FakeAdapter()
    router = _router(adapter, config=_config())
    order = _order()
    ctx = SafetyContext.mint(
        order, mode="live", user_jti="jti-1", adapter_id="upstox", account_id="personal", actor_type="human"
    )
    with pytest.raises(SafetyBypassError, match="verification failed"):
        await router.place_order(
            _ctx(), order=order, safety_ctx=ctx, hint=RoutingHint(adapter_id="dhan", account_id="personal")
        )
    assert adapter.placed == []
