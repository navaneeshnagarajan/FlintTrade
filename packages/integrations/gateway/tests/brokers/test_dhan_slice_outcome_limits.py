"""Fail closed at the existing Dhan slice response seam on unverified outcomes.

The adversarial response shapes below are NOT asserted to be native fixtures.
The official v2 page and pinned SDK establish slicing dispatch, but supply no
per-child result fixture. Preserve scalar ACK compatibility without treating it
as completeness, fills or a successful parent/child reconciliation.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from dhanhq import Order as SDKOrder

from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter, _ROUTER_TOKEN

pytestmark = pytest.mark.unit


class RecordingHTTP:
    def __init__(self, data: Any) -> None:
        self.data = data
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        assert endpoint == "/orders/slicing"
        self.calls.append((endpoint, payload))
        return {"status": "success", "data": self.data}


class RecordingSDK(SDKOrder):
    def __init__(self, transport: RecordingHTTP) -> None:
        self.dhan_http = transport


def stack(data: Any):
    transport = RecordingHTTP(data)
    sdk = RecordingSDK(transport)
    adapter = DhanAdapter(client_factory=lambda _session: sdk, security_resolver=lambda _symbol, _exchange: "1333")
    session = Session("synthetic-token", 4102444800.0, "Synthetic", "dhan")
    order = SimpleNamespace(
        symbol="HDFCBANK", exchange="NSE", action="BUY", product="CNC", pricetype="LIMIT", quantity="10",
        price="100", trigger_price="0", disclosed_quantity="0", validity="IOC", variety="iceberg",
    )
    return adapter, session, order, transport


@pytest.mark.parametrize("data", [
    {"orderId": "nominal-parent", "orders": [{"orderId": "child-ack"}, {"error": "child-refusal"}]},
    {"orderId": "nominal-parent", "order_ids": ["child-one", "child-two"]},
    [{"orderId": "child-one"}, {"orderId": "child-two"}],
    {"orderId": True}, {"orderId": ""}, {"orderId": "ack-fixture", "orderStatus": {"unknown": True}},
])
async def test_unverified_or_malformed_slice_outcomes_never_collapse_into_one_successful_ack(data: Any) -> None:
    adapter, session, order, transport = stack(data)

    with pytest.raises(BrokerError, match="slice.*unverified.*after dispatch"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert len(transport.calls) == 1  # It may have dispatched: never retry it here.
    assert transport.calls[0][0] == "/orders/slicing"


async def test_existing_scalar_slice_ack_is_retained_as_ack_only_not_verified_child_outcomes() -> None:
    adapter, session, order, transport = stack({"orderId": "ack-fixture", "orderStatus": "TRANSIT"})

    result = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)

    assert result == "ack-fixture"
    assert len(transport.calls) == 1
    assert transport.calls[0][1]["quantity"] == 10 and transport.calls[0][1]["validity"] == "IOC"
