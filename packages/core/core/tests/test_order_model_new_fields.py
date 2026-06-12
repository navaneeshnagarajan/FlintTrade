"""Order model — optional validity + OCO leg fields (None defaults).

These fields ride the existing place/modify path (Dhan forever OCO, Kotak Neo
validity pass-through). They MUST stay optional so every existing constructor
call and serialised payload (sandbox, journal, ditto mirrors) keeps working,
and they MUST appear in the instance ``__dict__`` so the SafetyContext
canonical hash covers them (the engine-side mutation test pins that property).
"""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order

pytestmark = pytest.mark.unit


def test_new_fields_default_to_none() -> None:
    order = Order(symbol="RELIANCE", action="BUY")
    assert order.validity is None
    assert order.price1 is None
    assert order.trigger_price1 is None
    assert order.quantity1 is None


def test_old_payloads_without_new_fields_still_construct() -> None:
    """Serialisation tolerance: a pre-upgrade dump round-trips unchanged."""
    legacy = {
        "symbol": "RELIANCE", "action": "BUY", "exchange": "NSE",
        "pricetype": "LIMIT", "product": "CNC", "quantity": "5", "price": "2900",
    }
    order = Order(**legacy)
    assert order.validity is None and order.price1 is None


def test_new_fields_round_trip_through_model_dump() -> None:
    order = Order(
        symbol="RELIANCE", action="BUY", variety="gtt", trigger_price="2890",
        validity="IOC", price1="2800", trigger_price1="2805", quantity1="5",
    )
    dumped = order.model_dump()
    assert dumped["validity"] == "IOC"
    assert dumped["price1"] == "2800"
    assert dumped["trigger_price1"] == "2805"
    assert dumped["quantity1"] == "5"
    assert Order(**dumped) == order


def test_new_fields_are_in_instance_dict_for_hashing() -> None:
    """The SafetyContext canonicaliser hashes ``order.__dict__`` — the new
    fields must live there (set OR unset) or they would escape the HMAC."""
    unset = Order(symbol="RELIANCE", action="BUY")
    set_ = Order(symbol="RELIANCE", action="BUY", validity="DAY",
                 price1="1", trigger_price1="2", quantity1="3")
    for field in ("validity", "price1", "trigger_price1", "quantity1"):
        assert field in unset.__dict__
        assert field in set_.__dict__


def test_exclude_none_dump_omits_unset_new_fields() -> None:
    """Wire-payload builders that use ``exclude_none`` stay byte-identical for
    legacy orders — the new fields only appear when explicitly set."""
    order = Order(symbol="RELIANCE", action="BUY")
    dumped = order.model_dump(exclude_none=True)
    for field in ("validity", "price1", "trigger_price1", "quantity1"):
        assert field not in dumped
