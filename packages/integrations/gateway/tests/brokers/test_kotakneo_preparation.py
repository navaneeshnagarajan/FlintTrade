"""Retained exact-listing intent at the installed SDK, using only inert transport."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from typing import Any
from urllib.parse import parse_qs

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_contracts import KotakContractResolver
from .test_kotakneo_options_prerequisites import listed_resolver, master_row
from .test_kotakneo_options_prerequisites import sdk_runtime as sdk_runtime

pytestmark = pytest.mark.unit


def _order(**changes: Any) -> Order:
    """Build explicit synthetic selected-option intent, never provider eligibility."""
    row = master_row()
    return Order(**{"symbol": row["pTrdSymbol"], "exchange": "NFO", "action": "BUY", "quantity": "65",
                    "product": "NRML", "pricetype": "LIMIT", "price": "9.40", **changes})


async def test_preflight_retains_full_intent_and_adopts_once_without_resolver_rebuild(
    sdk_runtime: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use exactly the captured receipt and installed SDK resource after pure preflight."""
    facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "synthetic-order"})
    resolver = listed_resolver([master_row()])
    adapter = KotakNeoAdapter(client_factory=lambda _: facade, contract_resolver=resolver)
    session = Session("synthetic", 9e9, "NativeCase", "kotakneo", algo_id="synthetic-tag")
    session.extra["client"] = facade
    resolutions = []
    original = KotakContractResolver.resolve

    def resolve(self: KotakContractResolver, *args: Any, **kwargs: Any) -> Any:
        resolutions.append((self, args, kwargs))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(KotakContractResolver, "resolve", resolve)
    order = _order(variety="amo", validity="IOC")
    captures = []
    evidence = adapter.preflight_order(order, tag=session.algo_id, session=session,
                                       _capture_preparation=captures.append)
    assert calls == [] and len(resolutions) == 1 and len(captures) == 1
    prepared = captures[0]
    assert json.loads(prepared.intent_json) == order.model_dump(mode="json")
    assert prepared.contract_evidence() == evidence
    assert prepared.sdk_kwargs() == {
        "exchange_segment": "nse_fo", "product": "NRML", "price": "9.40", "order_type": "L",
        "quantity": "65", "validity": "IOC", "trading_symbol": order.symbol, "transaction_type": "B",
        "trigger_price": "0", "disclosed_quantity": "0", "amo": "YES", "tag": "synthetic-tag",
    }
    with pytest.raises((FrozenInstanceError, AttributeError)):
        prepared.intent_json = "{}"
    evidence["instrument_id"] = "different"
    prepared.sdk_kwargs()["quantity"] = "1"
    prepared.contract_evidence()["lot_size"] = 1
    assert await adapter.place_order(session, order, preparation=prepared,
        _router_token=ROUTER_TOKEN) == "synthetic-order"
    assert len(resolutions) == 1, "adoption must not rebuild history from another resolver lookup"
    assert len(calls) == 1
    assert calls[0].method == "POST" and calls[0].url.path == "/quick/order/rule/ms/place"
    body = json.loads(parse_qs(calls[0].content.decode())["jData"][0])
    assert body == {"am": "YES", "dq": "0", "es": "nse_fo", "mp": "0", "pc": "NRML", "pr": "9.40",
                    "pt": "L", "qt": "65", "rt": "IOC", "tp": "0", "ts": order.symbol, "tt": "B",
                    "ig": "synthetic-tag", "os": "NEOTRADEAPI"}


async def test_retained_preparation_does_not_recreate_a_legacy_client(sdk_runtime: Any) -> None:
    """A constructor factory is not a current-session getter or a second target."""
    clients = []

    def factory(_session: Session) -> Any:
        facade, calls = sdk_runtime({"stat": "Ok", "stCode": 200, "nOrdNo": "retained-order"})
        clients.append((facade, calls))
        return facade

    adapter = KotakNeoAdapter(client_factory=factory, contract_resolver=listed_resolver([master_row()]))
    session = Session("synthetic", 9e9, "NativeCase", "kotakneo")
    order = _order()
    prepared = adapter.prepare_order(order)
    assert clients == []
    assert await adapter.place_order(session, order, preparation=prepared,
        _router_token=ROUTER_TOKEN) == "retained-order"
    assert len(clients) == 1 and len(clients[0][1]) == 1
    assert session.extra.get("client") is None, "retention must not rewrite the caller's session"
