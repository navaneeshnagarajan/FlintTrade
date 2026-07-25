"""T1 (gap G8): selector-bound principal on RequestContext.

A principal may be bound to exactly one ``(adapter_id, account_id)`` selector,
carried as the canonical composite string ``'adapter_id:account_id'`` (identity
X7). ``parse_selector`` splits on the FIRST colon only, so account ids that
themselves contain colons (e.g. an OpenAlgo sub-account) survive intact.
"""

from __future__ import annotations

import pytest

from flinttrade_engine.request_context import RequestContext, parse_selector


def test_parse_selector_basic() -> None:
    assert parse_selector("dhan:personal") == ("dhan", "personal")


def test_parse_selector_splits_on_first_colon_only() -> None:
    # The account id keeps any further colons; only the first colon delimits.
    assert parse_selector("openalgo:zerodha:sub") == ("openalgo", "zerodha:sub")


@pytest.mark.parametrize("bad", ["bad", "", ":account", "adapter:", ":"])
def test_parse_selector_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_selector(bad)


def test_selector_parts_round_trip() -> None:
    ctx = RequestContext(
        jti="j",
        actor_type="human",
        actor_id="a",
        mode="live",
        selector="dhan:personal",
    )
    assert ctx.selector_parts() == ("dhan", "personal")


def test_selector_defaults_to_none() -> None:
    ctx = RequestContext(jti="j", actor_type="human", actor_id="a", mode="live")
    assert ctx.selector is None
    assert ctx.selector_parts() is None


def test_backwards_compatible_positional_construction() -> None:
    # The 6-positional-arg form used across existing tests MUST still work — the
    # new ``selector`` field is appended last and stays optional.
    ctx = RequestContext("j", "human", "a", "live", "custom", "deadbeef")
    assert ctx.intent_source == "custom"
    assert ctx.external_nonce_hash == "deadbeef"
    assert ctx.selector is None


def test_request_context_remains_frozen() -> None:
    ctx = RequestContext(jti="j", actor_type="human", actor_id="a", mode="live")
    with pytest.raises(Exception):
        ctx.selector = "dhan:personal"  # type: ignore[misc]
