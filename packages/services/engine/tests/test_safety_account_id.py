"""T4-C (gap G4): account_id is signed into the SafetyContext canonical tuple.

The selector-bound principal (identity X7) means a gate minted for one account
must NOT verify when the router resolves a different account under the same
adapter — closing the account-swap replay vector.
"""

from __future__ import annotations

import types

import pytest

from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyContext, gate_order, set_safety_gate_secret

SECRET = b"0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


def _order() -> object:
    return types.SimpleNamespace(symbol="RELIANCE", quantity=10, side="BUY", exchange="NSE")


def _ctx() -> RequestContext:
    return RequestContext(jti="jti-1", actor_type="human", actor_id="user-1", mode="live")


def test_account_id_is_signed_and_round_trips() -> None:
    order = _order()
    ctx = SafetyContext.mint(
        order, mode="live", user_jti="jti-1", adapter_id="dhan", account_id="personal", actor_type="human"
    )
    assert ctx.account_id == "personal"
    assert ctx.verify(order, _ctx(), "dhan", "personal") is True


def test_account_swap_is_rejected() -> None:
    order = _order()
    ctx = SafetyContext.mint(
        order, mode="live", user_jti="jti-1", adapter_id="dhan", account_id="personal", actor_type="human"
    )
    # Same adapter, DIFFERENT account — must fail (the swap vector).
    assert ctx.verify(order, _ctx(), "dhan", "family") is False


def test_gate_order_threads_account_id() -> None:
    order = _order()
    sc = gate_order(order, _ctx(), "dhan", account_id="personal")
    assert sc.account_id == "personal"
    assert sc.verify(order, _ctx(), "dhan", "personal") is True
    assert sc.verify(order, _ctx(), "dhan", "family") is False


def test_default_account_id_back_compat() -> None:
    # Account-agnostic callers (no account_id) sign and verify the shared default.
    order = _order()
    sc = gate_order(order, _ctx(), "dhan")
    assert sc.account_id == "default"
    assert sc.verify(order, _ctx(), "dhan") is True
