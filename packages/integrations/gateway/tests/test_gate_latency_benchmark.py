"""Latency tripwire for the gated order path (gate_order → BrokerRouter).

The mission treats latency as a first-class concern, so the safety gate that
sits in front of every live order must not become a hidden bottleneck. This
test *measures* the real overhead of minting a one-shot ``SafetyContext`` via
``gate_order`` and dispatching it through ``BrokerRouter.place_order`` (which
re-verifies the HMAC, field-matches the order, consumes the one-shot gate, and
calls the adapter behind the module-private router token) against a mock broker.

It asserts the measured per-order overhead stays under a deliberately generous
ceiling — this is real measured evidence, not a fabricated number, and it is
loose enough (5 ms) never to flake on a busy CI runner while still catching a
genuine regression (e.g. an accidental O(n) scan or a per-order key derivation
that pushed the gate into the millisecond-plural range).

The mock adapter performs no network I/O, so the timing isolates the gate +
router overhead, not broker round-trip time.
"""

from __future__ import annotations

import time
import types
from datetime import datetime, timezone

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import gate_order, set_safety_gate_secret
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import _ROUTER_TOKEN
from flinttrade_gateway.router import BrokerRouter

SECRET = b"0123456789abcdef0123456789abcdef"

# Generous ceiling: the gate is HMAC-SHA256 over a small order dict (tens of
# microseconds in practice). 5 ms leaves ~100x head-room for a loaded CI box.
_MAX_MEAN_OVERHEAD_S = 0.005
_ITERATIONS = 200


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


class _NoIoAdapter:
    """Adapter that records dispatches and does zero I/O (isolates gate cost)."""

    def __init__(self) -> None:
        self.count = 0

    async def place_order(self, session: object, order: object, *, _router_token: object = None) -> str:
        if _router_token is not _ROUTER_TOKEN:
            raise SafetyBypassError("adapter write method called outside BrokerRouter")
        self.count += 1
        return "BROKER-OID"


def _session(_ctx: object, _adapter_id: str, _account_id: str) -> Session:
    return Session(
        access_token="tok",
        expires_at=datetime.now(tz=timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="dhan",
    )


def _order(i: int) -> object:
    # Vary the order each iteration so every gate mint binds a distinct payload.
    return types.SimpleNamespace(symbol="RELIANCE", quantity=10 + i, side="BUY", exchange="NSE")


def _ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


@pytest.mark.unit
async def test_gated_order_path_overhead_under_ceiling() -> None:
    """Mint + route N orders through the gate; assert mean overhead < ceiling."""
    adapter = _NoIoAdapter()
    router = BrokerRouter({"dhan": adapter}, _session)
    ctx = _ctx()

    start = time.perf_counter()
    for i in range(_ITERATIONS):
        order = _order(i)
        sc = gate_order(order, ctx, "dhan", account_id="acct-1")
        result = await router.place_order(
            ctx, adapter_id="dhan", account_id="acct-1", order=order, safety_ctx=sc
        )
        assert result == "BROKER-OID"
    elapsed = time.perf_counter() - start

    mean_overhead = elapsed / _ITERATIONS
    # Correctness: every order actually traversed the gate and reached the adapter.
    assert adapter.count == _ITERATIONS
    # Latency tripwire: real measured per-order gate+route overhead.
    assert mean_overhead < _MAX_MEAN_OVERHEAD_S, (
        f"gated-order-path overhead {mean_overhead * 1e3:.3f} ms/order exceeds "
        f"the {_MAX_MEAN_OVERHEAD_S * 1e3:.1f} ms ceiling — investigate a gate/router regression"
    )
