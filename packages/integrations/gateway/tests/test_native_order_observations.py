"""Presence-sensitive ordinary observations through real adapter/read owners."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from flinttrade_core.broker_read_port import BrokerOrderFamily, BrokerReadSuccess, OrderStateRequest
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from packages.integrations.gateway.tests.test_canonical_broker_observations import bound as bound

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
def test_ordinary_native_identity_and_independent_times_reach_bound_port(bound: Any, broker: str) -> None:
    """Neither timestamp selection nor a normal DTO may erase independent facts."""
    if broker == "dhan":
        native = dict(orderId="OrderAa", exchangeOrderId="ExchangeAa", orderStatus="PART_TRADED",
            tradingSymbol="SYNTHETIC", securityId="101", exchangeSegment="NSE_EQ", dhanClientId="NativeCase",
            transactionType="BUY", productType="CNC", orderType="LIMIT", quantity=2, filledQty=1,
            price=12.5, correlationId="ConfiguredTag", createTime="creation", updateTime="update",
            exchangeTime="exchange")
        class DhanClient:
            def __init__(self) -> None:
                self.dhan_http = self

            def get_order_list(self) -> dict:
                return {"status": "success", "data": [native]}

            def get_forever(self) -> dict:
                return {"status": "success", "data": []}

            def get_super_order_list(self) -> dict:
                return {"status": "success", "data": []}

            def get(self, path: str) -> dict:
                assert path == "/alerts/orders"
                return {"status": "success", "data": []}
        adapter = DhanAdapter(client_factory=lambda _: DhanClient())
        expected = {name: native[name] for name in ("dhanClientId", "exchangeSegment", "correlationId",
                                                   "createTime", "updateTime", "exchangeTime")}
    else:
        native = dict(nOrdNo="OrderAa", exOrdId="ExchangeAa", ordSt="cancelled", trdSym="SYNTHETIC",
            exSeg="nse_cm", actId="NativeCase", trnsTp="B", prod="CNC", prcTp="L", qty="2", fldQty="1",
            prc="12.50", GuiOrdId="ConfiguredTag", ordDtTm="order-time", ordEntTm="entry-time",
            exchTmstp="exchange-time", flDtTm="history-update", flDt="2026-10-23", flTm="fill-time")
        class KotakClient:
            def order_book(self) -> dict:
                return {"stat": "Ok", "stCode": 200, "data": [native]}
        adapter = KotakNeoAdapter(client_factory=lambda _: KotakClient())
        expected = {name: native[name] for name in ("actId", "exSeg", "GuiOrdId", "ordDtTm", "ordEntTm",
                                                   "exchTmstp", "flDtTm", "flDt", "flTm")}
    handle = bound(adapter, broker=broker)
    result = asyncio.run(handle.port.order_states(OrderStateRequest(BrokerOrderFamily.REGULAR)))
    assert type(result) is BrokerReadSuccess
    row = result.value[0]
    observed = json.loads(row.raw_observation_json)["broker_fields"]
    assert {name: observed[name] for name in expected} == expected
    assert row.broker_account_id == "NativeCase"
    assert row.broker_exchange_segment == ("NSE_EQ" if broker == "dhan" else "nse_cm")
    assert row.correlation_id == "ConfiguredTag"
    assert "native_order_date" not in observed


def test_dhan_correlation_lookup_preserves_the_same_native_observations() -> None:
    """The ordinary correlation endpoint must not use a lossy bare projection."""
    from flinttrade_gateway.brokers._base import Session

    native = dict(orderId="OrderAa", orderStatus="CANCELLED", correlationId="ConfiguredTag",
                  dhanClientId="NativeCase", exchangeSegment="NSE_EQ", createTime="creation",
                  updateTime="update", exchangeTime="exchange")
    class Client:
        def get_order_by_correlationID(self, value: str) -> dict:
            assert value == "ConfiguredTag"
            return {"status": "success", "data": native}
    adapter = DhanAdapter(client_factory=lambda _: Client())
    result = asyncio.run(adapter.get_order_by_correlation_id(Session("synthetic", 9e9, "NativeCase", "dhan"),
                                                            "ConfiguredTag"))
    assert result["created_at"] == "creation"
    assert result["broker_fields"]["exchangeSegment"] == "NSE_EQ"
    assert result["broker_fields"]["correlationId"] == "ConfiguredTag"
