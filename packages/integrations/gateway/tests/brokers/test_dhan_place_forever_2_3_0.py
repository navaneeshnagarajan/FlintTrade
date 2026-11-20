"""Fixture contract for the dhanhq 2.3.0 ``place_forever`` call shape.

The pinned SDK no longer accepts ``symbol``. These rows lock the kwargs the
adapter would pass, including sign and lot quantity, without dispatching an
order or contacting a broker.
"""

from __future__ import annotations

import json
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import pytest
from dhanhq import ForeverOrder

from flinttrade_gateway.brokers.dhan_mapping import to_forever_kwargs

pytestmark = pytest.mark.unit

_FIXTURE = Path(__file__).parent / "fixtures" / "dhan_place_forever_2_3_0.json"
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["single", "short", "oco", "multi_lot"])
def test_place_forever_fixture_matches_2_3_0_signature(name: str) -> None:
    case = _CASES[name]
    order = SimpleNamespace(**case["order"])
    kwargs = to_forever_kwargs(order, case["security_id"], tag=case["tag"])
    assert kwargs == case["kwargs"]
    assert "symbol" not in kwargs
    bound = signature(ForeverOrder.place_forever).bind(object(), **kwargs)
    assert "symbol" not in bound.arguments
    with pytest.raises(TypeError, match="symbol"):
        signature(ForeverOrder.place_forever).bind(object(), **kwargs, symbol=case["order"]["symbol"])
