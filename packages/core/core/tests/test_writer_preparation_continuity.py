"""Synthetic normal-factory writer continuity, with real inert SDK resources."""
from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from packages.core.core.tests.test_exact_contract_http_preflight import (
    _post,
    exact_stack as exact_stack,
)
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack as route_stack

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("phase", ["books", "queue"])
def test_selected_adapter_cannot_change_after_preflight(
    exact_stack: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    broker: str,
    phase: str,
) -> None:
    """A real delegate on a replacement must not inherit the captured target.

    Args:
        exact_stack: Normal-factory builder with installed SDKs and inert transports.
        monkeypatch: Scoped test-owned observers and synthetic faults.
        broker: Exact synthetic broker selector.
        phase: Held request boundary at which the target changes.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    stack = exact_stack(broker)
    replacement = SimpleNamespace(broker_id=broker, capabilities=stack.adapter.capabilities,
                                  place_order=stack.adapter.place_order)
    if phase == "books":
        original = stack.source.positions

        async def read(*args: Any, **kwargs: Any) -> Any:
            stack.router._adapters[broker] = replacement
            return await original(*args, **kwargs)

        monkeypatch.setattr(stack.source, "positions", read)
    else:
        class Queue:
            async def acquire(self, *_args: Any) -> None:
                stack.router._adapters[broker] = replacement
        stack.router._rate_limiter = Queue()
    response, observed = _post(stack)
    assert observed["wire"] == []
    assert observed["invoked"] == []
    assert response.status_code != 200
    if phase == "books":
        assert observed["minted"] == 0


def test_dhan_retains_the_actual_preflight_receipt(
    exact_stack: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original preparation, not a second resolver result, reaches placement.

    Args:
        exact_stack: Normal-factory builder with installed SDKs and inert transports.
        monkeypatch: Scoped test-owned observers and synthetic faults.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    stack = exact_stack("dhan")
    captured, invoked = [], []
    original_prepare, original_place = stack.adapter.prepare_order, stack.adapter.place_order

    def prepare(*args: Any, **kwargs: Any) -> Any:
        result = original_prepare(*args, **kwargs)
        captured.append(result)
        return result

    async def place(*args: Any, **kwargs: Any) -> Any:
        invoked.append(kwargs.get("preparation"))
        return await original_place(*args, **kwargs)

    monkeypatch.setattr(stack.adapter, "prepare_order", prepare)
    monkeypatch.setattr(stack.adapter, "place_order", place)
    response, observed = _post(stack)
    assert response.status_code == 200, response.get_json()
    assert len(captured) == 1
    assert invoked == [captured[0]] and invoked[0] is captured[0]
    assert len(observed["wire"]) == 1


@pytest.mark.parametrize("timing", ["PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60"])
def test_dhan_amo_timing_is_full_signed_retained_intent(exact_stack: Callable[..., Any], timing: str) -> None:
    """Common SDK kwargs cannot replace the AMO family's requested pump window.

    Args:
        exact_stack: Normal-factory builder with installed SDKs and inert transports.
        timing: Documented literal AMO pump window.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    stack = exact_stack("dhan")
    response, observed = _post(stack, {"variety": "amo", "amo_time": timing})
    assert response.status_code == 200, response.get_json()
    assert observed["wire"][0]["afterMarketOrder"] is True
    assert observed["wire"][0]["amoTime"] == timing
    assert stack.minted[0][0].amo_time == timing
    assert observed["invoked"][0]["amo_time"] == timing


@pytest.mark.parametrize("field,value", [("amo_time", "OTHER"), ("amoTime", "PRE_OPEN"),
                                          ("amo_time", False), ("amo_time", 0)])
def test_unrepresented_or_invalid_amo_intent_refuses_before_books(
    exact_stack: Callable[..., Any],
    field: str,
    value: Any,
) -> None:
    """Unsupported native aliases and timing shapes cannot be discarded.

    Args:
        exact_stack: Normal-factory builder with installed SDKs and inert transports.
        field: Raw request field under challenge.
        value: Literal synthetic invalid request value.

    Raises:
        AssertionError: If the real writer, ledger or uncertainty boundary differs.
    """
    stack = exact_stack("dhan")
    response, observed = _post(stack, {"variety": "amo", field: value})
    assert response.status_code == 400
    assert observed["reads"] == [] and observed["minted"] == 0
    assert observed["wire"] == [] and observed["invoked"] == []
