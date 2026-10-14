"""RC creation correspondence is signature-only, never execution authority."""
from __future__ import annotations

from inspect import signature

import pytest

from flinttrade_gateway.brokers import dhan_mapping as mapping
from packages.integrations.gateway.tests.brokers.test_dhan_legacy_adapter_contract import (
    RecordingHTTP,
    RecordingSDK,
    request,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("oco", [False, True])
def test_forever_rc_binding_preserves_exact_fields_without_symbol_or_dispatch(oco: bool) -> None:
    transport = RecordingHTTP()
    sdk = RecordingSDK(transport)
    second = {"price1": "110", "trigger_price1": "109", "quantity1": "9007199254740993"} if oco else {}
    kwargs = mapping.to_forever_kwargs(request(**second), "11536", tag="synthetic-correlation")
    expected = {
        "security_id": "11536", "exchange_segment": "NSE_EQ", "transaction_type": "BUY", "product_type": "CNC",
        "order_type": "LIMIT", "quantity": 9007199254740993, "price": 100.0, "trigger_Price": 99.0,
        "order_flag": "SINGLE", "disclosed_quantity": 0, "validity": "IOC", "tag": "synthetic-correlation",
    }
    if oco:
        expected.update(order_flag="OCO", price1=110.0, trigger_Price1=109.0, quantity1=9007199254740993)
    assert kwargs == expected
    assert signature(sdk.place_forever).bind(**kwargs).arguments == expected
    with pytest.raises(TypeError, match="symbol"):
        signature(sdk.place_forever).bind(**kwargs, symbol="TCS")
    assert transport.calls == []
