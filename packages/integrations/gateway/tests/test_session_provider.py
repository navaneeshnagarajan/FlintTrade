"""T5 (gap G3): AuthenticatingSessionProvider enforces per-(actor, account) ACLs.

Contract §11.4 / identity H2 — the single enforcement gate for both reads and
writes: an actor not listed in account_acls[adapter_id][account_id] is refused
with SafetyBypassError before any Session is returned.
"""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext
from flinttrade_gateway.registry import BrokerRegistry
from flinttrade_gateway.session_provider import AuthenticatingSessionProvider


def _ctx(actor_id: str = "nava@flinttrade.local") -> RequestContext:
    return RequestContext(jti="x", actor_type="human", actor_id=actor_id, mode="live")


def _provider(session: object) -> AuthenticatingSessionProvider:
    reg = BrokerRegistry()
    reg.put_session("dhan", "personal", session)
    return AuthenticatingSessionProvider(reg, {"dhan": {"personal": ["nava@flinttrade.local"]}})


def test_authorised_actor_gets_session() -> None:
    s = object()
    assert _provider(s)(_ctx(), "dhan", "personal") is s


def test_unauthorised_actor_refused() -> None:
    with pytest.raises(SafetyBypassError, match="not authorised"):
        _provider(object())(_ctx(actor_id="other@example.com"), "dhan", "personal")


def test_unknown_account_refused() -> None:
    # account 'family' has no ACL entry -> empty allow-list -> refused.
    with pytest.raises(SafetyBypassError, match="not authorised"):
        _provider(object())(_ctx(), "dhan", "family")


def test_same_gate_guards_reads_and_writes() -> None:
    # The provider does not distinguish read from write — both obtain their
    # Session here, so an intruder is refused on either path identically.
    with pytest.raises(SafetyBypassError, match="not authorised"):
        _provider(object())(_ctx(actor_id="intruder"), "dhan", "personal")
