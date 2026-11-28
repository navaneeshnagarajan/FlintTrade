"""Actual retained Kotak preparation through the normal inert HTTP factory."""
from __future__ import annotations

from typing import Any

import pytest

from packages.core.core.tests.test_exact_contract_http_preflight import _post, exact_stack as exact_stack
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack as route_stack

pytestmark = pytest.mark.integration


def test_kotak_retains_the_actual_preflight_receipt(exact_stack: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not repeat resolution or replace full signed intent with SDK kwargs."""
    stack = exact_stack("kotakneo")
    captured, invoked = [], []
    prepare, place = stack.adapter.prepare_order, stack.adapter.place_order

    def observed_prepare(*args: Any, **kwargs: Any) -> Any:
        result = prepare(*args, **kwargs)
        captured.append(result)
        return result

    async def observed_place(*args: Any, **kwargs: Any) -> Any:
        invoked.append(kwargs.get("preparation"))
        return await place(*args, **kwargs)

    monkeypatch.setattr(stack.adapter, "prepare_order", observed_prepare)
    monkeypatch.setattr(stack.adapter, "place_order", observed_place)
    response, observed = _post(stack)
    assert response.status_code == 200, response.get_json()
    assert len(captured) == 1
    assert invoked == [captured[0]] and invoked[0] is captured[0]
    assert len(observed["wire"]) == 1
