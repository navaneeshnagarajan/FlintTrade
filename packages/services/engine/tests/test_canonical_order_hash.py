"""Canonical-order-hash tests for SafetyContext (broker-adapter-contract §8.0).

``_canonical_order_hash`` underpins the order-substitution replay guard: the
same order hashed at mint time and at verify time MUST yield the same digest,
and a *different* order MUST yield a different one. The routed-order path
(``order_routes.py``) feeds a plain ``dict`` body straight through
``gate_order``; because a dict has no ``__dict__``, the original implementation
fell back to ``repr(order)`` and so made the digest sensitive to dict-key
*insertion order*. These tests pin the canonicalised behaviour:

  (a) two dicts with the SAME keys/values but DIFFERENT insertion order hash
      EQUAL, and
  (b) dicts with DIFFERENT values hash DIFFERENT.
"""

from __future__ import annotations

import types
from collections import OrderedDict

from flinttrade_engine.safety import SafetyContext, _canonical_order_hash


# ---------------------------------------------------------------------------
# Mapping inputs (the routed-order dict-body path)
# ---------------------------------------------------------------------------


def test_dicts_same_content_different_insertion_order_hash_equal() -> None:
    """(a) Insertion order MUST NOT affect the digest for equal mappings."""
    a = {"symbol": "RELIANCE", "quantity": 10, "side": "BUY", "exchange": "NSE"}
    b = {"exchange": "NSE", "side": "BUY", "quantity": 10, "symbol": "RELIANCE"}
    assert _canonical_order_hash(a) == _canonical_order_hash(b)


def test_dicts_different_values_hash_differ() -> None:
    """(b) A changed field MUST flip the digest (order-substitution guard)."""
    a = {"symbol": "RELIANCE", "quantity": 10, "side": "BUY", "exchange": "NSE"}
    b = {"symbol": "TCS", "quantity": 10, "side": "BUY", "exchange": "NSE"}
    assert _canonical_order_hash(a) != _canonical_order_hash(b)


def test_ordereddict_insertion_order_does_not_affect_hash() -> None:
    """Any ``Mapping`` (here ``OrderedDict``) is canonicalised by sorted keys."""
    a = OrderedDict([("a", 1), ("b", 2), ("c", 3)])
    b = OrderedDict([("c", 3), ("b", 2), ("a", 1)])
    assert _canonical_order_hash(a) == _canonical_order_hash(b)


def test_public_order_hash_for_matches_helper_on_dict() -> None:
    """The public helper stays consistent with the private canonicaliser."""
    body = {"symbol": "INFY", "quantity": 5, "side": "SELL", "exchange": "NSE"}
    assert SafetyContext.order_hash_for(body) == _canonical_order_hash(body)


# ---------------------------------------------------------------------------
# Object inputs (the existing ``__dict__`` path must keep working)
# ---------------------------------------------------------------------------


def test_object_with_dunder_dict_still_hashes_canonically() -> None:
    """The ``__dict__`` path is preserved for ordinary objects (SimpleNamespace)."""
    a = types.SimpleNamespace(symbol="RELIANCE", quantity=10, side="BUY")
    b = types.SimpleNamespace(symbol="RELIANCE", quantity=10, side="BUY")
    assert _canonical_order_hash(a) == _canonical_order_hash(b)


def test_object_and_equivalent_dict_round_trip() -> None:
    """An object's ``__dict__`` and the equivalent mapping hash identically.

    This is the consistency guarantee the routed-order path relies on: minting
    over a dict body and verifying over the same content must agree.
    """
    ns = types.SimpleNamespace(symbol="RELIANCE", quantity=10, side="BUY")
    as_dict = {"symbol": "RELIANCE", "quantity": 10, "side": "BUY"}
    assert _canonical_order_hash(ns) == _canonical_order_hash(as_dict)


def test_unserialisable_non_mapping_falls_back_to_repr() -> None:
    """A genuinely un-serialisable non-mapping still hashes via the repr fallback."""

    class _Opaque:
        __slots__ = ()  # no __dict__, not a Mapping

        def __repr__(self) -> str:
            return "<opaque-fixed-repr>"

    obj = _Opaque()
    # Deterministic: the same opaque object hashes to a stable digest.
    assert _canonical_order_hash(obj) == _canonical_order_hash(_Opaque())
